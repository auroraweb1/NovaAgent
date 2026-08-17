from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class HealthService:
    version: str
    ready: bool = True

    def live(self) -> dict[str, object]:
        return {
            "status": "ok",
            "service": "novaagent",
            "version": self.version,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def readiness(self) -> dict[str, object]:
        status = "ready" if self.ready else "not_ready"
        return {
            "status": status,
            "service": "novaagent",
            "version": self.version,
            "checks": {"configuration": "ok" if self.ready else "failed"},
            "timestamp": datetime.now(UTC).isoformat(),
        }
