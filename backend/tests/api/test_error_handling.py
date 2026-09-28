from collections.abc import Callable, Mapping
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ConflictError
from app.main import create_app

pytestmark = pytest.mark.feature("error-handling")


class RecordingErrorTracker:
    def __init__(self) -> None:
        self.exceptions: list[BaseException] = []

    def capture_exception(
        self, exc: BaseException, *, context: Mapping[str, Any] | None = None
    ) -> str:
        self.exceptions.append(exc)
        return "evt-1"

    def capture_message(
        self, message: str, *, level: str = "error", context: Mapping[str, Any] | None = None
    ) -> str:
        return "evt-2"


@pytest.fixture
def tracker() -> RecordingErrorTracker:
    return RecordingErrorTracker()


@pytest.fixture
def failing_app(make_settings: Callable[..., Settings], tracker: RecordingErrorTracker) -> FastAPI:
    app = create_app(make_settings(), error_tracker=tracker)

    def explode() -> None:
        raise RuntimeError("database password=hunter2 exploded")

    def conflict() -> None:
        raise ConflictError("Run already finished", details={"run_id": "r-1"})

    app.add_api_route("/boom", explode)
    app.add_api_route("/conflict", conflict)
    return app


def test_unknown_routes_use_the_error_envelope(unit_client: TestClient) -> None:
    response = unit_client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["x-request-id"]


def test_method_not_allowed_uses_the_error_envelope(unit_client: TestClient) -> None:
    response = unit_client.post("/api/v1/health/live")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_validation_errors_use_the_error_envelope(unit_client: TestClient) -> None:
    response = unit_client.get("/api/v1/runs", params={"limit": 0})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any(item["loc"][-1] == "limit" for item in error["details"])
    assert all("input" not in item for item in error["details"])  # inputs are never echoed


def test_domain_errors_map_to_their_status_code(failing_app: FastAPI) -> None:
    with TestClient(failing_app) as client:
        response = client.get("/conflict")

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "conflict",
        "message": "Run already finished",
        "details": {"run_id": "r-1"},
        "request_id": response.headers["x-request-id"],
    }


def test_unhandled_exceptions_return_a_generic_500(
    failing_app: FastAPI, tracker: RecordingErrorTracker
) -> None:
    with TestClient(failing_app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "hunter2" not in response.text
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    assert body["error"]["details"] == {"event_id": "evt-1"}
    assert len(tracker.exceptions) == 1
    assert isinstance(tracker.exceptions[0], RuntimeError)
