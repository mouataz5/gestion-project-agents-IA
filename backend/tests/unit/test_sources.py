import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import REPO_ROOT
from app.crawlers.base import CompanyTarget, JobQuery
from app.crawlers.mock import MockAtsSource, MockFeedSource
from app.crawlers.registry import (
    SourceRegistry,
    SourcesConfigError,
    load_companies_file,
    load_sources_config,
)
from app.jobs.types import EmploymentType, PostingDateStatus, RemoteStatus, Seniority

pytestmark = pytest.mark.feature("job-discovery")

CRAWLER_DIR = REPO_ROOT / "crawler"
FIXTURES = CRAWLER_DIR / "fixtures" / "mock_jobs"
NOW = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)


def _query() -> JobQuery:
    return JobQuery(posted_after=NOW - timedelta(hours=24), posted_before=NOW, now=NOW)


def _company(token: str, ats_type: str = "GREENHOUSE") -> CompanyTarget:
    return CompanyTarget(
        id=uuid.uuid4(), name=token, ats_type=ats_type, board_token=token, career_url=None
    )


# --- sources.yaml and the registry -------------------------------------------------------------


@pytest.mark.feature("compliance")
def test_the_repository_source_registry_is_valid() -> None:
    config = load_sources_config(CRAWLER_DIR)

    keys = [source.key for source in config.sources]
    assert len(keys) == len(set(keys))
    assert {"mock_ats", "mock_feed", "manual_import", "greenhouse", "linkedin"} <= set(keys)
    linkedin = next(source for source in config.sources if source.key == "linkedin")
    assert linkedin.policy == "manual_only"
    assert "JobAgent" in config.user_agent


@pytest.mark.feature("compliance")
def test_mock_mode_runs_only_the_mock_sources_in_priority_order() -> None:
    registry = SourceRegistry(
        load_sources_config(CRAWLER_DIR), mock_mode=True, fixtures_dir=FIXTURES
    )

    assert [source.key for source in registry.runnable()] == ["mock_ats", "mock_feed"]
    reasons = dict(registry.skipped())
    assert "manual" in reasons["manual_import"]
    assert "manual" in reasons["linkedin"]
    assert "Phase 10" in reasons["greenhouse"] or "disabled" in reasons["greenhouse"]


@pytest.mark.feature("compliance")
def test_live_mode_never_runs_mock_sources() -> None:
    registry = SourceRegistry(
        load_sources_config(CRAWLER_DIR), mock_mode=False, fixtures_dir=FIXTURES
    )

    assert registry.runnable() == []
    assert "MOCK_MODE" in dict(registry.skipped())["mock_ats"]


@pytest.mark.feature("compliance")
@pytest.mark.parametrize(
    ("content", "path"),
    [
        (
            "version: 1\nuser_agent: x\nsources:\n  - {key: a, name: A, kind: FEED, policy: maybe}\n",
            "sources.0.policy",
        ),
        (
            "version: 1\nuser_agent: x\nsources:\n  - {key: a, name: A, kind: FEED, policy: allowed, colour: red}\n",
            "sources.0.colour",
        ),
        ("version: 2\nuser_agent: x\nsources: []\n", "version"),
    ],
)
def test_invalid_source_registries_are_rejected(tmp_path: Path, content: str, path: str) -> None:
    (tmp_path / "sources.yaml").write_text(content, encoding="utf-8")

    with pytest.raises(SourcesConfigError) as excinfo:
        load_sources_config(tmp_path)

    assert any(error["loc"] == path for error in excinfo.value.details)


@pytest.mark.feature("compliance")
def test_duplicate_source_keys_are_rejected(tmp_path: Path) -> None:
    source = "{key: a, name: A, kind: FEED, policy: allowed}"
    (tmp_path / "sources.yaml").write_text(
        f"version: 1\nuser_agent: x\nsources:\n  - {source}\n  - {source}\n", encoding="utf-8"
    )

    with pytest.raises(SourcesConfigError):
        load_sources_config(tmp_path)


def test_the_repository_watchlist_seed_is_valid_and_fictional() -> None:
    companies = load_companies_file(CRAWLER_DIR).companies

    assert [company.name for company in companies][:2] == ["Nova AI", "Datawise Labs"]
    assert all(
        company.career_url.endswith((".example/careers", ".example/jobs")) for company in companies
    )
    assert [company.enabled for company in companies].count(False) == 1


# --- mock sources -----------------------------------------------------------------------------


def test_mock_boards_cover_the_watchlist_tokens() -> None:
    source = MockAtsSource(FIXTURES)

    assert source.supports(_company("nova-ai"))
    assert not source.supports(_company("unknown-company"))


def test_mock_board_postings_normalize_to_the_job_model() -> None:
    source = MockAtsSource(FIXTURES)
    company = _company("nova-ai")

    raws = source.search_company(company, _query())
    job = source.normalize(next(raw for raw in raws if raw.source_job_id == "nova-1001"))

    assert len(raws) == 4
    assert job.source == "mock_ats"
    assert job.company == "Nova AI"
    assert job.company_id == company.id
    assert job.title == "Senior AI Engineer"
    assert job.location == "Paris, France"
    assert job.country_code == "FR"
    assert job.remote_status is RemoteStatus.HYBRID
    assert job.employment_type is EmploymentType.FULL_TIME
    assert job.seniority is Seniority.SENIOR
    assert job.posting_date_status is PostingDateStatus.KNOWN
    assert job.posted_at == NOW - timedelta(hours=5)
    assert job.application_url == "https://nova-ai.example/careers/jobs/1001"
    assert job.canonical_url == "https://nova-ai.example/careers/jobs/1001"
    assert job.ats_type == "GREENHOUSE"
    assert "<" not in job.description
    assert "• Design RAG pipelines with LangGraph" in job.description
    assert job.required_skills == ["Python", "LLMs", "RAG", "LangGraph"]
    assert (job.salary_min, job.salary_max, job.salary_currency, job.salary_period) == (
        65000,
        80000,
        "EUR",
        "year",
    )
    assert job.visa_information == "Visa sponsorship is available for non-EU candidates."
    assert len(job.content_hash) == 64
    assert job.raw_content["id"] == "nova-1001"


def test_feed_items_carry_relative_and_unknown_dates() -> None:
    source = MockFeedSource(FIXTURES)

    jobs = {raw.source_job_id: source.normalize(raw) for raw in source.search(_query())}

    assert len(jobs) == 9
    assert jobs["feed-03"].posting_date_status is PostingDateStatus.ESTIMATED
    assert jobs["feed-03"].posted_at == NOW - timedelta(hours=4)
    assert jobs["feed-05"].posting_date_status is PostingDateStatus.UNKNOWN
    assert jobs["feed-05"].posted_at is None
    assert jobs["feed-07"].posting_date_status is PostingDateStatus.ESTIMATED
    # The tracking parameters of the aggregator link do not hide the duplicate.
    assert jobs["feed-01"].canonical_url == "https://nova-ai.example/careers/jobs/1001"


def test_every_fixture_posting_normalizes() -> None:
    ats = MockAtsSource(FIXTURES)
    feed = MockFeedSource(FIXTURES)
    tokens = [path.stem for path in (FIXTURES / "boards").glob("*.json")]

    normalized = [
        ats.normalize(raw)
        for token in tokens
        for raw in ats.search_company(_company(token), _query())
    ] + [feed.normalize(raw) for raw in feed.search(_query())]

    assert len(normalized) == 20
    assert all(job.title and job.company and job.content_hash for job in normalized)
    assert ats.health_check().ok
    assert feed.health_check().ok
