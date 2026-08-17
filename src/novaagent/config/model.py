from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from novaagent.domain.providers import ALLOWED_PROVIDERS, ProviderName


def default_enabled_providers() -> tuple[ProviderName, ...]:
    return ("qwen", "doubao")


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    environment: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("log_level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        return normalized


class WebSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    auth_mode: Literal["local", "token"] = "local"

    @model_validator(mode="after")
    def require_token_for_non_loopback(self) -> WebSettings:
        loopback_hosts = {"127.0.0.1", "localhost", "::1"}
        if self.host not in loopback_hosts and self.auth_mode != "token":
            raise ValueError("non-loopback Web hosts require token authentication")
        return self


class ProviderEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = ""


class ProvidersSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    default: ProviderName = "qwen"
    enabled: tuple[ProviderName, ...] = Field(default_factory=default_enabled_providers)
    qwen: ProviderEntry = Field(default_factory=ProviderEntry)
    doubao: ProviderEntry = Field(default_factory=ProviderEntry)

    @field_validator("enabled")
    @classmethod
    def validate_enabled(cls, value: tuple[ProviderName, ...]) -> tuple[ProviderName, ...]:
        if not value:
            raise ValueError("at least one provider must be enabled")
        if len(set(value)) != len(value):
            raise ValueError("providers.enabled must not contain duplicates")
        unknown = set(value) - ALLOWED_PROVIDERS
        if unknown:
            raise ValueError(f"unsupported providers: {sorted(unknown)}")
        return value

    @model_validator(mode="after")
    def validate_default(self) -> ProvidersSettings:
        if self.default not in self.enabled:
            raise ValueError("providers.default must be included in providers.enabled")
        return self


class PathsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data_dir: Path = Path("~/.novaagent/data")
    log_dir: Path = Path("~/.novaagent/logs")
    workspace_dir: Path = Path("~/.novaagent/workspace")


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    app: AppSettings = Field(default_factory=AppSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    providers: ProvidersSettings = Field(default_factory=ProvidersSettings)
    paths: PathsSettings = Field(default_factory=PathsSettings)
