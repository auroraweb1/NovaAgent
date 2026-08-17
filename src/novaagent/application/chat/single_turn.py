from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from novaagent.application.protocol.driver import create_user_message, run_protocol
from novaagent.domain.errors import MessageTooLongError, ProtocolValidationError
from novaagent.domain.events import AgentEvent, RunCompletedPayload, RunStartedPayload, TokenUsage
from novaagent.domain.messages import Message
from novaagent.domain.models import ProviderDescriptor
from novaagent.domain.ports import ModelOptions, ModelPort, ModelRequest

MESSAGE_CHARACTER_LIMIT = 32_000

IdFactory = Callable[[str], str]
Clock = Callable[[], datetime]
MonotonicClock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class SingleTurnChatResult:
    run_id: str
    message: Message
    provider: str
    model: str
    usage: TokenUsage | None
    latency_ms: int


@dataclass(slots=True)
class SingleTurnEventProjection:
    run_id: str | None = None
    usage: TokenUsage | None = None

    async def publish(self, event: AgentEvent) -> None:
        if isinstance(event.payload, RunStartedPayload):
            self.run_id = event.run_id
        elif isinstance(event.payload, RunCompletedPayload):
            self.usage = event.payload.usage


class SingleTurnChatService:
    def __init__(
        self,
        *,
        model: ModelPort,
        provider: ProviderDescriptor,
        options: ModelOptions,
        id_factory: IdFactory | None = None,
        clock: Clock | None = None,
        monotonic: MonotonicClock | None = None,
    ) -> None:
        self._model = model
        self._provider = provider
        self._options = options
        self._id_factory = id_factory or _default_id_factory
        self._clock = clock or _utc_now
        self._monotonic = monotonic or perf_counter

    async def chat(self, text: str) -> SingleTurnChatResult:
        if len(text) > MESSAGE_CHARACTER_LIMIT:
            raise MessageTooLongError(MESSAGE_CHARACTER_LIMIT)

        user_message = create_user_message(
            text,
            message_id=self._id_factory("msg"),
            created_at=self._clock(),
        )
        request = ModelRequest(messages=(user_message,), tools=(), options=self._options)
        projection = SingleTurnEventProjection()
        started_at = self._monotonic()
        message = await run_protocol(
            request,
            model=self._model,
            sink=projection,
            id_factory=self._id_factory,
            clock=self._clock,
        )
        latency_ms = max(0, round((self._monotonic() - started_at) * 1000))
        if projection.run_id is None:  # pragma: no cover - protects protocol integration
            raise ProtocolValidationError("Model run did not produce a run identifier")
        return SingleTurnChatResult(
            run_id=projection.run_id,
            message=message,
            provider=self._provider.name,
            model=self._provider.model,
            usage=projection.usage,
            latency_ms=latency_ms,
        )


def _default_id_factory(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _utc_now() -> datetime:
    return datetime.now(UTC)
