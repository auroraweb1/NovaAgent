from __future__ import annotations

import os
import platform
import sys
from collections.abc import Mapping
from pathlib import Path

from novaagent.config.loader import runtime_paths
from novaagent.config.model import Settings
from novaagent.domain.providers import PROVIDER_SECRET_ENV


class DiagnosticsService:
    def __init__(
        self,
        settings: Settings,
        version: str,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._settings = settings
        self._version = version
        self._environ = os.environ if environ is None else environ

    def snapshot(self) -> dict[str, object]:
        paths = runtime_paths(self._settings)
        providers = {
            name: {
                "enabled": name in self._settings.providers.enabled,
                "model_configured": bool(getattr(self._settings.providers, name).model),
                "secret_present": bool(self._environ.get(PROVIDER_SECRET_ENV[name])),
            }
            for name in ("qwen",)
        }
        return {
            "service": "novaagent",
            "version": self._version,
            "python": platform.python_version(),
            "environment": self._settings.app.environment,
            "web": {
                "host": self._settings.web.host,
                "port": self._settings.web.port,
                "auth_mode": self._settings.web.auth_mode,
            },
            "providers": {
                "default": self._settings.providers.default,
                "enabled": list(self._settings.providers.enabled),
                "details": providers,
            },
            "paths": {name: str(path) for name, path in paths.as_mapping().items()},
            "runtime": {
                "platform": sys.platform,
                "working_directory": str(Path.cwd()),
            },
        }
