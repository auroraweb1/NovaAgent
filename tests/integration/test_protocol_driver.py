from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from fakes.protocol import InMemoryEventSink, ScriptedModel
from novaagent.application.protocol.driver import (
    REASONING_SUMMARY_LIMIT,
    REASONING_SUMMARY_TRUNCATED_NOTICE,
    run_protocol,
)
from novaagent.domain.errors import DependencyUnavailableError
from novaagent.domain.events import (
    AgentEvent,
    ReasoningSummaryDeltaPayload,
    RunCompletedPayload,
    TokenUsage,
)
from novaagent.domain.messages import Message, MessageRole, TextBlock, ToolCallBlock
from novaagent.domain.ports import (
    ModelRequest,
    ReasoningSummaryModelDelta,
    TextModelDelta,
    ToolCallModelOutput,
    UsageModelOutput,
)
from novaagent.interfaces.web.protocol import event_from_dict, event_to_dict

NOW = datetime(2026, 8, 17, 2, 0, tzinfo=UTC)


class DeterministicIds:
    def __init__(self) -> None:
        self._value = 0

    def __call__(self, prefix: str) -> str:
        self._value += 1
        return f"{prefix}-{self._value}"


def request() -> ModelRequest:
    return ModelRequest((Message("input-1", MessageRole.USER, (TextBlock("你好"),), NOW),))


def test_minimum_fake_model_flow_produces_one_valid_reply() -> None:
    async def scenario() -> None:
        model = ScriptedModel((TextModelDelta("你"), TextModelDelta("好")))
        sink = InMemoryEventSink()
        result = await run_protocol(
            request(),
            model=model,
            sink=sink,
            session_id="session-1",
            id_factory=DeterministicIds(),
            clock=lambda: NOW,
        )

        assert result.role is MessageRole.ASSISTANT
        assert result.content == (TextBlock("你好"),)
        assert sink.text() == "你好"
        assert [event.type for event in sink.events] == [
            "run_started",
            "message_started",
            "text_delta",
            "text_delta",
            "message_completed",
            "run_completed",
        ]
        assert [event.sequence for event in sink.events] == list(range(6))
        sink.validate()
        assert tuple(event_from_dict(event_to_dict(item)) for item in sink.events) == sink.events
        assert model.requests == [request()]

    asyncio.run(scenario())


def test_reasoning_summary_is_optional_and_separate_from_final_text() -> None:
    async def scenario() -> None:
        model = ScriptedModel((ReasoningSummaryModelDelta("先检查输入"), TextModelDelta("完成")))
        sink = InMemoryEventSink()
        result = await run_protocol(request(), model=model, sink=sink, clock=lambda: NOW)

        summaries = [
            event.payload.delta
            for event in sink.events
            if isinstance(event.payload, ReasoningSummaryDeltaPayload)
        ]
        assert summaries == ["先检查输入"]
        assert result.content == (TextBlock("完成"),)

        without_summary = InMemoryEventSink()
        await run_protocol(
            request(),
            model=ScriptedModel((TextModelDelta("完成"),)),
            sink=without_summary,
            clock=lambda: NOW,
        )
        assert "reasoning_summary_delta" not in {event.type for event in without_summary.events}

    asyncio.run(scenario())


def test_reasoning_summary_is_bounded_and_truncation_notice_occurs_once() -> None:
    async def scenario() -> None:
        model = ScriptedModel(
            (
                ReasoningSummaryModelDelta("a" * (REASONING_SUMMARY_LIMIT + 10)),
                ReasoningSummaryModelDelta("ignored"),
                TextModelDelta("answer"),
            )
        )
        sink = InMemoryEventSink()
        await run_protocol(request(), model=model, sink=sink, clock=lambda: NOW)

        summaries = [
            event.payload.delta
            for event in sink.events
            if isinstance(event.payload, ReasoningSummaryDeltaPayload)
        ]
        assert len(summaries[0]) == REASONING_SUMMARY_LIMIT
        assert summaries.count(REASONING_SUMMARY_TRUNCATED_NOTICE) == 1
        assert "ignored" not in summaries

    asyncio.run(scenario())


def test_model_failure_is_sanitized_and_terminates_run() -> None:
    async def scenario() -> None:
        sink = InMemoryEventSink()
        model = ScriptedModel((TextModelDelta("partial"),), failure=RuntimeError("secret"))
        with pytest.raises(DependencyUnavailableError, match="模型暂时不可用"):
            await run_protocol(request(), model=model, sink=sink, clock=lambda: NOW)

        assert [event.type for event in sink.events][-2:] == ["error", "run_failed"]
        assert "secret" not in repr(sink.events)
        sink.validate()

    asyncio.run(scenario())


def test_tool_call_output_uses_a_typed_event_without_executing_the_tool() -> None:
    async def scenario() -> None:
        sink = InMemoryEventSink()
        model = ScriptedModel(
            (
                ToolCallModelOutput(ToolCallBlock("call-1", "lookup", {"query": "x"})),
                TextModelDelta("等待工具阶段"),
            )
        )
        await run_protocol(request(), model=model, sink=sink)

        assert "tool_call" in [event.type for event in sink.events]
        assert "tool_result" not in [event.type for event in sink.events]
        sink.validate()

    asyncio.run(scenario())


def test_empty_model_output_fails_without_creating_a_final_message() -> None:
    async def scenario() -> None:
        sink = InMemoryEventSink()
        with pytest.raises(Exception) as captured:
            await run_protocol(request(), model=ScriptedModel(()), sink=sink, clock=lambda: NOW)

        assert getattr(captured.value, "code", None) == "protocol_invalid"
        assert [event.type for event in sink.events][-2:] == ["error", "run_failed"]
        assert "message_completed" not in [event.type for event in sink.events]
        sink.validate()

    asyncio.run(scenario())


def test_event_sink_failure_is_not_misreported_as_a_model_error() -> None:
    class FailingSink:
        def __init__(self) -> None:
            self.types: list[str] = []

        async def publish(self, event: AgentEvent) -> None:
            self.types.append(event.type)
            if event.type == "text_delta":
                raise RuntimeError("sink unavailable")

    async def scenario() -> None:
        sink = FailingSink()
        with pytest.raises(RuntimeError, match="sink unavailable"):
            await run_protocol(
                request(), model=ScriptedModel((TextModelDelta("answer"),)), sink=sink
            )

        assert sink.types == ["run_started", "message_started", "text_delta"]

    asyncio.run(scenario())


def test_model_usage_is_attached_to_the_successful_run_completion() -> None:
    async def scenario() -> None:
        usage = TokenUsage(input_tokens=8, output_tokens=2)
        sink = InMemoryEventSink()
        await run_protocol(
            request(),
            model=ScriptedModel((TextModelDelta("answer"), UsageModelOutput(usage))),
            sink=sink,
        )

        completed = sink.events[-1].payload
        assert isinstance(completed, RunCompletedPayload)
        assert completed.usage == usage
        assert completed.usage.total_tokens == 10

    asyncio.run(scenario())
