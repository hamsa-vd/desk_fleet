"""JSON logging to stdout with secret redaction on every record."""

import json
import logging
import re
import sys
from typing import Any

from deskfleet.config.settings import Settings

REDACTED = "***REDACTED***"

# Provider key shapes: OpenAI (sk-), LangSmith (lsv2_), Groq (gsk_).
_SECRET_VALUE_PATTERN = re.compile(r"\b(?:sk-|lsv2_|gsk_)[A-Za-z0-9_\-]{4,}")
_SECRET_FIELD_PATTERN = re.compile(r"key|token|secret|password|authorization", re.IGNORECASE)

# Standard LogRecord attributes; anything else on the record is caller-supplied context.
_RESERVED_RECORD_FIELDS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRET_VALUE_PATTERN.sub(REDACTED, value)
    if isinstance(value, dict):
        return {
            k: REDACTED if _SECRET_FIELD_PATTERN.search(str(k)) else _scrub(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(_scrub(v) for v in value)
    return value


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _scrub(record.msg)
        if record.args:
            record.args = _scrub(record.args)
        for field, value in list(record.__dict__.items()):
            if field in _RESERVED_RECORD_FIELDS:
                continue
            record.__dict__[field] = (
                REDACTED if _SECRET_FIELD_PATTERN.search(field) else _scrub(value)
            )
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for field, value in record.__dict__.items():
            if field not in _RESERVED_RECORD_FIELDS:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SecretRedactionFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)

    if settings.langchain_tracing_v2 and not settings.langchain_endpoint_is_known:
        get_logger(__name__).warning(
            "unrecognised_langchain_endpoint",
            extra={"endpoint": settings.langchain_endpoint},
        )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
