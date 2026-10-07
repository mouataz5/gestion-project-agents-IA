"""Master CV lifecycle: upload -> parsed draft -> user edits -> confirm -> (revise).

* Upload validates the file, parses it deterministically and stores it under a generated,
  content-addressed key (identical files share storage). The result is a PARSED draft.
* Drafts are edited by the user. Confirming a draft makes it the active master CV (the
  previous one becomes SUPERSEDED) and rebuilds the fact base (experiences, education,
  projects, skill evidence) in the same transaction.
* Confirmed versions are immutable; "revise" copies one into a new editable draft.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.storage import StorageObjectNotFoundError, StorageProvider
from app.cv.evidence import technologies_in
from app.cv.files import DEFAULT_MAX_BYTES, detect_cv_file, sanitize_filename
from app.cv.models import DateRange, ParsedCV, YearMonth
from app.cv.parser import confirmation_errors, parse_cv, structure_warnings
from app.models import (
    Candidate,
    CvKind,
    CvStatus,
    CvVersion,
    DatePrecision,
    Education,
    Experience,
    Project,
)
from app.services.cv_versions import find_active_master
from app.services.skills import SkillService


class CvStructureError(AppError):
    status_code = 422
    code = "invalid_cv_structure"


class MasterCvService:
    def __init__(
        self, session: Session, storage: StorageProvider, *, max_bytes: int = DEFAULT_MAX_BYTES
    ) -> None:
        self._session = session
        self._storage = storage
        self._max_bytes = max_bytes

    # -- queries ------------------------------------------------------------------------------

    def list_versions(self, candidate: Candidate) -> list[CvVersion]:
        return list(
            self._session.scalars(
                select(CvVersion)
                .where(CvVersion.candidate_id == candidate.id, CvVersion.kind == CvKind.MASTER)
                .order_by(CvVersion.version.desc())
            )
        )

    def get(self, candidate: Candidate, version_id: uuid.UUID) -> CvVersion:
        version = self._session.scalar(
            select(CvVersion).where(
                CvVersion.id == version_id,
                CvVersion.candidate_id == candidate.id,
                CvVersion.kind == CvKind.MASTER,
            )
        )
        if version is None:
            raise NotFoundError("CV version not found")
        return version

    def active(self, candidate: Candidate) -> CvVersion | None:
        return find_active_master(self._session, candidate)

    def read_file(self, version: CvVersion) -> bytes:
        if version.storage_key is None:  # a tailored version: generated, never uploaded
            raise NotFoundError("This CV version has no uploaded file")
        try:
            return self._storage.get_bytes(version.storage_key)
        except StorageObjectNotFoundError as exc:
            raise NotFoundError("The original file is no longer in storage") from exc

    def experiences(self, candidate: Candidate) -> list[Experience]:
        return list(
            self._session.scalars(
                select(Experience)
                .where(Experience.candidate_id == candidate.id)
                .order_by(Experience.position)
            )
        )

    # -- commands -----------------------------------------------------------------------------

    def upload(self, candidate: Candidate, *, filename: str, data: bytes) -> CvVersion:
        kind = detect_cv_file(filename, data, max_bytes=self._max_bytes)
        parsed, text = parse_cv(data, kind)
        digest = hashlib.sha256(data).hexdigest()
        # Generated, content-addressed key: never derived from the user's filename.
        key = f"candidates/{candidate.id}/master_cv/{digest}{kind.extension}"
        if not self._storage.exists(key):
            self._storage.put_bytes(key, data)

        self._lock(candidate)
        version = CvVersion(
            candidate_id=candidate.id,
            kind=CvKind.MASTER,
            version=self._next_version(candidate),
            status=CvStatus.PARSED,
            original_filename=sanitize_filename(filename),
            content_type=kind.content_type,
            size_bytes=len(data),
            sha256=digest,
            storage_key=key,
            extracted_text=text,
            structure=parsed.model_dump(mode="json"),
            parse_warnings=list(parsed.warnings),
            parser_version=parsed.parser_version,
        )
        self._session.add(version)
        self._session.flush()
        return version

    def update_structure(
        self, candidate: Candidate, version_id: uuid.UUID, structure: ParsedCV
    ) -> CvVersion:
        version = self.get(candidate, version_id)
        self._require_draft(version)
        cleaned = structure.model_copy(
            update={
                "parser_version": version.parser_version,
                "warnings": structure_warnings(structure),
            }
        )
        version.structure = cleaned.model_dump(mode="json")
        self._session.flush()
        return version

    def confirm(self, candidate: Candidate, version_id: uuid.UUID) -> CvVersion:
        version = self.get(candidate, version_id)
        self._require_draft(version)
        structure = ParsedCV.model_validate(version.structure)
        errors = confirmation_errors(structure)
        if errors:
            raise CvStructureError(
                "Complete the highlighted fields before confirming the CV", details=errors
            )

        self._lock(candidate)
        previous = self.active(candidate)
        if previous is not None:
            previous.status = CvStatus.SUPERSEDED
            self._session.flush()  # free the "one active master" slot first
        version.status = CvStatus.CONFIRMED
        version.confirmed_at = utcnow()
        self._session.flush()

        skills = SkillService(self._session).refresh(candidate)
        self._rebuild_facts(candidate, version, structure, [skill.name for skill in skills])
        return version

    def revise(self, candidate: Candidate, version_id: uuid.UUID) -> CvVersion:
        source = self.get(candidate, version_id)
        if source.status is CvStatus.PARSED:
            raise ConflictError("Drafts are edited directly; only confirmed versions are revised")
        self._lock(candidate)
        revision = CvVersion(
            candidate_id=candidate.id,
            kind=CvKind.MASTER,
            version=self._next_version(candidate),
            status=CvStatus.PARSED,
            original_filename=source.original_filename,
            content_type=source.content_type,
            size_bytes=source.size_bytes,
            sha256=source.sha256,
            storage_key=source.storage_key,
            extracted_text=source.extracted_text,
            structure=dict(source.structure),
            parse_warnings=list(source.parse_warnings),
            parser_version=source.parser_version,
            revised_from_id=source.id,
        )
        self._session.add(revision)
        self._session.flush()
        return revision

    # -- internals ----------------------------------------------------------------------------

    def _lock(self, candidate: Candidate) -> None:
        # Serialises version numbering and confirmation for one candidate.
        self._session.refresh(candidate, with_for_update=True)

    def _next_version(self, candidate: Candidate) -> int:
        current = self._session.scalar(
            select(func.max(CvVersion.version)).where(
                CvVersion.candidate_id == candidate.id, CvVersion.kind == CvKind.MASTER
            )
        )
        return (current or 0) + 1

    @staticmethod
    def _require_draft(version: CvVersion) -> None:
        if version.status is not CvStatus.PARSED:
            raise ConflictError(
                f"Version {version.version} is {version.status.value.lower()} and read-only; "
                "use revise to create an editable copy",
                details={"status": version.status.value},
            )

    def _rebuild_facts(
        self,
        candidate: Candidate,
        version: CvVersion,
        structure: ParsedCV,
        vocabulary: list[str],
    ) -> None:
        for model in (Experience, Education, Project):
            self._session.execute(delete(model).where(model.candidate_id == candidate.id))

        def technologies(*texts: str | None) -> list[str]:
            return technologies_in("\n".join(t for t in texts if t), vocabulary)

        common: dict[str, Any] = {"candidate_id": candidate.id, "cv_version_id": version.id}
        for position, experience in enumerate(structure.experiences):
            self._session.add(
                Experience(
                    **common,
                    **_date_columns(experience.dates),
                    position=position,
                    title=experience.title,
                    employer=experience.employer,
                    location=experience.location,
                    bullets=experience.bullets,
                    details=experience.details,
                    technologies=technologies(
                        experience.title, *experience.details, *experience.bullets
                    ),
                )
            )
        for position, education in enumerate(structure.education):
            self._session.add(
                Education(
                    **common,
                    **_date_columns(education.dates),
                    position=position,
                    degree=education.degree,
                    institution=education.institution,
                    location=education.location,
                    bullets=education.bullets,
                    details=education.details,
                    technologies=technologies(
                        education.degree, *education.details, *education.bullets
                    ),
                )
            )
        for position, project in enumerate(structure.projects):
            self._session.add(
                Project(
                    **common,
                    **_date_columns(project.dates),
                    position=position,
                    name=project.name,
                    bullets=project.bullets,
                    details=project.details,
                    technologies=technologies(project.name, *project.details, *project.bullets),
                )
            )
        self._session.flush()


def _as_date(value: YearMonth | None) -> tuple[date | None, DatePrecision | None]:
    if value is None:
        return None, None
    precision = DatePrecision.MONTH if value.month else DatePrecision.YEAR
    return date(value.year, value.month or 1, 1), precision


def _date_columns(dates: DateRange | None) -> dict[str, Any]:
    if dates is None:
        return {"date_text": None, "is_current": False}
    start, start_precision = _as_date(dates.start)
    end, end_precision = _as_date(dates.end)
    return {
        "date_text": dates.text,
        "start_date": start,
        "start_precision": start_precision,
        "end_date": end,
        "end_precision": end_precision,
        "is_current": dates.is_current,
    }
