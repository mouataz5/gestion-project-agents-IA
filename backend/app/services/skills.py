"""Candidate skills: declared skills and CV skills with their evidence (derived data).

Rebuilt whenever the profile's core skills or the active master CV change, so the table
always reflects the confirmed fact base.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.cv.evidence import compute_skill_evidence
from app.cv.models import ParsedCV, SkillEvidence
from app.cv.parser import PARSER_VERSION
from app.models import Candidate, CandidateSkill
from app.schemas.candidate import CandidateProfile
from app.services.cv_versions import find_active_master


class SkillService:
    # ``list`` is defined last: in a class body it would shadow the builtin in annotations.
    def __init__(self, session: Session) -> None:
        self._session = session

    def refresh(self, candidate: Candidate) -> list[SkillEvidence]:
        """Recompute evidence from the active master CV and the profile's core skills."""
        active = find_active_master(self._session, candidate)
        parsed = (
            ParsedCV.model_validate(active.structure)
            if active is not None
            else ParsedCV(parser_version=PARSER_VERSION)
        )
        declared = CandidateProfile.model_validate(candidate.profile).core_skills
        results = compute_skill_evidence(parsed, declared)

        self._session.execute(
            delete(CandidateSkill).where(CandidateSkill.candidate_id == candidate.id)
        )
        self._session.add_all(
            CandidateSkill(
                candidate_id=candidate.id,
                cv_version_id=active.id if active is not None else None,
                position=position,
                name=result.name,
                normalized_name=result.normalized_name,
                category=result.category,
                strength=result.strength,
                sources=[source.value for source in result.sources],
                evidence=[item.model_dump() for item in result.evidence],
            )
            for position, result in enumerate(results)
        )
        self._session.flush()
        return results

    def list(self, candidate: Candidate) -> list[CandidateSkill]:
        return list(
            self._session.scalars(
                select(CandidateSkill)
                .where(CandidateSkill.candidate_id == candidate.id)
                .order_by(CandidateSkill.position)
            )
        )
