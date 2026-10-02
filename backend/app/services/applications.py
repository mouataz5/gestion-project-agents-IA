"""Applications (spec §18): the candidate's pipeline entries and their status transitions."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications.lifecycle import ApplicationStatus, ensure_transition
from app.core.errors import ConflictError, NotFoundError
from app.models import Application, Candidate, Job
from app.services.audit import Actor, AuditAction, AuditService


class DuplicateListingError(ConflictError):
    code = "duplicate_listing"


class ApplicationService:
    """Methods flush but never commit: the caller owns the transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, application_id: uuid.UUID) -> Application:
        application = self._session.get(Application, application_id)
        if application is None:
            raise NotFoundError(f"Application {application_id} not found")
        return application

    def find(self, candidate: Candidate, job: Job) -> Application | None:
        return self._session.scalar(
            select(Application).where(
                Application.candidate_id == candidate.id, Application.job_id == job.id
            )
        )

    def for_job(self, job: Job) -> list[Application]:
        return list(
            self._session.scalars(
                select(Application)
                .where(Application.job_id == job.id)
                .order_by(Application.created_at)
            )
        )

    def create_discovered(
        self, candidate: Candidate, job: Job, *, run_id: uuid.UUID | None = None
    ) -> tuple[Application, bool]:
        """Queue ``job`` for the candidate (idempotent). Duplicate listings are never queued:
        their primary record is."""
        if job.duplicate_of_id is not None:
            raise DuplicateListingError(
                "This listing duplicates another job; track the primary record instead",
                details={"primary_job_id": str(job.duplicate_of_id)},
            )
        existing = self.find(candidate, job)
        if existing is not None:
            return existing, False
        application = Application(
            candidate_id=candidate.id,
            job_id=job.id,
            company=job.company,
            role=job.title,
            country=job.country,
            application_url=job.application_url,
            source=job.source,
            status=ApplicationStatus.DISCOVERED,
            run_id=run_id,
        )
        self._session.add(application)
        self._session.flush()
        return application, True

    def transition(
        self,
        application: Application,
        target: ApplicationStatus,
        *,
        reason: str | None = None,
        actor: str = Actor.SYSTEM,
    ) -> None:
        """Move to ``target`` if the lifecycle allows it (409 otherwise); audited."""
        source = application.status
        ensure_transition(source, target)
        application.status = target
        application.status_reason = reason
        details: dict[str, Any] = {"from": source.value, "to": target.value}
        if reason:
            details["reason"] = reason
        AuditService(self._session).record(
            action=AuditAction.APPLICATION_STATUS_CHANGED,
            actor=actor,
            entity_type="application",
            entity_id=str(application.id),
            details=details,
        )
        self._session.flush()
