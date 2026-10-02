"""Job sources: policy (from ``crawler/sources.yaml``), whether each runs now, last status."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, SettingsDep, require_api_token
from app.crawlers.registry import load_sources_config
from app.schemas.jobs import JobSourceRead
from app.services.job_sources import JobSourceService

router = APIRouter(prefix="/job-sources", tags=["jobs"], dependencies=[Depends(require_api_token)])


@router.get("", response_model=list[JobSourceRead], summary="Job sources and their policy")
def list_job_sources(db: DbSession, settings: SettingsDep) -> list[JobSourceRead]:
    statuses = JobSourceService(db).statuses(
        load_sources_config(settings.crawler_dir), mock_mode=settings.mock_mode
    )
    db.commit()  # the table mirrors the YAML policy
    return [
        JobSourceRead(
            key=item.source.key,
            name=item.source.name,
            kind=item.source.kind,
            policy=item.source.policy,
            enabled=item.source.enabled,
            is_mock=item.source.is_mock,
            priority=item.source.priority,
            rate_limit_per_minute=item.source.rate_limit_per_minute,
            description=item.source.description,
            notes=item.source.notes,
            runnable=item.runnable,
            skip_reason=item.skip_reason,
            last_run_at=item.source.last_run_at,
            last_status=item.source.last_status,
            last_error=item.source.last_error,
            last_counts=item.source.last_counts,
        )
        for item in statuses
    ]
