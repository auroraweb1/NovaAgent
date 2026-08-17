from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest

from novaagent.application.protocol import create_user_message
from novaagent.domain.errors import (
    EmptyMessageError,
    MessageRoleError,
    ProtocolValidationError,
    ToolCallError,
)
from novaagent.domain.messages import (
    FileRefBlock,
    ImageRefBlock,
    JSONInput,
    Message,
    MessageRole,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultStatus,
    freeze_json,
)

NOW = datetime(2026, 8, 17, 2, 0, tzinfo=UTC)


def test_user_message_preserves_valid_whitespace_and_is_frozen() -> None:
    message = create_user_message(" 你好\n", message_id="msg-1", created_at=NOW)

    assert message.role is MessageRole.USER
    assert message.content == (TextBlock(" 你好\n"),)
    assert dict(message.metadata) == {}
    with pytest.raises(FrozenInstanceError):
        message.name = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("text", ["", " ", "\n", "\t", " \n\t "])
def test_blank_user_input_has_stable_product_error(text: str) -> None:
    with pytest.raises(EmptyMessageError) as captured:
        create_user_message(text, message_id="msg-1", created_at=NOW)

    assert captured.value.code == "message_empty"
    assert captured.value.field == "message"
    assert captured.value.message == "请输入内容后再发送"


def test_message_rejects_empty_or_whitespace_only_content() -> None:
    with pytest.raises(ProtocolValidationError, match="must not be empty"):
        TextBlock("")
    with pytest.raises(ProtocolValidationError, match="meaningful"):
        Message("msg-1", MessageRole.USER, (TextBlock(" \n"),), NOW)
    with pytest.raises(ProtocolValidationError, match="must not be empty"):
        Message("msg-1", MessageRole.USER, (), NOW)


def test_message_validates_identity_time_role_and_name() -> None:
    with pytest.raises(ProtocolValidationError, match="Identifier"):
        Message(" ", MessageRole.USER, (TextBlock("hello"),), NOW)
    with pytest.raises(ProtocolValidationError, match="timezone-aware UTC"):
        Message(
            "msg-1",
            MessageRole.USER,
            (TextBlock("hello"),),
            NOW.astimezone(timezone(timedelta(hours=8))),
        )
    with pytest.raises(MessageRoleError, match="Unknown"):
        Message("msg-1", "visitor", (TextBlock("hello"),), NOW)  # type: ignore[arg-type]
    with pytest.raises(ProtocolValidationError, match="Name"):
        Message("msg-1", MessageRole.USER, (TextBlock("hello"),), NOW, name=" ")


def test_message_enforces_role_content_combinations() -> None:
    resource = FileRefBlock("file-1", "text/plain")
    with pytest.raises(MessageRoleError, match="only support text"):
        Message("msg-1", MessageRole.SYSTEM, (resource,), NOW)
    with pytest.raises(MessageRoleError, match="require a tool result"):
        Message("msg-2", MessageRole.TOOL, (TextBlock("done"),), NOW)


def test_resource_reference_validation() -> None:
    block = ImageRefBlock(
        resource_id="image-1",
        media_type="image/png",
        name="diagram.png",
        size_bytes=12,
        sha256="a" * 64,
    )
    assert block.type == "image_ref"
    with pytest.raises(ProtocolValidationError, match="MIME"):
        FileRefBlock("file-1", "plain-text")
    with pytest.raises(ProtocolValidationError, match="non-negative"):
        FileRefBlock("file-1", "text/plain", size_bytes=-1)
    with pytest.raises(ProtocolValidationError, match="64 hexadecimal"):
        FileRefBlock("file-1", "text/plain", sha256="bad")


def test_tool_call_defensively_freezes_json_arguments() -> None:
    raw: dict[str, JSONInput] = {"items": [1, {"enabled": True}]}
    block = ToolCallBlock("call-1", "lookup", raw)
    raw["items"] = []

    assert block.arguments["items"] == (1, {"enabled": True})
    nested = block.arguments["items"]
    assert isinstance(nested, tuple)
    with pytest.raises(TypeError):
        cast(dict[str, JSONInput], block.arguments)["new"] = "value"


def test_json_freezer_rejects_unsupported_values_and_numbers() -> None:
    with pytest.raises(ProtocolValidationError, match="not JSON-compatible"):
        freeze_json(object())
    with pytest.raises(ProtocolValidationError, match="finite"):
        freeze_json(float("nan"))
    with pytest.raises(ProtocolValidationError, match="keys"):
        freeze_json({1: "value"})


def test_tool_call_and_result_invariants() -> None:
    with pytest.raises(ToolCallError, match="call_id"):
        ToolCallBlock("", "lookup", {})
    with pytest.raises(ToolCallError, match="tool_name"):
        ToolCallBlock("call-1", " ", {})
    with pytest.raises(ProtocolValidationError, match="require error_code"):
        ToolResultBlock("call-1", ToolResultStatus.ERROR, (TextBlock("failed"),))
    with pytest.raises(ProtocolValidationError, match="cannot include"):
        ToolResultBlock("call-1", ToolResultStatus.SUCCESS, (TextBlock("done"),), "unexpected")
    with pytest.raises(ProtocolValidationError, match="Unknown tool result status"):
        ToolResultBlock("call-1", "pending", (TextBlock("wait"),))  # type: ignore[arg-type]


def test_metadata_is_copied_and_cannot_override_message_fields() -> None:
    raw: dict[str, JSONInput] = {"source": {"name": "web"}}
    message = Message("msg-1", MessageRole.USER, (TextBlock("hello"),), NOW, metadata=raw)
    raw.clear()

    assert message.metadata == {"source": {"name": "web"}}
    with pytest.raises(TypeError):
        cast(dict[str, JSONInput], message.metadata)["message_id"] = "changed"
