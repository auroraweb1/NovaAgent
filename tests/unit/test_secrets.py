from __future__ import annotations

from pathlib import Path

import pytest

from novaagent.config.secrets import load_runtime_environment
from novaagent.domain.errors import ConfigurationError


def test_local_env_file_supplies_secrets_and_process_values_win(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
# local-only credentials
export DASHSCOPE_API_KEY='from-file'
NOVAAGENT_WEB_TOKEN=web-token
""".strip(),
        encoding="utf-8",
    )

    environment = load_runtime_environment(
        environ={"DASHSCOPE_API_KEY": "from-process"},
        env_file=env_file,
    )

    assert environment["DASHSCOPE_API_KEY"] == "from-process"
    assert environment["NOVAAGENT_WEB_TOKEN"] == "web-token"


def test_explicit_missing_env_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="unable to read environment file"):
        load_runtime_environment(environ={}, env_file=tmp_path / "missing.env")


@pytest.mark.parametrize("line", ["not-a-secret", "OPENAI_API_KEY=value", "=missing-name"])
def test_local_env_file_rejects_unsupported_or_malformed_lines(tmp_path: Path, line: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(line, encoding="utf-8")

    with pytest.raises(ConfigurationError, match="environment file"):
        load_runtime_environment(environ={}, env_file=env_file)


def test_explicit_environment_mapping_does_not_read_implicit_project_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DASHSCOPE_API_KEY=must-not-be-read", encoding="utf-8")

    environment = load_runtime_environment(environ={"NOVAAGENT_ENVIRONMENT": "test"})

    assert "DASHSCOPE_API_KEY" not in environment


def test_default_project_dotenv_is_loaded_without_explicit_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("NOVAAGENT_ENV_FILE", raising=False)
    (tmp_path / ".env").write_text("DASHSCOPE_API_KEY=from-project-file", encoding="utf-8")

    environment = load_runtime_environment()

    assert environment["DASHSCOPE_API_KEY"] == "from-project-file"


def test_novaagent_env_file_selects_an_explicit_local_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "local-secrets.env"
    env_file.write_text("DASHSCOPE_API_KEY=from-selected-file", encoding="utf-8")
    monkeypatch.setenv("NOVAAGENT_ENV_FILE", str(env_file))
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    environment = load_runtime_environment()

    assert environment["DASHSCOPE_API_KEY"] == "from-selected-file"
