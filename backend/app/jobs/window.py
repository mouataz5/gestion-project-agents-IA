"""The posting window: ``posted_after`` ≤ posted_at ≤ ``posted_before`` (both inclusive)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.jobs.types import PostingDateStatus, WindowStatus


@dataclass(frozen=True)
class PostingWindow:
    posted_after: datetime
    posted_before: datetime

    @classmethod
    def lookback(cls, now: datetime, *, hours: int) -> PostingWindow:
        """The default daily search: ``now - JOB_LOOKBACK_HOURS`` until now."""
        return cls(posted_after=now - timedelta(hours=hours), posted_before=now)

    def classify(self, posted_at: datetime | None, status: PostingDateStatus) -> WindowStatus:
        if status is PostingDateStatus.UNKNOWN or posted_at is None:
            return WindowStatus.UNKNOWN_DATE  # never claimed as "posted in the window"
        if self.posted_after <= posted_at <= self.posted_before:
            return WindowStatus.IN_WINDOW
        return WindowStatus.OUT_OF_WINDOW
