from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from novaagent import __version__
from novaagent.application.diagnostics import DiagnosticsService
from novaagent.application.health import HealthService
from novaagent.config.loader import runtime_paths
from novaagent.config.model import Settings
from novaagent.domain.errors import NovaAgentError


def create_app(settings: Settings, *, environ: Mapping[str, str] | None = None) -> FastAPI:
    environment = dict(os.environ if environ is None else environ)
    app = FastAPI(title="NovaAgent", version=__version__)
    health = HealthService(version=__version__)
    diagnostics = DiagnosticsService(settings=settings, version=__version__)
    expected_token = environment.get("NOVAAGENT_WEB_TOKEN")

    @app.exception_handler(NovaAgentError)
    async def handle_domain_error(_: Request, error: NovaAgentError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": _error_payload(error.code, error.message)},
        )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
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
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": _error_payload("authentication_required", "authentication required")
                },
            )

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

    @app.get("/")
    async def root(_: None = Depends(require_auth)) -> dict[str, object]:
        return {
            "service": "novaagent",
            "version": __version__,
            "stage": "01-engineering-foundation",
            "chat": "not_implemented",
        }

    return app


def _error_payload(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message, "request_id": str(uuid4())}
