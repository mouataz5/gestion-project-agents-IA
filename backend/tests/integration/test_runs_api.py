import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.tasks import TaskName
from app.main import create_app
from app.models import RunStatus, RunTrigger, RunType
from app.services.runs import RunService

pytestmark = [pytest.mark.feature("automation-runs"), pytest.mark.integration]


def test_starting_a_diagnostic_run_enqueues_the_worker_task(client: TestClient, recording_queue) -> None:  # type: ignore[no-untyped-def]
    response = client.post("/api/v1/runs/diagnostic")

    assert response.status_code == 202
    body = response.json()
    run_id = body["run_id"]
    assert body["status"] == "PENDING"
    assert body["task_id"] == "task-1"
    assert len(recording_queue.calls) == 1
    call = recording_queue.calls[0]
    assert call.name == TaskName.RUN_DIAGNOSTIC
    assert call.args == (run_id,)

    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["run_type"] == "DIAGNOSTIC"
    assert detail["trigger"] == "API"
    assert detail["status"] == "PENDING"
    assert detail["task_id"] == "task-1"
    assert detail["events"] == []


def test_starting_a_run_is_audited(client: TestClient) -> None:
    response = client.post("/api/v1/runs/diagnostic")
    run_id = response.json()["run_id"]

    entries = client.get("/api/v1/audit-logs").json()["items"]

    requested = [entry for entry in entries if entry["action"] == "run.requested"]
    assert len(requested) == 1
    assert requested[0]["entity_type"] == "automation_run"
    assert requested[0]["entity_id"] == run_id
    assert requested[0]["actor"] == "user"
    assert requested[0]["request_id"] == response.headers["x-request-id"]


def test_queue_outage_marks_the_run_failed(integration_settings: Settings, unavailable_queue, api_token: str) -> None:  # type: ignore[no-untyped-def]
    app = create_app(integration_settings, task_queue=unavailable_queue)
    headers = {"Authorization": f"Bearer {api_token}"}

    with TestClient(app, headers=headers) as client:
        response = client.post("/api/v1/runs/diagnostic")
        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "queue_unavailable"
        run_id = error["details"]["run_id"]

        run = client.get(f"/api/v1/runs/{run_id}").json()

    assert run["status"] == "FAILED"
    assert run["error_count"] == 1
    assert run["errors"][0]["stage"] == "enqueue"
    assert run["finished_at"] is not None


def test_listing_runs_paginates_and_filters(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        service = RunService(session)
        first = service.create_run(run_type=RunType.DIAGNOSTIC, trigger=RunTrigger.MANUAL)
        service.mark_running(first)
        service.finish(first)
        second = service.create_run(run_type=RunType.DIAGNOSTIC, trigger=RunTrigger.API)
        failed = service.create_run(run_type=RunType.DISCOVERY, trigger=RunTrigger.SCHEDULED)
        service.mark_running(failed)
        service.record_error(failed, stage="discovery", error="source unreachable")
        service.finish(failed, status=RunStatus.FAILED)
        session.commit()
        newest_id = str(failed.id)
        second_id = str(second.id)

    page = client.get("/api/v1/runs", params={"limit": 2}).json()
    assert page["total"] == 3
    assert page["limit"] == 2
    assert page["offset"] == 0
    assert [item["id"] for item in page["items"]] == [newest_id, second_id]

    failed_only = client.get("/api/v1/runs", params={"status": "FAILED"}).json()
    assert [item["id"] for item in failed_only["items"]] == [newest_id]

    discovery = client.get("/api/v1/runs", params={"run_type": "DISCOVERY"}).json()
    assert discovery["total"] == 1

    second_page = client.get("/api/v1/runs", params={"limit": 2, "offset": 2}).json()
    assert len(second_page["items"]) == 1


def test_unknown_run_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/runs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_malformed_run_id_returns_422(client: TestClient) -> None:
    assert client.get("/api/v1/runs/not-a-uuid").status_code == 422


def test_runs_require_authentication(app) -> None:  # type: ignore[no-untyped-def]
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/v1/runs").status_code == 401
        assert anonymous.post("/api/v1/runs/diagnostic").status_code == 401
