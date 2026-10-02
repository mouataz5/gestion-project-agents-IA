"""Discovery runs over the mock sources: counters, events, window, dedup, queueing, isolation."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.crawlers.mock import MockFeedSource
from app.models import Application, Company, Job, JobSkill, JobSource

pytestmark = [pytest.mark.feature("job-discovery"), pytest.mark.integration]

NOW = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)


def _fixed(now: datetime) -> Callable[[], datetime]:
    return lambda: now


def _jobs(jobs_db: sessionmaker[Session]) -> dict[str, Job]:
    with jobs_db() as session:
        return {
            job.source_job_id or job.application_url: job for job in session.scalars(select(Job))
        }


def test_a_mock_discovery_run_loads_dedupes_filters_and_queues(
    discover: Callable[..., Any],
    import_companies: Callable[[], None],
    jobs_db: sessionmaker[Session],
) -> None:
    import_companies()

    run = discover(clock=_fixed(NOW))

    assert run.status == "SUCCEEDED"
    assert run.jobs_processed == 19  # postings fetched and normalized
    assert run.jobs_discovered == 14  # new unique jobs
    totals = run.summary["totals"]
    assert totals == {
        "fetched": 19,
        "filtered_out": 3,
        "new": 14,
        "updated": 0,
        "duplicates": 2,
        "in_window": 9,
        "out_of_window": 4,
        "unknown_date": 1,
        "outside_target_countries": 1,
        "queued": 8,
        "errors": 0,
    }
    assert run.summary["window"]["lookback_hours"] == 24
    assert {stage for stage, _, _ in run.events} >= {
        "discovery.config",
        "discovery.source.mock_ats",
        "discovery.source.mock_feed",
        "discovery.summary",
    }

    jobs = _jobs(jobs_db)
    assert len(jobs) == 16  # 14 primary records + 2 duplicate listings
    assert "nova-1003" not in jobs  # "Account Executive" is not an AI/ML role
    assert "qc-5001" not in jobs  # disabled watchlist company
    assert jobs["feed-01"].duplicate_of_id == jobs["nova-1001"].id  # same URL + tracking params
    assert jobs["feed-02"].duplicate_of_id == jobs["kr-3001"].id  # same content
    assert jobs["feed-05"].posting_date_status.value == "UNKNOWN"
    assert jobs["feed-03"].posting_date_status.value == "ESTIMATED"
    assert jobs["nova-1001"].discovery_run_id == run.id
    assert jobs["nova-1001"].company_id is not None

    with jobs_db() as session:
        queued = {
            session.get(Job, application.job_id).source_job_id  # type: ignore[union-attr]
            for application in session.scalars(select(Application))
        }
        assert queued == {
            "nova-1001",
            "nova-1002",
            "dw-2001",
            "kr-3001",
            "kr-3002",
            "sa-4001",
            "feed-03",
            "feed-07",
        }
        statuses = {a.status.value for a in session.scalars(select(Application))}
        assert statuses == {"DISCOVERED"}
        companies = {c.name: c for c in session.scalars(select(Company))}
        assert companies["Nova AI"].last_checked_at == NOW
        assert companies["Nova AI"].last_check_status == "ok: 4 postings"
        assert companies["Quiet Corp"].last_checked_at is None
        sources = {s.key: s for s in session.scalars(select(JobSource))}
        assert sources["mock_ats"].last_status == "ok"
        assert sources["mock_ats"].last_run_at == NOW
        assert sources["greenhouse"].last_run_at is None
        skills = session.scalars(
            select(JobSkill).where(JobSkill.job_id == jobs["nova-1001"].id)
        ).all()
        assert {(s.name, s.importance.value) for s in skills} >= {
            ("LangGraph", "REQUIRED"),
            ("MCP", "PREFERRED"),
        }


def test_a_second_run_is_idempotent(
    discover: Callable[..., Any],
    import_companies: Callable[[], None],
    jobs_db: sessionmaker[Session],
) -> None:
    import_companies()
    discover(clock=_fixed(NOW))

    again = discover(clock=_fixed(NOW + timedelta(hours=1)))

    assert again.status == "SUCCEEDED"
    assert again.jobs_discovered == 0
    assert again.summary["totals"]["new"] == 0
    assert again.summary["totals"]["queued"] == 0
    assert again.summary["totals"]["updated"] == 16
    assert len(_jobs(jobs_db)) == 16


def test_a_failing_source_does_not_stop_the_run(
    discover: Callable[..., Any],
    import_companies: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch,
    jobs_db: sessionmaker[Session],
) -> None:
    import_companies()

    def broken(self: MockFeedSource, query: Any) -> Any:
        raise RuntimeError("feed unavailable")

    monkeypatch.setattr(MockFeedSource, "search", broken)

    run = discover(clock=_fixed(NOW))

    assert run.status == "PARTIAL_SUCCESS"
    assert run.error_count == 1
    assert run.jobs_discovered == 8  # the ATS boards still delivered
    assert any(
        stage == "discovery.source.mock_feed" and level == "ERROR" for stage, level, _ in run.events
    )
    with jobs_db() as session:
        feed = session.scalars(select(JobSource).where(JobSource.key == "mock_feed")).one()
        assert feed.last_status == "error"
        assert "feed unavailable" in (feed.last_error or "")


def test_an_empty_watchlist_is_reported(
    discover: Callable[..., Any], jobs_db: sessionmaker[Session]
) -> None:
    run = discover(clock=_fixed(NOW))

    assert run.status == "SUCCEEDED"
    assert any("watchlist is empty" in message for _, _, message in run.events)
    # Only the aggregator feed was searched: without ATS records its listings are all new.
    assert run.summary["totals"]["new"] == 8
    assert run.summary["totals"]["duplicates"] == 0


def test_live_mode_never_runs_mock_sources(
    discover: Callable[..., Any], import_companies: Callable[[], None]
) -> None:
    import_companies()

    run = discover(clock=_fixed(NOW), mock_mode=False)

    assert run.status == "SUCCEEDED"
    assert run.jobs_discovered == 0
    assert any(
        level == "WARNING" and "No discovery source" in message for _, level, message in run.events
    )
