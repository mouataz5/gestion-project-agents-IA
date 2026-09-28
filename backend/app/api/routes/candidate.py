"""Candidate profile (authenticated): read, edit, YAML import/export and skill evidence."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import CurrentCandidate, DbSession, SettingsDep, require_api_token
from app.api.downloads import content_disposition
from app.core.clock import utcnow
from app.models import Candidate
from app.schemas.candidate import CandidateRead, CandidateSkillRead, CandidateUpdate
from app.schemas.common import ErrorResponse
from app.schemas.cv import CvVersionSummary
from app.services.audit import Actor, AuditAction, AuditService
from app.services.candidate_profile import (
    CandidateService,
    export_filename,
    needs_user_input,
    profile_to_yaml,
)
from app.services.cv_versions import find_active_master
from app.services.skills import SkillService

router = APIRouter(
    prefix="/candidate", tags=["candidate"], dependencies=[Depends(require_api_token)]
)


def _read(db: DbSession, candidate: Candidate) -> CandidateRead:
    profile = CandidateService.profile_of(candidate)
    active = find_active_master(db, candidate)
    return CandidateRead(
        id=candidate.id,
        slug=candidate.slug,
        profile=profile,
        profile_version=candidate.profile_version,
        needs_user_input=needs_user_input(profile),
        active_master_cv=CvVersionSummary.model_validate(active) if active else None,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


@router.get(
    "",
    response_model=CandidateRead,
    summary="The candidate profile (imported from candidate/profile.yaml on first use)",
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def get_candidate(candidate: CurrentCandidate, db: DbSession) -> CandidateRead:
    return _read(db, candidate)


@router.put(
    "",
    response_model=CandidateRead,
    summary="Replace the profile (optimistic concurrency on profile_version)",
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def update_candidate(
    payload: CandidateUpdate, candidate: CurrentCandidate, db: DbSession, settings: SettingsDep
) -> CandidateRead:
    service = CandidateService(db, candidate_dir=settings.candidate_dir)
    changed = service.update_profile(
        candidate, payload.profile, expected_version=payload.profile_version
    )
    AuditService(db).record(
        action=AuditAction.CANDIDATE_PROFILE_UPDATED,
        actor=Actor.USER,
        entity_type="candidate",
        entity_id=str(candidate.id),
        details={"profile_version": candidate.profile_version, "changed_sections": changed},
    )
    db.commit()
    return _read(db, candidate)


@router.post(
    "/import",
    response_model=CandidateRead,
    summary="Reload the profile from candidate/profile.yaml (+ profile.local.yaml)",
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def import_candidate(
    candidate: CurrentCandidate, db: DbSession, settings: SettingsDep
) -> CandidateRead:
    service = CandidateService(db, candidate_dir=settings.candidate_dir)
    changed = service.import_from_files(candidate)
    AuditService(db).record(
        action=AuditAction.CANDIDATE_IMPORTED,
        actor=Actor.USER,
        entity_type="candidate",
        entity_id=str(candidate.id),
        details={
            "source": "yaml",
            "profile_version": candidate.profile_version,
            "changed_sections": changed,
        },
    )
    db.commit()
    return _read(db, candidate)


@router.get(
    "/export",
    summary="Download the profile as YAML (private contact details only on request)",
    response_class=Response,
    responses={200: {"content": {"application/yaml": {}}}},
)
def export_candidate(
    candidate: CurrentCandidate,
    db: DbSession,
    include_private: Annotated[bool, Query(description="Include contact details")] = False,
) -> Response:
    content = profile_to_yaml(
        CandidateService.profile_of(candidate), include_private=include_private
    )
    AuditService(db).record(
        action=AuditAction.CANDIDATE_EXPORTED,
        actor=Actor.USER,
        entity_type="candidate",
        entity_id=str(candidate.id),
        details={"include_private": include_private},
    )
    db.commit()
    return Response(
        content=content,
        media_type="application/yaml; charset=utf-8",
        headers={
            "Content-Disposition": content_disposition(
                export_filename(candidate, today=utcnow().date())
            ),
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/skills",
    response_model=list[CandidateSkillRead],
    summary="Declared and CV skills with their evidence in the confirmed master CV",
)
def list_skills(candidate: CurrentCandidate, db: DbSession) -> list[CandidateSkillRead]:
    return [CandidateSkillRead.model_validate(skill) for skill in SkillService(db).list(candidate)]
