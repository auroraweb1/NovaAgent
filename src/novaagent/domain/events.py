from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DiagnosticEvent:
    """A serializable diagnostic item emitted by the foundation services."""

    name: str
    status: str
    details: dict[str, Any]
