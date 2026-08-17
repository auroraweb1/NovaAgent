from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from fakes.protocol import ScriptedModel
from novaagent.application.chat.single_turn import (
    MESSAGE_CHARACTER_LIMIT,
    SingleTurnChatService,
    SingleTurnEventProjection,
)
from novaagent.domain.errors import EmptyMessageError, MessageTooLongError
from novaagent.domain.events import TokenUsage
from novaagent.domain.messages import MessageRole, TextBlock
from novaagent.domain.models import ProviderDescriptor
from novaagent.domain.ports import ModelOptions, TextModelDelta, UsageModelOutput

NOW = datetime(2026, 8, 17, 4, 0, tzinfo=UTC)


class DeterministicIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}-{self.value}"


def service(
    model: ScriptedModel, *, monotonic_values: Iterator[float] | None = None
) -> SingleTurnChatService:
    values = monotonic_values or iter((10.0, 10.125))
    return SingleTurnChatService(
        model=model,
        provider=ProviderDescriptor("qwen", "qwen3.8-max"),
        options=ModelOptions(temperature=0.7, max_output_tokens=2048),
        id_factory=DeterministicIds(),
        clock=lambda: NOW,
        monotonic=lambda: next(values),
    )


def test_single_turn_service_builds_one_text_message_and_projects_result() -> None:
    async def scenario() -> None:
        usage = TokenUsage(5, 3)
        model = ScriptedModel((TextModelDelta("NOVAAGENT_OK"), UsageModelOutput(usage)))

        result = await service(model).chat("  保留空白  ")

        assert result.run_id.startswith("run-")
        assert result.message.role is MessageRole.ASSISTANT
        assert result.message.content == (TextBlock("NOVAAGENT_OK"),)
        assert result.provider == "qwen"
        assert result.model == "qwen3.8-max"
        assert result.usage == usage
        assert result.latency_ms == 125
        assert model.requests is not None
        assert len(model.requests) == 1
        request = model.requests[0]
        assert request.tools == ()
        assert len(request.messages) == 1
        assert request.messages[0].role is MessageRole.USER
        assert request.messages[0].content == (TextBlock("  保留空白  "),)
        assert request.options == ModelOptions(temperature=0.7, max_output_tokens=2048)

    asyncio.run(scenario())


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_input_is_rejected_before_model_call(text: str) -> None:
    async def scenario() -> None:
        model = ScriptedModel((TextModelDelta("unused"),))

        with pytest.raises(EmptyMessageError):
            await service(model).chat(text)

        assert model.requests == []

    asyncio.run(scenario())


def test_oversized_input_is_rejected_before_model_call() -> None:
    async def scenario() -> None:
        model = ScriptedModel((TextModelDelta("unused"),))

        with pytest.raises(MessageTooLongError) as raised:
            await service(model).chat("字" * (MESSAGE_CHARACTER_LIMIT + 1))

        assert raised.value.field == "message"
        assert model.requests == []

    asyncio.run(scenario())


def test_each_chat_gets_distinct_run_and_message_identifiers() -> None:
    async def scenario() -> None:
        model = ScriptedModel((TextModelDelta("answer"),))
        chat = service(model, monotonic_values=iter((1.0, 1.1, 2.0, 2.1)))

        first = await chat.chat("one")
        second = await chat.chat("two")

        assert first.run_id != second.run_id
        assert first.message.message_id != second.message.message_id

    asyncio.run(scenario())


def test_event_projection_retains_only_run_id_and_usage() -> None:
    projection = SingleTurnEventProjection()

    assert set(projection.__dataclass_fields__) == {"run_id", "usage"}
    assert not hasattr(projection, "events")
