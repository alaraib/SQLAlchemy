import logging
import re
import sys
import traceback

import structlog


_configured = False
_safe_device_id = re.compile(r"(?:RTR|SW)-[0-9]{1,6}\Z")
_sensitive_fields = frozenset({"password", "token", "api_key", "authorization", "secret"})


class SafeBoundLogger(structlog.stdlib.BoundLogger):
    def exception(self, event=None, *args, **kwargs):
        kwargs.setdefault("exc_info", True)
        return self._proxy_to_logger("error", event, *args, **kwargs)


def _safe_exception(_, __, event_dict):
    if event_dict.pop("exc_info", None):
        frames = traceback.extract_tb(sys.exc_info()[2])
        event_dict["stack_trace"] = [
            {"file": frame.filename, "line": frame.lineno, "function": frame.name}
            for frame in frames
        ]
    return event_dict


def _event_fields(_, __, event_dict):
    fields = {
        key: event_dict[key]
        for key in (
            "event", "level", "timestamp", "device_id", "request_id",
            "method", "path", "status_code", "duration_ms", "error_type",
            "stack_trace",
        )
        if key in event_dict
    }
    fields.update(
        (key, value)
        for key, value in event_dict.items()
        if isinstance(key, str) and key.lower() in _sensitive_fields
    )
    return fields


def redact_sensitive_fields(_, __, event_dict):
    return {
        key: "***" if isinstance(key, str) and key.lower() in _sensitive_fields else value
        for key, value in event_dict.items()
    }


def configure_logging() -> None:
    global _configured
    if _configured:
        return

    logger = logging.getLogger("netpulse")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
    logger.propagate = False
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _safe_exception,
            _event_fields,
            redact_sensitive_fields,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=SafeBoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    _configured = True


def safe_device_id(device_id: str) -> str:
    return device_id if _safe_device_id.fullmatch(device_id) else "[redacted]"