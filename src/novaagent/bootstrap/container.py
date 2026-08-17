from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI

from novaagent.config.loader import load_settings
from novaagent.config.model import Settings
from novaagent.infrastructure.logging import configure_logging
from novaagent.interfaces.web import create_app


def build_settings(
    *,
    config_file: Path | None = None,
    environment: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    return load_settings(config_file=config_file, environment=environment, environ=environ)


def build_app(settings: Settings, *, environ: Mapping[str, str] | None = None) -> FastAPI:
    runtime_logger = configure_logging(settings.app.log_level)
    runtime_logger.info("application configured", extra={"event": "application_configured"})
    return create_app(settings, environ=environ)
