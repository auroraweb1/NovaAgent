from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from novaagent.application.chat.context_window import (
    DEFAULT_CONTEXT_ESTIMATED_TOKEN_BUDGET,
    DEFAULT_CONTEXT_TURNS,
    select_context,
)
from novaagent.application.protocol.driver import create_user_message, run_protocol
from novaagent.domain.errors import ContextTooLargeError, ProtocolValidationError
from novaagent.domain.events import AgentEvent, MessageCompletedPayload
from novaagent.domain.messages import Message
from novaagent.domain.ports import (
    EventSinkPort,
    ModelOptions,
    ModelRequest,
    MultiTurnSessionStorePort,
)
from novaagent.domain.sessions import SessionSnapshot


class StreamingModelPort(Protocol):
    def stream_live(self, request: ModelRequest) -> AsyncIterator[object]: ...


@dataclass(frozen=True, slots=True)
class MultiTurnChatResult:
    run_id: str
    snapshot: SessionSnapshot
    message: Message


class ActiveRunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, tuple[asyncio.Task[object], str]] = {}
        self._lock = asyncio.Lock()

    async def register(self, run_id: str, task: asyncio.Task[object]) -> None:
        async with self._lock:
            self._runs[run_id] = (task, "user_requested")

    async def cancel(self, run_id: str, reason: str) -> bool:
        async with self._lock:
            entry = self._runs.get(run_id)
            if entry is None:
                return False
            task, _ = entry
            self._runs[run_id] = (task, reason)
            task.cancel()
            return True

    async def reason(self, run_id: str) -> str:
        async with self._lock:
            entry = self._runs.get(run_id)
            return entry[1] if entry is not None else "user_requested"

    def reason_now(self, run_id: str) -> str:
        entry = self._runs.get(run_id)
        return entry[1] if entry is not None else "user_requested"

    async def remove(self, run_id: str) -> None:
        async with self._lock:
            self._runs.pop(run_id, None)


class _ForwardingSink:
    def __init__(self, sink: EventSinkPort) -> None:
        self._sink = sink
        self.message: Message | None = None
        self.run_id: str | None = None

    async def publish(self, event: AgentEvent) -> None:
        await self._sink.publish(event)
        if self.run_id is None:
            self.run_id = event.run_id
        if isinstance(event.payload, MessageCompletedPayload):
            self.message = event.payload.message


class _StreamingModelAdapter:
    def __init__(self, model: StreamingModelPort) -> None:
        self._model = model

    def stream(self, request: ModelRequest) -> AsyncIterator[object]:
        return self._model.stream_live(request)


class MultiTurnChatService:
    def __init__(
        self,
        *,
        model: StreamingModelPort,
        store: MultiTurnSessionStorePort,
        options: ModelOptions,
        registry: ActiveRunRegistry | None = None,
        id_factory: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        max_turns: int = DEFAULT_CONTEXT_TURNS,
        context_budget: int = DEFAULT_CONTEXT_ESTIMATED_TOKEN_BUDGET,
    ) -> None:
        self._model = model
        self._store = store
        self._options = options
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
        user_message = create_user_message(
            text,
            message_id=self._id_factory("validation"),
            created_at=self._clock(),
        )
        try:
            select_context(
                system_messages=(),
                history=session.messages,
                current_user=user_message,
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
            text,
            message_id=self._id_factory("msg"),
            created_at=self._clock(),
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
        if task is None:  # pragma: no cover - called from an async task
            raise RuntimeError("multi-turn chat requires an asyncio task")
        await self.registry.register(run_id, task)
        forward = _ForwardingSink(sink)
        try:
            request = ModelRequest(
                messages=context.messages,
                options=self._options,
            )
            message = await run_protocol(
                request,
                model=_StreamingModelAdapter(self._model),  # type: ignore[arg-type]
                sink=forward,
                session_id=session_id,
                id_factory=self._run_id_factory(run_id),
                clock=self._clock,
                context=context,
                cancellation_reason=lambda: self._cancel_reason(run_id),
            )
            snapshot = await self._store.commit_turn(
                session_id, expected_revision, user_message, message
            )
            return MultiTurnChatResult(run_id=run_id, snapshot=snapshot, message=message)
        finally:
            await self.registry.remove(run_id)
            await self._store.clear_active_run(session_id, run_id)

    def _run_id_factory(self, run_id: str) -> Callable[[str], str]:
        generated = False

        def make(prefix: str) -> str:
            nonlocal generated
            if prefix == "run" and not generated:
                generated = True
                return run_id
            return self._id_factory(prefix)

        return make

    def _cancel_reason(self, run_id: str) -> str:
        return self.registry.reason_now(run_id)

    async def cancel(self, run_id: str, *, reason: str) -> bool:
        return await self.registry.cancel(run_id, reason)


def _default_id_factory(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _utc_now() -> datetime:
    return datetime.now(UTC)
