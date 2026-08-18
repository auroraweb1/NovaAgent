from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact(record.getMessage()),
        }
        for key in ("event", "request_id", "version", "environment"):
            if hasattr(record, key):
                payload[key] = _redact(str(getattr(record, key)))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def configure_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("novaagent")
    logger.setLevel(level)
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def _redact(value: str) -> str:
    redacted = value
    for marker in ("DASHSCOPE_API_KEY", "NOVAAGENT_WEB_TOKEN"):
        if marker in redacted:
            redacted = redacted.replace(marker, f"{marker}=<redacted>")
    return redacted
