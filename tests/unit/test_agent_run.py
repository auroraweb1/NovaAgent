from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from novaagent.application.agent import AgentRunService, EchoTool, ToolRegistry
from novaagent.application.agent.service import StreamingModelPort
from novaagent.application.protocol.driver import REASONING_SUMMARY_LIMIT
from novaagent.config.model import AgentSettings
from novaagent.domain.errors import (
    AgentContextLimitError,
    AgentModelOutputInvalidError,
    AgentStepLimitError,
    AgentTimeoutError,
    AgentToolCallLimitError,
    ContextTooLargeError,
    DependencyUnavailableError,
)
from novaagent.domain.events import (
    AgentEvent,
    ReasoningSummaryDeltaPayload,
    RunCancelledPayload,
    RunCompletedPayload,
    TokenUsage,
    ToolCallPayload,
    ToolResultPayload,
)
from novaagent.domain.messages import MessageRole, ToolCallBlock, ToolResultStatus
from novaagent.domain.ports import (
    ModelOptions,
    ModelOutput,
    ModelRequest,
    ReasoningSummaryModelDelta,
    TextModelDelta,
    ToolCallModelOutput,
    UsageModelOutput,
)
from novaagent.infrastructure.sessions import InMemorySessionStore


class Sink:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    async def publish(self, event: AgentEvent) -> None:
        self.events.append(event)


class SequenceModel:
    def __init__(self, scripts: tuple[tuple[ModelOutput, ...], ...]) -> None:
        self.scripts = list(scripts)
        self.requests: list[ModelRequest] = []

    async def _stream(self, request: ModelRequest) -> AsyncIterator[ModelOutput]:
        self.requests.append(request)
        for output in self.scripts.pop(0):
            yield output

    def stream_live(self, request: ModelRequest) -> AsyncIterator[ModelOutput]:
        return self._stream(request)


def make_service(
    model: StreamingModelPort,
    store: InMemorySessionStore,
    *,
    tools: ToolRegistry | None = None,
    settings: AgentSettings | None = None,
    context_budget: int = 24_000,
) -> AgentRunService:
    counters: dict[str, int] = {}

    def make_id(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}-{counters[prefix]}"

    return AgentRunService(
        model=model,
        store=store,
        tools=tools or ToolRegistry((EchoTool(),)),
        options=ModelOptions(temperature=0.2, max_output_tokens=32),
        settings=settings or AgentSettings(),
        id_factory=make_id,
        clock=lambda: datetime(2026, 8, 17, tzinfo=UTC),
        context_budget=context_budget,
    )


def test_agent_executes_tool_then_commits_only_formal_turn() -> None:
    async def scenario() -> None:
        store = InMemorySessionStore()
        session = await store.create_session()
        model = SequenceModel(
            (
                (
                    ToolCallModelOutput(ToolCallBlock("call-1", "echo", {"text": "ok"})),
                    UsageModelOutput(TokenUsage(3, 1)),
                ),
                (TextModelDelta("final answer"), UsageModelOutput(TokenUsage(5, 2))),
            )
        )
        sink = Sink()
        result = await make_service(model, store).stream_chat(
            session_id=session.session_id,
            expected_revision=0,
            text="use echo",
            sink=sink,
        )
        assert result.snapshot.revision == 1
        assert [message.role for message in result.snapshot.messages] == [
            MessageRole.USER,
            MessageRole.ASSISTANT,
        ]
        assert [event.type for event in sink.events].count("tool_call") == 1
        assert [event.type for event in sink.events].count("tool_result") == 1
        assert isinstance(sink.events[-1].payload, RunCompletedPayload)
        assert sink.events[-1].payload.usage == TokenUsage(8, 3)
        assert len(model.requests) == 2
        assert [message.role for message in model.requests[1].messages[-2:]] == [
            MessageRole.ASSISTANT,
            MessageRole.TOOL,
        ]

    asyncio.run(scenario())


def test_recoverable_tool_error_is_returned_to_model() -> None:
    async def scenario() -> None:
        store = InMemorySessionStore()
        session = await store.create_session()
        model = SequenceModel(
            (
                (ToolCallModelOutput(ToolCallBlock("call-1", "missing", {})),),
                (TextModelDelta("handled"),),
            )
        )
        sink = Sink()
        await make_service(model, store, tools=ToolRegistry()).stream_chat(
            session_id=session.session_id,
            expected_revision=0,
            text="call missing",
            sink=sink,
        )
        tool_event = next(
            event for event in sink.events if isinstance(event.payload, ToolResultPayload)
        )
        assert isinstance(tool_event.payload, ToolResultPayload)
        assert tool_event.payload.result.status is ToolResultStatus.ERROR
        assert tool_event.payload.result.error_code == "tool_not_found"

    asyncio.run(scenario())


def test_multiple_tools_are_executed_in_provider_order() -> None:
    async def scenario() -> None:
        store = InMemorySessionStore()
        session = await store.create_session()
        model = SequenceModel(
            (
                (
                    ToolCallModelOutput(ToolCallBlock("call-1", "echo", {"text": "first"})),
                    ToolCallModelOutput(ToolCallBlock("call-2", "echo", {"text": "second"})),
                ),
                (TextModelDelta("done"),),
            )
        )
        sink = Sink()
        await make_service(model, store).stream_chat(
            session_id=session.session_id,
            expected_revision=0,
            text="two tools",
            sink=sink,
        )
        tool_events: list[str] = []
        for event in sink.events:
            if isinstance(event.payload, ToolCallPayload):
                tool_events.append(event.payload.call.call_id)
            elif isinstance(event.payload, ToolResultPayload):
                tool_events.append(event.payload.result.call_id)
        assert tool_events == ["call-1", "call-1", "call-2", "call-2"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("scripts", "settings", "error_type"),
    [
        (
            ((ToolCallModelOutput(ToolCallBlock("call-1", "echo", {"text": "x"})),),),
            AgentSettings(max_steps=1),
            AgentStepLimitError,
        ),
        (
            (
                (
                    TextModelDelta("partial"),
                    ToolCallModelOutput(ToolCallBlock("call-1", "echo", {"text": "x"})),
                ),
            ),
            AgentSettings(),
            AgentModelOutputInvalidError,
        ),
    ],
)
def test_agent_failures_do_not_commit(
    scripts: tuple[tuple[ModelOutput, ...], ...],
    settings: AgentSettings,
    error_type: type[Exception],
) -> None:
    async def scenario() -> None:
        store = InMemorySessionStore()
        session = await store.create_session()
        sink = Sink()
        with pytest.raises(error_type):
            await make_service(SequenceModel(scripts), store, settings=settings).stream_chat(
                session_id=session.session_id,
                expected_revision=0,
                text="hello",
                sink=sink,
            )
        snapshot = await store.get_session(session.session_id)
        assert snapshot.messages == ()
        assert snapshot.active_run_id is None
        assert sink.events[-1].type == "run_failed"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("scripts", "settings", "error_type"),
    [
        (
            (
                (
                    ToolCallModelOutput(ToolCallBlock("call-1", "echo", {"text": "a"})),
                    ToolCallModelOutput(ToolCallBlock("call-2", "echo", {"text": "b"})),
                ),
            ),
            AgentSettings(max_tool_calls_per_step=1),
            AgentToolCallLimitError,
        ),
        (
            (
                (ToolCallModelOutput(ToolCallBlock("call-1", "echo", {"text": "a"})),),
                (ToolCallModelOutput(ToolCallBlock("call-2", "echo", {"text": "b"})),),
            ),
            AgentSettings(max_tool_calls=1),
            AgentToolCallLimitError,
        ),
        (
            (
                (ToolCallModelOutput(ToolCallBlock("call-1", "echo", {"text": "a"})),),
                (ToolCallModelOutput(ToolCallBlock("call-1", "echo", {"text": "b"})),),
            ),
            AgentSettings(),
            AgentModelOutputInvalidError,
        ),
    ],
)
def test_agent_rejects_tool_call_limits_and_duplicate_ids(
    scripts: tuple[tuple[ModelOutput, ...], ...],
    settings: AgentSettings,
    error_type: type[Exception],
) -> None:
    async def scenario() -> None:
        store = InMemorySessionStore()
        session = await store.create_session()
        with pytest.raises(error_type):
            await make_service(SequenceModel(scripts), store, settings=settings).stream_chat(
                session_id=session.session_id,
                expected_revision=0,
                text="limits",
                sink=Sink(),
            )
        assert (await store.get_session(session.session_id)).messages == ()

    asyncio.run(scenario())


def test_agent_bounds_reasoning_and_nulls_partial_usage() -> None:
    async def scenario() -> None:
        store = InMemorySessionStore()
        session = await store.create_session()
        reasoning = "r" * (REASONING_SUMMARY_LIMIT + 10)
        model = SequenceModel(((ReasoningSummaryModelDelta(reasoning), TextModelDelta("answer")),))
        sink = Sink()
        await make_service(model, store).stream_chat(
            session_id=session.session_id,
            expected_revision=0,
            text="reason",
            sink=sink,
        )
        summary = [
            event.payload.delta
            for event in sink.events
            if isinstance(event.payload, ReasoningSummaryDeltaPayload)
        ]
        assert len(summary[0]) == REASONING_SUMMARY_LIMIT
        assert len(summary) == 2
        assert isinstance(sink.events[-1].payload, RunCompletedPayload)
        assert sink.events[-1].payload.usage is None

    asyncio.run(scenario())


def test_agent_context_budget_is_checked_after_tool_result() -> None:
    async def scenario() -> None:
        store = InMemorySessionStore()
        session = await store.create_session()
        model = SequenceModel(
            ((ToolCallModelOutput(ToolCallBlock("call-1", "echo", {"text": "x" * 80})),),)
        )
        with pytest.raises(AgentContextLimitError):
            await make_service(model, store, context_budget=120).stream_chat(
                session_id=session.session_id,
                expected_revision=0,
                text="short",
                sink=Sink(),
            )

    asyncio.run(scenario())


class BlockingModel:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def _stream(self) -> AsyncIterator[ModelOutput]:
        self.started.set()
        await asyncio.Event().wait()
        yield TextModelDelta("unreachable")

    def stream_live(self, request: ModelRequest) -> AsyncIterator[ModelOutput]:
        return self._stream()


@pytest.mark.parametrize(
    ("limit", "code"), [("model", "agent_model_step_timeout"), ("total", "agent_timeout")]
)
def test_agent_timeouts_do_not_commit(limit: str, code: str) -> None:
    async def scenario() -> None:
        store = InMemorySessionStore()
        session = await store.create_session()
        settings = AgentSettings().model_copy(
            update={
                "model_step_timeout_seconds": 0.001 if limit == "model" else 10,
                "total_timeout_seconds": 0.001 if limit == "total" else 10,
            }
        )
        with pytest.raises(AgentTimeoutError) as raised:
            await make_service(BlockingModel(), store, settings=settings).stream_chat(
                session_id=session.session_id,
                expected_revision=0,
                text="wait",
                sink=Sink(),
            )
        assert raised.value.code == code
        assert (await store.get_session(session.session_id)).messages == ()

    asyncio.run(scenario())


def test_agent_cancellation_and_context_preflight() -> None:
    async def scenario() -> None:
        store = InMemorySessionStore()
        session = await store.create_session()
        model = BlockingModel()
        sink = Sink()
        service = make_service(model, store)
        task = asyncio.create_task(
            service.stream_chat(
                session_id=session.session_id,
                expected_revision=0,
                text="wait",
                sink=sink,
            )
        )
        await model.started.wait()
        run_id = (await store.get_session(session.session_id)).active_run_id
        assert run_id is not None
        assert await service.cancel(run_id, reason="user_requested")
        with pytest.raises(asyncio.CancelledError):
            await task
        assert any(isinstance(event.payload, RunCancelledPayload) for event in sink.events)
        with pytest.raises(ContextTooLargeError):
            await make_service(
                SequenceModel(((TextModelDelta("unused"),),)),
                store,
                context_budget=5,
            ).validate_context(session_id=session.session_id, text="too large")

    asyncio.run(scenario())


def test_unexpected_model_failure_is_mapped_without_commit() -> None:
    async def scenario() -> None:
        store = InMemorySessionStore()
        session = await store.create_session()
        with pytest.raises(DependencyUnavailableError):
            await make_service(FailingModel(), store).stream_chat(
                session_id=session.session_id,
                expected_revision=0,
                text="fail",
                sink=Sink(),
            )

    asyncio.run(scenario())


class FailingModel:
    async def _stream(self) -> AsyncIterator[ModelOutput]:
        raise RuntimeError("private")
        yield TextModelDelta("unreachable")

    def stream_live(self, request: ModelRequest) -> AsyncIterator[ModelOutput]:
        return self._stream()
