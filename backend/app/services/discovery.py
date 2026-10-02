"""Job discovery run: search every runnable source, normalize, deduplicate, apply the posting
window and queue matching jobs for the candidate. Executed by a worker, recorded as a
DISCOVERY automation run.

Counters: ``jobs_processed`` = postings fetched and normalized, ``jobs_discovered`` = new unique
jobs. A failing source (or company board, or posting) is recorded as an error and the run
continues: it ends ``PARTIAL_SUCCESS`` (``FAILED`` only when every source failed).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from itertools import islice
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.crawlers.base import CompanyBoardSource, CompanyTarget, JobQuery, JobSource, RawJob
from app.crawlers.registry import SourceRegistry, load_sources_config
from app.db.session import session_scope
from app.jobs.relevance import title_matches
from app.jobs.types import RemoteStatus, WindowStatus
from app.jobs.window import PostingWindow
from app.models import Candidate, Company, EventLevel, Job, RunStatus
from app.services.applications import ApplicationService
from app.services.audit import Actor, AuditAction, AuditService
from app.services.candidate_profile import CandidateService
from app.services.companies import CompanyService
from app.services.job_sources import JobSourceService
from app.services.jobs import JobService, UpsertOutcome, UpsertResult
from app.services.runs import RunRecorder

logger = get_logger(__name__)

MOCK_FIXTURES = ("fixtures", "mock_jobs")
TOTAL_KEYS: tuple[str, ...] = (
    "fetched",
    "filtered_out",
    "new",
    "updated",
    "duplicates",
    "in_window",
    "out_of_window",
    "unknown_date",
    "outside_target_countries",
    "queued",
    "errors",
)
_WINDOW_KEYS = {
    WindowStatus.IN_WINDOW: "in_window",
    WindowStatus.OUT_OF_WINDOW: "out_of_window",
    WindowStatus.UNKNOWN_DATE: "unknown_date",
}
_OUTCOME_KEYS = {
    UpsertOutcome.NEW: "new",
    UpsertOutcome.UPDATED: "updated",
    UpsertOutcome.DUPLICATE: "duplicates",
}


def _zero() -> dict[str, int]:
    return dict.fromkeys(TOTAL_KEYS, 0)


@dataclass(frozen=True)
class _Targets:
    """What the candidate is looking for (no candidate: jobs are stored but not queued)."""

    candidate: Candidate | None
    roles: tuple[str, ...] = ()
    countries: frozenset[str] = frozenset()

    def accepts_country(self, job: Job) -> bool:
        if not self.countries or job.country_code is None:
            return True  # no preference, or not stated: the analysis (Phase 4) decides
        return job.country_code in self.countries or job.remote_status is RemoteStatus.REMOTE


@dataclass
class _SourceRun:
    key: str
    priority: int
    counts: dict[str, int] = field(default_factory=_zero)
    processed: int = 0
    failed: str | None = None


class DiscoveryService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._clock = clock or utcnow

    def execute(self, run_id: uuid.UUID, *, task_id: str | None = None) -> dict[str, Any]:
        now = self._clock()
        window = PostingWindow.lookback(now, hours=self._settings.job_lookback_hours)
        crawler_dir = self._settings.crawler_dir
        totals = _zero()
        processed = 0
        with RunRecorder(self._session_factory, run_id, task_id=task_id) as recorder:
            self._audit(AuditAction.RUN_STARTED, run_id, {"task_id": task_id})

            config = load_sources_config(crawler_dir)
            registry = SourceRegistry(
                config,
                mock_mode=self._settings.mock_mode,
                fixtures_dir=crawler_dir.joinpath(*MOCK_FIXTURES),
            )
            with session_scope(self._session_factory) as session:
                JobSourceService(session).sync(config)
                companies = CompanyService(session).watchlist_targets()
                company_roles = {
                    company.id: tuple(company.target_roles)
                    for company in session.scalars(select(Company).where(Company.enabled))
                }
                targets = self._targets(session, recorder)

            runnable = registry.runnable()
            skipped = dict(registry.skipped())
            recorder.event(
                "discovery.config",
                f"Searching {len(runnable)} source(s) for jobs posted in the last "
                f"{self._settings.job_lookback_hours} hours",
                data={
                    "mock_mode": self._settings.mock_mode,
                    "window": self._window_data(window),
                    "sources": [source.key for source in runnable],
                    "skipped_sources": skipped,
                    "watchlist_companies": len(companies),
                },
            )
            if not runnable:
                mode = "MOCK_MODE=true" if self._settings.mock_mode else "live mode"
                recorder.event(
                    "discovery.config",
                    f"No discovery source can run in {mode}: see the skip reason of each source "
                    "on the Jobs page (real sources arrive in Phase 10).",
                    level=EventLevel.WARNING,
                    data={"skipped_sources": skipped},
                )
            if not companies and any(isinstance(source, CompanyBoardSource) for source in runnable):
                recorder.event(
                    "discovery.watchlist",
                    "The company watchlist is empty: no ATS board was searched. Add companies "
                    "(or import companies.yaml) on the Companies page.",
                    level=EventLevel.WARNING,
                )

            query = JobQuery(
                posted_after=window.posted_after,
                posted_before=window.posted_before,
                now=now,
                keywords=targets.roles,
                countries=tuple(sorted(targets.countries)),
                companies=tuple(companies),
            )
            checked: set[uuid.UUID] = set()
            runs: list[_SourceRun] = []
            for source in runnable:
                state = _SourceRun(
                    key=source.key, priority=registry.source_config(source.key).priority
                )
                runs.append(state)
                self._run_source(
                    source,
                    state,
                    query=query,
                    window=window,
                    targets=targets,
                    company_roles=company_roles,
                    checked=checked,
                    recorder=recorder,
                    run_id=run_id,
                )
                for key in TOTAL_KEYS:
                    totals[key] += state.counts[key]
                processed += state.processed

            unchecked = [company.name for company in companies if company.id not in checked]
            if unchecked and runnable:
                recorder.event(
                    "discovery.watchlist",
                    f"{len(unchecked)} watchlist compan{'y' if len(unchecked) == 1 else 'ies'} "
                    "could not be checked by any runnable source",
                    data={"companies": unchecked[:50]},
                )

            summary: dict[str, Any] = {
                "window": self._window_data(window),
                "mock_mode": self._settings.mock_mode,
                "totals": totals,
                "sources": {
                    state.key: {
                        **state.counts,
                        "status": self._source_status(state),
                    }
                    for state in runs
                },
                "skipped_sources": skipped,
                "companies_checked": len(checked),
                "candidate_queueing": targets.candidate is not None,
            }
            recorder.event(
                "discovery.summary",
                f"{totals['new']} new job(s), {totals['in_window']} posted in the window, "
                f"{totals['queued']} queued for analysis",
                data=totals,
            )
            recorder.increment(jobs_discovered=totals["new"], jobs_processed=processed)
            if runs and all(state.failed for state in runs):
                status = RunStatus.FAILED
            elif totals["errors"]:
                status = RunStatus.PARTIAL_SUCCESS
            else:
                status = RunStatus.SUCCEEDED
            recorder.finish(status, summary=summary)

        self._audit(AuditAction.RUN_FINISHED, run_id, {"status": status.value, "totals": totals})
        logger.info("discovery.completed", run_id=str(run_id), status=status.value, **totals)
        return {
            "run_id": str(run_id),
            "status": status.value,
            "jobs_discovered": totals["new"],
            "jobs_processed": processed,
            "totals": totals,
        }

    # --- one source --------------------------------------------------------------------------
    def _run_source(
        self,
        source: JobSource,
        state: _SourceRun,
        *,
        query: JobQuery,
        window: PostingWindow,
        targets: _Targets,
        company_roles: Mapping[uuid.UUID, tuple[str, ...]],
        checked: set[uuid.UUID],
        recorder: RunRecorder,
        run_id: uuid.UUID,
    ) -> None:
        stage = f"discovery.source.{source.key}"
        counts = state.counts
        limit = self._settings.discovery_max_jobs_per_source
        with session_scope(self._session_factory) as session:
            companies = CompanyService(session)
            raws: list[RawJob] = []
            try:
                if isinstance(source, CompanyBoardSource):
                    for company in query.companies:
                        found = self._search_company(
                            source, company, query, stage, counts, companies, recorder
                        )
                        if found is not None:
                            checked.add(company.id)
                            raws.extend(found)
                else:
                    raws = list(islice(source.search(query), limit + 1))
            except Exception as exc:  # the source failed as a whole: record it and move on
                counts["errors"] += 1
                state.failed = str(exc) or type(exc).__name__
                recorder.error(stage, exc)
            if len(raws) > limit:
                recorder.event(
                    stage,
                    f"{source.key}: more than {limit} postings; only the first {limit} were "
                    "read (DISCOVERY_MAX_JOBS_PER_SOURCE)",
                    level=EventLevel.WARNING,
                )
                raws = raws[:limit]

            jobs = JobService(session)
            applications = ApplicationService(session)
            for raw in raws:
                counts["fetched"] += 1
                try:
                    posting = source.normalize(raw)
                except Exception as exc:
                    counts["errors"] += 1
                    recorder.error(
                        stage, exc, data={"source_job_id": raw.source_job_id, "step": "normalize"}
                    )
                    continue
                state.processed += 1
                extra_roles = company_roles.get(raw.company_id, ()) if raw.company_id else ()
                roles = (*targets.roles, *extra_roles)
                if not title_matches(posting.title, roles):
                    counts["filtered_out"] += 1
                    continue
                try:
                    with session.begin_nested():
                        result = jobs.upsert(
                            posting, priority=state.priority, now=query.now, run_id=run_id
                        )
                        self._classify_and_queue(
                            result, counts, window, targets, applications, run_id
                        )
                except Exception as exc:
                    counts["errors"] += 1
                    recorder.error(
                        stage, exc, data={"source_job_id": raw.source_job_id, "step": "store"}
                    )

            JobSourceService(session).record_run(
                source.key,
                at=query.now,
                status=self._source_status(state),
                counts=counts,
                error=state.failed,
            )

        recorder.event(
            stage,
            f"{source.key}: {counts['fetched']} fetched, {counts['new']} new, "
            f"{counts['updated']} updated, {counts['duplicates']} duplicate(s), "
            f"{counts['filtered_out']} filtered out, {counts['queued']} queued",
            level=EventLevel.WARNING if counts["errors"] and not state.failed else EventLevel.INFO,
            data=counts,
        )

    def _search_company(
        self,
        source: CompanyBoardSource,
        company: CompanyTarget,
        query: JobQuery,
        stage: str,
        counts: dict[str, int],
        companies: CompanyService,
        recorder: RunRecorder,
    ) -> list[RawJob] | None:
        """One watchlist board; None when this source does not serve the company."""
        if not source.supports(company):
            return None
        try:
            found = source.search_company(company, query)
        except Exception as exc:
            counts["errors"] += 1
            companies.record_check(company.id, at=query.now, status=f"error: {exc}")
            recorder.error(stage, exc, data={"company": company.name})
            return []
        noun = "posting" if len(found) == 1 else "postings"
        companies.record_check(company.id, at=query.now, status=f"ok: {len(found)} {noun}")
        return found

    @staticmethod
    def _classify_and_queue(
        result: UpsertResult,
        counts: dict[str, int],
        window: PostingWindow,
        targets: _Targets,
        applications: ApplicationService,
        run_id: uuid.UUID,
    ) -> None:
        counts[_OUTCOME_KEYS[result.outcome]] += 1
        if not result.is_primary:
            return  # a duplicate listing: its primary record was classified already
        job = result.job
        status = window.classify(job.posted_at, job.posting_date_status)
        counts[_WINDOW_KEYS[status]] += 1
        if status is not WindowStatus.IN_WINDOW or targets.candidate is None:
            return  # unknown dates are queued manually ("Track"), never automatically
        if not targets.accepts_country(job):
            counts["outside_target_countries"] += 1
            return
        _, created = applications.create_discovered(targets.candidate, job, run_id=run_id)
        if created:
            counts["queued"] += 1

    # --- helpers -----------------------------------------------------------------------------
    def _targets(self, session: Session, recorder: RunRecorder) -> _Targets:
        service = CandidateService(session, candidate_dir=self._settings.candidate_dir)
        try:
            candidate, created = service.get_or_import_default()
        except AppError as exc:
            recorder.event(
                "discovery.candidate",
                f"No candidate profile ({exc.message}): jobs are stored but not queued.",
                level=EventLevel.WARNING,
            )
            return _Targets(candidate=None)
        if created:
            AuditService(session).record(
                action=AuditAction.CANDIDATE_IMPORTED,
                actor=Actor.WORKER,
                entity_type="candidate",
                entity_id=str(candidate.id),
                details={"source": "yaml", "reason": "discovery", "profile_version": 1},
            )
        profile = service.profile_of(candidate)
        countries = profile.targets.countries
        return _Targets(
            candidate=candidate,
            roles=tuple(profile.targets.roles),
            countries=frozenset(c.code for c in (*countries.primary, *countries.secondary)),
        )

    @staticmethod
    def _source_status(state: _SourceRun) -> str:
        if state.failed:
            return "error"
        return "partial" if state.counts["errors"] else "ok"

    @staticmethod
    def _window_data(window: PostingWindow) -> dict[str, Any]:
        hours = round((window.posted_before - window.posted_after).total_seconds() / 3600)
        return {
            "lookback_hours": hours,
            "posted_after": window.posted_after.isoformat(),
            "posted_before": window.posted_before.isoformat(),
        }

    def _audit(self, action: AuditAction, run_id: uuid.UUID, details: dict[str, Any]) -> None:
        with session_scope(self._session_factory) as session:
            AuditService(session).record(
                action=action,
                actor=Actor.WORKER,
                entity_type="automation_run",
                entity_id=str(run_id),
                details=details,
            )
