from __future__ import annotations

from datetime import UTC, datetime

import pytest

from novaagent.domain.errors import EventSequenceError, ProtocolValidationError
from novaagent.domain.events import (
    AgentEvent,
    ArtifactPayload,
    ErrorPayload,
    EventSequenceValidator,
    MessageCompletedPayload,
    MessageStartedPayload,
    ReasoningSummaryDeltaPayload,
    RunCancelledPayload,
    RunCompletedPayload,
    RunFailedPayload,
    RunStartedPayload,
    TextDeltaPayload,
    TokenUsage,
    ToolCallPayload,
    ToolResultPayload,
    validate_event_sequence,
)
from novaagent.domain.messages import (
    FileRefBlock,
    Message,
    MessageRole,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultStatus,
)

NOW = datetime(2026, 8, 17, 2, 0, tzinfo=UTC)


def event(sequence: int, payload: object, *, run_id: str = "run-1") -> AgentEvent:
    return AgentEvent(
        event_id=f"evt-{sequence}",
        run_id=run_id,
        sequence=sequence,
        occurred_at=NOW,
        payload=payload,  # type: ignore[arg-type]
    )


def assistant_message(message_id: str = "msg-1") -> Message:
    return Message(
        message_id,
        MessageRole.ASSISTANT,
        (TextBlock("你好"),),
        NOW,
    )


def successful_events() -> list[AgentEvent]:
    return [
        event(0, RunStartedPayload("session-1")),
        event(1, MessageStartedPayload("msg-1")),
        event(2, TextDeltaPayload("msg-1", "你")),
        event(3, TextDeltaPayload("msg-1", "好")),
        event(4, MessageCompletedPayload(assistant_message())),
        event(5, RunCompletedPayload("msg-1")),
    ]


def test_successful_and_failed_sequences_are_valid() -> None:
    validate_event_sequence(successful_events())
    validate_event_sequence(
        [
            event(0, RunStartedPayload()),
            event(1, ErrorPayload("model_unavailable", "不可用", True)),
            event(2, RunFailedPayload("model_unavailable")),
        ]
    )
    validate_event_sequence(
        [event(0, RunStartedPayload()), event(1, RunCancelledPayload("user request"))]
    )


@pytest.mark.parametrize(
    ("events", "message"),
    [
        ([event(0, MessageStartedPayload("msg-1"))], "First event"),
        ([event(0, RunStartedPayload()), event(2, RunCancelledPayload())], "Expected sequence"),
        (
            [
                event(0, RunStartedPayload()),
                event(1, RunCancelledPayload(), run_id="run-2"),
            ],
            "share one run_id",
        ),
        (
            [event(0, RunStartedPayload()), event(1, RunStartedPayload())],
            "only appear once",
        ),
        (
            [event(0, RunStartedPayload()), event(1, TextDeltaPayload("msg-1", "x"))],
            "earlier message_started",
        ),
        (
            [
                event(0, RunStartedPayload()),
                event(1, MessageStartedPayload("msg-1")),
                event(2, RunCompletedPayload("msg-1")),
            ],
            "requires message_completed",
        ),
        (
            [
                event(0, RunStartedPayload()),
                event(1, ErrorPayload("failed", "failed", False)),
                event(2, TextDeltaPayload("msg-1", "x")),
            ],
            "immediately followed",
        ),
        (
            [event(0, RunStartedPayload()), event(1, RunFailedPayload("failed"))],
            "requires an immediately preceding error",
        ),
    ],
)
def test_invalid_event_sequences_are_rejected(events: list[AgentEvent], message: str) -> None:
    with pytest.raises(EventSequenceError, match=message):
        validate_event_sequence(events)


def test_terminal_event_is_unique_and_required() -> None:
    with pytest.raises(EventSequenceError, match="must not be empty"):
        EventSequenceValidator().finish()
    with pytest.raises(EventSequenceError, match="requires one terminal"):
        validate_event_sequence([event(0, RunStartedPayload())])
    validator = EventSequenceValidator()
    validator.add(event(0, RunStartedPayload()))
    validator.add(event(1, RunCancelledPayload()))
    with pytest.raises(EventSequenceError, match="after a terminal"):
        validator.add(event(2, RunCancelledPayload()))


def test_event_ids_are_unique_within_a_run() -> None:
    duplicate = event(1, RunCancelledPayload())
    duplicate = AgentEvent(  # use the first event's identifier with the next sequence
        event_id="evt-0",
        run_id=duplicate.run_id,
        sequence=duplicate.sequence,
        occurred_at=duplicate.occurred_at,
        payload=duplicate.payload,
    )
    with pytest.raises(EventSequenceError, match="event_id must be unique"):
        validate_event_sequence([event(0, RunStartedPayload()), duplicate])


def test_message_and_tool_correlations_are_enforced() -> None:
    with pytest.raises(EventSequenceError, match="message_started cannot repeat"):
        validate_event_sequence(
            [
                event(0, RunStartedPayload()),
                event(1, MessageStartedPayload("msg-1")),
                event(2, MessageStartedPayload("msg-1")),
            ]
        )
    result = ToolResultBlock("call-1", ToolResultStatus.SUCCESS, (TextBlock("done"),))
    with pytest.raises(EventSequenceError, match="matching tool_call"):
        validate_event_sequence(
            [
                event(0, RunStartedPayload()),
                event(1, ToolResultPayload(result)),
            ]
        )
    call = ToolCallBlock("call-1", "lookup", {})
    with pytest.raises(EventSequenceError, match="call_id must be unique"):
        validate_event_sequence(
            [
                event(0, RunStartedPayload()),
                event(1, ToolCallPayload(call)),
                event(2, ToolCallPayload(call)),
            ]
        )
    validate_event_sequence(
        [
            event(0, RunStartedPayload()),
            event(1, ToolCallPayload(call)),
            event(2, ToolResultPayload(result)),
            event(3, RunCancelledPayload()),
        ]
    )


def test_completed_message_must_match_started_assistant_message() -> None:
    user_message = Message("msg-1", MessageRole.USER, (TextBlock("hello"),), NOW)
    with pytest.raises(EventSequenceError, match="assistant role"):
        validate_event_sequence(
            [
                event(0, RunStartedPayload()),
                event(1, MessageStartedPayload("msg-1")),
                event(2, MessageCompletedPayload(user_message)),
            ]
        )
    with pytest.raises(EventSequenceError, match="does not match"):
        validate_event_sequence(successful_events()[:-1] + [event(5, RunCompletedPayload("other"))])
    with pytest.raises(EventSequenceError, match="requires an earlier message_started"):
        validate_event_sequence(
            [event(0, RunStartedPayload()), event(1, MessageCompletedPayload(assistant_message()))]
        )
    completed_twice = successful_events()[:-1]
    completed_twice.append(event(5, MessageCompletedPayload(assistant_message())))
    with pytest.raises(EventSequenceError, match="can only appear once"):
        validate_event_sequence(completed_twice)
    mismatched = Message("msg-1", MessageRole.ASSISTANT, (TextBlock("different"),), NOW)
    with pytest.raises(EventSequenceError, match="deltas do not match"):
        validate_event_sequence(
            [
                event(0, RunStartedPayload()),
                event(1, MessageStartedPayload("msg-1")),
                event(2, TextDeltaPayload("msg-1", "streamed")),
                event(3, MessageCompletedPayload(mismatched)),
            ]
        )


def test_failed_event_code_must_match_the_error() -> None:
    with pytest.raises(EventSequenceError, match="does not match"):
        validate_event_sequence(
            [
                event(0, RunStartedPayload()),
                event(1, ErrorPayload("model_failed", "failed", False)),
                event(2, RunFailedPayload("different")),
            ]
        )


def test_event_value_validation() -> None:
    with pytest.raises(ProtocolValidationError, match="non-negative"):
        event(-1, RunStartedPayload())
    with pytest.raises(ProtocolValidationError, match="Unknown event payload"):
        event(0, object())
    with pytest.raises(ProtocolValidationError, match="must not be empty"):
        TextDeltaPayload("msg-1", "")
    with pytest.raises(ProtocolValidationError, match="must not be empty"):
        ReasoningSummaryDeltaPayload("")
    with pytest.raises(ProtocolValidationError, match="Identifier"):
        ArtifactPayload(" ", FileRefBlock("file-1", "text/plain"))
    with pytest.raises(ProtocolValidationError, match="Error code"):
        ErrorPayload(" ", "failed", False)
    with pytest.raises(ProtocolValidationError, match="Error message"):
        ErrorPayload("failed", " ", False)
    with pytest.raises(ProtocolValidationError, match="error_code"):
        RunFailedPayload(" ")
    with pytest.raises(ProtocolValidationError, match="Name"):
        RunCancelledPayload(" ")
    with pytest.raises(ProtocolValidationError, match="input_tokens"):
        TokenUsage(-1, 0)
    with pytest.raises(ProtocolValidationError, match="output_tokens"):
        TokenUsage(0, -1)
