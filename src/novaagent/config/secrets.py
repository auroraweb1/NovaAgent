from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from novaagent.domain.errors import ConfigurationError

LOCAL_SECRET_KEYS = frozenset(
    {
        "DASHSCOPE_API_KEY",
        "DOUBAO_API_KEY",
        "NOVAAGENT_WEB_TOKEN",
    }
)
ENV_FILE_VARIABLE = "NOVAAGENT_ENV_FILE"
_KEY_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def load_runtime_environment(
    *,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> dict[str, str]:
    """Merge an ignored local dotenv file with the process environment."""
    process_environment = dict(os.environ if environ is None else environ)
    selected_file = env_file
    required_file = env_file is not None
    if selected_file is None:
        configured = process_environment.get(ENV_FILE_VARIABLE)
        if configured:
            selected_file = Path(configured).expanduser()
            required_file = True
        elif environ is None:
            selected_file = Path.cwd() / ".env"
    local_environment = (
        _read_dotenv(selected_file.expanduser(), required=required_file)
        if selected_file is not None
        else {}
    )
    return {**local_environment, **process_environment}


def _read_dotenv(path: Path, *, required: bool) -> dict[str, str]:
    if not path.is_file():
        if required:
            raise ConfigurationError(f"unable to read environment file: {path}")
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ConfigurationError(f"unable to read environment file: {path}") from error

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigurationError(
                f"invalid environment file line {line_number}",
                field=f"{path}:{line_number}",
            )
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in LOCAL_SECRET_KEYS or not _KEY_PATTERN.fullmatch(key):
            raise ConfigurationError(
                f"unsupported key in environment file: {key}",
                field=f"{path}:{line_number}",
            )
        values[key] = _unquote(value.strip())
    return values


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
