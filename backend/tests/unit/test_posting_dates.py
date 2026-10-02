from datetime import UTC, datetime, timedelta

import pytest

from app.jobs.hashing import content_hash
from app.jobs.posting_dates import parse_relative_age, resolve_posting_date
from app.jobs.types import PostingDateStatus, WindowStatus
from app.jobs.window import PostingWindow

pytestmark = pytest.mark.feature("posting-window")

NOW = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
H = timedelta(hours=1)
D = timedelta(days=1)


# --- content hash ---------------------------------------------------------------------------


@pytest.mark.feature("job-deduplication")
def test_content_hash_is_stable_across_whitespace_case_and_unicode_forms() -> None:
    base = content_hash(
        company="Nova AI",
        title="Senior AI Engineer",
        location="Paris, France",
        description="Build RAG systems.\n\nWith LangGraph.",
    )
    variant = content_hash(
        company="  NOVA AI ",
        title="senior  ai engineer",
        location="paris, france",
        description="Build RAG systems. With   LangGraph.",
    )
    fullwidth = content_hash(
        company="Ｎｏｖａ AI",  # noqa: RUF001 - full-width letters normalise (NFKC) to ASCII
        title="Senior AI Engineer",
        location="Paris, France",
        description="Build RAG systems. With LangGraph.",
    )

    assert base == variant == fullwidth
    assert len(base) == 64


@pytest.mark.feature("job-deduplication")
def test_content_hash_changes_with_the_content() -> None:
    first = content_hash(company="Nova AI", title="AI Engineer", location="Paris", description="x")
    other_title = content_hash(
        company="Nova AI", title="ML Engineer", location="Paris", description="x"
    )
    other_city = content_hash(
        company="Nova AI", title="AI Engineer", location="Lyon", description="x"
    )
    missing = content_hash(company="Nova AI", title="AI Engineer", location=None, description="x")
    empty = content_hash(company="Nova AI", title="AI Engineer", location="", description="x")

    assert len({first, other_title, other_city}) == 3
    assert missing == empty


# --- relative dates ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "minimum", "maximum"),
    [
        ("just posted", timedelta(0), H),
        ("Just now", timedelta(0), H),
        ("à l'instant", timedelta(0), H),
        ("Posted today", timedelta(0), D),
        ("aujourd'hui", timedelta(0), D),
        ("5 minutes ago", timedelta(minutes=5), timedelta(minutes=6)),
        ("an hour ago", H, 2 * H),
        ("3 hours ago", 3 * H, 4 * H),
        ("3h ago", 3 * H, 4 * H),
        ("il y a 6 heures", 6 * H, 7 * H),
        ("il y a une heure", H, 2 * H),
        ("yesterday", timedelta(0), 2 * D),
        ("hier", timedelta(0), 2 * D),
        ("1 day ago", D, 2 * D),
        ("Reposted 2 days ago", 2 * D, 3 * D),
        ("il y a 3 jours", 3 * D, 4 * D),
        ("Publiée il y a 2 semaines", timedelta(weeks=2), timedelta(weeks=3)),
        ("a week ago", timedelta(weeks=1), timedelta(weeks=2)),
        ("1 month ago", timedelta(days=30), timedelta(days=60)),
        ("30+ days ago", timedelta(days=30), None),
        ("il y a plus de 30 jours", timedelta(days=30), None),
    ],
)
def test_relative_ages_are_parsed(text: str, minimum: timedelta, maximum: timedelta | None) -> None:
    assert parse_relative_age(text) == (minimum, maximum)


@pytest.mark.parametrize("text", ["", "Paris", "Senior AI Engineer", "2 apples", "soon"])
def test_text_without_an_age_is_not_parsed(text: str) -> None:
    assert parse_relative_age(text) is None


def test_source_timestamps_are_known() -> None:
    posted = NOW - 5 * H

    result = resolve_posting_date(posted_at=posted, now=NOW)

    assert result.status is PostingDateStatus.KNOWN
    assert result.posted_at == posted


def test_iso_strings_and_naive_datetimes_are_read_as_utc() -> None:
    assert resolve_posting_date(posted_at="2026-10-02T03:00:00Z", now=NOW).posted_at == NOW - 5 * H
    naive = datetime(2026, 10, 2, 3, 0)  # noqa: DTZ001 - sources sometimes omit the time zone
    assert resolve_posting_date(posted_at=naive, now=NOW).posted_at == NOW - 5 * H


def test_relative_dates_are_estimated_conservatively_with_their_basis() -> None:
    result = resolve_posting_date(posted_text="3 hours ago", now=NOW)

    assert result.status is PostingDateStatus.ESTIMATED
    assert result.posted_at == NOW - 4 * H  # the oldest plausible time
    assert result.basis is not None
    assert "3 hours ago" in result.basis
    assert NOW.isoformat() in result.basis


def test_missing_or_unreadable_dates_are_unknown() -> None:
    for kwargs in ({}, {"posted_text": "recently"}, {"posted_at": "not a date"}):
        result = resolve_posting_date(now=NOW, **kwargs)  # type: ignore[arg-type]
        assert result.status is PostingDateStatus.UNKNOWN
        assert result.posted_at is None


def test_future_timestamps_are_clamped_or_rejected() -> None:
    slight = resolve_posting_date(posted_at=NOW + timedelta(minutes=10), now=NOW)
    assert slight.status is PostingDateStatus.KNOWN
    assert slight.posted_at == NOW

    bogus = resolve_posting_date(posted_at=NOW + 3 * D, now=NOW)
    assert bogus.status is PostingDateStatus.UNKNOWN
    assert bogus.posted_at is None


# --- posting window -------------------------------------------------------------------------


def test_window_defaults_to_the_lookback_period() -> None:
    window = PostingWindow.lookback(NOW, hours=24)

    assert window.posted_after == NOW - D
    assert window.posted_before == NOW


@pytest.mark.parametrize(
    ("posted_at", "status", "expected"),
    [
        (NOW - 5 * H, PostingDateStatus.KNOWN, WindowStatus.IN_WINDOW),
        (NOW - D, PostingDateStatus.KNOWN, WindowStatus.IN_WINDOW),  # boundary is inclusive
        (NOW - D - timedelta(seconds=1), PostingDateStatus.KNOWN, WindowStatus.OUT_OF_WINDOW),
        (NOW - 4 * H, PostingDateStatus.ESTIMATED, WindowStatus.IN_WINDOW),
        (NOW - 2 * D, PostingDateStatus.ESTIMATED, WindowStatus.OUT_OF_WINDOW),
        (None, PostingDateStatus.UNKNOWN, WindowStatus.UNKNOWN_DATE),
        # an unknown date is never "in the window", whatever value is stored
        (NOW - H, PostingDateStatus.UNKNOWN, WindowStatus.UNKNOWN_DATE),
    ],
)
def test_window_classification(
    posted_at: datetime | None, status: PostingDateStatus, expected: WindowStatus
) -> None:
    assert PostingWindow.lookback(NOW, hours=24).classify(posted_at, status) is expected


def test_one_day_ago_is_never_claimed_as_last_24_hours() -> None:
    estimate = resolve_posting_date(posted_text="1 day ago", now=NOW)
    today = resolve_posting_date(posted_text="today", now=NOW)
    window = PostingWindow.lookback(NOW, hours=24)

    assert window.classify(estimate.posted_at, estimate.status) is WindowStatus.OUT_OF_WINDOW
    assert window.classify(today.posted_at, today.status) is WindowStatus.IN_WINDOW


def test_custom_windows_use_posted_after_and_posted_before() -> None:
    window = PostingWindow(posted_after=NOW - 3 * D, posted_before=NOW - 2 * D)

    assert window.classify(NOW - 60 * H, PostingDateStatus.KNOWN) is WindowStatus.IN_WINDOW
    assert window.classify(NOW - H, PostingDateStatus.KNOWN) is WindowStatus.OUT_OF_WINDOW
