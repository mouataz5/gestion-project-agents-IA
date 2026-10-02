"""Deduplication matrix: same posting, cross-source duplicates and source priority."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import REPO_ROOT
from app.crawlers.base import NormalizedJob, build_job
from app.crawlers.registry import load_sources_config
from app.models import Application, Job
from app.services.applications import ApplicationService
from app.services.candidate_profile import CandidateService
from app.services.job_sources import JobSourceService
from app.services.jobs import JobService, UpsertOutcome

pytestmark = [pytest.mark.feature("job-deduplication"), pytest.mark.integration]

NOW = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
ATS, FEED, MANUAL = 100, 10, 5


@pytest.fixture
def session(jobs_db: sessionmaker[Session]) -> Iterator[Session]:
    with jobs_db() as session:
        JobSourceService(session).sync(load_sources_config(REPO_ROOT / "crawler"))
        session.commit()
        yield session


def make_job(**overrides: Any) -> NormalizedJob:
    values: dict[str, Any] = {
        "source": "mock_ats",
        "source_job_id": "a-1",
        "company": "Nova AI",
        "title": "AI Engineer",
        "location": "Paris, France",
        "description": "Build RAG systems with LangGraph.",
        "application_url": "https://nova-ai.example/careers/jobs/1",
        "posted_at": NOW - timedelta(hours=2),
        "fetched_at": NOW,
    }
    values.update(overrides)
    return build_job(**values)


def _count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Job)) or 0


def test_new_jobs_are_stored_as_primary_records(session: Session) -> None:
    result = JobService(session).upsert(make_job(), priority=ATS, now=NOW)

    assert result.outcome is UpsertOutcome.NEW
    assert result.job.id == result.primary.id
    assert result.job.duplicate_of_id is None
    assert result.job.discovered_at == NOW


def test_the_same_source_id_updates_the_existing_posting(session: Session) -> None:
    service = JobService(session)
    first = service.upsert(make_job(), priority=ATS, now=NOW)

    again = service.upsert(
        make_job(title="Senior AI Engineer"), priority=ATS, now=NOW + timedelta(hours=1)
    )

    assert again.outcome is UpsertOutcome.UPDATED
    assert again.job.id == first.job.id
    assert again.job.title == "Senior AI Engineer"
    assert again.job.last_seen_at == NOW + timedelta(hours=1)
    assert again.job.discovered_at == NOW
    assert _count(session) == 1


def test_tracking_parameters_do_not_hide_a_duplicate(session: Session) -> None:
    service = JobService(session)
    primary = service.upsert(make_job(), priority=ATS, now=NOW).job

    result = service.upsert(
        make_job(
            source="mock_feed",
            source_job_id="feed-9",
            description="Short aggregator summary.",
            application_url="https://nova-ai.example/careers/jobs/1?utm_source=feed&utm_medium=rss",
        ),
        priority=FEED,
        now=NOW,
    )

    assert result.outcome is UpsertOutcome.DUPLICATE
    assert result.job.duplicate_of_id == primary.id
    assert result.primary.id == primary.id
    assert _count(session) == 2


def test_identical_content_from_another_source_is_linked(session: Session) -> None:
    service = JobService(session)
    primary = service.upsert(make_job(), priority=ATS, now=NOW).job

    result = service.upsert(
        make_job(
            source="mock_feed",
            source_job_id="feed-10",
            title="  ai ENGINEER ",
            application_url="https://aggregator.example/jobs/10",
        ),
        priority=FEED,
        now=NOW,
    )

    assert result.outcome is UpsertOutcome.DUPLICATE
    assert result.job.duplicate_of_id == primary.id


def test_duplicates_always_point_to_the_primary_record(session: Session) -> None:
    service = JobService(session)
    primary = service.upsert(make_job(), priority=ATS, now=NOW).job
    aggregator_url = "https://aggregator.example/jobs/10"
    service.upsert(
        make_job(source="mock_feed", source_job_id="feed-10", application_url=aggregator_url),
        priority=FEED,
        now=NOW,
    )

    third = service.upsert(
        make_job(
            source="manual_import",
            source_job_id=None,
            description="Pasted by the user.",
            application_url=aggregator_url + "?ref=email",
        ),
        priority=MANUAL,
        now=NOW,
    )

    assert third.outcome is UpsertOutcome.DUPLICATE
    assert third.job.duplicate_of_id == primary.id


def test_a_direct_ats_record_takes_over_from_an_aggregator(
    session: Session, candidate_dir: Any
) -> None:
    service = JobService(session)
    candidate, _ = CandidateService(session, candidate_dir=candidate_dir).get_or_import_default()
    feed_job = service.upsert(
        make_job(source="mock_feed", source_job_id="feed-1"), priority=FEED, now=NOW
    ).job
    other_duplicate = service.upsert(
        make_job(
            source="manual_import",
            source_job_id=None,
            description="Pasted.",
            application_url="https://nova-ai.example/careers/jobs/1?utm_source=x",
        ),
        priority=MANUAL,
        now=NOW,
    ).job
    application, created = ApplicationService(session).create_discovered(candidate, feed_job)
    assert created

    result = service.upsert(make_job(source_job_id="ats-1"), priority=ATS, now=NOW)

    assert result.outcome is UpsertOutcome.DUPLICATE
    assert result.swapped is True
    assert result.primary.id == result.job.id
    assert result.job.duplicate_of_id is None
    session.refresh(feed_job)
    session.refresh(other_duplicate)
    session.refresh(application)
    assert feed_job.duplicate_of_id == result.job.id
    assert other_duplicate.duplicate_of_id == result.job.id
    assert application.job_id == result.job.id


def test_repeated_imports_without_source_ids_update_the_same_record(session: Session) -> None:
    service = JobService(session)
    job = make_job(
        source="manual_import",
        source_job_id=None,
        application_url="https://www.linkedin.com/jobs/view/3912345678?trk=a",
    )
    first = service.upsert(job, priority=MANUAL, now=NOW)

    again = service.upsert(
        make_job(
            source="manual_import",
            source_job_id=None,
            application_url="https://fr.linkedin.com/jobs/view/ai-engineer-3912345678?trk=b",
        ),
        priority=MANUAL,
        now=NOW,
    )

    assert first.outcome is UpsertOutcome.NEW
    assert again.outcome is UpsertOutcome.UPDATED
    assert again.job.id == first.job.id
    assert _count(session) == 1
    assert session.scalar(select(func.count()).select_from(Application)) == 0
