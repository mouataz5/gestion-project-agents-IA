"""Master CV (authenticated): upload, versions, draft review, confirmation and revisions."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from app.api.deps import (
    CurrentCandidate,
    DbSession,
    SettingsDep,
    StorageDep,
    require_api_token,
)
from app.api.downloads import content_disposition
from app.cv.models import ParsedCV
from app.cv.parser import summarize
from app.models import CvVersion
from app.schemas.common import ErrorResponse
from app.schemas.cv import CvVersionDetail, CvVersionSummary
from app.services.audit import Actor, AuditAction, AuditService
from app.services.master_cv import MasterCvService

router = APIRouter(
    prefix="/candidate/master-cv",
    tags=["master-cv"],
    dependencies=[Depends(require_api_token)],
)

_NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}
_READ_ONLY: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


def _service(db: DbSession, storage: StorageDep, settings: SettingsDep) -> MasterCvService:
    return MasterCvService(db, storage, max_bytes=settings.max_upload_bytes)


ServiceDep = Annotated[MasterCvService, Depends(_service)]


def _audit(db: DbSession, action: AuditAction, version: CvVersion, **details: object) -> None:
    AuditService(db).record(
        action=action,
        actor=Actor.USER,
        entity_type="cv_version",
        entity_id=str(version.id),
        details={"version": version.version, "status": version.status.value, **details},
    )


@router.post(
    "",
    response_model=CvVersionDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a master CV (.docx or .pdf); it is parsed into a draft to review",
    responses={
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def upload_master_cv(
    file: Annotated[UploadFile, File(description="The CV file (.docx or .pdf)")],
    candidate: CurrentCandidate,
    service: ServiceDep,
    settings: SettingsDep,
    db: DbSession,
) -> CvVersionDetail:
    # Read one byte more than allowed so oversized files are detected without reading them all.
    data = file.file.read(settings.max_upload_bytes + 1)
    version = service.upload(candidate, filename=file.filename or "", data=data)
    _audit(
        db,
        AuditAction.CV_UPLOADED,
        version,
        content_type=version.content_type,
        size_bytes=version.size_bytes,
        **summarize(ParsedCV.model_validate(version.structure)),
    )
    db.commit()
    return CvVersionDetail.model_validate(version)


@router.get("", response_model=list[CvVersionSummary], summary="Master CV versions, newest first")
def list_master_cvs(candidate: CurrentCandidate, service: ServiceDep) -> list[CvVersionSummary]:
    return [CvVersionSummary.model_validate(v) for v in service.list_versions(candidate)]


@router.get(
    "/{version_id}",
    response_model=CvVersionDetail,
    summary="A master CV version with its parsed structure",
    responses=_NOT_FOUND,
)
def get_master_cv(
    version_id: uuid.UUID, candidate: CurrentCandidate, service: ServiceDep
) -> CvVersionDetail:
    return CvVersionDetail.model_validate(service.get(candidate, version_id))


@router.get(
    "/{version_id}/file",
    summary="Download the original uploaded file",
    response_class=Response,
    responses={**_NOT_FOUND, 200: {"content": {"application/octet-stream": {}}}},
)
def download_master_cv(
    version_id: uuid.UUID, candidate: CurrentCandidate, service: ServiceDep
) -> Response:
    version = service.get(candidate, version_id)
    return Response(
        content=service.read_file(version),
        media_type=version.content_type,
        headers={
            "Content-Disposition": content_disposition(version.original_filename or "cv"),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put(
    "/{version_id}/structure",
    response_model=CvVersionDetail,
    summary="Save corrections to a draft (confirmed versions are read-only)",
    responses=_READ_ONLY,
)
def update_master_cv_structure(
    version_id: uuid.UUID,
    structure: ParsedCV,
    candidate: CurrentCandidate,
    service: ServiceDep,
    db: DbSession,
) -> CvVersionDetail:
    version = service.update_structure(candidate, version_id, structure)
    _audit(db, AuditAction.CV_STRUCTURE_UPDATED, version, **summarize(structure))
    db.commit()
    return CvVersionDetail.model_validate(version)


@router.post(
    "/{version_id}/confirm",
    response_model=CvVersionDetail,
    summary="Confirm a draft: it becomes the active master CV and rebuilds the fact base",
    responses={**_READ_ONLY, 422: {"model": ErrorResponse}},
)
def confirm_master_cv(
    version_id: uuid.UUID, candidate: CurrentCandidate, service: ServiceDep, db: DbSession
) -> CvVersionDetail:
    version = service.confirm(candidate, version_id)
    _audit(
        db,
        AuditAction.CV_CONFIRMED,
        version,
        **summarize(ParsedCV.model_validate(version.structure)),
    )
    db.commit()
    return CvVersionDetail.model_validate(version)


@router.post(
    "/{version_id}/revise",
    response_model=CvVersionDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Copy a confirmed version into a new editable draft",
    responses=_READ_ONLY,
)
def revise_master_cv(
    version_id: uuid.UUID, candidate: CurrentCandidate, service: ServiceDep, db: DbSession
) -> CvVersionDetail:
    revision = service.revise(candidate, version_id)
    source = service.get(candidate, version_id)
    _audit(db, AuditAction.CV_REVISED, revision, revised_from_version=source.version)
    db.commit()
    return CvVersionDetail.model_validate(revision)
