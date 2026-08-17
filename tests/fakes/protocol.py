from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from novaagent.domain.events import AgentEvent, TextDeltaPayload, validate_event_sequence
from novaagent.domain.messages import Message, validate_identifier
from novaagent.domain.ports import ModelOutput, ModelRequest


@dataclass(slots=True)
class ScriptedModel:
    outputs: tuple[ModelOutput, ...]
    failure: Exception | None = None
    requests: list[ModelRequest] | None = None

    def __post_init__(self) -> None:
        self.outputs = tuple(self.outputs)
        if self.requests is None:
            self.requests = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelOutput]:
        assert self.requests is not None
        self.requests.append(request)
        for output in self.outputs:
            yield output
        if self.failure is not None:
            raise self.failure


@dataclass(slots=True)
class InMemoryEventSink:
    received: list[AgentEvent] | None = None

    def __post_init__(self) -> None:
        if self.received is None:
            self.received = []

    async def publish(self, event: AgentEvent) -> None:
        assert self.received is not None
        self.received.append(event)

    @property
    def events(self) -> tuple[AgentEvent, ...]:
        assert self.received is not None
        return tuple(self.received)

    def validate(self) -> None:
        validate_event_sequence(self.events)

    def text(self) -> str:
        return "".join(
            event.payload.delta
            for event in self.events
            if isinstance(event.payload, TextDeltaPayload)
        )


class InMemorySessionStore:
    def __init__(self) -> None:
        self._messages: dict[str, tuple[Message, ...]] = {}

    async def get_messages(self, session_id: str) -> tuple[Message, ...]:
        validate_identifier(session_id, field_path="session_id")
        return self._messages.get(session_id, ())

    async def append_messages(self, session_id: str, messages: Sequence[Message]) -> None:
        validate_identifier(session_id, field_path="session_id")
        batch = tuple(messages)
        self._messages[session_id] = self._messages.get(session_id, ()) + batch
