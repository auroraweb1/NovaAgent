from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from novaagent.domain.errors import (
    SessionBusyError,
    SessionLimitReachedError,
    SessionNotFoundError,
    SessionRevisionConflictError,
)
from novaagent.domain.messages import Message
from novaagent.domain.sessions import SessionSnapshot, SessionSummary, title_from_message

MAX_SESSIONS = 100


@dataclass(slots=True)
class _SessionRecord:
    session_id: str
    revision: int
    title: str
    messages: list[Message]
    created_at: datetime
    updated_at: datetime
    active_run_id: str | None
    lock: asyncio.Lock


class InMemorySessionStore:
    def __init__(self, *, max_sessions: int = MAX_SESSIONS) -> None:
        self._max_sessions = max_sessions
        self._records: dict[str, _SessionRecord] = {}
        self._registry_lock = asyncio.Lock()

    async def create_session(self) -> SessionSnapshot:
        async with self._registry_lock:
            if len(self._records) >= self._max_sessions:
                raise SessionLimitReachedError()
            now = datetime.now(UTC)
            session_id = f"session-{uuid4()}"
            record = _SessionRecord(
                session_id=session_id,
                revision=0,
                title="新会话",
                messages=[],
                created_at=now,
                updated_at=now,
                active_run_id=None,
                lock=asyncio.Lock(),
            )
            self._records[session_id] = record
            return _snapshot(record)

    async def list_sessions(self) -> tuple[SessionSummary, ...]:
        async with self._registry_lock:
            records = tuple(self._records.values())
        snapshots: list[SessionSummary] = []
        for record in records:
            async with record.lock:
                snapshots.append(_summary(record))
        snapshots.sort(key=lambda item: (item.updated_at, item.session_id), reverse=True)
        return tuple(snapshots)

    async def get_session(self, session_id: str) -> SessionSnapshot:
        record = await self._record(session_id)
        async with record.lock:
            return _snapshot(record)

    async def commit_turn(
        self,
        session_id: str,
        expected_revision: int,
        user: Message,
        assistant: Message,
    ) -> SessionSnapshot:
        record = await self._record(session_id)
        async with record.lock:
            _check_revision(record, expected_revision)
            if record.active_run_id is None:
                raise SessionBusyError()
            record.messages.extend((user, assistant))
            if record.title == "新会话":
                record.title = title_from_message(user)
            record.revision += 1
            record.updated_at = datetime.now(UTC)
            return _snapshot(record)

    async def clear_session(self, session_id: str, expected_revision: int) -> SessionSnapshot:
        record = await self._record(session_id)
        async with record.lock:
            _check_revision(record, expected_revision)
            if record.active_run_id is not None:
                raise SessionBusyError()
            record.messages.clear()
            record.title = "新会话"
            record.revision += 1
            record.updated_at = datetime.now(UTC)
            return _snapshot(record)

    async def delete_session(self, session_id: str, expected_revision: int) -> None:
        record = await self._record(session_id)
        async with record.lock:
            _check_revision(record, expected_revision)
            if record.active_run_id is not None:
                raise SessionBusyError()
        async with self._registry_lock:
            current = self._records.get(session_id)
            if current is record:
                del self._records[session_id]

    async def set_active_run(
        self, session_id: str, expected_revision: int, run_id: str
    ) -> SessionSnapshot:
        record = await self._record(session_id)
        async with record.lock:
            _check_revision(record, expected_revision)
            if record.active_run_id is not None:
                raise SessionBusyError()
            record.active_run_id = run_id
            record.updated_at = datetime.now(UTC)
            return _snapshot(record)

    async def clear_active_run(self, session_id: str, run_id: str) -> None:
        record = await self._record(session_id)
        async with record.lock:
            if record.active_run_id == run_id:
                record.active_run_id = None
                record.updated_at = datetime.now(UTC)

    async def _record(self, session_id: str) -> _SessionRecord:
        async with self._registry_lock:
            record = self._records.get(session_id)
        if record is None:
            raise SessionNotFoundError()
        return record


def _check_revision(record: _SessionRecord, expected_revision: int) -> None:
    if expected_revision != record.revision:
        raise SessionRevisionConflictError()


def _snapshot(record: _SessionRecord) -> SessionSnapshot:
    return SessionSnapshot(
        session_id=record.session_id,
        revision=record.revision,
        title=record.title,
        messages=tuple(record.messages),
        created_at=record.created_at,
        updated_at=record.updated_at,
        active_run_id=record.active_run_id,
    )


def _summary(record: _SessionRecord) -> SessionSummary:
    return SessionSummary(
        session_id=record.session_id,
        revision=record.revision,
        title=record.title,
        message_count=len(record.messages),
        created_at=record.created_at,
        updated_at=record.updated_at,
        active_run_id=record.active_run_id,
    )
