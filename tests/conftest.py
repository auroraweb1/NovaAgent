from pathlib import Path

import pytest


@pytest.fixture
def runtime_environment(tmp_path: Path) -> dict[str, str]:
    return {
        "NOVAAGENT_DATA_DIR": str(tmp_path / "data"),
        "NOVAAGENT_LOG_DIR": str(tmp_path / "logs"),
        "NOVAAGENT_WORKSPACE_DIR": str(tmp_path / "workspace"),
        "NOVAAGENT_ENVIRONMENT": "test",
    }
