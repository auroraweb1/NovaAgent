from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from novaagent.application.chat.multi_turn import MultiTurnChatService
from novaagent.domain.errors import ContextTooLargeError, ProviderUnavailableError
from novaagent.domain.events import AgentEvent, RunCancelledPayload, RunCompletedPayload, TokenUsage
from novaagent.domain.ports import ModelOptions, TextModelDelta, UsageModelOutput
from novaagent.infrastructure.sessions import InMemorySessionStore


class Sink:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    async def publish(self, event: AgentEvent) -> None:
        self.events.append(event)


class SuccessfulModel:
    async def _stream(self):
        yield TextModelDelta("answer")
        yield UsageModelOutput(TokenUsage(2, 3))

    def stream_live(self, _request):
        return self._stream()


class FailingModel:
    async def _stream(self):
        raise ProviderUnavailableError()
        yield TextModelDelta("unreachable")

    def stream_live(self, _request):
        return self._stream()


class BlockingModel:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def _stream(self):
        self.started.set()
        await self.release.wait()
        yield TextModelDelta("unreachable")

    def stream_live(self, _request):
        return self._stream()


def service(model, store, **kwargs):
    counters: dict[str, int] = {}

    def make_id(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}-test-{counters[prefix]}"

    return MultiTurnChatService(
        model=model,
        store=store,
        options=ModelOptions(temperature=0.7, max_output_tokens=10),
        id_factory=make_id,
        clock=lambda: datetime(2026, 8, 17, tzinfo=UTC),
        **kwargs,
    )


def test_multi_turn_success_commits_history_and_context_event() -> None:
    asyncio.run(_test_multi_turn_success_commits_history_and_context_event())


async def _test_multi_turn_success_commits_history_and_context_event() -> None:
    store = InMemorySessionStore()
    session = await store.create_session()
    sink = Sink()
    result = await service(SuccessfulModel(), store).stream_chat(
        session_id=session.session_id,
        expected_revision=0,
        text="hello",
        sink=sink,
    )
    assert result.snapshot.revision == 1
    assert len(result.snapshot.messages) == 2
    assert any(event.type == "context_prepared" for event in sink.events)
    assert isinstance(sink.events[-1].payload, RunCompletedPayload)


def test_multi_turn_failure_does_not_commit_history() -> None:
    asyncio.run(_test_multi_turn_failure_does_not_commit_history())


async def _test_multi_turn_failure_does_not_commit_history() -> None:
    store = InMemorySessionStore()
    session = await store.create_session()
    sink = Sink()
    with pytest.raises(ProviderUnavailableError):
        await service(FailingModel(), store).stream_chat(
            session_id=session.session_id,
            expected_revision=0,
            text="hello",
            sink=sink,
        )
    assert (await store.get_session(session.session_id)).messages == ()


def test_multi_turn_cancel_cleans_run_without_commit() -> None:
    asyncio.run(_test_multi_turn_cancel_cleans_run_without_commit())


async def _test_multi_turn_cancel_cleans_run_without_commit() -> None:
    store = InMemorySessionStore()
    session = await store.create_session()
    model = BlockingModel()
    sink = Sink()
    chat = service(model, store)
    task = asyncio.create_task(
        chat.stream_chat(
            session_id=session.session_id,
            expected_revision=0,
            text="hello",
            sink=sink,
        )
    )
    await model.started.wait()
    active_run = (await store.get_session(session.session_id)).active_run_id
    assert active_run is not None
    assert await chat.cancel(active_run, reason="user_requested")
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any(isinstance(event.payload, RunCancelledPayload) for event in sink.events)
    assert (await store.get_session(session.session_id)).active_run_id is None
    assert (await store.get_session(session.session_id)).messages == ()


def test_multi_turn_context_limit_is_rejected_before_run() -> None:
    asyncio.run(_test_multi_turn_context_limit_is_rejected_before_run())


async def _test_multi_turn_context_limit_is_rejected_before_run() -> None:
    store = InMemorySessionStore()
    session = await store.create_session()
    with pytest.raises(ContextTooLargeError):
        await service(SuccessfulModel(), store, context_budget=5).stream_chat(
            session_id=session.session_id,
            expected_revision=0,
            text="too large",
            sink=Sink(),
        )
