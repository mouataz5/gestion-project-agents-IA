import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

pytestmark = [pytest.mark.feature("system-info"), pytest.mark.integration]


def _status(settings: Settings, queue: object, token: str) -> dict[str, object]:
    app = create_app(settings, task_queue=queue)  # type: ignore[arg-type]
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        response = client.get("/api/v1/system/status")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict)
    return body


def _components(body: dict[str, object]) -> dict[str, dict[str, object]]:
    components = body["components"]
    assert isinstance(components, list)
    return {component["name"]: component for component in components}


def test_status_is_ok_with_a_responding_worker(
    integration_settings: Settings, recording_queue, api_token: str  # type: ignore[no-untyped-def]
) -> None:
    body = _status(integration_settings, recording_queue, api_token)

    assert body["status"] == "ok"
    components = _components(body)
    assert set(components) == {"database", "migrations", "redis", "storage", "worker"}
    assert components["worker"]["status"] == "ok"
    assert components["worker"]["critical"] is False
    assert "celery@test-worker" in str(components["worker"]["detail"])


def test_status_is_degraded_without_workers(
    integration_settings: Settings, recording_queue, api_token: str  # type: ignore[no-untyped-def]
) -> None:
    recording_queue.workers = []

    body = _status(integration_settings, recording_queue, api_token)

    assert body["status"] == "degraded"
    assert _components(body)["worker"]["status"] == "degraded"


def test_status_reports_an_unreachable_queue(
    integration_settings: Settings, unavailable_queue, api_token: str  # type: ignore[no-untyped-def]
) -> None:
    body = _status(integration_settings, unavailable_queue, api_token)

    assert body["status"] == "degraded"
    worker = _components(body)["worker"]
    assert worker["status"] == "down"
    assert "QueueUnavailableError" in str(worker["detail"])
