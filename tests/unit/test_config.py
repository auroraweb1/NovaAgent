from pathlib import Path

import pytest

from novaagent.config.loader import load_settings, runtime_paths
from novaagent.config.paths import RuntimePaths
from novaagent.domain.errors import (
    ConfigurationError,
    PathConfigurationError,
    ProviderNotAllowedError,
)


def test_default_settings_use_only_allowed_providers(runtime_environment: dict[str, str]) -> None:
    settings = load_settings(environ=runtime_environment)

    assert settings.providers.default == "qwen"
    assert settings.providers.enabled == ("qwen", "doubao")
    assert settings.web.host == "127.0.0.1"
    assert settings.app.environment == "test"


def test_environment_overrides_provider_and_web_settings(
    runtime_environment: dict[str, str],
) -> None:
    environment = {
        **runtime_environment,
        "NOVAAGENT_PROVIDERS_DEFAULT": "doubao",
        "NOVAAGENT_PROVIDERS_ENABLED": "doubao",
        "NOVAAGENT_WEB_PORT": "9876",
    }

    settings = load_settings(environ=environment)

    assert settings.providers.default == "doubao"
    assert settings.providers.enabled == ("doubao",)
    assert settings.web.port == 9876


def test_unknown_provider_is_rejected(runtime_environment: dict[str, str]) -> None:
    environment = {**runtime_environment, "NOVAAGENT_PROVIDERS_ENABLED": "qwen,openai"}

    with pytest.raises(ProviderNotAllowedError, match="openai"):
        load_settings(environ=environment)


def test_unknown_novaagent_environment_variable_is_rejected(
    runtime_environment: dict[str, str],
) -> None:
    environment = {**runtime_environment, "NOVAAGENT_UNKNOWN": "value"}

    with pytest.raises(ConfigurationError, match="unknown NovaAgent environment variable"):
        load_settings(environ=environment)


def test_non_loopback_host_requires_token(runtime_environment: dict[str, str]) -> None:
    environment = {**runtime_environment, "NOVAAGENT_WEB_HOST": "0.0.0.0"}

    with pytest.raises(ConfigurationError, match="non-loopback"):
        load_settings(environ=environment)


def test_root_runtime_path_is_rejected(runtime_environment: dict[str, str]) -> None:
    environment = {**runtime_environment, "NOVAAGENT_DATA_DIR": "/"}

    with pytest.raises(PathConfigurationError, match="filesystem root"):
        load_settings(environ=environment)


def test_runtime_paths_are_absolute(runtime_environment: dict[str, str]) -> None:
    settings = load_settings(environ=runtime_environment)

    assert all(path.is_absolute() for path in runtime_paths(settings).as_mapping().values())


def test_missing_configuration_file_is_rejected(tmp_path: Path) -> None:
    missing_file = tmp_path / "missing.toml"

    with pytest.raises(ConfigurationError, match="unable to read configuration file") as raised:
        load_settings(config_file=missing_file, environ={})

    assert raised.value.code == "configuration_invalid"
    assert raised.value.field is None


def test_invalid_toml_configuration_is_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "invalid.toml"
    config_file.write_text("[web\nport = 8765", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="invalid TOML configuration") as raised:
        load_settings(config_file=config_file, environ={})

    assert raised.value.code == "configuration_invalid"


def test_environment_overrides_configuration_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[web]
port = 9000

[providers]
default = "qwen"
enabled = ["qwen"]
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(
        environ={
            "NOVAAGENT_CONFIG_FILE": str(config_file),
            "NOVAAGENT_WEB_PORT": "9001",
        }
    )

    assert settings.web.port == 9001
    assert settings.providers.enabled == ("qwen",)


def test_non_integer_web_port_is_rejected(runtime_environment: dict[str, str]) -> None:
    environment = {**runtime_environment, "NOVAAGENT_WEB_PORT": "not-a-port"}

    with pytest.raises(ConfigurationError, match="must be an integer") as raised:
        load_settings(environ=environment)

    assert raised.value.field == "NOVAAGENT_WEB_PORT"


@pytest.mark.parametrize(
    ("enabled", "message"),
    [
        ("", "at least one provider must be enabled"),
        ("qwen,qwen", "must not contain duplicates"),
    ],
)
def test_invalid_enabled_provider_lists_are_rejected(
    runtime_environment: dict[str, str], enabled: str, message: str
) -> None:
    environment = {**runtime_environment, "NOVAAGENT_PROVIDERS_ENABLED": enabled}

    with pytest.raises(ConfigurationError, match=message) as raised:
        load_settings(environ=environment)

    assert raised.value.field == "providers.enabled"


def test_default_provider_must_be_enabled(runtime_environment: dict[str, str]) -> None:
    environment = {
        **runtime_environment,
        "NOVAAGENT_PROVIDERS_DEFAULT": "qwen",
        "NOVAAGENT_PROVIDERS_ENABLED": "doubao",
    }

    with pytest.raises(ConfigurationError, match="must be included") as raised:
        load_settings(environ=environment)

    assert raised.value.field == "providers"


def test_disallowed_provider_table_is_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text("[providers.openai]\nmodel = 'gpt'\n", encoding="utf-8")

    with pytest.raises(ProviderNotAllowedError, match="openai") as raised:
        load_settings(config_file=config_file, environ={})

    assert raised.value.code == "provider_not_allowed"
    assert raised.value.field == "providers"


def test_invalid_log_level_is_rejected(runtime_environment: dict[str, str]) -> None:
    environment = {**runtime_environment, "NOVAAGENT_LOG_LEVEL": "verbose"}

    with pytest.raises(ConfigurationError, match="log_level must be") as raised:
        load_settings(environ=environment)

    assert raised.value.field == "app.log_level"


def test_relative_runtime_paths_are_resolved_from_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    environment = {
        "NOVAAGENT_DATA_DIR": "runtime/data",
        "NOVAAGENT_LOG_DIR": "runtime/logs",
        "NOVAAGENT_WORKSPACE_DIR": "runtime/workspace",
    }

    paths = runtime_paths(load_settings(environ=environment))

    assert paths.data_dir == tmp_path / "runtime/data"
    assert paths.log_dir == tmp_path / "runtime/logs"
    assert paths.workspace_dir == tmp_path / "runtime/workspace"


def test_runtime_directories_are_created(tmp_path: Path) -> None:
    paths = RuntimePaths(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        workspace_dir=tmp_path / "workspace",
    )

    paths.ensure_directories()

    assert all(path.is_dir() for path in paths.as_mapping().values())


def test_runtime_directory_creation_failure_is_reported(tmp_path: Path) -> None:
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("occupied", encoding="utf-8")
    paths = RuntimePaths(
        data_dir=blocking_file / "data",
        log_dir=tmp_path / "logs",
        workspace_dir=tmp_path / "workspace",
    )

    with pytest.raises(PathConfigurationError, match="unable to create data_dir") as raised:
        paths.ensure_directories()

    assert raised.value.code == "path_invalid"
    assert raised.value.field == "data_dir"
