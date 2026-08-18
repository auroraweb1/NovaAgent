from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import cast

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
    StreamProtocolInvalidError,
)
from novaagent.domain.events import TokenUsage
from novaagent.domain.messages import (
    ImageRefBlock,
    Message,
    MessageRole,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultStatus,
)
from novaagent.domain.ports import (
    ModelOptions,
    ModelOutput,
    ModelRequest,
    TextModelDelta,
    ToolCallModelOutput,
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


async def collect_live(
    adapter: QwenModelAdapter, model_request: ModelRequest
) -> tuple[ModelOutput, ...]:
    return tuple([item async for item in adapter.stream_live(model_request)])


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


def test_live_stream_maps_deltas_usage_and_request_options() -> None:
    asyncio.run(_test_live_stream_maps_deltas_usage_and_request_options())


async def _test_live_stream_maps_deltas_usage_and_request_options() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = b"".join(
            [
                b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
                b'data: {"choices":[{"delta":{"content":"A"}}]}\n\n',
                b'data: {"choices":[{"delta":{"content":"B"}}]}\n\n',
                b'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":3}}\n\n',
                b"data: [DONE]\n\n",
            ]
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    adapter, client = adapter_for(handler)
    try:
        outputs = await collect_live(adapter, request())
    finally:
        await client.aclose()
    assert [item.text for item in outputs if isinstance(item, TextModelDelta)] == ["A", "B"]
    usage = [item for item in outputs if isinstance(item, UsageModelOutput)]
    assert usage[0].usage.total_tokens == 5
    payload = json.loads(requests[0].content)
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["enable_thinking"] is False


def test_non_streaming_tool_call_maps_request_and_response() -> None:
    async def scenario() -> None:
        requests: list[httpx.Request] = []

        def handler(http_request: httpx.Request) -> httpx.Response:
            requests.append(http_request)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "lookup",
                                            "arguments": '{"query":"x"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
            )

        adapter, client = adapter_for(handler)
        try:
            outputs = await collect(adapter, request(tools=True))
        finally:
            await client.aclose()
        call = next(item.call for item in outputs if isinstance(item, ToolCallModelOutput))
        assert call == ToolCallBlock("call-1", "lookup", {"query": "x"})
        payload = json.loads(requests[0].content)
        assert payload["tool_choice"] == "auto"
        assert payload["tools"][0]["function"]["name"] == "lookup"

    asyncio.run(scenario())


def test_live_stream_aggregates_tool_call_fragments() -> None:
    async def scenario() -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            fragments = [
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {"name": "echo", "arguments": '{"te'},
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "",
                                        "type": "function",
                                        "function": {"arguments": 'xt":"ok"}'},
                                    }
                                ]
                            }
                        }
                    ]
                },
            ]
            body = "".join(
                [*(f"data: {json.dumps(item)}\n\n" for item in fragments), "data: [DONE]\n\n"]
            ).encode()
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

        adapter, client = adapter_for(handler)
        try:
            outputs = await collect_live(adapter, request(tools=True))
        finally:
            await client.aclose()
        calls = [item.call for item in outputs if isinstance(item, ToolCallModelOutput)]
        assert calls == [ToolCallBlock("call-1", "echo", {"text": "ok"})]

    asyncio.run(scenario())


def test_live_stream_ignores_empty_tool_identity_placeholders() -> None:
    async def scenario() -> None:
        fragments = [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "echo",
                                        "arguments": '{"text":"ok"}',
                                    },
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        ]
        body = "".join(
            [*(f"data: {json.dumps(item)}\n\n" for item in fragments), "data: [DONE]\n\n"]
        ).encode()
        adapter, client = adapter_for(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=body,
            )
        )
        try:
            outputs = await collect_live(adapter, request(tools=True))
        finally:
            await client.aclose()
        calls = [item.call for item in outputs if isinstance(item, ToolCallModelOutput)]
        assert calls == [ToolCallBlock("call-1", "echo", {"text": "ok"})]

    asyncio.run(scenario())


def test_live_stream_rejects_conflicting_non_empty_tool_identity() -> None:
    fragments = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "function": {
                                    "name": "echo",
                                    "arguments": '{"text":"ok"}',
                                },
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-2",
                                "function": {"arguments": ""},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]
    body = "".join(
        [*(f"data: {json.dumps(item)}\n\n" for item in fragments), "data: [DONE]\n\n"]
    ).encode()

    async def scenario() -> None:
        adapter, client = adapter_for(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=body,
            )
        )
        try:
            with pytest.raises(ProviderResponseInvalidError):
                await collect_live(adapter, request(tools=True))
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("tool_calls", "expected"),
    [
        ({}, ProviderResponseInvalidError),
        ([1], ProviderResponseInvalidError),
        ([], StreamProtocolInvalidError),
    ],
)
def test_live_stream_rejects_malformed_tool_call_batches(
    tool_calls: object, expected: type[Exception]
) -> None:
    async def scenario() -> None:
        body = {
            "choices": [{"delta": {"tool_calls": tool_calls}}],
        }
        adapter, client = adapter_for(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(f"data: {json.dumps(body)}\n\ndata: [DONE]\n\n").encode(),
            )
        )
        try:
            with pytest.raises(expected):
                await collect_live(adapter, request(tools=True))
        finally:
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "delta",
    [
        {
            "tool_calls": [
                {
                    "index": 0,
                    "type": "other",
                    "id": "c",
                    "function": {"name": "e", "arguments": "{}"},
                }
            ]
        },
        {"tool_calls": [{"index": 0, "id": 4, "function": {"name": "e", "arguments": "{}"}}]},
        {"tool_calls": [{"index": 0, "id": "c", "function": 4}]},
        {"tool_calls": [{"index": 0, "id": "c", "function": {"name": 4, "arguments": "{}"}}]},
        {"tool_calls": [{"index": 0, "id": "c", "function": {"name": "e", "arguments": 4}}]},
        {"tool_calls": [{"index": 1, "id": "c", "function": {"name": "e", "arguments": "{}"}}]},
    ],
)
def test_live_stream_rejects_invalid_tool_fragments(delta: dict[str, object]) -> None:
    async def scenario() -> None:
        body = {"choices": [{"delta": delta}]}
        adapter, client = adapter_for(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(f"data: {json.dumps(body)}\n\ndata: [DONE]\n\n").encode(),
            )
        )
        try:
            with pytest.raises(ProviderResponseInvalidError):
                await collect_live(adapter, request(tools=True))
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_live_stream_rejects_duplicate_tool_ids_and_unexpected_finish_reason() -> None:
    async def scenario() -> None:
        duplicate = [
            {"index": 0, "id": "same", "function": {"name": "echo", "arguments": "{}"}},
            {"index": 1, "id": "same", "function": {"name": "echo", "arguments": "{}"}},
        ]
        bad_finish = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "c", "function": {"name": "echo", "arguments": "{}"}}
                        ]
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        for body in (
            {"choices": [{"delta": {"tool_calls": duplicate}}]},
            bad_finish,
        ):
            payload = cast(dict[str, object], body)

            def handler(_: httpx.Request, payload: dict[str, object] = payload) -> httpx.Response:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=(f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n").encode(),
                )

            adapter, client = adapter_for(handler)
            try:
                with pytest.raises(ProviderResponseInvalidError):
                    await collect_live(adapter, request(tools=True))
            finally:
                await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "body",
    [
        b"data: {bad-json}\n\n",
        b"event: wrong\n\n",
        b"data: []\n\n",
        b'data: {"choices":[]}\n\n',
        b'data: {"choices":[1]}\n\n',
        b'data: {"choices":[{"delta":1}]}\n\n',
        b'data: {"choices":[{"delta":{"tool_calls":[{}]}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":1}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"A"}}]}\n\n',
        b'data: {"choices":[{"delta":{"tool_calls":[]}}]}\n\ndata: [DONE]\n\n',
    ],
)
def test_live_stream_rejects_invalid_or_truncated_protocol(body: bytes) -> None:
    asyncio.run(_test_live_stream_rejects_invalid_or_truncated_protocol(body))


async def _test_live_stream_rejects_invalid_or_truncated_protocol(body: bytes) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    adapter, client = adapter_for(handler)
    try:
        with pytest.raises((StreamProtocolInvalidError, ProviderResponseInvalidError)):
            await collect_live(adapter, request())
    finally:
        await client.aclose()


def test_live_stream_retries_http_503_before_first_delta() -> None:
    asyncio.run(_test_live_stream_retries_http_503_before_first_delta())


async def _test_live_stream_retries_http_503_before_first_delta() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": {"code": "busy"}})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n',
        )

    adapter, client = adapter_for(handler)
    try:
        outputs = await collect_live(adapter, request())
    finally:
        await client.aclose()
    assert calls == 2
    assert [item.text for item in outputs if isinstance(item, TextModelDelta)] == ["ok"]


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("offline"),
        httpx.PoolTimeout("busy"),
        httpx.RequestError("request failed"),
    ],
)
def test_live_stream_network_errors_are_mapped(error: httpx.RequestError) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if isinstance(error, httpx.ConnectError):
                raise httpx.ConnectError("offline", request=request)
            if isinstance(error, httpx.PoolTimeout):
                raise httpx.PoolTimeout("busy", request=request)
            raise httpx.RequestError("request failed", request=request)

        adapter, client = adapter_for(handler, settings=QwenProviderSettings(max_retries=0))
        try:
            expected = (
                ProviderBusyError
                if isinstance(error, httpx.PoolTimeout)
                else ProviderUnavailableError
            )
            with pytest.raises(expected):
                await collect_live(adapter, request())
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_retry_after_invalid_value_uses_jitter_fallback() -> None:
    async def scenario() -> None:
        delays: list[float] = []
        calls = 0

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429, headers={"Retry-After": "invalid"}, json={})
            return httpx.Response(200, json=success_response(include_usage=False))

        async def sleep(delay: float) -> None:
            delays.append(delay)

        adapter, client = adapter_for(handler, sleep=sleep)
        try:
            await collect(adapter, request())
        finally:
            await client.aclose()
        assert calls == 2
        assert delays == [0.25]

    asyncio.run(scenario())


def test_live_stream_requires_secret_without_outbound_request() -> None:
    asyncio.run(_test_live_stream_requires_secret_without_outbound_request())


def test_live_stream_concurrency_gate_returns_busy() -> None:
    async def scenario() -> None:
        adapter, client = adapter_for(lambda _: httpx.Response(200))
        adapter._semaphore = asyncio.Semaphore(0)
        try:
            with pytest.raises(ProviderBusyError):
                await collect_live(adapter, request())
        finally:
            await client.aclose()

    asyncio.run(scenario())


async def _test_live_stream_requires_secret_without_outbound_request() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, client = adapter_for(handler, key=None)
    try:
        with pytest.raises(SecretMissingError):
            await collect_live(adapter, request())
    finally:
        await client.aclose()
    assert calls == 0


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


def test_nested_provider_error_code_is_not_exposed() -> None:
    async def scenario() -> None:
        adapter, client = adapter_for(
            lambda _: httpx.Response(418, json={"error": {"code": "secret-code"}}),
            settings=QwenProviderSettings(max_retries=0),
        )
        try:
            with pytest.raises(ProviderInputRejectedError) as raised:
                await collect(adapter, request())
        finally:
            await client.aclose()
        assert "secret-code" not in str(raised.value)

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


@pytest.mark.parametrize(
    "message",
    [
        {"content": "ok", "tool_calls": {}},
        {"content": "ok", "tool_calls": [1]},
        {"content": None, "tool_calls": []},
    ],
)
def test_invalid_non_streaming_tool_responses_are_rejected(message: dict[str, object]) -> None:
    async def scenario() -> None:
        adapter, client = adapter_for(
            lambda _: httpx.Response(200, json={"choices": [{"message": message}]})
        )
        try:
            with pytest.raises(ProviderResponseInvalidError):
                await collect(adapter, request(tools=True))
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


def test_missing_key_and_unsupported_content_make_no_network_call() -> None:
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
            await collect(with_key, tool_message)
        finally:
            await missing_client.aclose()
            await client.aclose()

        assert calls == 2

    asyncio.run(scenario())


def test_qwen_rejects_invalid_tool_message_shapes() -> None:
    async def scenario() -> None:
        adapter, client = adapter_for(lambda _: httpx.Response(200, json=success_response()))
        try:
            assistant = Message(
                "assistant-tools",
                MessageRole.ASSISTANT,
                (ToolCallBlock("call-1", "echo", {"text": "ok"}),),
                NOW,
            )
            await collect(adapter, ModelRequest((assistant,)))
            mixed = Message(
                "mixed",
                MessageRole.USER,
                (ToolCallBlock("call-2", "echo", {}), ImageRefBlock("image", "image/png")),
                NOW,
            )
            with pytest.raises(ProtocolValidationError, match="Unsupported"):
                await collect(adapter, ModelRequest((mixed,)))
            non_text_result = ToolResultBlock(
                "call-3", ToolResultStatus.SUCCESS, (ImageRefBlock("image", "image/png"),)
            )
            tool_message = Message("tool", MessageRole.TOOL, (non_text_result,), NOW)
            with pytest.raises(ProtocolValidationError, match="text content"):
                await collect(adapter, ModelRequest((tool_message,)))
            user_call = Message(
                "user-call",
                MessageRole.USER,
                (ToolCallBlock("call-4", "echo", {}),),
                NOW,
            )
            with pytest.raises(ProtocolValidationError, match="assistant role"):
                await collect(adapter, ModelRequest((user_call,)))
            mixed_tool_message = Message(
                "mixed-tool",
                MessageRole.TOOL,
                (
                    ToolResultBlock("call-5", ToolResultStatus.SUCCESS, (TextBlock("ok"),)),
                    TextBlock("unexpected"),
                ),
                NOW,
            )
            with pytest.raises(ProtocolValidationError, match="tool results"):
                await collect(adapter, ModelRequest((mixed_tool_message,)))
        finally:
            await client.aclose()

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
