"""System tasks: connectivity ping and the recorded system self-test."""

from __future__ import annotations

import socket
import uuid
from typing import Any

from celery import Task

from app.core.clock import utcnow
from app.core.tasks import TaskName
from app.services.diagnostics import DiagnosticsService
from job_agent_workers.celery_app import celery_app
from job_agent_workers.runtime import get_runtime


@celery_app.task(name=TaskName.PING.value)
def ping() -> dict[str, str]:
    return {"status": "pong", "hostname": socket.gethostname(), "timestamp": utcnow().isoformat()}


@celery_app.task(name=TaskName.RUN_DIAGNOSTIC.value, bind=True)
def run_diagnostic(self: Task[[str], dict[str, Any]], run_id: str) -> dict[str, Any]:
    runtime = get_runtime()
    service = DiagnosticsService(
        settings=runtime.settings,
        session_factory=runtime.session_factory,
        health=runtime.health,
    )
    return service.execute(uuid.UUID(run_id), task_id=self.request.id)
