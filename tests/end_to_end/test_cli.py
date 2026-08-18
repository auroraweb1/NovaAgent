import argparse
import json

import pytest

from novaagent.interfaces.management_cli.main import _doctor


def test_doctor_reports_missing_secrets_without_failing(
    runtime_environment: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("NOVAAGENT_DATA_DIR", runtime_environment["NOVAAGENT_DATA_DIR"])
    monkeypatch.setenv("NOVAAGENT_LOG_DIR", runtime_environment["NOVAAGENT_LOG_DIR"])
    monkeypatch.setenv("NOVAAGENT_WORKSPACE_DIR", runtime_environment["NOVAAGENT_WORKSPACE_DIR"])
    monkeypatch.setenv("NOVAAGENT_ENVIRONMENT", "test")

    args = argparse.Namespace(config_file=None, environment="test")
    assert _doctor(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["warnings"] == ["DASHSCOPE_API_KEY is not set"]
