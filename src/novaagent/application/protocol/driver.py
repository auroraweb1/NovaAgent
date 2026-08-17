from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from novaagent.application.chat.context_window import ContextSelection
from novaagent.domain.errors import (
    DependencyUnavailableError,
    EmptyMessageError,
    NovaAgentError,
    ProtocolValidationError,
)
from novaagent.domain.events import (
    AgentEvent,
    AgentEventPayload,
    ContextPreparedPayload,
    ErrorPayload,
    EventSequenceValidator,
    MessageCompletedPayload,
    MessageStartedPayload,
    ReasoningSummaryDeltaPayload,
    RunCancelledPayload,
    RunCompletedPayload,
    RunFailedPayload,
    RunStartedPayload,
    TextDeltaPayload,
    TokenUsage,
    ToolCallPayload,
)
from novaagent.domain.messages import Message, MessageRole, TextBlock
from novaagent.domain.ports import (
    EventSinkPort,
    ModelPort,
    ModelRequest,
    ReasoningSummaryModelDelta,
    TextModelDelta,
    ToolCallModelOutput,
    UsageModelOutput,
)

REASONING_SUMMARY_LIMIT = 4096
REASONING_SUMMARY_TRUNCATED_NOTICE = "思考摘要过长，后续内容已省略"

IdFactory = Callable[[str], str]
Clock = Callable[[], datetime]


def create_user_message(
    text: str,
    *,
    message_id: str,
    created_at: datetime,
) -> Message:
    """Validate a Web/Application text input without normalizing valid content."""
    if not text.strip():
        raise EmptyMessageError()
    return Message(
        message_id=message_id,
        role=MessageRole.USER,
        content=(TextBlock(text),),
        created_at=created_at,
    )


async def run_protocol(
    request: ModelRequest,
    *,
    model: ModelPort,
    sink: EventSinkPort,
    session_id: str | None = None,
    id_factory: IdFactory | None = None,
    clock: Clock | None = None,
    context: ContextSelection | None = None,
    cancellation_reason: Callable[[], str] | str = "user_requested",
) -> Message:
    """Drive one deterministic model stream into a validated AgentEvent sequence."""
    make_id = id_factory or _default_id_factory
    now = clock or _utc_now
    run_id = make_id("run")
    message_id = make_id("msg")
    sequence = 0
    validator = EventSequenceValidator()

    async def publish(payload: AgentEventPayload) -> None:
        nonlocal sequence
        event = AgentEvent(
            event_id=make_id("evt"),
            run_id=run_id,
            sequence=sequence,
            occurred_at=now(),
            payload=payload,
        )
        validator.add(event)
        await sink.publish(event)
        sequence += 1

    await publish(RunStartedPayload(session_id=session_id))
    if context is not None:
        await publish(
            ContextPreparedPayload(
                included_messages=context.included_messages,
                dropped_messages=context.dropped_messages,
                estimated_input_tokens=context.estimated_input_tokens,
            )
        )
    await publish(MessageStartedPayload(message_id=message_id))

    text_parts: list[str] = []
    summary_length = 0
    summary_truncated = False
    usage: TokenUsage | None = None

    async def fail(error: Exception) -> NovaAgentError:
        public_error = _public_model_error(error)
        await publish(
            ErrorPayload(
                code=public_error.code,
                message=public_error.message,
                retryable=public_error.retryable,
                field=public_error.field,
            )
        )
        await publish(RunFailedPayload(error_code=public_error.code))
        validator.finish()
        return public_error

    iterator = model.stream(request).__aiter__()
    while True:
        try:
            output = await anext(iterator)
        except StopAsyncIteration:
            break
        except asyncio.CancelledError:
            reason = cancellation_reason() if callable(cancellation_reason) else cancellation_reason
            try:
                await publish(RunCancelledPayload(reason=reason))
                validator.finish()
            except Exception:
                pass
            raise
        except Exception as error:
            public_error = await fail(error)
            raise public_error from error

        if isinstance(output, TextModelDelta):
            text_parts.append(output.text)
            await publish(TextDeltaPayload(message_id=message_id, delta=output.text))
        elif isinstance(output, ReasoningSummaryModelDelta):
            if summary_truncated:
                continue
            remaining = REASONING_SUMMARY_LIMIT - summary_length
            visible = output.text[:remaining]
            if visible:
                await publish(ReasoningSummaryDeltaPayload(delta=visible))
                summary_length += len(visible)
            if len(output.text) > remaining:
                await publish(
                    ReasoningSummaryDeltaPayload(delta=REASONING_SUMMARY_TRUNCATED_NOTICE)
                )
                summary_truncated = True
        elif isinstance(output, ToolCallModelOutput):
            await publish(ToolCallPayload(call=output.call))
        elif isinstance(output, UsageModelOutput):
            usage = output.usage
        else:  # pragma: no cover - protects against a non-conforming adapter
            validation_error = ProtocolValidationError("Model emitted an unsupported output")
            public_error = await fail(validation_error)
            raise public_error

    final_text = "".join(text_parts)
    if not final_text.strip():
        validation_error = ProtocolValidationError("Model produced no meaningful final text")
        public_error = await fail(validation_error)
        raise public_error
    message = Message(
        message_id=message_id,
        role=MessageRole.ASSISTANT,
        content=(TextBlock(final_text),),
        created_at=now(),
    )
    await publish(MessageCompletedPayload(message=message))
    await publish(RunCompletedPayload(message_id=message_id, usage=usage))
    validator.finish()
    return message


def _public_model_error(error: Exception) -> NovaAgentError:
    if isinstance(error, NovaAgentError):
        return error
    return DependencyUnavailableError("模型暂时不可用，请稍后重试")


def _default_id_factory(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _utc_now() -> datetime:
    return datetime.now(UTC)
