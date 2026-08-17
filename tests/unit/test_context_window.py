from __future__ import annotations

from datetime import UTC, datetime

import pytest

from novaagent.application.chat.context_window import select_context
from novaagent.domain.errors import ProtocolValidationError
from novaagent.domain.messages import Message, MessageRole, TextBlock

NOW = datetime(2026, 8, 17, tzinfo=UTC)


def message(message_id: str, role: MessageRole, text: str) -> Message:
    return Message(message_id, role, (TextBlock(text),), NOW)


def test_context_keeps_recent_complete_turns_and_reports_dropped_messages() -> None:
    history = tuple(
        item
        for index in range(3)
        for item in (
            message(f"u-{index}", MessageRole.USER, f"old user {index}"),
            message(f"a-{index}", MessageRole.ASSISTANT, f"old answer {index}"),
        )
    )

    selection = select_context(
        system_messages=(),
        history=history,
        current_user=message("u-current", MessageRole.USER, "current"),
        max_turns=2,
    )

    assert [item.message_id for item in selection.messages] == [
        "u-1",
        "a-1",
        "u-2",
        "a-2",
        "u-current",
    ]
    assert selection.included_messages == 4
    assert selection.dropped_messages == 2


def test_context_rejects_oversized_current_message() -> None:
    with pytest.raises(ProtocolValidationError, match="context budget"):
        select_context(
            system_messages=(),
            history=(),
            current_user=message("u", MessageRole.USER, "x" * 100),
            budget=10,
        )
