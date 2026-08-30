import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Context variable for holding request ID across async tasks
request_id_ctx_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def get_request_id() -> str | None:
    """Retrieve current request ID from context variable."""
    return request_id_ctx_var.get()


def set_request_id(req_id: str | None) -> contextvars.Token[str | None]:
    """Set current request ID in context variable."""
    return request_id_ctx_var.set(req_id)


class SensitiveDataFilter(logging.Filter):
    """
    Log filter to sanitize and ensure sensitive tokens and headers are never logged.
    """

    SENSITIVE_KEYS = {
        "password",
        "secret",
        "token",
        "authorization",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            # Check if any sensitive keys are present in string message
            lowered = record.msg.lower()
            for key in self.SENSITIVE_KEYS:
                if f"{key}=" in lowered or f'"{key}"' in lowered:
                    record.msg = "[FILTERED_SENSITIVE_DATA]"
                    break
        return True


class StructuredTextFormatter(logging.Formatter):
    """
    Structured text formatter:
    Example: 2026-08-30T19:10:00Z INFO request_id=abc123 app.api GET /health 200
    """

    def format(self, record: logging.LogRecord) -> str:
        req_id = get_request_id() or getattr(record, "request_id", "-")
        # Format ISO timestamp in UTC
        iso_time = datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        levelname = record.levelname
        name = record.name
        message = record.getMessage()

        base = f"{iso_time} {levelname:<5} request_id={req_id} [{name}] {message}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


class JSONFormatter(logging.Formatter):
    """JSON structured log formatter for containerized/production environments."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "level": record.levelname,
            "logger": record.name,
            "request_id": get_request_id() or getattr(record, "request_id", None),
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def setup_logging(log_level: str = "INFO", log_format: str = "text") -> None:
    """Configure root and application loggers."""
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level.upper())

    if log_format.lower() == "json":
        formatter: logging.Formatter = JSONFormatter()
    else:
        formatter = StructuredTextFormatter()

    console_handler.setFormatter(formatter)
    console_handler.addFilter(SensitiveDataFilter())

    root_logger.addHandler(console_handler)

    # Adjust uvicorn / third party log levels
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False
