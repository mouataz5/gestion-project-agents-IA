import uuid
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.main import create_app
from app.models import AuditLog, RunStatus, RunTrigger, RunType
from app.services.runs import RunService
from job_agent_workers.runtime import WorkerRuntime, reset_runtime, set_runtime
from job_agent_workers.tasks.system import ping, run_diagnostic

pytestmark = pytest.mark.feature("system-diagnostics")

DIAGNOSTIC_STAGES = {
    "diagnostic.configuration",
    "diagnostic.database",
    "diagnostic.migrations",
    "diagnostic.redis",
    "diagnostic.storage",
}


def _pending_run(runtime: WorkerRuntime) -> uuid.UUID:
    with runtime.session_factory() as session:
        run = RunService(session).create_run(run_type=RunType.DIAGNOSTIC, trigger=RunTrigger.API)
        session.commit()
        return run.id


def test_ping_returns_pong() -> None:
    result = ping.apply().get()

    assert result["status"] == "pong"
    assert result["hostname"]


@pytest.mark.integration
def test_diagnostic_run_succeeds_and_is_fully_recorded(worker_runtime: WorkerRuntime) -> None:
    run_id = _pending_run(worker_runtime)

    result = run_diagnostic.apply(args=[str(run_id)]).get()

    assert result["status"] == "SUCCEEDED"
    with worker_runtime.session_factory() as session:
        run = RunService(session).get_run(run_id)
        assert run.status is RunStatus.SUCCEEDED
        assert run.task_id  # the Celery task id is recorded
        assert {event.stage for event in run.events} == DIAGNOSTIC_STAGES
        assert run.summary["checks_failed"] == []
        actions = session.scalars(
            select(AuditLog.action).where(AuditLog.entity_id == str(run_id))
        ).all()
        assert set(actions) == {"run.started", "run.finished"}


@pytest.mark.integration
def test_failed_checks_are_recorded_without_crashing(
    make_settings: Callable[..., Settings], postgres_url: str, clean_db: None
) -> None:
    # Real database, unreachable Redis.
    runtime = WorkerRuntime.from_settings(make_settings(database_url=postgres_url))
    set_runtime(runtime)
    try:
        run_id = _pending_run(runtime)
        result = run_diagnostic.apply(args=[str(run_id)]).get()

        assert result["status"] == "PARTIAL_SUCCESS"
        assert result["checks_failed"] == ["redis"]
        with runtime.session_factory() as session:
            run = RunService(session).get_run(run_id)
            assert run.status is RunStatus.PARTIAL_SUCCESS
            assert run.error_count == 1
            assert run.errors[0]["stage"] == "diagnostic.redis"
    finally:
        reset_runtime()


class RecordingErrorTracker:
    def __init__(self) -> None:
        self.captured: list[tuple[BaseException, dict[str, Any]]] = []

    def capture_exception(
        self, exc: BaseException, *, context: Mapping[str, Any] | None = None
    ) -> str:
        self.captured.append((exc, dict(context or {})))
        return "evt"

    def capture_message(
        self, message: str, *, level: str = "error", context: Mapping[str, Any] | None = None
    ) -> str:
        return "evt"


@pytest.mark.integration
def test_task_failures_are_reported_to_the_error_tracker(worker_runtime: WorkerRuntime) -> None:
    tracker = RecordingErrorTracker()
    worker_runtime.error_tracker = tracker

    result = run_diagnostic.apply(args=[str(uuid.uuid4())])

    with pytest.raises(NotFoundError):
        result.get()
    assert len(tracker.captured) == 1
    exception, context = tracker.captured[0]
    assert isinstance(exception, NotFoundError)
    assert context["task_name"] == "system.run_diagnostic"


@pytest.mark.integration
def test_api_to_worker_end_to_end(
    integration_settings: Settings,
    worker_runtime: WorkerRuntime,
    eager_queue: Any,
    api_token: str,
) -> None:
    app = create_app(integration_settings, task_queue=eager_queue)

    with TestClient(app, headers={"Authorization": f"Bearer {api_token}"}) as client:
        created = client.post("/api/v1/runs/diagnostic")
        assert created.status_code == 202
        run = client.get(f"/api/v1/runs/{created.json()['run_id']}").json()

    assert run["status"] == "SUCCEEDED"
    assert run["run_type"] == "DIAGNOSTIC"
    assert {event["stage"] for event in run["events"]} == DIAGNOSTIC_STAGES
    assert run["duration_seconds"] is not None
