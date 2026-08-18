from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Annotated, Protocol
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from novaagent import __version__
from novaagent.application.chat import MultiTurnChatResult, SingleTurnChatService
from novaagent.application.diagnostics import DiagnosticsService
from novaagent.application.health import HealthService
from novaagent.config.loader import runtime_paths
from novaagent.config.model import Settings
from novaagent.domain.errors import (
    AuthenticationRequiredError,
    EmptyMessageError,
    MessageTooLongError,
    NovaAgentError,
    RequestInvalidError,
    RequestTooLargeError,
    RunNotFoundError,
    SessionBusyError,
    SessionRevisionConflictError,
)
from novaagent.domain.events import TERMINAL_EVENT_TYPES, AgentEvent
from novaagent.domain.ports import EventSinkPort, MultiTurnSessionStorePort
from novaagent.interfaces.web.chat_protocol import (
    ChatRequestSchema,
    chat_response_from_result,
)
from novaagent.interfaces.web.protocol import event_to_dict
from novaagent.interfaces.web.session_protocol import (
    StreamChatRequestSchema,
    session_detail_response,
    session_response,
    summary_to_schema,
)

CHAT_BODY_LIMIT = 64 * 1024
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_STATIC_DIR = Path(__file__).with_name("static")

type Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


class SessionRunService(Protocol):
    @property
    def store(self) -> MultiTurnSessionStorePort: ...

    async def validate_context(self, *, session_id: str, text: str) -> None: ...

    async def stream_chat(
        self,
        *,
        session_id: str,
        expected_revision: int,
        text: str,
        sink: EventSinkPort,
    ) -> MultiTurnChatResult: ...

    async def cancel(self, run_id: str, *, reason: str) -> bool: ...


_ERROR_STATUS = {
    "message_empty": 422,
    "message_too_long": 422,
    "request_invalid": 422,
    "request_too_large": 413,
    "authentication_required": 401,
    "secret_missing": 503,
    "provider_authentication_failed": 502,
    "provider_rate_limited": 429,
    "provider_timeout": 504,
    "provider_busy": 503,
    "provider_model_invalid": 503,
    "provider_input_rejected": 422,
    "provider_unavailable": 503,
    "provider_response_invalid": 502,
    "protocol_invalid": 500,
    "dependency_unavailable": 503,
    "session_not_found": 404,
    "session_busy": 409,
    "session_revision_conflict": 409,
    "session_limit_reached": 409,
    "context_too_large": 422,
    "run_not_found": 404,
    "stream_protocol_invalid": 502,
}


def create_app(
    settings: Settings,
    *,
    chat_service: SingleTurnChatService,
    diagnostics: DiagnosticsService,
    multi_turn_service: SessionRunService,
    lifespan: Lifespan,
    environ: Mapping[str, str],
) -> FastAPI:
    app = FastAPI(title="NovaAgent", version=__version__, lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=_allowed_hosts(settings),
    )
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR), name="assets")
    health = HealthService(version=__version__)
    expected_token = environ.get("NOVAAGENT_WEB_TOKEN")

    @app.exception_handler(NovaAgentError)
    async def handle_domain_error(request: Request, error: NovaAgentError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid4()))
        payload: dict[str, object] = {
            "code": error.code,
            "message": error.message,
            "request_id": request_id,
            "retryable": error.retryable,
        }
        if error.field is not None:
            payload["field"] = error.field
        return JSONResponse(
            status_code=_ERROR_STATUS.get(error.code, 500),
            content={"error": payload},
        )

    @app.exception_handler(Exception)
    async def handle_internal_error(request: Request, _: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid4()))
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "服务发生内部错误，请使用请求编号进行诊断",
                    "request_id": request_id,
                    "retryable": False,
                }
            },
        )

    @app.middleware("http")
    async def add_response_metadata(request: Request, call_next):  # type: ignore[no-untyped-def]
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            supplied_request_id
            if _REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else str(uuid4())
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    def require_auth(
        authorization: Annotated[str | None, Header()] = None,
        x_novaagent_token: Annotated[str | None, Header()] = None,
    ) -> None:
        if settings.web.auth_mode == "local":
            return
        supplied = x_novaagent_token
        if supplied is None and authorization and authorization.lower().startswith("bearer "):
            supplied = authorization[7:]
        if not expected_token or supplied != expected_token:
            raise AuthenticationRequiredError()

    @app.get("/health/live")
    async def live() -> dict[str, object]:
        return health.live()

    @app.get("/health/ready")
    async def ready() -> dict[str, object]:
        runtime_paths(settings).ensure_directories()
        return health.readiness()

    @app.get("/api/v1/diagnostics")
    async def diagnostics_endpoint(_: None = Depends(require_auth)) -> dict[str, object]:
        return diagnostics.snapshot()

    @app.post("/api/v1/chat")
    async def chat(request: Request, _: None = Depends(require_auth)) -> JSONResponse:
        chat_request = await _read_chat_request(request)
        result = await chat_service.chat(chat_request.message)
        response = chat_response_from_result(result)
        return JSONResponse(response.model_dump(mode="json"))

    @app.post("/api/v1/sessions", status_code=201)
    async def create_session(_: None = Depends(require_auth)) -> JSONResponse:
        snapshot = await multi_turn_service.store.create_session()
        return JSONResponse(session_response(snapshot).model_dump(mode="json"), status_code=201)

    @app.get("/api/v1/sessions")
    async def list_sessions(_: None = Depends(require_auth)) -> dict[str, object]:
        summaries = await multi_turn_service.store.list_sessions()
        return {
            "protocol_version": "1",
            "sessions": [summary_to_schema(item).model_dump(mode="json") for item in summaries],
        }

    @app.get("/api/v1/sessions/{session_id}")
    async def get_session(session_id: str, _: None = Depends(require_auth)) -> JSONResponse:
        snapshot = await multi_turn_service.store.get_session(session_id)
        return JSONResponse(session_detail_response(snapshot).model_dump(mode="json"))

    @app.delete("/api/v1/sessions/{session_id}/messages")
    async def clear_session(
        session_id: str,
        expected_revision: int = Query(ge=0),
        _: None = Depends(require_auth),
    ) -> JSONResponse:
        snapshot = await multi_turn_service.store.clear_session(session_id, expected_revision)
        return JSONResponse(session_detail_response(snapshot).model_dump(mode="json"))

    @app.delete("/api/v1/sessions/{session_id}", status_code=204)
    async def delete_session(
        session_id: str,
        expected_revision: int = Query(ge=0),
        _: None = Depends(require_auth),
    ) -> None:
        await multi_turn_service.store.delete_session(session_id, expected_revision)

    @app.post("/api/v1/runs/{run_id}/cancel", status_code=202)
    async def cancel_run(run_id: str, _: None = Depends(require_auth)) -> JSONResponse:
        if not await multi_turn_service.cancel(run_id, reason="user_requested"):
            raise RunNotFoundError()
        return JSONResponse(
            {
                "protocol_version": "1",
                "run_id": run_id,
                "status": "cancellation_requested",
            },
            status_code=202,
        )

    @app.post("/api/v1/sessions/{session_id}/messages:stream")
    async def stream_chat(
        session_id: str,
        request: Request,
        _: None = Depends(require_auth),
    ) -> StreamingResponse:
        stream_request = await _read_json_model(request, StreamChatRequestSchema)
        if not stream_request.message.strip():
            raise EmptyMessageError()
        if len(stream_request.message) > 32_000:
            raise MessageTooLongError(32_000)
        session = await multi_turn_service.store.get_session(session_id)
        if session.revision != stream_request.expected_revision:
            raise SessionRevisionConflictError()
        if session.active_run_id is not None:
            raise SessionBusyError()
        await multi_turn_service.validate_context(
            session_id=session_id,
            text=stream_request.message,
        )

        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue(maxsize=64)
        run_id_holder: dict[str, str | None] = {"run_id": None}

        async def produce() -> None:
            try:
                await multi_turn_service.stream_chat(
                    session_id=session_id,
                    expected_revision=stream_request.expected_revision,
                    text=stream_request.message,
                    sink=_QueueSink(queue, run_id_holder),
                )
            except asyncio.CancelledError:
                raise
            except NovaAgentError:
                # Model errors are already represented by error/run_failed events.
                pass
            finally:
                await queue.put(None)

        async def generate() -> AsyncIterator[bytes]:
            task = asyncio.create_task(produce())
            terminal_seen = False
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except TimeoutError:
                        yield b": keepalive\n\n"
                        continue
                    if item is None:
                        break
                    yield _sse_frame(item)
                    if item.type in TERMINAL_EVENT_TYPES:
                        terminal_seen = True
                        break
            except asyncio.CancelledError:
                if run_id_holder["run_id"] is not None:
                    await multi_turn_service.cancel(
                        run_id_holder["run_id"], reason="client_disconnected"
                    )
                else:
                    task.cancel()
                raise
            finally:
                if not task.done() and not terminal_seen:
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html", media_type="text/html")

    return app


async def _read_chat_request(request: Request) -> ChatRequestSchema:
    return await _read_json_model(request, ChatRequestSchema)


async def _read_json_model(request: Request, model_type):  # type: ignore[no-untyped-def]
    content_type = request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise RequestInvalidError("请求必须使用 application/json")

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > CHAT_BODY_LIMIT:
            raise RequestTooLargeError()
        chunks.append(chunk)
    try:
        raw = b"".join(chunks)
        if not raw.strip():
            raw = b"{}"
        return model_type.model_validate_json(raw)
    except ValidationError as error:
        first = error.errors()[0]
        location = first.get("loc", ())
        field = str(location[0]) if location and location[0] == "message" else None
        raise RequestInvalidError(field=field) from error


class _QueueSink:
    def __init__(
        self, queue: asyncio.Queue[AgentEvent | None], holder: dict[str, str | None]
    ) -> None:
        self._queue = queue
        self._holder = holder

    async def publish(self, event: AgentEvent) -> None:
        self._holder["run_id"] = event.run_id
        await self._queue.put(event)


def _sse_frame(event: AgentEvent) -> bytes:
    payload = json.dumps(event_to_dict(event), ensure_ascii=False, separators=(",", ":"))
    return f"event: agent_event\nid: {event.sequence}\ndata: {payload}\n\n".encode()


def _allowed_hosts(settings: Settings) -> list[str]:
    hosts = {settings.web.host, "127.0.0.1", "localhost", "::1"}
    if settings.app.environment == "test":
        hosts.add("testserver")
    return sorted(hosts)
