"""Automation runs: history, detail and on-demand diagnostic runs (authenticated)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, TaskQueueDep, require_api_token
from app.core.errors import QueueUnavailableError
from app.core.logging import get_logger
from app.core.tasks import TaskName
from app.models import RunStatus, RunTrigger, RunType
from app.schemas.common import ErrorResponse
from app.schemas.runs import (
    AnalysisRunRequest,
    CvGenerationRunRequest,
    RunCreated,
    RunDetail,
    RunPage,
    RunSummary,
)
from app.services.audit import Actor, AuditAction, AuditService
from app.services.runs import RunService

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_api_token)])
logger = get_logger(__name__)


@router.get("", response_model=RunPage, summary="List automation runs (newest first)")
def list_runs(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    run_status: Annotated[RunStatus | None, Query(alias="status")] = None,
    run_type: RunType | None = None,
) -> RunPage:
    runs, total = RunService(db).list_runs(
        limit=limit, offset=offset, status=run_status, run_type=run_type
    )
    return RunPage(
        items=[RunSummary.model_validate(run) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{run_id}",
    response_model=RunDetail,
    summary="Run detail with its event timeline",
    responses={404: {"model": ErrorResponse}},
)
def get_run(run_id: uuid.UUID, db: DbSession) -> RunDetail:
    return RunDetail.model_validate(RunService(db).get_run(run_id))


def _start_run(
    db: DbSession,
    queue: TaskQueueDep,
    run_type: RunType,
    task: TaskName,
    parameters: dict[str, Any] | None = None,
) -> RunCreated:
    runs = RunService(db)
    audit = AuditService(db)
    run = runs.create_run(run_type=run_type, trigger=RunTrigger.API, parameters=parameters)
    audit.record(
        action=AuditAction.RUN_REQUESTED,
        actor=Actor.USER,
        entity_type="automation_run",
        entity_id=str(run.id),
        details={"run_type": run_type.value},
    )
    db.commit()  # the worker must be able to read the run before the task is published

    try:
        task_id = queue.enqueue(task, args=[str(run.id)])
    except QueueUnavailableError as exc:
        runs.mark_failed(run, stage="enqueue", error="Task queue unavailable")
        audit.record(
            action=AuditAction.RUN_ENQUEUE_FAILED,
            actor=Actor.SYSTEM,
            entity_type="automation_run",
            entity_id=str(run.id),
        )
        db.commit()
        logger.error("run.enqueue_failed", run_id=str(run.id))
        raise QueueUnavailableError(
            "The task queue is unavailable; the run was marked as FAILED.",
            details={"run_id": str(run.id)},
        ) from exc

    run.task_id = task_id
    db.commit()
    return RunCreated(run_id=run.id, status=RunStatus.PENDING, task_id=task_id)


_QUEUE_UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    503: {"model": ErrorResponse, "description": "The task queue is unavailable"}
}


@router.post(
    "/diagnostic",
    response_model=RunCreated,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a system self-test run on a worker",
    responses=_QUEUE_UNAVAILABLE,
)
def start_diagnostic(db: DbSession, queue: TaskQueueDep) -> RunCreated:
    return _start_run(db, queue, RunType.DIAGNOSTIC, TaskName.RUN_DIAGNOSTIC)


@router.post(
    "/discovery",
    response_model=RunCreated,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a job discovery run on a worker",
    responses=_QUEUE_UNAVAILABLE,
)
def start_discovery(db: DbSession, queue: TaskQueueDep) -> RunCreated:
    return _start_run(db, queue, RunType.DISCOVERY, TaskName.RUN_DISCOVERY)


@router.post(
    "/analysis",
    response_model=RunCreated,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a job analysis run (all queued jobs, or the jobs given) on a worker",
    responses=_QUEUE_UNAVAILABLE,
)
def start_analysis(
    db: DbSession, queue: TaskQueueDep, payload: AnalysisRunRequest | None = None
) -> RunCreated:
    request = payload or AnalysisRunRequest()
    parameters: dict[str, Any] = {"force": request.force}
    if request.job_ids is not None:
        parameters["job_ids"] = [str(job_id) for job_id in request.job_ids]
    return _start_run(db, queue, RunType.ANALYSIS, TaskName.RUN_ANALYSIS, parameters)


@router.post(
    "/cv-generation",
    response_model=RunCreated,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a CV generation run (tailored CVs and ATS scores) on a worker",
    responses=_QUEUE_UNAVAILABLE,
)
def start_cv_generation(
    db: DbSession, queue: TaskQueueDep, payload: CvGenerationRunRequest | None = None
) -> RunCreated:
    request = payload or CvGenerationRunRequest()
    parameters: dict[str, Any] = {"force": request.force}
    if request.job_ids is not None:
        parameters["job_ids"] = [str(job_id) for job_id in request.job_ids]
    return _start_run(db, queue, RunType.CV_GENERATION, TaskName.RUN_CV_GENERATION, parameters)
