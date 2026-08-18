from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from novaagent.config.model import Settings
from novaagent.config.paths import RuntimePaths, resolve_runtime_paths
from novaagent.config.secrets import ENV_FILE_VARIABLE, load_runtime_environment
from novaagent.domain.errors import ConfigurationError, ProviderNotAllowedError
from novaagent.domain.providers import ALLOWED_PROVIDERS

ALLOWED_ENVIRONMENT_KEYS = frozenset(
    {
        "NOVAAGENT_CONFIG_FILE",
        ENV_FILE_VARIABLE,
        "NOVAAGENT_ENVIRONMENT",
        "NOVAAGENT_LOG_LEVEL",
        "NOVAAGENT_AGENT_MAX_STEPS",
        "NOVAAGENT_AGENT_MAX_TOOL_CALLS",
        "NOVAAGENT_AGENT_MAX_TOOL_CALLS_PER_STEP",
        "NOVAAGENT_AGENT_TOTAL_TIMEOUT_SECONDS",
        "NOVAAGENT_AGENT_MODEL_STEP_TIMEOUT_SECONDS",
        "NOVAAGENT_AGENT_TOOL_TIMEOUT_SECONDS",
        "NOVAAGENT_WEB_HOST",
        "NOVAAGENT_WEB_PORT",
        "NOVAAGENT_WEB_AUTH_MODE",
        "NOVAAGENT_PROVIDERS_DEFAULT",
        "NOVAAGENT_PROVIDERS_ENABLED",
        "NOVAAGENT_QWEN_MODEL",
        "NOVAAGENT_QWEN_TEMPERATURE",
        "NOVAAGENT_QWEN_MAX_OUTPUT_TOKENS",
        "NOVAAGENT_QWEN_TIMEOUT_SECONDS",
        "NOVAAGENT_QWEN_MAX_RETRIES",
        "NOVAAGENT_QWEN_MAX_CONCURRENCY",
        "NOVAAGENT_DATA_DIR",
        "NOVAAGENT_LOG_DIR",
        "NOVAAGENT_WORKSPACE_DIR",
        "NOVAAGENT_WEB_TOKEN",
    }
)


def load_settings(
    *,
    config_file: Path | None = None,
    environment: str | None = None,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> Settings:
    env = load_runtime_environment(environ=environ, env_file=env_file)
    _reject_unknown_environment(env)
    selected_file = config_file or _config_file_from_env(env)
    raw = _read_toml(selected_file) if selected_file is not None else {}
    merged = _apply_environment(raw, env)
    if environment is not None:
        merged.setdefault("app", {})["environment"] = environment
    _reject_disallowed_providers(merged)
    try:
        settings = Settings.model_validate(merged)
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(item) for item in first["loc"])
        raise ConfigurationError(str(first["msg"]), field=location) from error
    _validate_paths(settings)
    return settings


def runtime_paths(settings: Settings) -> RuntimePaths:
    return resolve_runtime_paths(
        settings.paths.data_dir,
        settings.paths.log_dir,
        settings.paths.workspace_dir,
    )


def _config_file_from_env(environ: Mapping[str, str]) -> Path | None:
    configured = environ.get("NOVAAGENT_CONFIG_FILE")
    if configured:
        return Path(configured).expanduser()
    default = Path("~/.novaagent/config.toml").expanduser()
    return default if default.is_file() else None


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            loaded = tomllib.load(stream)
    except OSError as error:
        raise ConfigurationError(f"unable to read configuration file: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"invalid TOML configuration: {path}") from error
    return loaded


def _apply_environment(raw: Mapping[str, Any], environ: Mapping[str, str]) -> dict[str, Any]:
    result = _deep_copy_mapping(raw)
    app = result.setdefault("app", {})
    agent = result.setdefault("agent", {})
    web = result.setdefault("web", {})
    providers = result.setdefault("providers", {})
    qwen = providers.setdefault("qwen", {})
    paths = result.setdefault("paths", {})
    _set_if_present(app, "environment", environ, "NOVAAGENT_ENVIRONMENT")
    _set_if_present(app, "log_level", environ, "NOVAAGENT_LOG_LEVEL")
    for field, env_name in (
        ("max_steps", "NOVAAGENT_AGENT_MAX_STEPS"),
        ("max_tool_calls", "NOVAAGENT_AGENT_MAX_TOOL_CALLS"),
        ("max_tool_calls_per_step", "NOVAAGENT_AGENT_MAX_TOOL_CALLS_PER_STEP"),
    ):
        if env_name in environ:
            agent[field] = _parse_int(environ[env_name], env_name)
    for field, env_name in (
        ("total_timeout_seconds", "NOVAAGENT_AGENT_TOTAL_TIMEOUT_SECONDS"),
        ("model_step_timeout_seconds", "NOVAAGENT_AGENT_MODEL_STEP_TIMEOUT_SECONDS"),
        ("tool_timeout_seconds", "NOVAAGENT_AGENT_TOOL_TIMEOUT_SECONDS"),
    ):
        if env_name in environ:
            agent[field] = _parse_float(environ[env_name], env_name)
    _set_if_present(web, "host", environ, "NOVAAGENT_WEB_HOST")
    if "NOVAAGENT_WEB_PORT" in environ:
        web["port"] = _parse_int(environ["NOVAAGENT_WEB_PORT"], "NOVAAGENT_WEB_PORT")
    _set_if_present(web, "auth_mode", environ, "NOVAAGENT_WEB_AUTH_MODE")
    _set_if_present(providers, "default", environ, "NOVAAGENT_PROVIDERS_DEFAULT")
    if "NOVAAGENT_PROVIDERS_ENABLED" in environ:
        providers["enabled"] = [
            item.strip()
            for item in environ["NOVAAGENT_PROVIDERS_ENABLED"].split(",")
            if item.strip()
        ]
    _set_if_present(qwen, "model", environ, "NOVAAGENT_QWEN_MODEL")
    if "NOVAAGENT_QWEN_TEMPERATURE" in environ:
        qwen["temperature"] = _parse_float(
            environ["NOVAAGENT_QWEN_TEMPERATURE"], "NOVAAGENT_QWEN_TEMPERATURE"
        )
    for field, env_name in (
        ("max_output_tokens", "NOVAAGENT_QWEN_MAX_OUTPUT_TOKENS"),
        ("max_retries", "NOVAAGENT_QWEN_MAX_RETRIES"),
        ("max_concurrency", "NOVAAGENT_QWEN_MAX_CONCURRENCY"),
    ):
        if env_name in environ:
            qwen[field] = _parse_int(environ[env_name], env_name)
    if "NOVAAGENT_QWEN_TIMEOUT_SECONDS" in environ:
        qwen["timeout_seconds"] = _parse_float(
            environ["NOVAAGENT_QWEN_TIMEOUT_SECONDS"],
            "NOVAAGENT_QWEN_TIMEOUT_SECONDS",
        )
    _set_if_present(paths, "data_dir", environ, "NOVAAGENT_DATA_DIR")
    _set_if_present(paths, "log_dir", environ, "NOVAAGENT_LOG_DIR")
    _set_if_present(paths, "workspace_dir", environ, "NOVAAGENT_WORKSPACE_DIR")
    return result


def _deep_copy_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        result[key] = _deep_copy_mapping(item) if isinstance(item, Mapping) else item
    return result


def _set_if_present(
    target: dict[str, Any], field: str, environ: Mapping[str, str], env_name: str
) -> None:
    if env_name in environ:
        target[field] = environ[env_name]


def _parse_int(value: str, field: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise ConfigurationError(f"{field} must be an integer", field=field) from error


def _parse_float(value: str, field: str) -> float:
    try:
        return float(value)
    except ValueError as error:
        raise ConfigurationError(f"{field} must be a number", field=field) from error


def _reject_unknown_environment(environ: Mapping[str, str]) -> None:
    unknown = sorted(
        key
        for key in environ
        if key.startswith("NOVAAGENT_") and key not in ALLOWED_ENVIRONMENT_KEYS
    )
    if unknown:
        raise ConfigurationError(f"unknown NovaAgent environment variable: {unknown[0]}")


def _validate_paths(settings: Settings) -> None:
    resolve_runtime_paths(
        settings.paths.data_dir,
        settings.paths.log_dir,
        settings.paths.workspace_dir,
    )


def _reject_disallowed_providers(config: Mapping[str, Any]) -> None:
    providers = config.get("providers", {})
    if not isinstance(providers, Mapping):
        return
    provider_keys = set(providers) - {"default", "enabled", *ALLOWED_PROVIDERS}
    if provider_keys:
        raise ProviderNotAllowedError(sorted(provider_keys)[0])
    configured = providers.get("enabled", [])
    if isinstance(configured, list):
        for provider in configured:
            if provider not in ALLOWED_PROVIDERS:
                raise ProviderNotAllowedError(str(provider))
    default = providers.get("default")
    if default is not None and default not in ALLOWED_PROVIDERS:
        raise ProviderNotAllowedError(str(default))
