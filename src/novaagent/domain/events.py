from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from novaagent.domain.errors import EventSequenceError, ProtocolValidationError
from novaagent.domain.messages import (
    FileRefBlock,
    Message,
    MessageRole,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    validate_identifier,
    validate_optional_name,
    validate_utc_datetime,
)


@dataclass(frozen=True)
class DiagnosticEvent:
    """A serializable diagnostic item emitted by the foundation services."""

    name: str
    status: str
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if isinstance(self.input_tokens, bool) or self.input_tokens < 0:
            raise ProtocolValidationError(
                "input_tokens must be non-negative", field="usage.input_tokens"
            )
        if isinstance(self.output_tokens, bool) or self.output_tokens < 0:
            raise ProtocolValidationError(
                "output_tokens must be non-negative", field="usage.output_tokens"
            )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class RunStartedPayload:
    type: ClassVar[str] = "run_started"
    session_id: str | None = None

    def __post_init__(self) -> None:
        if self.session_id is not None:
            validate_identifier(self.session_id, field_path="payload.session_id")


@dataclass(frozen=True, slots=True)
class MessageStartedPayload:
    type: ClassVar[str] = "message_started"
    message_id: str

    def __post_init__(self) -> None:
        validate_identifier(self.message_id, field_path="payload.message_id")


@dataclass(frozen=True, slots=True)
class TextDeltaPayload:
    type: ClassVar[str] = "text_delta"
    message_id: str
    delta: str

    def __post_init__(self) -> None:
        validate_identifier(self.message_id, field_path="payload.message_id")
        if self.delta == "":
            raise ProtocolValidationError("Text delta must not be empty", field="payload.delta")


@dataclass(frozen=True, slots=True)
class ReasoningSummaryDeltaPayload:
    type: ClassVar[str] = "reasoning_summary_delta"
    delta: str

    def __post_init__(self) -> None:
        if self.delta == "":
            raise ProtocolValidationError(
                "Reasoning summary delta must not be empty", field="payload.delta"
            )


@dataclass(frozen=True, slots=True)
class ToolCallPayload:
    type: ClassVar[str] = "tool_call"
    call: ToolCallBlock


@dataclass(frozen=True, slots=True)
class ToolResultPayload:
    type: ClassVar[str] = "tool_result"
    result: ToolResultBlock


@dataclass(frozen=True, slots=True)
class ArtifactPayload:
    type: ClassVar[str] = "artifact"
    artifact_id: str
    resource: FileRefBlock

    def __post_init__(self) -> None:
        validate_identifier(self.artifact_id, field_path="payload.artifact_id")


@dataclass(frozen=True, slots=True)
class ErrorPayload:
    type: ClassVar[str] = "error"
    code: str
    message: str
    retryable: bool
    field: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ProtocolValidationError("Error code must be non-empty", field="payload.code")
        if not self.message.strip():
            raise ProtocolValidationError(
                "Error message must be non-empty", field="payload.message"
            )
        validate_optional_name(self.field, field_path="payload.field")


@dataclass(frozen=True, slots=True)
class MessageCompletedPayload:
    type: ClassVar[str] = "message_completed"
    message: Message


@dataclass(frozen=True, slots=True)
class RunCompletedPayload:
    type: ClassVar[str] = "run_completed"
    message_id: str
    usage: TokenUsage | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.message_id, field_path="payload.message_id")


@dataclass(frozen=True, slots=True)
class RunFailedPayload:
    type: ClassVar[str] = "run_failed"
    error_code: str

    def __post_init__(self) -> None:
        if not self.error_code.strip():
            raise ProtocolValidationError(
                "Failure error_code must be non-empty", field="payload.error_code"
            )


@dataclass(frozen=True, slots=True)
class RunCancelledPayload:
    type: ClassVar[str] = "run_cancelled"
    reason: str | None = None

    def __post_init__(self) -> None:
        validate_optional_name(self.reason, field_path="payload.reason")


type AgentEventPayload = (
    RunStartedPayload
    | MessageStartedPayload
    | TextDeltaPayload
    | ReasoningSummaryDeltaPayload
    | ToolCallPayload
    | ToolResultPayload
    | ArtifactPayload
    | ErrorPayload
    | MessageCompletedPayload
    | RunCompletedPayload
    | RunFailedPayload
    | RunCancelledPayload
)

_AGENT_EVENT_PAYLOAD_TYPES = (
    RunStartedPayload,
    MessageStartedPayload,
    TextDeltaPayload,
    ReasoningSummaryDeltaPayload,
    ToolCallPayload,
    ToolResultPayload,
    ArtifactPayload,
    ErrorPayload,
    MessageCompletedPayload,
    RunCompletedPayload,
    RunFailedPayload,
    RunCancelledPayload,
)


@dataclass(frozen=True, slots=True)
class AgentEvent:
    event_id: str
    run_id: str
    sequence: int
    occurred_at: datetime
    payload: AgentEventPayload

    def __post_init__(self) -> None:
        validate_identifier(self.event_id, field_path="event_id")
        validate_identifier(self.run_id, field_path="run_id")
        if isinstance(self.sequence, bool) or self.sequence < 0:
            raise ProtocolValidationError("sequence must be non-negative", field="sequence")
        validate_utc_datetime(self.occurred_at, field_path="occurred_at")
        if not isinstance(self.payload, _AGENT_EVENT_PAYLOAD_TYPES):
            raise ProtocolValidationError("Unknown event payload", field="payload")

    @property
    def type(self) -> str:
        return self.payload.type


TERMINAL_EVENT_TYPES = frozenset(
    {RunCompletedPayload.type, RunFailedPayload.type, RunCancelledPayload.type}
)


@dataclass(slots=True)
class EventSequenceValidator:
    """Incrementally validates the ordering and correlation rules for one run."""

    _run_id: str | None = None
    _next_sequence: int = 0
    _event_ids: set[str] = field(default_factory=set)
    _message_ids: set[str] = field(default_factory=set)
    _text_parts: dict[str, list[str]] = field(default_factory=dict)
    _completed_message_id: str | None = None
    _tool_call_ids: set[str] = field(default_factory=set)
    _error_code: str | None = None
    _terminal_type: str | None = None

    def add(self, event: AgentEvent) -> None:
        self._validate_common(event)
        self._validate_payload(event)
        self._run_id = event.run_id
        self._event_ids.add(event.event_id)
        self._next_sequence += 1
        if event.type in TERMINAL_EVENT_TYPES:
            self._terminal_type = event.type

    def finish(self) -> None:
        if self._run_id is None:
            raise EventSequenceError("Event sequence must not be empty")
        if self._terminal_type is None:
            raise EventSequenceError("Event sequence requires one terminal event")

    def _validate_common(self, event: AgentEvent) -> None:
        if self._terminal_type is not None:
            raise EventSequenceError("No event is allowed after a terminal event")
        if event.event_id in self._event_ids:
            raise EventSequenceError("event_id must be unique", field="event_id")
        if self._run_id is None:
            if event.type != RunStartedPayload.type:
                raise EventSequenceError("First event must be run_started", field="type")
        else:
            if event.run_id != self._run_id:
                raise EventSequenceError("All events must share one run_id", field="run_id")
            if event.type == RunStartedPayload.type:
                raise EventSequenceError("run_started can only appear once", field="type")
        if event.sequence != self._next_sequence:
            raise EventSequenceError(
                f"Expected sequence {self._next_sequence}, got {event.sequence}",
                field="sequence",
            )
        if self._error_code is not None and event.type != RunFailedPayload.type:
            raise EventSequenceError("error must be immediately followed by run_failed")

    def _validate_payload(self, event: AgentEvent) -> None:
        payload = event.payload
        if isinstance(payload, MessageStartedPayload):
            if payload.message_id in self._message_ids:
                raise EventSequenceError("message_started cannot repeat a message_id")
            self._message_ids.add(payload.message_id)
            self._text_parts[payload.message_id] = []
        elif isinstance(payload, TextDeltaPayload):
            if payload.message_id not in self._message_ids:
                raise EventSequenceError("text_delta requires an earlier message_started")
            self._text_parts[payload.message_id].append(payload.delta)
        elif isinstance(payload, ToolCallPayload):
            call_id = payload.call.call_id
            if call_id in self._tool_call_ids:
                raise EventSequenceError("tool_call call_id must be unique")
            self._tool_call_ids.add(call_id)
        elif isinstance(payload, ToolResultPayload):
            if payload.result.call_id not in self._tool_call_ids:
                raise EventSequenceError("tool_result requires an earlier matching tool_call")
        elif isinstance(payload, MessageCompletedPayload):
            self._validate_message_completed(payload)
        elif isinstance(payload, ErrorPayload):
            self._error_code = payload.code
        elif isinstance(payload, RunCompletedPayload):
            if self._completed_message_id is None:
                raise EventSequenceError("run_completed requires message_completed")
            if payload.message_id != self._completed_message_id:
                raise EventSequenceError("run_completed message_id does not match final message")
        elif isinstance(payload, RunFailedPayload):
            if self._error_code is None:
                raise EventSequenceError("run_failed requires an immediately preceding error")
            if payload.error_code != self._error_code:
                raise EventSequenceError("run_failed error_code does not match error")

    def _validate_message_completed(self, payload: MessageCompletedPayload) -> None:
        message = payload.message
        if self._completed_message_id is not None:
            raise EventSequenceError("message_completed can only appear once")
        if message.message_id not in self._message_ids:
            raise EventSequenceError("message_completed requires an earlier message_started")
        if message.role is not MessageRole.ASSISTANT:
            raise EventSequenceError("Completed output message must use assistant role")
        deltas = self._text_parts[message.message_id]
        final_text = "".join(
            block.text for block in message.content if isinstance(block, TextBlock)
        )
        if deltas and "".join(deltas) != final_text:
            raise EventSequenceError("Text deltas do not match the completed message")
        self._completed_message_id = message.message_id


def validate_event_sequence(events: tuple[AgentEvent, ...] | list[AgentEvent]) -> None:
    validator = EventSequenceValidator()
    for event in events:
        validator.add(event)
    validator.finish()
