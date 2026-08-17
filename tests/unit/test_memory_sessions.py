from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from novaagent.domain.errors import (
    SessionBusyError,
    SessionLimitReachedError,
    SessionNotFoundError,
    SessionRevisionConflictError,
)
from novaagent.domain.messages import Message, MessageRole, TextBlock
from novaagent.infrastructure.sessions import InMemorySessionStore

NOW = datetime(2026, 8, 17, tzinfo=UTC)


def message(message_id: str, role: MessageRole, text: str) -> Message:
    return Message(message_id, role, (TextBlock(text),), NOW)


def test_memory_store_commits_turns_and_enforces_revision() -> None:
    asyncio.run(_test_memory_store_commits_turns_and_enforces_revision())


async def _test_memory_store_commits_turns_and_enforces_revision() -> None:
    store = InMemorySessionStore()
    session = await store.create_session()
    await store.set_active_run(session.session_id, 0, "run-1")
    updated = await store.commit_turn(
        session.session_id,
        0,
        message("u", MessageRole.USER, "hello"),
        message("a", MessageRole.ASSISTANT, "world"),
    )
    assert updated.revision == 1
    assert updated.title == "hello"
    assert updated.message_count == 2

    with pytest.raises(SessionRevisionConflictError):
        await store.set_active_run(session.session_id, 0, "run-2")


def test_memory_store_rejects_busy_clear_and_isolates_sessions() -> None:
    asyncio.run(_test_memory_store_rejects_busy_clear_and_isolates_sessions())


async def _test_memory_store_rejects_busy_clear_and_isolates_sessions() -> None:
    store = InMemorySessionStore()
    first = await store.create_session()
    second = await store.create_session()
    await store.set_active_run(first.session_id, 0, "run-1")

    with pytest.raises(SessionBusyError):
        await store.clear_session(first.session_id, 0)

    summaries = await store.list_sessions()
    assert {item.session_id for item in summaries} == {first.session_id, second.session_id}


def test_memory_store_covers_limits_delete_and_active_cleanup() -> None:
    asyncio.run(_test_memory_store_covers_limits_delete_and_active_cleanup())


async def _test_memory_store_covers_limits_delete_and_active_cleanup() -> None:
    store = InMemorySessionStore(max_sessions=1)
    session = await store.create_session()
    with pytest.raises(SessionLimitReachedError):
        await store.create_session()
    await store.set_active_run(session.session_id, 0, "run-1")
    await store.clear_active_run(session.session_id, "other-run")
    await store.clear_active_run(session.session_id, "run-1")
    await store.delete_session(session.session_id, 0)
    with pytest.raises(SessionNotFoundError):
        await store.get_session(session.session_id)
