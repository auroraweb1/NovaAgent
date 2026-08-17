from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novaagent.domain.sessions import SessionSnapshot, SessionSummary
from novaagent.interfaces.web.protocol import message_to_dict


class SessionProtocolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StreamChatRequestSchema(SessionProtocolSchema):
    message: str
    expected_revision: int = Field(ge=0)


class SessionSummarySchema(SessionProtocolSchema):
    session_id: str
    revision: int
    title: str
    message_count: int
    active_run_id: str | None
    created_at: datetime
    updated_at: datetime


class SessionResponseSchema(SessionProtocolSchema):
    protocol_version: Literal["1"]
    session: SessionSummarySchema


class SessionDetailResponseSchema(SessionProtocolSchema):
    protocol_version: Literal["1"]
    session: SessionSummarySchema
    messages: list[dict[str, object]]


def summary_to_schema(summary: SessionSummary) -> SessionSummarySchema:
    return SessionSummarySchema.model_validate(
        {
            "session_id": summary.session_id,
            "revision": summary.revision,
            "title": summary.title,
            "message_count": summary.message_count,
            "active_run_id": summary.active_run_id,
            "created_at": summary.created_at,
            "updated_at": summary.updated_at,
        }
    )


def session_response(snapshot: SessionSnapshot) -> SessionResponseSchema:
    return SessionResponseSchema(
        protocol_version="1",
        session=summary_to_schema(
            SessionSummary(
                session_id=snapshot.session_id,
                revision=snapshot.revision,
                title=snapshot.title,
                message_count=snapshot.message_count,
                active_run_id=snapshot.active_run_id,
                created_at=snapshot.created_at,
                updated_at=snapshot.updated_at,
            )
        ),
    )


def session_detail_response(snapshot: SessionSnapshot) -> SessionDetailResponseSchema:
    return SessionDetailResponseSchema(
        protocol_version="1",
        session=session_response(snapshot).session,
        messages=[message_to_dict(message) for message in snapshot.messages],
    )
