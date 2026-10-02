"""Posting dates: source timestamps (KNOWN), relative text (ESTIMATED) or nothing (UNKNOWN).

Relative texts are ranges, not points: "1 day ago" means between 24 and 48 hours ago. The
estimate stored is the *oldest* plausible time, so a job is only claimed as "posted in the last
24 hours" when every reading of the text agrees. The original text and the reference time are
kept as the estimation basis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.jobs.types import PostingDateStatus

# A timestamp slightly in the future is clock skew; far in the future it is bogus.
_MAX_CLOCK_SKEW = timedelta(hours=1)

_UNITS: dict[str, timedelta] = {
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
}
_UNIT_WORDS: dict[str, str] = {
    "min": "minute",
    "mins": "minute",
    "minute": "minute",
    "minutes": "minute",
    "h": "hour",
    "hr": "hour",
    "hrs": "hour",
    "hour": "hour",
    "hours": "hour",
    "heure": "hour",
    "heures": "hour",
    "d": "day",
    "day": "day",
    "days": "day",
    "jour": "day",
    "jours": "day",
    "w": "week",
    "wk": "week",
    "week": "week",
    "weeks": "week",
    "semaine": "week",
    "semaines": "week",
    "month": "month",
    "months": "month",
    "mois": "month",
}
_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "un": 1, "une": 1}

_AGE_RE = re.compile(
    r"(?P<plus>plus de\s+|over\s+|more than\s+)?"
    r"(?P<count>\d+|an?|one|une?)\s*(?P<more>\+)?\s*"
    r"(?P<unit>minutes?|mins?|hours?|hrs?|h|days?|d|weeks?|wks?|w|months?|heures?|jours?|"
    r"semaines?|mois)\b",
    re.IGNORECASE,
)
_JUST_NOW_RE = re.compile(r"\b(just (posted|now)|à l['’]instant|new|nouveau)\b", re.IGNORECASE)
_TODAY_RE = re.compile(r"\b(today|aujourd['’]hui)\b", re.IGNORECASE)
_YESTERDAY_RE = re.compile(r"\b(yesterday|hier)\b", re.IGNORECASE)
_AGO_RE = re.compile(r"\b(ago|il y a)\b", re.IGNORECASE)


@dataclass(frozen=True)
class PostingDate:
    posted_at: datetime | None
    status: PostingDateStatus
    basis: str | None = None


def parse_relative_age(text: str) -> tuple[timedelta, timedelta | None] | None:
    """Age range ``(minimum, maximum)`` stated by a relative text; maximum None = unbounded."""
    if not text or not text.strip():
        return None
    if _JUST_NOW_RE.search(text):
        return timedelta(0), timedelta(hours=1)
    if _TODAY_RE.search(text):
        return timedelta(0), timedelta(days=1)
    if _YESTERDAY_RE.search(text):
        return timedelta(0), timedelta(days=2)
    match = _AGE_RE.search(text)
    if match is None or not _AGO_RE.search(text):
        return None
    raw_count = match.group("count").lower()
    count = int(raw_count) if raw_count.isdigit() else _NUMBER_WORDS[raw_count]
    unit = _UNITS[_UNIT_WORDS[match.group("unit").lower()]]
    minimum = count * unit
    if match.group("more") or match.group("plus"):
        return minimum, None
    return minimum, (count + 1) * unit


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_timestamp(value: datetime | str) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    try:
        return _as_utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def resolve_posting_date(
    *,
    now: datetime,
    posted_at: datetime | str | None = None,
    posted_text: str | None = None,
) -> PostingDate:
    """Turn what a source provides into a posting date with an honest status."""
    if posted_at is not None:
        timestamp = _parse_timestamp(posted_at)
        if timestamp is not None:
            if timestamp > now + _MAX_CLOCK_SKEW:
                return PostingDate(
                    None,
                    PostingDateStatus.UNKNOWN,
                    f"source timestamp {timestamp.isoformat()} is in the future",
                )
            return PostingDate(min(timestamp, now), PostingDateStatus.KNOWN)
    if posted_text:
        age = parse_relative_age(posted_text)
        if age is not None:
            minimum, maximum = age
            oldest = now - (maximum if maximum is not None else minimum)
            newest = now - minimum
            span = (
                f"between {oldest.isoformat()} and {newest.isoformat()}"
                if maximum is not None
                else f"before {newest.isoformat()}"
            )
            basis = f'relative text "{posted_text.strip()}" read at {now.isoformat()}: {span}'
            return PostingDate(oldest, PostingDateStatus.ESTIMATED, basis)
        return PostingDate(None, PostingDateStatus.UNKNOWN, f'unreadable date "{posted_text}"')
    return PostingDate(None, PostingDateStatus.UNKNOWN)
