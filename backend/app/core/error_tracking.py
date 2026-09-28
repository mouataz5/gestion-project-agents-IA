"""Error tracking abstraction.

`LoggingErrorTracker` writes a structured, redacted `error.captured` event with an event id that
is also returned to API clients, so a user-visible error can be matched to its log entry. A
Sentry-compatible tracker (e.g. self-hosted GlitchTip) can implement the same protocol later.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Protocol

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.redaction import redact, redact_text


class ErrorTracker(Protocol):
    def capture_exception(
        self, exc: BaseException, *, context: Mapping[str, Any] | None = None
    ) -> str:
        """Record an exception and return its event id."""
        ...

    def capture_message(
        self, message: str, *, level: str = "error", context: Mapping[str, Any] | None = None
    ) -> str:
        """Record a message and return its event id."""
        ...


class LoggingErrorTracker:
    def __init__(self, logger_name: str = "app.errors") -> None:
        self._logger = get_logger(logger_name)

    def capture_exception(
        self, exc: BaseException, *, context: Mapping[str, Any] | None = None
    ) -> str:
        event_id = uuid.uuid4().hex
        self._logger.error(
            "error.captured",
            event_id=event_id,
            error_type=type(exc).__name__,
            error_message=redact_text(str(exc)),
            context=redact(dict(context or {})),
            exc_info=exc,
        )
        return event_id

    def capture_message(
        self, message: str, *, level: str = "error", context: Mapping[str, Any] | None = None
    ) -> str:
        event_id = uuid.uuid4().hex
        self._logger.log(
            _LEVELS.get(level, 40),
            "error.message",
            event_id=event_id,
            message=redact_text(message),
            context=redact(dict(context or {})),
        )
        return event_id


_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}


def create_error_tracker(settings: Settings) -> ErrorTracker:
    """Return the tracker selected by ``ERROR_TRACKER`` (only ``logging`` exists today)."""
    if settings.error_tracker == "logging":
        return LoggingErrorTracker()
    raise ValueError(f"Unsupported error tracker: {settings.error_tracker}")  # pragma: no cover
