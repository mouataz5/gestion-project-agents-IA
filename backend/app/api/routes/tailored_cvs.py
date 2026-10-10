"""Tailored CVs (Phase 5): the versions generated for each application, with their evidence
ledger and ATS scores (read-only: tailoring runs on a worker, see POST /runs/cv-generation)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import CurrentCandidate, DbSession, require_api_token
from app.schemas.ats import TailoredCvDetail, TailoredCvSummary
from app.schemas.common import ErrorResponse
from app.services.tailored_cvs import TailoredCvService

router = APIRouter(
    prefix="/candidate/tailored-cvs",
    tags=["tailored-cvs"],
    dependencies=[Depends(require_api_token)],
)

_NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}


@router.get(
    "",
    response_model=list[TailoredCvSummary],
    summary="Tailored CV versions, newest first (optionally for one job)",
)
def list_tailored_cvs(
    candidate: CurrentCandidate, db: DbSession, job_id: uuid.UUID | None = None
) -> list[TailoredCvSummary]:
    service = TailoredCvService(db)
    return service.summaries(candidate, service.versions(candidate, job_id=job_id))


@router.get(
    "/{version_id}",
    response_model=TailoredCvDetail,
    summary="A tailored CV with the master CV facts behind every text and its ATS scores",
    responses=_NOT_FOUND,
)
def get_tailored_cv(
    version_id: uuid.UUID, candidate: CurrentCandidate, db: DbSession
) -> TailoredCvDetail:
    service = TailoredCvService(db)
    return service.detail(candidate, service.get(candidate, version_id))
