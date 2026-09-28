"""Domain exceptions. Each maps to an HTTP status and a stable machine-readable code."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected, user-presentable errors."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        self.headers = headers


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthorized"

    def __init__(self, message: str = "Missing or invalid API token", **kwargs: Any) -> None:
        kwargs.setdefault("headers", {"WWW-Authenticate": "Bearer"})
        super().__init__(message, **kwargs)


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"


class QueueUnavailableError(ServiceUnavailableError):
    code = "queue_unavailable"
