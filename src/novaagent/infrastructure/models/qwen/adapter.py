from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import cast

import httpx

from novaagent.config.model import QwenProviderSettings
from novaagent.domain.errors import (
    NovaAgentError,
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
from novaagent.domain.messages import MessageRole, TextBlock, ToolCallBlock, ToolResultBlock
from novaagent.domain.models import ModelCapabilities
from novaagent.domain.ports import (
    ModelOutput,
    ModelRequest,
    TextModelDelta,
    ToolCallModelOutput,
    UsageModelOutput,
)

QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
QWEN_CHAT_URL = f"{QWEN_BASE_URL}/chat/completions"
RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})

SecretProvider = Callable[[], str | None]
Sleeper = Callable[[float], Awaitable[None]]
RandomSource = Callable[[], float]


class QwenModelAdapter:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        settings: QwenProviderSettings,
        secret_provider: SecretProvider,
        sleep: Sleeper = asyncio.sleep,
        random_source: RandomSource = random.random,
    ) -> None:
        self._client = client
        self._settings = settings
        self._secret_provider = secret_provider
        self._sleep = sleep
        self._random_source = random_source
        self._semaphore = asyncio.Semaphore(settings.max_concurrency)
        self._timeout = httpx.Timeout(settings.timeout_seconds, connect=5.0)
        self.capabilities = ModelCapabilities(
            provider="qwen",
            model=settings.model,
            native_streaming=True,
            tool_calling=True,
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelOutput]:
        api_key = self._secret_provider()
        if api_key is None or not api_key.strip():
            raise SecretMissingError(
                "未配置千问 API Key，请在本地 .env 或服务端运行时环境中配置 DASHSCOPE_API_KEY",
                field="providers.qwen.secret",
            )

        payload = self._request_payload(request, streaming=False)
        acquired = False
        try:
            try:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=1.0)
            except TimeoutError as error:
                raise ProviderBusyError() from error
            acquired = True
            outputs = await self._request_outputs(payload, api_key)
        finally:
            if acquired:
                self._semaphore.release()

        for output in outputs:
            yield output

    async def stream_live(self, request: ModelRequest) -> AsyncIterator[ModelOutput]:
        api_key = self._secret_provider()
        if api_key is None or not api_key.strip():
            raise SecretMissingError(
                "未配置千问 API Key，请在本地 .env 或服务端运行时环境中配置 DASHSCOPE_API_KEY",
                field="providers.qwen.secret",
            )

        payload = self._request_payload(request, streaming=True)
        acquired = False
        try:
            try:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=1.0)
            except TimeoutError as error:
                raise ProviderBusyError() from error
            acquired = True
            async for output in self._request_stream(payload, api_key):
                yield output
        finally:
            if acquired:
                self._semaphore.release()

    def _request_payload(
        self, request: ModelRequest, *, streaming: bool = False
    ) -> dict[str, object]:
        messages: list[dict[str, object]] = []
        for index, message in enumerate(request.messages):
            if message.role is MessageRole.TOOL:
                results = [block for block in message.content if isinstance(block, ToolResultBlock)]
                if not results or len(results) != len(message.content):
                    raise ProtocolValidationError(
                        "Tool messages require tool results", field=f"messages[{index}]"
                    )
                for result in results:
                    if not all(isinstance(block, TextBlock) for block in result.content):
                        raise ProtocolValidationError(
                            "Qwen tool results only support text content",
                            field=f"messages[{index}].content",
                        )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": result.call_id,
                            "content": _tool_result_text(result),
                        }
                    )
                continue
            calls = [block for block in message.content if isinstance(block, ToolCallBlock)]
            text_blocks = [block for block in message.content if isinstance(block, TextBlock)]
            if len(calls) and len(calls) + len(text_blocks) != len(message.content):
                raise ProtocolValidationError(
                    "Unsupported message content", field=f"messages[{index}].content"
                )
            if calls and text_blocks:
                raise ProtocolValidationError(
                    "Assistant tool calls cannot contain text", field=f"messages[{index}].content"
                )
            if calls:
                if message.role is not MessageRole.ASSISTANT:
                    raise ProtocolValidationError(
                        "Tool calls require assistant role",
                        field=f"messages[{index}].role",
                    )
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call.call_id,
                                "type": "function",
                                "function": {
                                    "name": call.tool_name,
                                    "arguments": json.dumps(
                                        _thaw_json(call.arguments),
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    ),
                                },
                            }
                            for call in calls
                        ],
                    }
                )
            else:
                if not all(isinstance(block, TextBlock) for block in message.content):
                    raise ProtocolValidationError(
                        "Qwen adapter only supports text content",
                        field=f"messages[{index}].content",
                    )
                messages.append(
                    {
                        "role": message.role.value,
                        "content": "".join(
                            cast(TextBlock, block).text for block in message.content
                        ),
                    }
                )

        payload: dict[str, object] = {
            "model": self._settings.model,
            "messages": messages,
            "stream": streaming,
            "enable_thinking": False,
            "temperature": request.options.temperature,
            "max_tokens": request.options.max_output_tokens,
        }
        if streaming:
            payload["stream_options"] = {"include_usage": True}
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": _thaw_json(tool.parameters),
                    },
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = "auto"
        return {key: value for key, value in payload.items() if value is not None}

    async def _request_stream(
        self, payload: dict[str, object], api_key: str
    ) -> AsyncIterator[ModelOutput]:
        attempts = self._settings.max_retries + 1
        for attempt in range(attempts):
            emitted = False
            try:
                async with self._client.stream(
                    "POST",
                    QWEN_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self._timeout,
                ) as response:
                    if response.status_code >= 400:
                        if (
                            response.status_code in RETRYABLE_STATUS_CODES
                            and attempt + 1 < attempts
                        ):
                            await self._sleep(self._retry_delay(attempt, response))
                            continue
                        raise self._http_error(response)

                    saw_done = False
                    saw_output = False
                    text_parts: list[str] = []
                    tool_fragments: dict[int, dict[str, str]] = {}
                    usage: TokenUsage | None = None
                    finish_reason: str | None = None
                    pending_calls: list[ToolCallBlock] = []
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            raise StreamProtocolInvalidError()
                        raw_data = line[5:].strip()
                        if raw_data == "[DONE]":
                            saw_done = True
                            break
                        try:
                            chunk = json.loads(raw_data)
                        except json.JSONDecodeError as error:
                            raise StreamProtocolInvalidError() from error
                        if not isinstance(chunk, Mapping):
                            raise StreamProtocolInvalidError()
                        usage = _stream_usage(chunk, usage)
                        choices = chunk.get("choices")
                        if choices == [] and usage is not None:
                            continue
                        if not isinstance(choices, list) or not choices:
                            raise StreamProtocolInvalidError()
                        choice = choices[0]
                        if not isinstance(choice, Mapping):
                            raise StreamProtocolInvalidError()
                        current_finish_reason = choice.get("finish_reason")
                        if current_finish_reason is not None:
                            if not isinstance(current_finish_reason, str):
                                raise ProviderResponseInvalidError()
                            finish_reason = current_finish_reason
                        delta = choice.get("delta")
                        if not isinstance(delta, Mapping):
                            raise StreamProtocolInvalidError()
                        tool_calls = delta.get("tool_calls")
                        if tool_calls is not None:
                            if not isinstance(tool_calls, list):
                                raise ProviderResponseInvalidError()
                            for item in tool_calls:
                                if not isinstance(item, Mapping):
                                    raise ProviderResponseInvalidError()
                                index = item.get("index")
                                if not isinstance(index, int) or index < 0:
                                    raise ProviderResponseInvalidError()
                                fragment = tool_fragments.setdefault(index, {})
                                emitted = True
                                call_type = item.get("type")
                                if call_type is not None and call_type != "function":
                                    raise ProviderResponseInvalidError()
                                call_id = item.get("id")
                                if call_id is not None:
                                    if not isinstance(call_id, str):
                                        raise ProviderResponseInvalidError()
                                    if call_id:
                                        _set_stable_fragment(fragment, "id", call_id)
                                function = item.get("function")
                                if function is not None and not isinstance(function, Mapping):
                                    raise ProviderResponseInvalidError()
                                if isinstance(function, Mapping):
                                    name = function.get("name")
                                    if name is not None:
                                        if not isinstance(name, str):
                                            raise ProviderResponseInvalidError()
                                        if name:
                                            _set_stable_fragment(fragment, "name", name)
                                    arguments = function.get("arguments")
                                    if arguments is not None:
                                        if not isinstance(arguments, str):
                                            raise ProviderResponseInvalidError()
                                        fragment["arguments"] = (
                                            fragment.get("arguments", "") + arguments
                                        )
                        content = delta.get("content")
                        if content is None:
                            continue
                        if not isinstance(content, str):
                            raise ProviderResponseInvalidError()
                        if content:
                            text_parts.append(content)
                            emitted = True
                            saw_output = True
                    if tool_fragments:
                        indexes = sorted(tool_fragments)
                        if indexes != list(range(len(indexes))):
                            raise ProviderResponseInvalidError()
                        calls: list[ToolCallBlock] = []
                        for index in indexes:
                            fragment = tool_fragments[index]
                            calls.append(_tool_call_from_parts(fragment))
                        if len({call.call_id for call in calls}) != len(calls):
                            raise ProviderResponseInvalidError()
                        if text_parts or finish_reason not in {None, "tool_calls"}:
                            raise ProviderResponseInvalidError()
                        pending_calls = calls
                        saw_output = True
                    elif finish_reason == "tool_calls":
                        raise ProviderResponseInvalidError()
                    if not saw_done or not saw_output:
                        raise StreamProtocolInvalidError()
                    for call in pending_calls:
                        yield ToolCallModelOutput(call)
                    for part in text_parts:
                        yield TextModelDelta(part)
                    if usage is not None:
                        yield UsageModelOutput(usage)
                    return
            except (httpx.ConnectError, httpx.ConnectTimeout) as error:
                if not emitted and attempt + 1 < attempts:
                    await self._sleep(self._retry_delay(attempt, None))
                    continue
                raise ProviderUnavailableError() from error
            except httpx.PoolTimeout as error:
                raise ProviderBusyError() from error
            except (httpx.ReadTimeout, httpx.WriteTimeout) as error:
                raise ProviderTimeoutError() from error
            except httpx.RequestError as error:
                if not emitted and attempt + 1 < attempts:
                    await self._sleep(self._retry_delay(attempt, None))
                    continue
                raise ProviderUnavailableError() from error

        raise ProviderUnavailableError()

    async def _request_outputs(
        self, payload: dict[str, object], api_key: str
    ) -> tuple[ModelOutput, ...]:
        attempts = self._settings.max_retries + 1
        response: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                response = await self._client.post(
                    QWEN_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self._timeout,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as error:
                if attempt + 1 < attempts:
                    await self._sleep(self._retry_delay(attempt, None))
                    continue
                raise ProviderUnavailableError() from error
            except httpx.PoolTimeout as error:
                raise ProviderBusyError() from error
            except (httpx.ReadTimeout, httpx.WriteTimeout) as error:
                raise ProviderTimeoutError() from error
            except httpx.RequestError as error:
                raise ProviderUnavailableError() from error

            if response.status_code in RETRYABLE_STATUS_CODES and attempt + 1 < attempts:
                await self._sleep(self._retry_delay(attempt, response))
                continue
            break

        if response is None:  # pragma: no cover - loop always returns or raises
            raise ProviderUnavailableError()
        if response.status_code >= 400:
            raise self._http_error(response)
        return self._parse_success(response)

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    return min(2.0, max(0.0, float(retry_after)))
                except ValueError:
                    pass
        jitter = 0.5 + min(1.0, max(0.0, self._random_source()))
        return min(2.0, 0.5 * (2**attempt) * jitter)

    def _http_error(self, response: httpx.Response) -> NovaAgentError:
        status = response.status_code
        code = self._provider_error_code(response).lower()
        if status in {401, 403}:
            return ProviderAuthenticationError()
        if status == 429:
            return ProviderRateLimitedError()
        if status in {408, 504}:
            return ProviderTimeoutError()
        if status == 404 or (status == 400 and ("model" in code or "parameter" in code)):
            return ProviderModelInvalidError()
        if status == 400:
            return ProviderInputRejectedError()
        if status >= 500:
            return ProviderUnavailableError()
        return ProviderInputRejectedError()

    def _provider_error_code(self, response: httpx.Response) -> str:
        data = self._json_object(response)
        direct = data.get("code")
        if isinstance(direct, str):
            return direct
        nested = data.get("error")
        if isinstance(nested, Mapping):
            code = nested.get("code")
            if isinstance(code, str):
                return code
        return ""

    def _parse_success(self, response: httpx.Response) -> tuple[ModelOutput, ...]:
        data = self._json_object(response)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise ProviderResponseInvalidError()
        message = choices[0].get("message")
        if not isinstance(message, Mapping):
            raise ProviderResponseInvalidError()
        tool_calls = message.get("tool_calls")
        if tool_calls is not None:
            if not isinstance(tool_calls, list):
                raise ProviderResponseInvalidError()
            tool_outputs: list[ModelOutput] = []
            call_ids: set[str] = set()
            for item in tool_calls:
                if not isinstance(item, Mapping):
                    raise ProviderResponseInvalidError()
                function = item.get("function")
                if not isinstance(function, Mapping):
                    raise ProviderResponseInvalidError()
                if item.get("type", "function") != "function":
                    raise ProviderResponseInvalidError()
                call = _parse_tool_call(item, function)
                if call.call_id in call_ids:
                    raise ProviderResponseInvalidError()
                call_ids.add(call.call_id)
                tool_outputs.append(ToolCallModelOutput(call))
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                if tool_outputs:
                    raise ProviderResponseInvalidError()
                tool_outputs.append(TextModelDelta(content))
            if not tool_outputs:
                raise ProviderResponseInvalidError()
            usage_data = data.get("usage")
            if usage_data is not None:
                tool_outputs.append(_usage_output(usage_data))
            return tuple(tool_outputs)
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderResponseInvalidError()

        outputs: list[ModelOutput] = [TextModelDelta(content)]
        usage_data = data.get("usage")
        if usage_data is not None:
            if not isinstance(usage_data, Mapping):
                raise ProviderResponseInvalidError()
            input_tokens = usage_data.get("prompt_tokens")
            output_tokens = usage_data.get("completion_tokens")
            if not _valid_token_count(input_tokens) or not _valid_token_count(output_tokens):
                raise ProviderResponseInvalidError()
            outputs.append(
                UsageModelOutput(TokenUsage(cast(int, input_tokens), cast(int, output_tokens)))
            )
        return tuple(outputs)

    def _json_object(self, response: httpx.Response) -> Mapping[str, object]:
        try:
            data = cast(object, response.json())
        except ValueError as error:
            raise ProviderResponseInvalidError() from error
        if not isinstance(data, Mapping):
            raise ProviderResponseInvalidError()
        return cast(Mapping[str, object], data)


def _valid_token_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _tool_result_text(result: ToolResultBlock) -> str:
    text = "".join(block.text for block in result.content if isinstance(block, TextBlock))
    if result.status.value == "error":
        return json.dumps({"error_code": result.error_code, "message": text}, ensure_ascii=False)
    return text


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _tool_call_from_parts(parts: Mapping[str, str]) -> ToolCallBlock:
    call_id = parts.get("id", "")
    name = parts.get("name", "")
    raw_arguments = parts.get("arguments", "")
    if not call_id or not name or not raw_arguments:
        raise ProviderResponseInvalidError()
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as error:
        raise ProviderResponseInvalidError() from error
    if not isinstance(arguments, Mapping):
        raise ProviderResponseInvalidError()
    try:
        return ToolCallBlock(call_id=call_id, tool_name=name, arguments=arguments)
    except Exception as error:
        raise ProviderResponseInvalidError() from error


def _set_stable_fragment(parts: dict[str, str], key: str, value: str) -> None:
    current = parts.get(key)
    if current is not None and current != value:
        raise ProviderResponseInvalidError()
    parts[key] = value


def _parse_tool_call(item: Mapping[str, object], function: Mapping[str, object]) -> ToolCallBlock:
    call_id = item.get("id")
    name = function.get("name")
    raw_arguments = function.get("arguments")
    if (
        not isinstance(call_id, str)
        or not isinstance(name, str)
        or not isinstance(raw_arguments, str)
    ):
        raise ProviderResponseInvalidError()
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as error:
        raise ProviderResponseInvalidError() from error
    if not isinstance(arguments, Mapping):
        raise ProviderResponseInvalidError()
    try:
        return ToolCallBlock(call_id=call_id, tool_name=name, arguments=arguments)
    except Exception as error:
        raise ProviderResponseInvalidError() from error


def _usage_output(usage_data: object) -> UsageModelOutput:
    if not isinstance(usage_data, Mapping):
        raise ProviderResponseInvalidError()
    input_tokens = usage_data.get("prompt_tokens")
    output_tokens = usage_data.get("completion_tokens")
    if not _valid_token_count(input_tokens) or not _valid_token_count(output_tokens):
        raise ProviderResponseInvalidError()
    return UsageModelOutput(TokenUsage(cast(int, input_tokens), cast(int, output_tokens)))


def _stream_usage(chunk: Mapping[str, object], current: TokenUsage | None) -> TokenUsage | None:
    usage_data = chunk.get("usage")
    if usage_data is None:
        return current
    if not isinstance(usage_data, Mapping):
        raise ProviderResponseInvalidError()
    input_tokens = usage_data.get("prompt_tokens")
    output_tokens = usage_data.get("completion_tokens")
    if not _valid_token_count(input_tokens) or not _valid_token_count(output_tokens):
        raise ProviderResponseInvalidError()
    return TokenUsage(cast(int, input_tokens), cast(int, output_tokens))
