"""Job sources: the runtime mirror of ``crawler/sources.yaml`` and their last-run status."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawlers.registry import SourcesFile, skip_reason
from app.models import JobSource

MAX_ERROR_LENGTH = 2000


@dataclass(frozen=True)
class SourceStatus:
    source: JobSource
    runnable: bool
    skip_reason: str | None


class JobSourceService:
    """Methods flush but never commit: the caller owns the transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def sync(self, config: SourcesFile) -> dict[str, JobSource]:
        """Create or update one row per configured source (policy comes from the YAML file).

        Sources removed from the file keep their row (jobs reference them) but are disabled.
        """
        existing = {source.key: source for source in self._session.scalars(select(JobSource))}
        configured: dict[str, JobSource] = {}
        for entry in config.sources:
            source = existing.get(entry.key)
            if source is None:
                source = JobSource(key=entry.key, last_counts={})
                self._session.add(source)
            source.name = entry.name
            source.kind = entry.kind
            source.policy = entry.policy
            source.enabled = entry.enabled
            source.is_mock = entry.mock
            source.priority = entry.priority
            source.rate_limit_per_minute = entry.rate_limit_per_minute
            source.description = entry.description
            source.notes = entry.notes
            configured[entry.key] = source
        for key, source in existing.items():
            if key not in configured:
                source.enabled = False
        self._session.flush()
        return configured

    def statuses(self, config: SourcesFile, *, mock_mode: bool) -> list[SourceStatus]:
        """Every configured source with whether it runs now, highest priority first."""
        sources = self.sync(config)
        entries = sorted(config.sources, key=lambda entry: (-entry.priority, entry.key))
        result: list[SourceStatus] = []
        for entry in entries:
            reason = skip_reason(entry, mock_mode=mock_mode)
            result.append(SourceStatus(sources[entry.key], reason is None, reason))
        return result

    def priorities(self) -> dict[str, int]:
        return {source.key: source.priority for source in self._session.scalars(select(JobSource))}

    def mock_keys(self) -> set[str]:
        return set(self._session.scalars(select(JobSource.key).where(JobSource.is_mock)))

    def record_run(
        self,
        key: str,
        *,
        at: datetime,
        status: str,
        counts: Mapping[str, Any],
        error: str | None = None,
    ) -> None:
        source = self._session.scalars(select(JobSource).where(JobSource.key == key)).one()
        source.last_run_at = at
        source.last_status = status
        source.last_error = error[:MAX_ERROR_LENGTH] if error else None
        source.last_counts = dict(counts)
        self._session.flush()
