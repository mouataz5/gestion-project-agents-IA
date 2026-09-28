"""Single source of "now" (timezone-aware UTC) so time can be controlled in tests."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
