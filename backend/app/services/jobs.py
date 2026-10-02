"""Jobs: storage with deduplication (upsert), listing with posting-window filters, statistics.

Deduplication rules (ADR-031):

* the same ``(source, source_job_id)`` — or, for postings without a source id (imports), the
  same source and canonical URL — is the same posting: it is updated (``UPDATED``);
* another posting with the same canonical URL, or the same content hash when it has a
  description, is a cross-source duplicate: it is stored with ``duplicate_of_id`` pointing to
  the group's primary record (``DUPLICATE``);
* the primary record is the one from the highest-priority source (ATS API > career page >
  feed > manual import). When a higher-priority record arrives it takes over: the previous
  primary, its duplicates and its applications are re-pointed to it (``swapped``).
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, TypeVar

from sqlalchemy import Select, and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.analysis.types import Recommendation, VisaStatus
from app.core.errors import NotFoundError
from app.crawlers.base import NormalizedJob
from app.cv.evidence import canonical_key
from app.jobs.hashing import content_hash
from app.jobs.types import (
    EmploymentType,
    PostingDateStatus,
    RemoteStatus,
    Seniority,
    SkillImportance,
    WindowStatus,
)
from app.jobs.window import PostingWindow
from app.models import (
    DEFAULT_CANDIDATE_SLUG,
    Application,
    AutomationRun,
    Candidate,
    Company,
    Job,
    JobAnalysis,
    JobSkill,
    JobSource,
    RunType,
)
from app.services.companies import normalize_company_name

_QueryT = TypeVar("_QueryT", bound=Select[*tuple[Any, ...]])

# Fields copied from a normalized posting to its stored record (dates are merged separately).
_FIELDS: tuple[str, ...] = (
    "company",
    "title",
    "description",
    "location",
    "country",
    "country_code",
    "remote_status",
    "employment_type",
    "seniority",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "application_url",
    "canonical_url",
    "company_url",
    "ats_type",
    "visa_information",
    "relocation_information",
    "required_skills",
    "preferred_skills",
    "languages",
    "education_requirements",
    "experience_requirements",
    "responsibilities",
    "raw_content",
)
_UNKNOWN_VALUES = (RemoteStatus.UNKNOWN, EmploymentType.UNKNOWN, Seniority.UNKNOWN)

WindowFilter = Literal["in_window", "out_of_window", "all"]


class UpsertOutcome(StrEnum):
    NEW = "NEW"  # a job not seen before (a new primary record)
    UPDATED = "UPDATED"  # the same posting seen again
    DUPLICATE = "DUPLICATE"  # another listing of a known job


@dataclass(frozen=True)
class UpsertResult:
    outcome: UpsertOutcome
    job: Job  # the stored record of this posting
    primary: Job  # the primary record of its group (``job`` itself unless it is a duplicate)
    swapped: bool = False  # this posting took over as the group's primary record

    @property
    def is_primary(self) -> bool:
        return self.job.id == self.primary.id


@dataclass(frozen=True)
class JobFilters:
    window: WindowFilter = "in_window"
    date_status: PostingDateStatus | None = None
    source: str | None = None
    country: str | None = None
    q: str | None = None
    company_id: uuid.UUID | None = None
    include_duplicates: bool = False
    recommendation: Recommendation | None = None
    visa_status: VisaStatus | None = None


@dataclass(frozen=True)
class PipelineInfo:
    """The default candidate's application for a job."""

    status: str
    recommendation: str | None
    visa_status: str | None


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {} or value in _UNKNOWN_VALUES


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class JobService:
    """Methods flush but never commit: the caller owns the transaction.

    ``hidden_sources`` (the mock sources outside MOCK_MODE) are excluded from every query.
    """

    def __init__(self, session: Session, *, hidden_sources: Collection[str] = ()) -> None:
        self._session = session
        self._hidden = tuple(hidden_sources)
        self._priorities: dict[str, int] | None = None

    # ==========================================================================================
    # Storage and deduplication
    # ==========================================================================================
    def upsert(
        self,
        posting: NormalizedJob,
        *,
        priority: int,
        now: datetime,
        run_id: uuid.UUID | None = None,
        merge: bool = False,
    ) -> UpsertResult:
        """Store ``posting``. ``merge`` keeps stored values the posting leaves empty (imports
        that only carry a URL must not erase what an earlier import provided)."""
        existing = self._same_posting(posting)
        if existing is not None:
            self._apply(existing, posting, merge=merge)
            existing.last_seen_at = now
            self._session.flush()
            return UpsertResult(UpsertOutcome.UPDATED, existing, self._primary_of(existing))

        matches = self._matches(posting)
        job = Job(
            source=posting.source,
            source_job_id=posting.source_job_id,
            discovered_at=now,
            last_seen_at=now,
            discovery_run_id=run_id,
        )
        self._apply(job, posting, merge=False)
        self._session.add(job)
        self._session.flush()
        self._replace_skills(job, posting)
        if not matches:
            return UpsertResult(UpsertOutcome.NEW, job, job)

        primary = max(
            {match.id: match for match in (self._primary_of(m) for m in matches)}.values(),
            key=lambda candidate: (
                self._priority(candidate.source),
                -candidate.discovered_at.timestamp(),
            ),
        )
        if priority > self._priority(primary.source):
            self._take_over(job, previous=primary)
            return UpsertResult(UpsertOutcome.DUPLICATE, job, job, swapped=True)
        job.duplicate_of_id = primary.id
        self._session.flush()
        return UpsertResult(UpsertOutcome.DUPLICATE, job, primary)

    def _priority(self, source: str) -> int:
        if self._priorities is None:
            self._priorities = dict(
                self._session.execute(select(JobSource.key, JobSource.priority)).all()
            )
        return self._priorities.get(source, 0)

    def _primary_of(self, job: Job) -> Job:
        if job.duplicate_of_id is None:
            return job
        primary = self._session.get(Job, job.duplicate_of_id)
        return primary if primary is not None else job

    def _same_posting(self, posting: NormalizedJob) -> Job | None:
        query = select(Job).where(Job.source == posting.source)
        if posting.source_job_id is not None:
            return self._session.scalar(query.where(Job.source_job_id == posting.source_job_id))
        if posting.canonical_url is None:
            return None
        return self._session.scalar(
            query.where(Job.canonical_url == posting.canonical_url)
            .order_by(Job.discovered_at)
            .limit(1)
        )

    def _matches(self, posting: NormalizedJob) -> list[Job]:
        conditions = []
        if posting.canonical_url:
            conditions.append(Job.canonical_url == posting.canonical_url)
        if posting.has_content:
            conditions.append(Job.content_hash == posting.content_hash)
        if not conditions:
            return []
        return list(
            self._session.scalars(select(Job).where(or_(*conditions)).order_by(Job.discovered_at))
        )

    def _take_over(self, job: Job, *, previous: Job) -> None:
        """Make ``job`` the primary record of ``previous``'s group."""
        job.duplicate_of_id = None
        job.discovered_at = min(job.discovered_at, previous.discovered_at)
        job.company_id = job.company_id or previous.company_id
        self._session.execute(
            update(Job)
            .where(or_(Job.id == previous.id, Job.duplicate_of_id == previous.id))
            .values(duplicate_of_id=job.id)
            .execution_options(synchronize_session="fetch")
        )
        taken = set(
            self._session.scalars(
                select(Application.candidate_id).where(Application.job_id == job.id)
            )
        )
        for application in self._session.scalars(
            select(Application).where(Application.job_id == previous.id)
        ):
            if application.candidate_id not in taken:
                application.job_id = job.id
        self._session.flush()

    def _apply(self, job: Job, posting: NormalizedJob, *, merge: bool) -> None:
        for name in _FIELDS:
            value = getattr(posting, name)
            if merge and _is_empty(value):
                continue
            setattr(job, name, list(value) if isinstance(value, list) else value)
        self._merge_posting_date(job, posting)
        job.content_hash = content_hash(
            company=job.company,
            title=job.title,
            location=job.location,
            description=job.description,
        )
        job.company_id = posting.company_id or self._company_id_for(job.company) or job.company_id
        if job.id is not None and not (
            merge and not posting.required_skills and not posting.preferred_skills
        ):
            self._replace_skills(job, posting)

    @staticmethod
    def _merge_posting_date(job: Job, posting: NormalizedJob) -> None:
        """A source timestamp replaces an estimate; an estimate never replaces a source
        timestamp; between two estimates the older (more conservative) one is kept."""
        new_status = posting.posting_date_status
        current: PostingDateStatus | None = job.posting_date_status
        if current is None or new_status is PostingDateStatus.KNOWN:
            replace = True
        elif new_status is PostingDateStatus.ESTIMATED:
            replace = current is PostingDateStatus.UNKNOWN or (
                current is PostingDateStatus.ESTIMATED
                and job.posted_at is not None
                and posting.posted_at is not None
                and posting.posted_at < job.posted_at
            )
        else:
            replace = False
        if replace:
            job.posted_at = posting.posted_at
            job.posting_date_status = new_status
            job.posting_date_basis = posting.posting_date_basis

    def _company_id_for(self, name: str) -> uuid.UUID | None:
        if not name:
            return None
        return self._session.scalar(
            select(Company.id).where(Company.normalized_name == normalize_company_name(name))
        )

    def _replace_skills(self, job: Job, posting: NormalizedJob) -> None:
        self._session.execute(delete(JobSkill).where(JobSkill.job_id == job.id))
        seen: set[str] = set()
        for importance, names in (
            (SkillImportance.REQUIRED, posting.required_skills),
            (SkillImportance.PREFERRED, posting.preferred_skills),
        ):
            for name in names:
                key = canonical_key(name)[:200]
                if not key or key in seen:
                    continue
                seen.add(key)
                self._session.add(
                    JobSkill(
                        job_id=job.id,
                        name=name[:200],
                        normalized_name=key,
                        importance=importance,
                    )
                )
        self._session.flush()

    # ==========================================================================================
    # Queries
    # ==========================================================================================
    def get(self, job_id: uuid.UUID) -> Job:
        job = self._session.get(Job, job_id)
        if job is None or job.source in self._hidden:
            raise NotFoundError(f"Job {job_id} not found")
        return job

    def _visible(self, query: _QueryT) -> _QueryT:
        return query.where(Job.source.not_in(self._hidden)) if self._hidden else query

    @staticmethod
    def _window_condition(window: PostingWindow, wanted: WindowFilter) -> Any:
        dated = and_(
            Job.posting_date_status != PostingDateStatus.UNKNOWN, Job.posted_at.is_not(None)
        )
        inside = and_(
            dated, Job.posted_at >= window.posted_after, Job.posted_at <= window.posted_before
        )
        if wanted == "in_window":
            return inside
        if wanted == "out_of_window":
            return and_(dated, ~inside)
        return None

    def list_jobs(
        self, filters: JobFilters, *, window: PostingWindow, limit: int, offset: int
    ) -> tuple[list[Job], int]:
        query = self._visible(select(Job))
        condition = self._window_condition(window, filters.window)
        if condition is not None:
            query = query.where(condition)
        if not filters.include_duplicates:
            query = query.where(Job.duplicate_of_id.is_(None))
        if filters.date_status is not None:
            query = query.where(Job.posting_date_status == filters.date_status)
        if filters.source:
            query = query.where(Job.source == filters.source)
        if filters.country:
            query = query.where(Job.country_code == filters.country.upper())
        if filters.company_id is not None:
            query = query.where(Job.company_id == filters.company_id)
        if filters.recommendation is not None or filters.visa_status is not None:
            query = query.join(Application, Application.job_id == Job.id).join(
                Candidate, Candidate.id == Application.candidate_id
            )
            query = query.where(Candidate.slug == DEFAULT_CANDIDATE_SLUG)
            if filters.recommendation is not None:
                query = query.where(Application.recommendation == filters.recommendation)
            if filters.visa_status is not None:
                query = query.where(Application.visa_status == filters.visa_status.value)
        if filters.q and filters.q.strip():
            pattern = f"%{_escape_like(filters.q.strip())}%"
            query = query.where(
                or_(
                    Job.title.ilike(pattern, escape="\\"),
                    Job.company.ilike(pattern, escape="\\"),
                    Job.location.ilike(pattern, escape="\\"),
                )
            )
        total = self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        items = self._session.scalars(
            query.order_by(Job.posted_at.desc().nulls_last(), Job.discovered_at.desc(), Job.id)
            .limit(limit)
            .offset(offset)
        ).all()
        return list(items), total

    def duplicates_of(self, job: Job) -> list[Job]:
        return list(
            self._session.scalars(
                self._visible(select(Job))
                .where(Job.duplicate_of_id == job.id)
                .order_by(Job.discovered_at)
            )
        )

    def duplicate_counts(self, job_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, int]:
        ids = list(job_ids)
        if not ids:
            return {}
        rows = self._session.execute(
            select(Job.duplicate_of_id, func.count())
            .where(Job.duplicate_of_id.in_(ids))
            .group_by(Job.duplicate_of_id)
        )
        return {job_id: count for job_id, count in rows if job_id is not None}

    def pipeline_statuses(self, job_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, PipelineInfo]:
        """Application status and analysis decision of the default candidate for each job."""
        ids = list(job_ids)
        if not ids:
            return {}
        rows = self._session.execute(
            select(
                Application.job_id,
                Application.status,
                Application.recommendation,
                Application.visa_status,
            )
            .join(Candidate, Candidate.id == Application.candidate_id)
            .where(Application.job_id.in_(ids), Candidate.slug == DEFAULT_CANDIDATE_SLUG)
        )
        return {
            job_id: PipelineInfo(
                status=status.value,
                recommendation=recommendation.value if recommendation else None,
                visa_status=visa_status,
            )
            for job_id, status, recommendation, visa_status in rows
        }

    def latest_analysis(self, job: Job) -> JobAnalysis | None:
        """The default candidate's most recent analysis of ``job``."""
        return self._session.scalar(
            select(JobAnalysis)
            .join(Candidate, Candidate.id == JobAnalysis.candidate_id)
            .where(JobAnalysis.job_id == job.id, Candidate.slug == DEFAULT_CANDIDATE_SLUG)
            .order_by(JobAnalysis.created_at.desc())
            .limit(1)
        )

    def stats(self, *, window: PostingWindow, today_start: datetime) -> dict[str, Any]:
        primary = self._visible(select(Job)).where(Job.duplicate_of_id.is_(None)).subquery()

        def count(*conditions: Any) -> int:
            query = select(func.count()).select_from(primary)
            for condition in conditions:
                query = query.where(condition)
            return self._session.scalar(query) or 0

        inside = and_(
            primary.c.posting_date_status != PostingDateStatus.UNKNOWN,
            primary.c.posted_at >= window.posted_after,
            primary.c.posted_at <= window.posted_before,
        )
        duplicates = self._session.scalar(
            self._visible(select(func.count()).select_from(Job)).where(
                Job.duplicate_of_id.is_not(None)
            )
        )
        by_source: dict[str, int] = dict(
            self._session.execute(
                select(primary.c.source, func.count())
                .select_from(primary)
                .group_by(primary.c.source)
                .order_by(primary.c.source)
            ).all()
        )
        last_run = self._last_run(RunType.DISCOVERY)
        decisions = self._visible(
            select(Application.recommendation, func.count())
            .join(Job, Job.id == Application.job_id)
            .join(Candidate, Candidate.id == Application.candidate_id)
        ).where(Candidate.slug == DEFAULT_CANDIDATE_SLUG, Application.recommendation.is_not(None))
        by_recommendation = {
            recommendation.value: count
            for recommendation, count in self._session.execute(
                decisions.group_by(Application.recommendation)
            )
            if recommendation is not None
        }
        return {
            "total": count(),
            "found_today": count(primary.c.discovered_at >= today_start),
            "in_window": count(inside),
            "unknown_date": count(primary.c.posting_date_status == PostingDateStatus.UNKNOWN),
            "duplicates": duplicates or 0,
            "by_source": by_source,
            "last_discovery": last_run,
            "analysed": sum(by_recommendation.values()),
            "qualified": by_recommendation.get("APPLY", 0) + by_recommendation.get("REVIEW", 0),
            "by_recommendation": {
                key: by_recommendation.get(key, 0) for key in ("APPLY", "REVIEW", "SKIP")
            },
            "last_analysis": self._last_run(RunType.ANALYSIS),
        }

    def _last_run(self, run_type: RunType) -> AutomationRun | None:
        return self._session.scalar(
            select(AutomationRun)
            .where(AutomationRun.run_type == run_type)
            .order_by(AutomationRun.created_at.desc())
            .limit(1)
        )

    @staticmethod
    def window_status(job: Job, window: PostingWindow) -> WindowStatus:
        return window.classify(job.posted_at, job.posting_date_status)
