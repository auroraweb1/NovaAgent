from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from novaagent.application.agent.registry import ToolRegistry
from novaagent.application.chat.context_window import (
    DEFAULT_CONTEXT_ESTIMATED_TOKEN_BUDGET,
    DEFAULT_CONTEXT_TURNS,
    ContextSelection,
    estimate_messages,
    select_context,
)
from novaagent.application.chat.multi_turn import ActiveRunRegistry, MultiTurnChatResult
from novaagent.application.protocol.driver import (
    REASONING_SUMMARY_LIMIT,
    REASONING_SUMMARY_TRUNCATED_NOTICE,
    create_user_message,
)
from novaagent.config.model import AgentSettings
from novaagent.domain.errors import (
    AgentContextLimitError,
    AgentModelOutputInvalidError,
    AgentStepLimitError,
    AgentTimeoutError,
    AgentToolCallLimitError,
    ContextTooLargeError,
    DependencyUnavailableError,
    NovaAgentError,
    ProtocolValidationError,
    ToolArgumentsInvalidError,
    ToolExecutionFailedError,
    ToolNotFoundError,
    ToolResultInvalidError,
    ToolTimeoutError,
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
    ToolResultPayload,
)
from novaagent.domain.messages import (
    Message,
    MessageRole,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultStatus,
)
from novaagent.domain.ports import (
    EventSinkPort,
    ModelOptions,
    ModelOutput,
    ModelRequest,
    MultiTurnSessionStorePort,
    ReasoningSummaryModelDelta,
    TextModelDelta,
    ToolCallModelOutput,
    ToolExecutionContext,
    UsageModelOutput,
)


class StreamingModelPort(Protocol):
    def stream_live(self, request: ModelRequest) -> AsyncIterator[ModelOutput]: ...


@dataclass(frozen=True, slots=True)
class ModelStepResult:
    text_parts: tuple[str, ...]
    reasoning_parts: tuple[str, ...]
    tool_calls: tuple[ToolCallBlock, ...]
    usage: TokenUsage | None


class ModelStepRunner:
    def __init__(self, model: StreamingModelPort, *, timeout_seconds: float) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds

    async def run(self, request: ModelRequest) -> ModelStepResult:
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[ToolCallBlock] = []
        usage: TokenUsage | None = None
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async for output in self._model.stream_live(request):
                    if isinstance(output, TextModelDelta):
                        text_parts.append(output.text)
                    elif isinstance(output, ReasoningSummaryModelDelta):
                        reasoning_parts.append(output.text)
                    elif isinstance(output, ToolCallModelOutput):
                        tool_calls.append(output.call)
                    elif isinstance(output, UsageModelOutput):
                        usage = output.usage
                    else:  # pragma: no cover - protects against non-conforming adapters
                        raise AgentModelOutputInvalidError()
        except TimeoutError as error:
            raise AgentTimeoutError("agent_model_step_timeout") from error
        if tool_calls and "".join(text_parts).strip():
            raise AgentModelOutputInvalidError()
        if not tool_calls and not "".join(text_parts).strip():
            raise AgentModelOutputInvalidError()
        return ModelStepResult(tuple(text_parts), tuple(reasoning_parts), tuple(tool_calls), usage)


class _EventPublisher:
    def __init__(
        self,
        *,
        run_id: str,
        sink: EventSinkPort,
        id_factory: Callable[[str], str],
        clock: Callable[[], datetime],
    ) -> None:
        self._run_id = run_id
        self._sink = sink
        self._id_factory = id_factory
        self._clock = clock
        self._sequence = 0
        self._validator = EventSequenceValidator()

    async def publish(self, payload: AgentEventPayload) -> None:
        event = AgentEvent(
            event_id=self._id_factory("evt"),
            run_id=self._run_id,
            sequence=self._sequence,
            occurred_at=self._clock(),
            payload=payload,
        )
        self._validator.add(event)
        await self._sink.publish(event)
        self._sequence += 1

    def finish(self) -> None:
        self._validator.finish()


class AgentRunService:
    def __init__(
        self,
        *,
        model: StreamingModelPort,
        store: MultiTurnSessionStorePort,
        tools: ToolRegistry,
        options: ModelOptions,
        settings: AgentSettings,
        registry: ActiveRunRegistry | None = None,
        id_factory: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        max_turns: int = DEFAULT_CONTEXT_TURNS,
        context_budget: int = DEFAULT_CONTEXT_ESTIMATED_TOKEN_BUDGET,
    ) -> None:
        self._model = model
        self._store = store
        self._tools = tools
        self._tools.freeze()
        self._options = options
        self._settings = settings
        self.registry = registry or ActiveRunRegistry()
        self._id_factory = id_factory or _default_id_factory
        self._clock = clock or _utc_now
        self._max_turns = max_turns
        self._context_budget = context_budget

    @property
    def store(self) -> MultiTurnSessionStorePort:
        return self._store

    async def validate_context(self, *, session_id: str, text: str) -> None:
        session = await self._store.get_session(session_id)
        current_user = create_user_message(
            text, message_id=self._id_factory("validation"), created_at=self._clock()
        )
        try:
            select_context(
                system_messages=(),
                history=session.messages,
                current_user=current_user,
                max_turns=self._max_turns,
                budget=self._context_budget,
            )
        except ProtocolValidationError as error:
            raise ContextTooLargeError() from error

    async def stream_chat(
        self,
        *,
        session_id: str,
        expected_revision: int,
        text: str,
        sink: EventSinkPort,
    ) -> MultiTurnChatResult:
        session = await self._store.get_session(session_id)
        user_message = create_user_message(
            text, message_id=self._id_factory("msg"), created_at=self._clock()
        )
        try:
            context = select_context(
                system_messages=(),
                history=session.messages,
                current_user=user_message,
                max_turns=self._max_turns,
                budget=self._context_budget,
            )
        except ProtocolValidationError as error:
            raise ContextTooLargeError() from error

        run_id = self._id_factory("run")
        await self._store.set_active_run(session_id, expected_revision, run_id)
        task = asyncio.current_task()
        if task is None:  # pragma: no cover
            raise RuntimeError("agent run requires an asyncio task")
        await self.registry.register(run_id, task)
        publisher = _EventPublisher(
            run_id=run_id,
            sink=sink,
            id_factory=self._id_factory,
            clock=self._clock,
        )
        try:
            try:
                async with asyncio.timeout(self._settings.total_timeout_seconds):
                    message = await self._run_loop(
                        run_id=run_id,
                        session_id=session_id,
                        context=context,
                        publisher=publisher,
                    )
            except asyncio.CancelledError:
                try:
                    await publisher.publish(
                        RunCancelledPayload(reason=self.registry.reason_now(run_id))
                    )
                    publisher.finish()
                except Exception:
                    pass
                raise
            except TimeoutError as error:
                timeout_error = AgentTimeoutError()
                await self._publish_failure(publisher, timeout_error)
                raise timeout_error from error
            except Exception as error:
                public_error = _public_agent_error(error)
                await self._publish_failure(publisher, public_error)
                raise public_error from error

            snapshot = await self._store.commit_turn(
                session_id, expected_revision, user_message, message
            )
            return MultiTurnChatResult(run_id=run_id, snapshot=snapshot, message=message)
        finally:
            await self.registry.remove(run_id)
            await self._store.clear_active_run(session_id, run_id)

    async def _run_loop(
        self,
        *,
        run_id: str,
        session_id: str,
        context: ContextSelection,
        publisher: _EventPublisher,
    ) -> Message:
        message_id = self._id_factory("msg")
        await publisher.publish(RunStartedPayload(session_id=session_id))
        await publisher.publish(
            ContextPreparedPayload(
                included_messages=context.included_messages,
                dropped_messages=context.dropped_messages,
                estimated_input_tokens=context.estimated_input_tokens,
            )
        )
        await publisher.publish(MessageStartedPayload(message_id=message_id))
        working_messages = list(context.messages)
        total_tool_calls = 0
        usage_input = 0
        usage_output = 0
        usage_complete = True
        seen_call_ids: set[str] = set()
        summary_length = 0
        summary_truncated = False
        runner = ModelStepRunner(
            self._model, timeout_seconds=self._settings.model_step_timeout_seconds
        )

        for step_index in range(self._settings.max_steps):
            if _estimate_working_messages(working_messages) > self._context_budget:
                raise AgentContextLimitError()
            step = await runner.run(
                ModelRequest(
                    messages=tuple(working_messages),
                    tools=self._tools.definitions,
                    options=self._options,
                )
            )
            if step.usage is not None:
                usage_input += step.usage.input_tokens
                usage_output += step.usage.output_tokens
            else:
                usage_complete = False
            for part in step.reasoning_parts:
                if summary_truncated:
                    continue
                remaining = REASONING_SUMMARY_LIMIT - summary_length
                visible = part[:remaining]
                if visible:
                    await publisher.publish(ReasoningSummaryDeltaPayload(delta=visible))
                    summary_length += len(visible)
                if len(part) > remaining:
                    await publisher.publish(
                        ReasoningSummaryDeltaPayload(delta=REASONING_SUMMARY_TRUNCATED_NOTICE)
                    )
                    summary_truncated = True
            if not step.tool_calls:
                for part in step.text_parts:
                    await publisher.publish(TextDeltaPayload(message_id=message_id, delta=part))
                message = Message(
                    message_id=message_id,
                    role=MessageRole.ASSISTANT,
                    content=(TextBlock("".join(step.text_parts)),),
                    created_at=self._clock(),
                )
                await publisher.publish(MessageCompletedPayload(message=message))
                usage = TokenUsage(usage_input, usage_output) if usage_complete else None
                await publisher.publish(RunCompletedPayload(message_id=message_id, usage=usage))
                publisher.finish()
                return message

            if len(step.tool_calls) > self._settings.max_tool_calls_per_step:
                raise AgentToolCallLimitError()
            total_tool_calls += len(step.tool_calls)
            if total_tool_calls > self._settings.max_tool_calls:
                raise AgentToolCallLimitError()
            if any(call.call_id in seen_call_ids for call in step.tool_calls):
                raise AgentModelOutputInvalidError()
            if step_index + 1 == self._settings.max_steps:
                raise AgentStepLimitError()
            seen_call_ids.update(call.call_id for call in step.tool_calls)

            assistant_tool_message = Message(
                message_id=self._id_factory("msg"),
                role=MessageRole.ASSISTANT,
                content=tuple(step.tool_calls),
                created_at=self._clock(),
            )
            working_messages.append(assistant_tool_message)
            results: list[ToolResultBlock] = []
            for call in step.tool_calls:
                await publisher.publish(ToolCallPayload(call=call))
                result = await self._execute_tool(call, run_id=run_id, session_id=session_id)
                results.append(result)
                await publisher.publish(ToolResultPayload(result=result))
            working_messages.append(
                Message(
                    message_id=self._id_factory("msg"),
                    role=MessageRole.TOOL,
                    content=tuple(results),
                    created_at=self._clock(),
                )
            )
        raise AgentStepLimitError()

    async def _execute_tool(
        self, call: ToolCallBlock, *, run_id: str, session_id: str
    ) -> ToolResultBlock:
        try:
            return await self._tools.execute(
                call,
                ToolExecutionContext(run_id=run_id, session_id=session_id),
                timeout_seconds=self._settings.tool_timeout_seconds,
            )
        except (
            ToolNotFoundError,
            ToolArgumentsInvalidError,
            ToolTimeoutError,
            ToolExecutionFailedError,
            ToolResultInvalidError,
        ) as error:
            return ToolResultBlock(
                call_id=call.call_id,
                status=ToolResultStatus.ERROR,
                content=(TextBlock(error.message),),
                error_code=error.code,
            )

    async def _publish_failure(self, publisher: _EventPublisher, error: NovaAgentError) -> None:
        await publisher.publish(
            ErrorPayload(
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                field=error.field,
            )
        )
        await publisher.publish(RunFailedPayload(error_code=error.code))
        publisher.finish()

    async def cancel(self, run_id: str, *, reason: str) -> bool:
        return await self.registry.cancel(run_id, reason)


def _public_agent_error(error: Exception) -> NovaAgentError:
    if isinstance(error, NovaAgentError):
        return error
    return DependencyUnavailableError("Agent 暂时不可用，请稍后重试")


def _default_id_factory(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _estimate_working_messages(messages: list[Message]) -> int:
    estimate = estimate_messages(messages)
    for message in messages:
        for block in message.content:
            if isinstance(block, ToolCallBlock):
                estimate += len(block.tool_name.encode("utf-8"))
                estimate += len(repr(dict(block.arguments)).encode("utf-8"))
            elif isinstance(block, ToolResultBlock):
                estimate += sum(
                    len(item.text.encode("utf-8"))
                    for item in block.content
                    if isinstance(item, TextBlock)
                )
    return estimate
