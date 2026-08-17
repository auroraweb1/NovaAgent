from __future__ import annotations

import asyncio
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
)
from novaagent.domain.events import TokenUsage
from novaagent.domain.messages import MessageRole, TextBlock
from novaagent.domain.models import ModelCapabilities
from novaagent.domain.ports import ModelOutput, ModelRequest, TextModelDelta, UsageModelOutput

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
        self.capabilities = ModelCapabilities(provider="qwen", model=settings.model)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelOutput]:
        api_key = self._secret_provider()
        if api_key is None or not api_key.strip():
            raise SecretMissingError(
                "未配置千问 API Key，请在本地 .env 或服务端运行时环境中配置 DASHSCOPE_API_KEY",
                field="providers.qwen.secret",
            )

        payload = self._request_payload(request)
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

    def _request_payload(self, request: ModelRequest) -> dict[str, object]:
        if request.tools:
            raise ProtocolValidationError(
                "Qwen stage 03 adapter does not support tools", field="tools"
            )

        messages: list[dict[str, str]] = []
        for index, message in enumerate(request.messages):
            if message.role is MessageRole.TOOL:
                raise ProtocolValidationError(
                    "Qwen stage 03 adapter does not support tool messages",
                    field=f"messages[{index}].role",
                )
            if not all(isinstance(block, TextBlock) for block in message.content):
                raise ProtocolValidationError(
                    "Qwen stage 03 adapter only supports text content",
                    field=f"messages[{index}].content",
                )
            text = "".join(cast(TextBlock, block).text for block in message.content)
            messages.append({"role": message.role.value, "content": text})

        payload: dict[str, object] = {
            "model": self._settings.model,
            "messages": messages,
            "stream": False,
            "enable_thinking": False,
            "temperature": request.options.temperature,
            "max_tokens": request.options.max_output_tokens,
        }
        return {key: value for key, value in payload.items() if value is not None}

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
        if message.get("tool_calls"):
            raise ProviderResponseInvalidError()
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
