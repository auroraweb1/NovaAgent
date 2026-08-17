from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from novaagent.domain.errors import PathConfigurationError


@dataclass(frozen=True)
class RuntimePaths:
    data_dir: Path
    log_dir: Path
    workspace_dir: Path

    def ensure_directories(self) -> None:
        for name, path in self.as_mapping().items():
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise PathConfigurationError(
                    f"unable to create {name} directory: {path}", field=name
                ) from error

    def as_mapping(self) -> dict[str, Path]:
        return {
            "data_dir": self.data_dir,
            "log_dir": self.log_dir,
            "workspace_dir": self.workspace_dir,
        }


def resolve_runtime_paths(data_dir: Path, log_dir: Path, workspace_dir: Path) -> RuntimePaths:
    paths = RuntimePaths(
        data_dir=_normalize(data_dir),
        log_dir=_normalize(log_dir),
        workspace_dir=_normalize(workspace_dir),
    )
    for name, path in paths.as_mapping().items():
        if path == Path(path.anchor):
            raise PathConfigurationError(f"{name} cannot be the filesystem root", field=name)
    return paths


def _normalize(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    return expanded
