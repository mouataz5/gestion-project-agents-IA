"""Manual job imports: a pasted job URL (the permitted LinkedIn path) or a job-alert email.

Nothing is fetched: the URL is validated (public http/https only) and stored with the metadata
the user provides. Missing fields stay empty rather than being guessed. Imported jobs are always
queued for the candidate (explicit user intent), whatever their posting date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.crawlers.base import build_job
from app.crawlers.registry import load_sources_config
from app.jobs.email_links import extract_job_links
from app.jobs.urls import UnsafeUrlError, validate_public_url
from app.models import Candidate, Job
from app.schemas.jobs import JobImportRequest
from app.services.applications import ApplicationService
from app.services.job_sources import JobSourceService
from app.services.jobs import JobService, UpsertOutcome

MANUAL_SOURCE = "manual_import"


@dataclass(frozen=True)
class ImportResult:
    job: Job  # the primary record (the existing job when the URL was already known)
    created: bool  # a new job was stored
    duplicate: bool  # the posting was already known from another source
    application_created: bool


class JobImportService:
    """Methods flush but never commit: the caller owns the transaction."""

    def __init__(self, session: Session, *, crawler_dir: Path, now: datetime) -> None:
        self._session = session
        self._now = now
        sources = JobSourceService(session).sync(load_sources_config(crawler_dir))
        self._priority = sources[MANUAL_SOURCE].priority if MANUAL_SOURCE in sources else 0
        self._jobs = JobService(session)

    def import_url(self, request: JobImportRequest, candidate: Candidate) -> ImportResult:
        url = validate_public_url(request.url)
        posting = build_job(
            source=MANUAL_SOURCE,
            title=request.title or "",
            company=request.company or "",
            location=request.location,
            description=request.description,
            posted_at=request.posted_at,
            posted_text=request.posted_text,
            application_url=url,
            raw_content={"imported_url": url},
            fetched_at=self._now,
        )
        result = self._jobs.upsert(posting, priority=self._priority, now=self._now, merge=True)
        _, application_created = ApplicationService(self._session).create_discovered(
            candidate, result.primary
        )
        return ImportResult(
            job=result.primary,
            created=result.outcome is UpsertOutcome.NEW,
            duplicate=not result.is_primary or result.outcome is UpsertOutcome.DUPLICATE,
            application_created=application_created,
        )

    def import_email(self, text: str, candidate: Candidate) -> tuple[int, list[ImportResult]]:
        """Import every job link of a job-alert email; returns ``(links_found, results)``."""
        links = extract_job_links(text)
        results: list[ImportResult] = []
        for link in links:
            try:
                results.append(self.import_url(JobImportRequest(url=link), candidate))
            except UnsafeUrlError:
                continue  # never stored; job-board links are public, so this is unexpected
        return len(links), results
