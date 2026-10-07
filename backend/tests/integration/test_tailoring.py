"""Tailored CV versions in PostgreSQL: the constraints of migration 0005 (one current tailored
version per application, no file for tailored versions, statuses that follow the kind) and the
cascades from an application to its tailoring history."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.ats.types import CallStatus, DocumentKind, IterationStatus
from app.models import (
    Application,
    AtsAnalysis,
    CvKind,
    CvStatus,
    CvTailoring,
    CvVersion,
    RequirementsExtraction,
)

pytestmark = [pytest.mark.feature("cv-tailoring"), pytest.mark.integration]


@dataclass(frozen=True)
class World:
    candidate_id: uuid.UUID
    master_id: uuid.UUID
    application_ids: tuple[uuid.UUID, ...]
    job_ids: tuple[uuid.UUID, ...]


@pytest.fixture
def world(
    jobs_db: sessionmaker[Session],
    discover: Callable[..., Any],
    import_companies: Callable[[], None],
    confirm_master_cv: Callable[[], uuid.UUID],
) -> World:
    import_companies()
    discover()
    master_id = confirm_master_cv()
    with jobs_db() as session:
        applications = list(session.scalars(select(Application).order_by(Application.created_at)))
        return World(
            candidate_id=applications[0].candidate_id,
            master_id=master_id,
            application_ids=tuple(application.id for application in applications[:2]),
            job_ids=tuple(application.job_id for application in applications[:2]),
        )


def _tailored(
    world: World,
    *,
    version: int,
    status: CvStatus = CvStatus.GENERATED,
    application: int = 0,
    **overrides: Any,
) -> CvVersion:
    values: dict[str, Any] = {
        "candidate_id": world.candidate_id,
        "kind": CvKind.TAILORED,
        "version": version,
        "status": status,
        "extracted_text": "Alex Example\n",
        "structure": {"parser_version": "tailored-cv.v1"},
        "parser_version": "tailored-cv.v1",
        "application_id": world.application_ids[application],
        "job_id": world.job_ids[application],
        "base_version_id": world.master_id,
        "evidence": {"format": 1},
        "ats_score": 88.3,
    }
    values.update(overrides)
    return CvVersion(**values)


def _rejected(jobs_db: sessionmaker[Session], *rows: Any) -> None:
    with jobs_db() as session:
        session.add_all(rows)
        with pytest.raises(IntegrityError):
            session.flush()


def test_a_tailored_version_needs_its_application_and_base(
    world: World, jobs_db: sessionmaker[Session]
) -> None:
    _rejected(jobs_db, _tailored(world, version=1, application_id=None))
    _rejected(jobs_db, _tailored(world, version=1, base_version_id=None))
    with jobs_db() as session:
        session.add(_tailored(world, version=1))
        session.commit()


def test_a_master_version_needs_its_file(world: World, jobs_db: sessionmaker[Session]) -> None:
    master = CvVersion(
        candidate_id=world.candidate_id,
        kind=CvKind.MASTER,
        version=99,
        status=CvStatus.PARSED,
        extracted_text="",
        structure={},
        parser_version="1.0",
    )

    _rejected(jobs_db, master)


def test_statuses_follow_the_kind(world: World, jobs_db: sessionmaker[Session]) -> None:
    _rejected(jobs_db, _tailored(world, version=1, status=CvStatus.CONFIRMED))
    with jobs_db() as session:
        master = session.get(CvVersion, world.master_id)
        assert master is not None
        master.status = CvStatus.GENERATED
        with pytest.raises(IntegrityError):
            session.flush()


def test_an_application_has_one_current_tailored_version(
    world: World, jobs_db: sessionmaker[Session]
) -> None:
    _rejected(jobs_db, _tailored(world, version=1), _tailored(world, version=2))
    with jobs_db() as session:
        session.add_all(
            [
                _tailored(world, version=1, status=CvStatus.SUPERSEDED),
                _tailored(world, version=2),
                _tailored(world, version=3, application=1),  # another application
            ]
        )
        session.commit()


def test_one_successful_extraction_per_posting_version(
    world: World, jobs_db: sessionmaker[Session]
) -> None:
    def extraction(status: CallStatus) -> RequirementsExtraction:
        return RequirementsExtraction(
            job_id=world.job_ids[0],
            status=status,
            input_hash="a" * 64,
            provider="mock",
            requested_model="mock-deterministic-1",
            prompt_name="job_requirements",
            prompt_version=1,
            prompt_sha256="b" * 64,
        )

    _rejected(jobs_db, extraction(CallStatus.SUCCEEDED), extraction(CallStatus.SUCCEEDED))
    with jobs_db() as session:
        session.add_all([extraction(CallStatus.FAILED), extraction(CallStatus.FAILED)])
        session.add(extraction(CallStatus.SUCCEEDED))
        session.commit()


def test_deleting_an_application_deletes_its_tailoring_history(
    world: World, jobs_db: sessionmaker[Session]
) -> None:
    with jobs_db() as session:
        version = _tailored(world, version=1)
        session.add(version)
        session.flush()
        tailoring = CvTailoring(
            application_id=world.application_ids[0],
            candidate_id=world.candidate_id,
            job_id=world.job_ids[0],
            master_version_id=world.master_id,
            cv_version_id=version.id,
            status=CallStatus.SUCCEEDED,
            input_hash="c" * 64,
            scoring_version="ats-score.v1",
            target_score=95,
            max_iterations=3,
            provider="mock",
            requested_model="mock-deterministic-1",
            prompt_name="cv_tailoring",
            prompt_version=1,
            prompt_sha256="d" * 64,
        )
        session.add(tailoring)
        session.flush()
        session.add(
            AtsAnalysis(
                tailoring_id=tailoring.id,
                iteration=0,
                document_kind=DocumentKind.MASTER,
                status=IterationStatus.SCORED,
                scoring_version="ats-score.v1",
                score=82.3,
            )
        )
        application = session.get(Application, world.application_ids[0])
        assert application is not None
        application.cv_version_id = version.id
        session.commit()

    with jobs_db() as session:
        application = session.get(Application, world.application_ids[0])
        session.delete(application)
        session.commit()

    with jobs_db() as session:
        for model in (CvTailoring, AtsAnalysis):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        tailored = select(func.count()).where(CvVersion.kind == CvKind.TAILORED)
        assert session.scalar(tailored) == 0
        assert session.get(CvVersion, world.master_id) is not None  # the master stays
