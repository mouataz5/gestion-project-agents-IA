"""Job tasks: the recorded job discovery and job analysis runs."""

from __future__ import annotations

import uuid
from typing import Any

from celery import Task

from app.core.tasks import TaskName
from app.services.analysis import AnalysisService
from app.services.discovery import DiscoveryService
from job_agent_workers.celery_app import celery_app
from job_agent_workers.runtime import get_runtime


@celery_app.task(name=TaskName.RUN_DISCOVERY.value, bind=True)
def run_discovery(self: Task[[str], dict[str, Any]], run_id: str) -> dict[str, Any]:
    runtime = get_runtime()
    service = DiscoveryService(settings=runtime.settings, session_factory=runtime.session_factory)
    return service.execute(uuid.UUID(run_id), task_id=self.request.id)


@celery_app.task(name=TaskName.RUN_ANALYSIS.value, bind=True)
def run_analysis(self: Task[[str], dict[str, Any]], run_id: str) -> dict[str, Any]:
    runtime = get_runtime()
    service = AnalysisService(settings=runtime.settings, session_factory=runtime.session_factory)
    return service.execute(uuid.UUID(run_id), task_id=self.request.id)
