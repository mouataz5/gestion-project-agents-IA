"""Mock sources for MOCK_MODE: fictional ATS boards and an aggregator feed (local JSON files).

Dates are expressed relative to the fetch time ("posted_hours_ago", "3 hours ago"), so the
fixtures stay inside or outside the posting window whenever they run. No network access.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.crawlers.base import (
    CompanyTarget,
    JobQuery,
    NormalizedJob,
    RawJob,
    SourceHealth,
    SourceKind,
    build_job,
)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,99}")


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return data


class MockAtsSource:
    """Company boards in ``fixtures/boards/<board_token>.json`` (Greenhouse/Lever-like APIs)."""

    key = "mock_ats"
    kind = SourceKind.ATS_API

    def __init__(self, fixtures_dir: Path) -> None:
        self._boards_dir = fixtures_dir / "boards"

    def _board_path(self, token: str | None) -> Path | None:
        if not token or not _TOKEN_RE.fullmatch(token):
            return None  # never build a path from an unchecked token
        path = self._boards_dir / f"{token}.json"
        return path if path.is_file() else None

    def supports(self, company: CompanyTarget) -> bool:
        return self._board_path(company.board_token) is not None

    def search_company(self, company: CompanyTarget, query: JobQuery) -> list[RawJob]:
        path = self._board_path(company.board_token)
        if path is None:
            return []
        board = _load(path)
        meta = {key: board.get(key) for key in ("company", "company_url", "ats_type")}
        return [
            RawJob(
                source=self.key,
                source_job_id=str(job["id"]),
                payload=job,
                fetched_at=query.now,
                company_id=company.id,
                url=job.get("url"),
                extra=meta,
            )
            for job in board.get("jobs", [])
        ]

    def search(self, query: JobQuery) -> Iterable[RawJob]:
        for company in query.companies:
            yield from self.search_company(company, query)

    def get_job(self, source_job_id: str) -> RawJob | None:
        return None  # boards are always listed whole

    def normalize(self, raw: RawJob) -> NormalizedJob:
        job = raw.payload
        salary = job.get("salary") or {}
        hours_ago = job.get("posted_hours_ago")
        return build_job(
            source=self.key,
            source_job_id=raw.source_job_id,
            company_id=raw.company_id,
            company=str(raw.extra.get("company") or ""),
            company_url=raw.extra.get("company_url"),
            ats_type=raw.extra.get("ats_type"),
            title=str(job.get("title", "")),
            description_html=job.get("description_html"),
            location=job.get("location"),
            workplace=job.get("workplace"),
            employment_type=job.get("employment_type"),
            posted_at=(
                raw.fetched_at - timedelta(hours=float(hours_ago))
                if hours_ago is not None
                else job.get("posted_at")
            ),
            application_url=job.get("url"),
            salary_min=salary.get("min"),
            salary_max=salary.get("max"),
            salary_currency=salary.get("currency"),
            salary_period=salary.get("period"),
            visa_information=job.get("visa"),
            relocation_information=job.get("relocation"),
            required_skills=job.get("required_skills", ()),
            preferred_skills=job.get("preferred_skills", ()),
            languages=job.get("languages", ()),
            education_requirements=job.get("education"),
            experience_requirements=job.get("experience"),
            responsibilities=job.get("responsibilities", ()),
            raw_content=dict(job),
            fetched_at=raw.fetched_at,
        )

    def health_check(self) -> SourceHealth:
        boards = sorted(self._boards_dir.glob("*.json")) if self._boards_dir.is_dir() else []
        return SourceHealth(ok=bool(boards), detail=f"{len(boards)} mock boards")


class MockFeedSource:
    """An aggregator feed in ``fixtures/feed.json`` with relative and missing dates."""

    key = "mock_feed"
    kind = SourceKind.FEED

    def __init__(self, fixtures_dir: Path) -> None:
        self._path = fixtures_dir / "feed.json"

    def search(self, query: JobQuery) -> Iterable[RawJob]:
        for item in _load(self._path).get("items", []):
            yield RawJob(
                source=self.key,
                source_job_id=str(item["guid"]),
                payload=item,
                fetched_at=query.now,
                url=item.get("link"),
            )

    def get_job(self, source_job_id: str) -> RawJob | None:
        return None

    def normalize(self, raw: RawJob) -> NormalizedJob:
        item = raw.payload
        return build_job(
            source=self.key,
            source_job_id=raw.source_job_id,
            company=str(item.get("company", "")),
            title=str(item.get("title", "")),
            description=item.get("description"),
            location=item.get("location"),
            posted_text=item.get("published"),
            application_url=item.get("link"),
            raw_content=dict(item),
            fetched_at=raw.fetched_at,
        )

    def health_check(self) -> SourceHealth:
        return SourceHealth(ok=self._path.is_file(), detail="mock aggregator feed")
