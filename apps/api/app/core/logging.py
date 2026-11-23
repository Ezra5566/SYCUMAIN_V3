"""Structured logging and request correlation.

Why this exists
---------------
The application previously wrote nothing of its own to the log: a production
500 was answered with a generic message, no traceback, and no way to connect it
to the request that caused it. That is the single worst property of an
operational system — the first real incident becomes guesswork.

Two ideas fix it, and neither needs a third-party library:

1. **One JSON object per line on stdout.** Containers already capture stdout,
   and every log shipper understands JSON. An operator can filter on
   ``level``, ``status_code``, ``duration_ms`` or ``path`` without parsing
   prose.
2. **A correlation id on every line.** :data:`request_id_var` is set once per
   request by ``RequestContextMiddleware`` and read by the formatter, so any
   line written anywhere inside that request — including a SQLAlchemy warning
   or an unhandled traceback — carries the id. The same id is returned in the
   ``X-Request-ID`` response header, which is what makes a user report
   (\"it failed, id abc123\") actionable.

Secrets are not logged here. Record names and status codes only; callers that
need details attach an explicit ``extra`` mapping.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.config.settings import get_settings

#: Correlation id of the request currently being served (empty outside one).
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
#: Authenticated user id, set once the request has been authenticated.
user_id_var: ContextVar[str] = ContextVar("user_id", default="")

_TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(request_id)s] %(message)s"

# Attributes every LogRecord carries; anything else was attached deliberately
# with `extra=` and belongs in the structured payload.
_STANDARD_RECORD_KEYS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName", "request_id"}


class JsonFormatter(logging.Formatter):
    """Render a log record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            # UTC with an explicit offset: a timestamp without a timezone is a
            # timestamp an operator will misread during an incident.
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        user_id = user_id_var.get()
        if user_id:
            payload["user_id"] = user_id

        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable development format, still showing the request id."""

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = request_id_var.get() or "-"
        return super().format(record)


def _wants_json() -> bool:
    """Choose the output format.

    ``auto`` (the default) means JSON everywhere except a local development
    run, where readable lines are more useful than machine-parseable ones.
    """
    settings = get_settings()
    choice = settings.LOG_FORMAT.strip().lower()
    if choice in {"json", "text"}:
        return choice == "json"
    return not settings.is_development


def configure_logging() -> None:
    """Install the process-wide logging configuration.

    Safe to call more than once: handlers are replaced rather than added, so a
    reload or a second import cannot duplicate every line.
    """
    settings = get_settings()
    level = getattr(logging, settings.LOG_LEVEL.strip().upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if _wants_json() else TextFormatter(_TEXT_FORMAT)
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Uvicorn installs its own handlers. Its access line duplicates the
    # structured request line emitted by RequestContextMiddleware, so the
    # handlers are removed; error/startup messages keep flowing into the JSON
    # pipeline through propagation.
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False

    # SQLAlchemy logs every statement *and its bound parameters* at INFO. Those
    # parameters include names, student numbers and dates, so statement logging
    # is opt-in (SQL_ECHO) rather than a side effect of DEBUG.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.SQL_ECHO else logging.WARNING
    )


__all__ = [
    "JsonFormatter",
    "TextFormatter",
    "configure_logging",
    "request_id_var",
    "user_id_var",
]
