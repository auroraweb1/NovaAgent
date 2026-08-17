from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from novaagent import __version__
from novaagent.application.chat import SingleTurnChatService
from novaagent.application.diagnostics import DiagnosticsService
from novaagent.application.health import HealthService
from novaagent.config.loader import runtime_paths
from novaagent.config.model import Settings
from novaagent.domain.errors import (
    AuthenticationRequiredError,
    NovaAgentError,
    RequestInvalidError,
    RequestTooLargeError,
)
from novaagent.interfaces.web.chat_protocol import (
    ChatRequestSchema,
    chat_response_from_result,
)

CHAT_BODY_LIMIT = 64 * 1024
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_STATIC_DIR = Path(__file__).with_name("static")

type Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]

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
}


def create_app(
    settings: Settings,
    *,
    chat_service: SingleTurnChatService,
    diagnostics: DiagnosticsService,
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

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html", media_type="text/html")

    return app


async def _read_chat_request(request: Request) -> ChatRequestSchema:
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
        return ChatRequestSchema.model_validate_json(b"".join(chunks))
    except ValidationError as error:
        first = error.errors()[0]
        location = first.get("loc", ())
        field = str(location[0]) if location and location[0] == "message" else None
        raise RequestInvalidError(field=field) from error


def _allowed_hosts(settings: Settings) -> list[str]:
    hosts = {settings.web.host, "127.0.0.1", "localhost", "::1"}
    if settings.app.environment == "test":
        hosts.add("testserver")
    return sorted(hosts)
