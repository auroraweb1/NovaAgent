from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from novaagent.domain.providers import ALLOWED_PROVIDERS, ProviderName


def default_enabled_providers() -> tuple[ProviderName, ...]:
    return ("qwen",)


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


QWEN_MODEL_PATTERN = re.compile(r"^qwen[a-z0-9._-]{0,124}$")


class QwenProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = "qwen3.8-max"
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_output_tokens: int = Field(default=2048, ge=1, le=32768)
    timeout_seconds: float = Field(default=60, ge=1, le=300)
    max_retries: int = Field(default=1, ge=0, le=2)
    max_concurrency: int = Field(default=4, ge=1, le=32)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if not QWEN_MODEL_PATTERN.fullmatch(value):
            raise ValueError(
                "qwen model must start with 'qwen' and contain only lowercase letters, "
                "numbers, dots, underscores, and hyphens"
            )
        return value


class AgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_steps: int = Field(default=8, ge=1, le=32)
    max_tool_calls: int = Field(default=16, ge=1, le=64)
    max_tool_calls_per_step: int = Field(default=8, ge=1, le=16)
    total_timeout_seconds: float = Field(default=180, ge=10, le=900)
    model_step_timeout_seconds: float = Field(default=75, ge=1, le=300)
    tool_timeout_seconds: float = Field(default=10, ge=1, le=120)


class ProvidersSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    default: ProviderName = "qwen"
    enabled: tuple[ProviderName, ...] = Field(default_factory=default_enabled_providers)
    qwen: QwenProviderSettings = Field(default_factory=QwenProviderSettings)

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
        if self.default != "qwen" or self.enabled != ("qwen",):
            raise ValueError("only qwen may be enabled")
        return self


class PathsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data_dir: Path = Path("~/.novaagent/data")
    log_dir: Path = Path("~/.novaagent/logs")
    workspace_dir: Path = Path("~/.novaagent/workspace")


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    app: AppSettings = Field(default_factory=AppSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    providers: ProvidersSettings = Field(default_factory=ProvidersSettings)
    paths: PathsSettings = Field(default_factory=PathsSettings)
