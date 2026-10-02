"""Jobs: listing with posting-window filters, detail, statistics, tracking and manual imports."""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Annotated, Any, TypeVar
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel

from app.api.deps import CurrentCandidate, DbSession, SettingsDep, require_api_token
from app.applications.lifecycle import ApplicationStatus
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import ConflictError
from app.jobs.types import PostingDateStatus
from app.jobs.window import PostingWindow
from app.models import Job
from app.schemas.common import ErrorResponse
from app.schemas.jobs import (
    EmailImportRequest,
    EmailImportResult,
    JobApplicationRead,
    JobDetail,
    JobImportRequest,
    JobImportResult,
    JobListing,
    JobPage,
    JobRead,
    JobStats,
    LastDiscovery,
    WindowRead,
)
from app.services.applications import ApplicationService
from app.services.audit import Actor, AuditAction, AuditService
from app.services.job_imports import ImportResult, JobImportService
from app.services.job_sources import JobSourceService
from app.services.jobs import JobFilters, JobService, WindowFilter

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_api_token)])

M = TypeVar("M", bound=BaseModel)


def _window(settings: Settings) -> PostingWindow:
    return PostingWindow.lookback(utcnow(), hours=settings.job_lookback_hours)


def _window_read(window: PostingWindow, settings: Settings) -> WindowRead:
    return WindowRead(
        lookback_hours=settings.job_lookback_hours,
        posted_after=window.posted_after,
        posted_before=window.posted_before,
    )


def _service(db: DbSession, settings: Settings) -> JobService:
    hidden = () if settings.mock_mode else JobSourceService(db).mock_keys()
    return JobService(db, hidden_sources=hidden)


def _model(model: type[M], job: Job, **computed: Any) -> M:
    values = {name: getattr(job, name) for name in model.model_fields if hasattr(job, name)}
    return model.model_validate({**values, **computed})


def _read(
    job: Job,
    window: PostingWindow,
    *,
    duplicate_count: int = 0,
    application_status: str | None = None,
) -> JobRead:
    return _model(
        JobRead,
        job,
        window_status=JobService.window_status(job, window),
        duplicate_count=duplicate_count,
        application_status=application_status,
    )


@router.get(
    "", response_model=JobPage, summary="List jobs (default: posted in the lookback window)"
)
def list_jobs(
    db: DbSession,
    settings: SettingsDep,
    window: WindowFilter = "in_window",
    date_status: PostingDateStatus | None = None,
    source: Annotated[str | None, Query(max_length=50)] = None,
    country: Annotated[str | None, Query(pattern=r"^[A-Za-z]{2}$")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    company_id: uuid.UUID | None = None,
    include_duplicates: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobPage:
    service = _service(db, settings)
    posting_window = _window(settings)
    filters = JobFilters(
        window=window,
        date_status=date_status,
        source=source,
        country=country,
        q=q,
        company_id=company_id,
        include_duplicates=include_duplicates,
    )
    jobs, total = service.list_jobs(filters, window=posting_window, limit=limit, offset=offset)
    ids = [job.id for job in jobs]
    duplicates = service.duplicate_counts(ids)
    statuses = service.pipeline_statuses(ids)
    return JobPage(
        items=[
            _read(
                job,
                posting_window,
                duplicate_count=duplicates.get(job.id, 0),
                application_status=statuses.get(job.id),
            )
            for job in jobs
        ],
        total=total,
        limit=limit,
        offset=offset,
        window=_window_read(posting_window, settings),
    )


@router.get("/stats", response_model=JobStats, summary="Discovery statistics for the dashboard")
def job_stats(db: DbSession, settings: SettingsDep) -> JobStats:
    posting_window = _window(settings)
    zone = ZoneInfo(settings.timezone)
    today_start = datetime.combine(
        posting_window.posted_before.astimezone(zone).date(), time(), zone
    )
    stats = _service(db, settings).stats(window=posting_window, today_start=today_start)
    last = stats.pop("last_discovery")
    return JobStats(
        **stats,
        window=_window_read(posting_window, settings),
        last_discovery=LastDiscovery.model_validate(last) if last is not None else None,
    )


@router.get(
    "/{job_id}",
    response_model=JobDetail,
    summary="Job detail with its other listings and pipeline entries",
    responses={404: {"model": ErrorResponse}},
)
def get_job(job_id: uuid.UUID, db: DbSession, settings: SettingsDep) -> JobDetail:
    service = _service(db, settings)
    posting_window = _window(settings)
    job = service.get(job_id)
    primary = service.get(job.duplicate_of_id) if job.duplicate_of_id else None
    duplicates = service.duplicates_of(job)
    applications = ApplicationService(db).for_job(job)
    statuses = service.pipeline_statuses([job.id])
    return _model(
        JobDetail,
        job,
        window_status=JobService.window_status(job, posting_window),
        duplicate_count=len(duplicates),
        application_status=statuses.get(job.id),
        primary=JobListing.model_validate(primary) if primary else None,
        duplicates=[JobListing.model_validate(item) for item in duplicates],
        applications=[JobApplicationRead.model_validate(item) for item in applications],
    )


@router.post(
    "/{job_id}/track",
    response_model=JobApplicationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Queue a job for the candidate (e.g. a job whose posting date is unknown)",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def track_job(
    job_id: uuid.UUID, db: DbSession, settings: SettingsDep, candidate: CurrentCandidate
) -> JobApplicationRead:
    job = _service(db, settings).get(job_id)
    application, created = ApplicationService(db).create_discovered(candidate, job)
    if not created:
        raise ConflictError(
            f"This job is already in the pipeline ({application.status.value})",
            details={"application_id": str(application.id)},
        )
    AuditService(db).record(
        action=AuditAction.JOB_TRACKED,
        actor=Actor.USER,
        entity_type="job",
        entity_id=str(job.id),
        details={"application_id": str(application.id), "status": ApplicationStatus.DISCOVERED},
    )
    db.commit()
    return JobApplicationRead.model_validate(application)


def _import_result(result: ImportResult, window: PostingWindow) -> JobImportResult:
    return JobImportResult(
        job=_read(result.job, window),
        created=result.created,
        duplicate=result.duplicate,
        application_created=result.application_created,
    )


def _audit_import(db: DbSession, result: ImportResult, via: str) -> None:
    AuditService(db).record(
        action=AuditAction.JOB_IMPORTED,
        actor=Actor.USER,
        entity_type="job",
        entity_id=str(result.job.id),
        details={
            "via": via,
            "canonical_url": result.job.canonical_url,
            "created": result.created,
            "duplicate": result.duplicate,
            "application_created": result.application_created,
        },
    )


@router.post(
    "/import",
    response_model=JobImportResult,
    status_code=status.HTTP_201_CREATED,
    summary="Import a job URL (LinkedIn or any public posting); stored, never fetched",
    responses={
        200: {"model": JobImportResult, "description": "The posting was already known"},
        422: {"model": ErrorResponse, "description": "Invalid or unsafe URL"},
    },
)
def import_job(
    payload: JobImportRequest,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    candidate: CurrentCandidate,
) -> JobImportResult:
    service = JobImportService(db, crawler_dir=settings.crawler_dir, now=utcnow())
    result = service.import_url(payload, candidate)
    _audit_import(db, result, "url")
    db.commit()
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return _import_result(result, _window(settings))


@router.post(
    "/import/email",
    response_model=EmailImportResult,
    summary="Import the job links of a job-alert email (used by the n8n workflow)",
    responses={422: {"model": ErrorResponse}},
)
def import_email(
    payload: EmailImportRequest,
    db: DbSession,
    settings: SettingsDep,
    candidate: CurrentCandidate,
) -> EmailImportResult:
    service = JobImportService(db, crawler_dir=settings.crawler_dir, now=utcnow())
    links_found, results = service.import_email(payload.text, candidate)
    for result in results:
        _audit_import(db, result, "email")
    db.commit()
    posting_window = _window(settings)
    return EmailImportResult(
        links_found=links_found,
        results=[_import_result(result, posting_window) for result in results],
    )
