"""Request context middleware (pure ASGI).

* Assigns a request id (valid incoming ``X-Request-ID`` or a new one) and returns it.
* Binds the id to the logging context for everything that runs during the request.
* Writes the access log (method, path, redacted query, status, duration) — never headers/bodies.
* Is the boundary for unhandled exceptions: they are reported to the error tracker and turned
  into a generic JSON 500 that carries the request id and the error event id.
"""

from __future__ import annotations

import json
import re
import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import error_body
from app.core.logging import get_logger
from app.core.redaction import redact_text

REQUEST_ID_HEADER = "x-request-id"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_QUIET_PATHS = ("/health/live", "/health/ready")

logger = get_logger("app.http")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._request_id(scope)
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            if response_started:
                raise  # nothing sensible can be sent any more
            event_id = self._track(scope, exc)
            status_code = 500
            await self._send_internal_error(send, request_id, event_id)
        finally:
            self._log_access(scope, status_code, started)

    @staticmethod
    def _request_id(scope: Scope) -> str:
        for name, value in scope.get("headers", []):
            if name == REQUEST_ID_HEADER.encode():
                candidate = bytes(value).decode("latin-1")
                if _VALID_REQUEST_ID.fullmatch(candidate):
                    return candidate
                break
        return uuid.uuid4().hex

    @staticmethod
    def _track(scope: Scope, exc: Exception) -> str | None:
        app = scope.get("app")
        tracker = getattr(getattr(app, "state", None), "error_tracker", None)
        if tracker is None:
            logger.exception("http.unhandled_exception")
            return None
        return str(
            tracker.capture_exception(
                exc, context={"method": scope.get("method"), "path": scope.get("path")}
            )
        )

    @staticmethod
    async def _send_internal_error(send: Send, request_id: str, event_id: str | None) -> None:
        body = json.dumps(
            error_body(
                "internal_error",
                "An unexpected error occurred. The error has been logged.",
                request_id=request_id,
                details={"event_id": event_id} if event_id else None,
            )
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-request-id", request_id.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _log_access(scope: Scope, status_code: int, started: float) -> None:
        path = str(scope.get("path", ""))
        query = scope.get("query_string", b"").decode("latin-1")
        fields = {
            "method": scope.get("method"),
            "path": path,
            "status_code": status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        if query:
            fields["query"] = redact_text(query)
        client = scope.get("client")
        if client:
            fields["client"] = client[0]
        quiet = path.endswith(_QUIET_PATHS) and status_code < 400
        if quiet:
            logger.debug("http.request", **fields)
        elif status_code >= 500:
            logger.error("http.request", **fields)
        else:
            logger.info("http.request", **fields)
