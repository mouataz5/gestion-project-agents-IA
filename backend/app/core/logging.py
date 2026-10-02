"""Structured logging with structlog.

* JSON (production) or human-readable console output, always on stdout.
* Standard-library loggers (uvicorn, celery, sqlalchemy, alembic) share the same pipeline.
* Context variables (``request_id``, ``run_id``, ``task_id``) are merged into every event.
* Every event — including exception tracebacks — passes through secret redaction last,
  right before rendering.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, TextIO

import structlog
from structlog.types import EventDict, Processor, WrappedLogger

from app.core.config import Settings
from app.core.redaction import redact, redact_text

# Kept at WARNING whatever LOG_LEVEL: connection chatter, and HTTP clients that log whole request
# bodies at DEBUG (the Anthropic SDK logs every prompt: job postings and candidate facts).
_QUIET_LOGGERS = (
    "sqlalchemy.engine",
    "sqlalchemy.pool",
    "httpx",
    "httpx2",
    "httpcore",
    "anthropic",
    "kombu",
    "amqp",
)


class _CurrentStdoutHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """StreamHandler that always writes to the *current* ``sys.stdout``.

    Resolving the stream at emit time keeps logging correct when stdout is swapped
    (test capture, process managers) after logging was configured.
    """

    job_agent_handler = True

    def __init__(self) -> None:
        super().__init__(stream=sys.stdout)

    @property
    def stream(self) -> TextIO:
        return sys.stdout

    @stream.setter
    def stream(self, value: TextIO) -> None:  # the stream is resolved dynamically
        return None


def _add_static_fields(component: str) -> Processor:
    def processor(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("component", component)
        return event_dict

    return processor


def _redact_event(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    redacted: dict[str, Any] = redact(dict(event_dict))
    event = redacted.get("event")
    if isinstance(event, str):
        redacted["event"] = redact_text(event)
    return redacted


def configure_logging(settings: Settings, *, component: str = "api") -> None:
    """Configure structlog and the standard library (idempotent)."""
    level = logging.getLevelNamesMapping()[settings.log_level]
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    pre_chain: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        _add_static_fields(component),
        structlog.processors.StackInfoRenderer(),
    ]
    renderer: Processor
    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *pre_chain,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=pre_chain,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,  # tracebacks become text ...
            _redact_event,  # ... so they are redacted too
            renderer,
        ],
    )

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "job_agent_handler", False):
            root.removeHandler(handler)
    handler = _CurrentStdoutHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(level)

    # Route server/framework loggers through the root handler.
    for name in ("uvicorn", "uvicorn.error", "celery", "alembic"):
        framework_logger = logging.getLogger(name)
        framework_logger.handlers.clear()
        framework_logger.propagate = True
    # The request middleware writes the access log (with redaction and request ids).
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    # Alembic's "Context impl ..." lines are useful when migrating, noise in health checks.
    logging.getLogger("alembic").setLevel(
        logging.INFO if component == "migrations" else logging.WARNING
    )
    if settings.database_echo:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
