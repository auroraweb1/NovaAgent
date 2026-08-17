from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI

from novaagent import __version__
from novaagent.application.chat import SingleTurnChatService
from novaagent.application.diagnostics import DiagnosticsService
from novaagent.config.loader import load_settings
from novaagent.config.model import Settings
from novaagent.config.secrets import load_runtime_environment
from novaagent.domain.models import ProviderDescriptor
from novaagent.domain.ports import ModelOptions
from novaagent.infrastructure.logging import configure_logging
from novaagent.infrastructure.models.qwen import QwenModelAdapter
from novaagent.interfaces.web import create_app


def build_settings(
    *,
    config_file: Path | None = None,
    environment: str | None = None,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> Settings:
    return load_settings(
        config_file=config_file,
        environment=environment,
        environ=environ,
        env_file=env_file,
    )


def build_app(
    settings: Settings,
    *,
    environ: Mapping[str, str] | None = None,
    qwen_transport: httpx.AsyncBaseTransport | None = None,
    env_file: Path | None = None,
) -> FastAPI:
    environment = load_runtime_environment(environ=environ, env_file=env_file)
    runtime_logger = configure_logging(settings.app.log_level)
    runtime_logger.info("application configured", extra={"event": "application_configured"})
    limits = httpx.Limits(
        max_connections=settings.providers.qwen.max_concurrency,
        max_keepalive_connections=settings.providers.qwen.max_concurrency,
    )
    client = httpx.AsyncClient(transport=qwen_transport, limits=limits)
    model = QwenModelAdapter(
        client=client,
        settings=settings.providers.qwen,
        secret_provider=lambda: environment.get("DASHSCOPE_API_KEY"),
    )
    chat_service = SingleTurnChatService(
        model=model,
        provider=ProviderDescriptor("qwen", settings.providers.qwen.model),
        options=ModelOptions(
            temperature=settings.providers.qwen.temperature,
            max_output_tokens=settings.providers.qwen.max_output_tokens,
        ),
    )
    diagnostics = DiagnosticsService(settings, __version__, environ=environment)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await client.aclose()

    return create_app(
        settings,
        chat_service=chat_service,
        diagnostics=diagnostics,
        lifespan=lifespan,
        environ=environment,
    )
