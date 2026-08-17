from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx
import pytest

from novaagent.config.model import QwenProviderSettings
from novaagent.domain.errors import (
    ProtocolValidationError,
    ProviderAuthenticationError,
    ProviderBusyError,
    ProviderInputRejectedError,
    ProviderModelInvalidError,
    ProviderRateLimitedError,
    ProviderResponseInvalidError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    SecretMissingError,
)
from novaagent.domain.events import TokenUsage
from novaagent.domain.messages import (
    ImageRefBlock,
    Message,
    MessageRole,
    TextBlock,
    ToolResultBlock,
    ToolResultStatus,
)
from novaagent.domain.ports import (
    ModelOptions,
    ModelOutput,
    ModelRequest,
    TextModelDelta,
    ToolDefinition,
    UsageModelOutput,
)
from novaagent.infrastructure.models.qwen.adapter import QWEN_CHAT_URL, QwenModelAdapter

NOW = datetime(2026, 8, 17, 4, 0, tzinfo=UTC)
Handler = Callable[[httpx.Request], httpx.Response]


def request(*, image: bool = False, tools: bool = False) -> ModelRequest:
    content = (ImageRefBlock("image-1", "image/png"),) if image else (TextBlock("你好，NovaAgent"),)
    definitions = (
        (ToolDefinition("lookup", "Look up a value", {"type": "object"}),) if tools else ()
    )
    return ModelRequest(
        messages=(Message("msg-1", MessageRole.USER, content, NOW),),
        tools=definitions,
        options=ModelOptions(temperature=0.25, max_output_tokens=512),
    )


def success_response(*, include_usage: bool = True) -> dict[str, object]:
    result: dict[str, object] = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "NOVAAGENT_OK",
                    "reasoning_content": "this must be discarded",
                }
            }
        ]
    }
    if include_usage:
        result["usage"] = {
            "prompt_tokens": 5,
            "completion_tokens": 3,
            "total_tokens": 999,
        }
    return result


async def collect(
    adapter: QwenModelAdapter, model_request: ModelRequest
) -> tuple[ModelOutput, ...]:
    return tuple([item async for item in adapter.stream(model_request)])


async def no_sleep(_: float) -> None:
    return None


def adapter_for(
    handler: Handler,
    *,
    key: str | None = "server-side-key",
    settings: QwenProviderSettings | None = None,
    sleep: Callable[[float], Awaitable[None]] = no_sleep,
) -> tuple[QwenModelAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        QwenModelAdapter(
            client=client,
            settings=settings or QwenProviderSettings(),
            secret_provider=lambda: key,
            sleep=sleep,
            random_source=lambda: 0.0,
        ),
        client,
    )


def test_qwen_request_contract_and_success_mapping() -> None:
    seen: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        seen.append(http_request)
        return httpx.Response(200, json=success_response())

    async def scenario() -> None:
        adapter, client = adapter_for(handler)
        try:
            outputs = await collect(adapter, request())
        finally:
            await client.aclose()

        assert outputs == (
            TextModelDelta("NOVAAGENT_OK"),
            UsageModelOutput(TokenUsage(5, 3)),
        )
        assert "reasoning" not in repr(outputs).lower()
        assert len(seen) == 1
        sent = seen[0]
        assert str(sent.url) == QWEN_CHAT_URL
        assert sent.headers["Authorization"].startswith("Bearer ")
        assert sent.headers["Authorization"] != "Bearer "
        payload = json.loads(sent.content)
        assert payload == {
            "model": "qwen3.8-max",
            "messages": [{"role": "user", "content": "你好，NovaAgent"}],
            "stream": False,
            "enable_thinking": False,
            "temperature": 0.25,
            "max_tokens": 512,
        }

    asyncio.run(scenario())


def test_usage_is_optional() -> None:
    async def scenario() -> None:
        adapter, client = adapter_for(
            lambda _: httpx.Response(200, json=success_response(include_usage=False))
        )
        try:
            assert await collect(adapter, request()) == (TextModelDelta("NOVAAGENT_OK"),)
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {}, ProviderAuthenticationError),
        (403, {}, ProviderAuthenticationError),
        (429, {}, ProviderRateLimitedError),
        (408, {}, ProviderTimeoutError),
        (504, {}, ProviderTimeoutError),
        (400, {"code": "InvalidParameter"}, ProviderModelInvalidError),
        (400, {"code": "DataInspectionFailed"}, ProviderInputRejectedError),
        (404, {}, ProviderModelInvalidError),
        (500, {}, ProviderUnavailableError),
    ],
)
def test_provider_http_errors_are_stably_classified(
    status: int, body: dict[str, object], expected: type[Exception]
) -> None:
    async def scenario() -> None:
        adapter, client = adapter_for(
            lambda _: httpx.Response(status, json=body),
            settings=QwenProviderSettings(max_retries=0),
        )
        try:
            with pytest.raises(expected) as raised:
                await collect(adapter, request())
        finally:
            await client.aclose()

        assert "server-side-key" not in str(raised.value)
        assert "DataInspectionFailed" not in str(raised.value)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": 123}}]},
        {"choices": [{"message": {"content": "ok", "tool_calls": [{"id": "x"}]}}]},
        {"choices": [{"message": {"content": "ok"}}], "usage": []},
        {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": True, "completion_tokens": 1},
        },
        {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": -1, "completion_tokens": 1},
        },
    ],
)
def test_invalid_provider_responses_are_rejected(body: object) -> None:
    async def scenario() -> None:
        adapter, client = adapter_for(lambda _: httpx.Response(200, json=body))
        try:
            with pytest.raises(ProviderResponseInvalidError):
                await collect(adapter, request())
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_non_json_provider_response_is_rejected() -> None:
    async def scenario() -> None:
        adapter, client = adapter_for(lambda _: httpx.Response(200, content=b"not json"))
        try:
            with pytest.raises(ProviderResponseInvalidError):
                await collect(adapter, request())
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_missing_key_and_unsupported_requests_make_no_network_call() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=success_response())

    async def scenario() -> None:
        missing, missing_client = adapter_for(handler, key="  ")
        with_key, client = adapter_for(handler)
        try:
            with pytest.raises(SecretMissingError):
                await collect(missing, request())
            with pytest.raises(ProtocolValidationError, match="tools"):
                await collect(with_key, request(tools=True))
            with pytest.raises(ProtocolValidationError, match="text content"):
                await collect(with_key, request(image=True))
            tool_message = ModelRequest(
                (
                    Message(
                        "msg-tool",
                        MessageRole.TOOL,
                        (
                            ToolResultBlock(
                                "call-1",
                                ToolResultStatus.SUCCESS,
                                (TextBlock("result"),),
                            ),
                        ),
                        NOW,
                    ),
                )
            )
            with pytest.raises(ProtocolValidationError, match="tool messages"):
                await collect(with_key, tool_message)
        finally:
            await missing_client.aclose()
            await client.aclose()

        assert calls == 0

    asyncio.run(scenario())


def test_connect_failure_retries_once_and_releases_semaphore() -> None:
    calls = 0

    def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("offline", request=http_request)
        return httpx.Response(200, json=success_response(include_usage=False))

    async def scenario() -> None:
        adapter, client = adapter_for(handler, settings=QwenProviderSettings(max_retries=1))
        try:
            assert await collect(adapter, request()) == (TextModelDelta("NOVAAGENT_OK"),)
            assert await collect(adapter, request()) == (TextModelDelta("NOVAAGENT_OK"),)
        finally:
            await client.aclose()

        assert calls == 3

    asyncio.run(scenario())


def test_retry_after_is_capped_at_two_seconds() -> None:
    calls = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "30"}, json={})
        return httpx.Response(200, json=success_response(include_usage=False))

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async def scenario() -> None:
        adapter, client = adapter_for(handler, sleep=record_sleep)
        try:
            await collect(adapter, request())
        finally:
            await client.aclose()

        assert calls == 2
        assert delays == [2.0]

    asyncio.run(scenario())


def test_read_timeout_is_not_retried() -> None:
    calls = 0

    def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("too slow", request=http_request)

    async def scenario() -> None:
        adapter, client = adapter_for(handler, settings=QwenProviderSettings(max_retries=2))
        try:
            with pytest.raises(ProviderTimeoutError):
                await collect(adapter, request())
        finally:
            await client.aclose()

        assert calls == 1

    asyncio.run(scenario())


def test_concurrency_gate_returns_busy_without_network_call() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=success_response())

    async def scenario() -> None:
        adapter, client = adapter_for(handler)
        adapter._semaphore = asyncio.Semaphore(0)
        try:
            with pytest.raises(ProviderBusyError):
                await collect(adapter, request())
        finally:
            await client.aclose()

        assert calls == 0

    asyncio.run(scenario())
