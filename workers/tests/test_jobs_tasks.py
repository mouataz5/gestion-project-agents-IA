import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import REPO_ROOT, Settings
from app.core.tasks import TaskName
from app.main import create_app
from app.models import AuditLog, Job, RunStatus, RunTrigger, RunType
from app.services.companies import CompanyService
from app.services.runs import RunService
from job_agent_workers.celery_app import celery_app
from job_agent_workers.runtime import WorkerRuntime
from job_agent_workers.tasks.jobs import run_discovery

pytestmark = pytest.mark.feature("job-discovery")


def _pending_discovery(runtime: WorkerRuntime) -> uuid.UUID:
    with runtime.session_factory() as session:
        CompanyService(session).import_from_yaml(REPO_ROOT / "crawler")
        run = RunService(session).create_run(run_type=RunType.DISCOVERY, trigger=RunTrigger.API)
        session.commit()
        return run.id


def test_the_discovery_task_is_registered() -> None:
    assert TaskName.RUN_DISCOVERY.value in celery_app.tasks


@pytest.mark.integration
def test_the_worker_runs_a_recorded_discovery(worker_runtime: WorkerRuntime) -> None:
    run_id = _pending_discovery(worker_runtime)

    result = run_discovery.apply(args=[str(run_id)]).get()

    assert result["status"] == "SUCCEEDED"
    assert result["jobs_discovered"] == 14
    with worker_runtime.session_factory() as session:
        run = RunService(session).get_run(run_id)
        assert run.status is RunStatus.SUCCEEDED
        assert run.task_id
        assert session.scalar(select(func.count()).select_from(Job)) == 16
        actions = session.scalars(
            select(AuditLog.action).where(AuditLog.entity_id == str(run_id))
        ).all()
        assert set(actions) == {"run.started", "run.finished"}


@pytest.mark.integration
def test_api_to_worker_discovery_end_to_end(
    integration_settings: Settings,
    worker_runtime: WorkerRuntime,
    eager_queue: Any,
    api_token: str,
) -> None:
    app = create_app(integration_settings, task_queue=eager_queue)

    with TestClient(app, headers={"Authorization": f"Bearer {api_token}"}) as client:
        client.post("/api/v1/companies/import")
        created = client.post("/api/v1/runs/discovery")
        assert created.status_code == 202, created.text
        run = client.get(f"/api/v1/runs/{created.json()['run_id']}").json()
        jobs = client.get("/api/v1/jobs").json()

    assert run["status"] == "SUCCEEDED"
    assert run["run_type"] == "DISCOVERY"
    assert run["jobs_discovered"] == 14
    assert jobs["total"] == 9
