"""Exception handlers producing one consistent error envelope:

{"error": {"code": "...", "message": "...", "details": ..., "request_id": "..."}}
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError

_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    429: "rate_limited",
}


def error_body(
    code: str, message: str, *, request_id: str | None, details: Any = None
) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "details": details, "request_id": request_id}
    }


def request_id_of(request: Request) -> str | None:
    value = request.scope.get("state", {}).get("request_id")
    return str(value) if value is not None else None


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):  # pragma: no cover - registered for AppError only
        raise exc
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(
            exc.code, exc.message, request_id=request_id_of(request), details=exc.details
        ),
        headers=exc.headers,
    )


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover
        raise exc
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ")
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, message, request_id=request_id_of(request)),
        headers=getattr(exc, "headers", None),
    )


async def _validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # pragma: no cover
        raise exc
    # Never echo submitted input back (it may contain secrets); keep location, message and type.
    details = [
        {"loc": list(error.get("loc", ())), "msg": error.get("msg"), "type": error.get("type")}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=error_body(
            "validation_error",
            "Request validation failed",
            request_id=request_id_of(request),
            details=details,
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
