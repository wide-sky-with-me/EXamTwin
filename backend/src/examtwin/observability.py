from __future__ import annotations

import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

_EXTRA_FIELDS = (
    "event",
    "request_id",
    "error_id",
    "error_code",
    "error_type",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "job_id",
    "stage",
    "tool_name",
    "claimed",
    "deleted",
    "failed",
    "retry_in_seconds",
    "traceback",
)


class JsonLogFormatter(logging.Formatter):
    """Small structured formatter that never serializes exception messages."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or request_id_context.get()
        if request_id:
            payload["request_id"] = request_id
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            error_type, _error, error_traceback = record.exc_info
            if error_type is not None:
                payload["exception_type"] = error_type.__name__
            payload["traceback"] = "".join(traceback.format_tb(error_traceback))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(*, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True


def safe_exception_extra(error: BaseException) -> dict[str, str]:
    return {
        "error_type": type(error).__name__,
        "traceback": "".join(traceback.format_tb(error.__traceback__)),
    }
