from __future__ import annotations

from datetime import UTC, datetime

import pytest

from novaagent.domain.errors import (
    ProtocolValidationError,
    UnsupportedContentTypeError,
    UnsupportedProtocolVersionError,
)
from novaagent.domain.events import (
    AgentEvent,
    ArtifactPayload,
    ContextPreparedPayload,
    ErrorPayload,
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
)
from novaagent.domain.messages import (
    AudioRefBlock,
    FileRefBlock,
    ImageRefBlock,
    Message,
    MessageRole,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultStatus,
)
from novaagent.interfaces.web.protocol import (
    event_from_dict,
    event_to_dict,
    message_from_dict,
    message_to_dict,
)

NOW = datetime(2026, 8, 17, 2, 0, tzinfo=UTC)


def complete_message() -> Message:
    call = ToolCallBlock("call-1", "lookup", {"query": "NovaAgent"})
    result = ToolResultBlock("call-1", ToolResultStatus.SUCCESS, (TextBlock("found"),))
    return Message(
        message_id="msg-1",
        role=MessageRole.ASSISTANT,
        content=(
            TextBlock("answer"),
            ImageRefBlock("image-1", "image/png", "image.png", 10, "a" * 64),
            AudioRefBlock("audio-1", "audio/mpeg"),
            FileRefBlock("file-1", "text/plain"),
            call,
            result,
        ),
        created_at=NOW,
        name="assistant",
        metadata={"nested": [1, True, None]},
    )


def test_message_json_round_trip_covers_every_content_block() -> None:
    message = complete_message()
    encoded = message_to_dict(message)

    assert encoded["protocol_version"] == "1"
    assert encoded["created_at"] == "2026-08-17T02:00:00Z"
    assert encoded["metadata"] == {"nested": [1, True, None]}
    assert message_from_dict(encoded) == message


def test_empty_metadata_is_always_serialized_and_none_fields_are_omitted() -> None:
    message = Message("msg-1", MessageRole.USER, (TextBlock("hello"),), NOW)
    encoded = message_to_dict(message)

    assert encoded["metadata"] == {}
    assert "name" not in encoded


def test_same_version_unknown_optional_fields_are_ignored() -> None:
    encoded = message_to_dict(Message("msg-1", MessageRole.USER, (TextBlock("hello"),), NOW))
    encoded["future_optional"] = {"enabled": True}
    content = encoded["content"]
    assert isinstance(content, list)
    content[0]["future_optional"] = "ignored"

    assert message_from_dict(encoded).content == (TextBlock("hello"),)


def test_unknown_version_type_and_missing_fields_are_rejected() -> None:
    base = message_to_dict(Message("msg-1", MessageRole.USER, (TextBlock("hello"),), NOW))
    with pytest.raises(UnsupportedProtocolVersionError):
        message_from_dict({**base, "protocol_version": "2"})
    with pytest.raises(UnsupportedContentTypeError):
        message_from_dict({**base, "content": [{"type": "video", "data": "x"}]})
    missing = dict(base)
    del missing["message_id"]
    with pytest.raises(ProtocolValidationError) as captured:
        message_from_dict(missing)
    assert captured.value.field == "message_id"
    with pytest.raises(ProtocolValidationError) as timestamp_error:
        message_from_dict({**base, "created_at": "not-a-time"})
    assert timestamp_error.value.field == "created_at"


@pytest.mark.parametrize(
    "payload",
    [
        RunStartedPayload("session-1"),
        ContextPreparedPayload(2, 0, 120),
        MessageStartedPayload("msg-1"),
        TextDeltaPayload("msg-1", "回答"),
        ReasoningSummaryDeltaPayload("先检查输入"),
        ToolCallPayload(ToolCallBlock("call-1", "lookup", {"query": "x"})),
        ToolResultPayload(
            ToolResultBlock(
                "call-1",
                ToolResultStatus.ERROR,
                (TextBlock("failed"),),
                "lookup_failed",
            )
        ),
        ArtifactPayload("artifact-1", FileRefBlock("file-1", "text/plain")),
        ErrorPayload("model_unavailable", "暂时不可用", True, "model"),
        MessageCompletedPayload(complete_message()),
        RunCompletedPayload("msg-1", TokenUsage(12, 5)),
        RunFailedPayload("model_unavailable"),
        RunCancelledPayload("user request"),
    ],
)
def test_event_json_round_trip(payload: object) -> None:
    event = AgentEvent("evt-1", "run-1", 0, NOW, payload)  # type: ignore[arg-type]
    encoded = event_to_dict(event)

    assert encoded["protocol_version"] == "1"
    assert encoded["type"] == event.type
    assert event_from_dict(encoded) == event


def test_reasoning_summary_has_no_raw_chain_of_thought_field() -> None:
    event = AgentEvent("evt-1", "run-1", 0, NOW, ReasoningSummaryDeltaPayload("处理思路"))
    encoded = event_to_dict(event)

    assert encoded["type"] == "reasoning_summary_delta"
    assert encoded["payload"] == {"delta": "处理思路"}
    assert "reasoning" not in encoded


def test_unknown_event_type_and_version_are_rejected() -> None:
    event = AgentEvent("evt-1", "run-1", 0, NOW, RunStartedPayload())
    encoded = event_to_dict(event)
    with pytest.raises(ProtocolValidationError, match="Unknown event type"):
        event_from_dict({**encoded, "type": "future_event"})
    with pytest.raises(UnsupportedProtocolVersionError):
        event_from_dict({**encoded, "protocol_version": "99"})


def test_malformed_event_payloads_are_rejected_with_field_paths() -> None:
    encoded = event_to_dict(AgentEvent("evt-1", "run-1", 0, NOW, RunStartedPayload()))
    with pytest.raises(ProtocolValidationError) as captured:
        event_from_dict({**encoded, "payload": "not-an-object"})
    assert captured.value.field == "payload"

    with pytest.raises(ProtocolValidationError, match="must be a boolean"):
        event_from_dict(
            {
                **encoded,
                "type": "error",
                "payload": {"code": "failed", "message": "failed", "retryable": "yes"},
            }
        )
    with pytest.raises(ProtocolValidationError, match="must be an object"):
        event_from_dict({**encoded, "type": "tool_call", "payload": {"call": "bad"}})
