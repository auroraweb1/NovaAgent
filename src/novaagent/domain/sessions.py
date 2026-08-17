from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from novaagent.domain.errors import ProtocolValidationError
from novaagent.domain.messages import Message, MessageRole, TextBlock, validate_identifier


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    session_id: str
    revision: int
    title: str
    messages: tuple[Message, ...]
    created_at: datetime
    updated_at: datetime
    active_run_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.session_id, field_path="session_id")
        if isinstance(self.revision, bool) or self.revision < 0:
            raise ProtocolValidationError("revision must be non-negative", field="revision")
        if not self.title.strip():
            raise ProtocolValidationError("title must not be empty", field="title")
        object.__setattr__(self, "messages", tuple(self.messages))
        if len(self.messages) % 2:
            raise ProtocolValidationError(
                "session messages must contain complete user/assistant turns",
                field="messages",
            )
        for index in range(0, len(self.messages), 2):
            if self.messages[index].role is not MessageRole.USER:
                raise ProtocolValidationError(
                    "session turns must start with a user message", field=f"messages[{index}]"
                )
            if self.messages[index + 1].role is not MessageRole.ASSISTANT:
                raise ProtocolValidationError(
                    "session turns must end with an assistant message",
                    field=f"messages[{index + 1}]",
                )
        if self.active_run_id is not None:
            validate_identifier(self.active_run_id, field_path="active_run_id")

    @property
    def message_count(self) -> int:
        return len(self.messages)


@dataclass(frozen=True, slots=True)
class SessionSummary:
    session_id: str
    revision: int
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime
    active_run_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.session_id, field_path="session_id")
        if self.revision < 0 or self.message_count < 0:
            raise ProtocolValidationError("session counters must be non-negative")
        if not self.title.strip():
            raise ProtocolValidationError("title must not be empty", field="title")
        if self.active_run_id is not None:
            validate_identifier(self.active_run_id, field_path="active_run_id")


def title_from_message(message: Message) -> str:
    for block in message.content:
        if isinstance(block, TextBlock) and block.text.strip():
            title = " ".join(block.text.strip().split())
            return title[:40] or "新会话"
    return "新会话"
