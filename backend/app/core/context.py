"""Accessors for per-request / per-task logging context (stored in structlog contextvars)."""

from __future__ import annotations

import structlog


def get_request_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("request_id")
    return str(value) if value is not None else None
