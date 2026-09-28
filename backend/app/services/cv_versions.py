"""Shared CV version queries (used by the master CV and skill services)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Candidate, CvKind, CvStatus, CvVersion


def find_active_master(session: Session, candidate: Candidate) -> CvVersion | None:
    """The confirmed master CV: the only source of facts for later phases."""
    return session.scalar(
        select(CvVersion).where(
            CvVersion.candidate_id == candidate.id,
            CvVersion.kind == CvKind.MASTER,
            CvVersion.status == CvStatus.CONFIRMED,
        )
    )
