"""Source abstraction: queries, raw postings, the normalized job (spec §7) and the protocols."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.jobs.countries import COUNTRY_NAMES, country_code, country_from_location
from app.jobs.hashing import content_hash
from app.jobs.normalize import (
    clean_text,
    detect_remote_status,
    html_to_text,
    infer_seniority,
    parse_employment_type,
)
from app.jobs.posting_dates import resolve_posting_date
from app.jobs.types import (
    AtsType,
    EmploymentType,
    PostingDateStatus,
    RemoteStatus,
    Seniority,
)
from app.jobs.urls import ats_type_from_url, canonical_url

MAX_TITLE_CHARS = 300
MAX_DESCRIPTION_CHARS = 100_000


class SourceKind(StrEnum):
    ATS_API = "ATS_API"
    CAREER_PAGE = "CAREER_PAGE"
    FEED = "FEED"
    MANUAL = "MANUAL"


class SourcePolicy(StrEnum):
    API_ONLY = "api_only"
    ALLOWED = "allowed"
    MANUAL_ONLY = "manual_only"
    DISABLED = "disabled"


@dataclass(frozen=True)
class CompanyTarget:
    """A watchlist company as seen by a source (its board token identifies it in its ATS)."""

    id: uuid.UUID
    name: str
    ats_type: str
    board_token: str | None
    career_url: str | None


@dataclass(frozen=True)
class JobQuery:
    posted_after: datetime
    posted_before: datetime
    now: datetime
    keywords: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    companies: tuple[CompanyTarget, ...] = ()


@dataclass(frozen=True)
class RawJob:
    source: str
    source_job_id: str | None
    payload: Mapping[str, Any]
    fetched_at: datetime
    company_id: uuid.UUID | None = None
    url: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceHealth:
    ok: bool
    detail: str


class NormalizedJob(BaseModel):
    """A posting in the spec §7 shape, ready for deduplication and storage."""

    source: str
    source_job_id: str | None = None
    company: str
    company_id: uuid.UUID | None = None
    title: str
    description: str = ""
    location: str | None = None
    country: str | None = None
    country_code: str | None = None
    remote_status: RemoteStatus = RemoteStatus.UNKNOWN
    employment_type: EmploymentType = EmploymentType.UNKNOWN
    seniority: Seniority = Seniority.UNKNOWN
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    posted_at: datetime | None = None
    posting_date_status: PostingDateStatus = PostingDateStatus.UNKNOWN
    posting_date_basis: str | None = None
    application_url: str | None = None
    canonical_url: str | None = None
    company_url: str | None = None
    ats_type: AtsType = AtsType.OTHER
    visa_information: str | None = None
    relocation_information: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    education_requirements: str | None = None
    experience_requirements: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    raw_content: dict[str, Any] = Field(default_factory=dict)
    content_hash: str

    @property
    def has_content(self) -> bool:
        """Only postings with a description are matched by content hash (imports of a bare URL
        share placeholder fields and must not be mistaken for each other)."""
        return bool(self.description.strip())


@runtime_checkable
class JobSource(Protocol):
    key: str
    kind: SourceKind

    def search(self, query: JobQuery) -> Iterable[RawJob]: ...

    def get_job(self, source_job_id: str) -> RawJob | None: ...

    def normalize(self, raw: RawJob) -> NormalizedJob: ...

    def health_check(self) -> SourceHealth: ...


@runtime_checkable
class CompanyBoardSource(JobSource, Protocol):
    """A source that lists one company's board at a time (Greenhouse, Lever, Ashby…)."""

    def supports(self, company: CompanyTarget) -> bool: ...

    def search_company(self, company: CompanyTarget, query: JobQuery) -> list[RawJob]: ...


def _texts(values: Iterable[Any] | None) -> list[str]:
    return [clean_text(str(value)) for value in values or () if clean_text(str(value))]


def build_job(
    *,
    source: str,
    title: str,
    company: str,
    fetched_at: datetime,
    source_job_id: str | None = None,
    company_id: uuid.UUID | None = None,
    description: str | None = None,
    description_html: str | None = None,
    location: str | None = None,
    country: str | None = None,
    workplace: str | None = None,
    employment_type: str | None = None,
    posted_at: datetime | str | None = None,
    posted_text: str | None = None,
    application_url: str | None = None,
    company_url: str | None = None,
    ats_type: AtsType | str | None = None,
    salary_min: int | None = None,
    salary_max: int | None = None,
    salary_currency: str | None = None,
    salary_period: str | None = None,
    visa_information: str | None = None,
    relocation_information: str | None = None,
    required_skills: Sequence[str] = (),
    preferred_skills: Sequence[str] = (),
    languages: Sequence[str] = (),
    education_requirements: str | None = None,
    experience_requirements: str | None = None,
    responsibilities: Sequence[str] = (),
    raw_content: Mapping[str, Any] | None = None,
) -> NormalizedJob:
    """Normalize what a source provides into a ``NormalizedJob`` (shared by every source)."""
    text = html_to_text(description_html) if description_html else clean_text(description)
    clean_title = clean_text(title)[:MAX_TITLE_CHARS]
    clean_company = clean_text(company)[:MAX_TITLE_CHARS]
    clean_location = clean_text(location) or None
    code = country_code(country) if country else country_from_location(clean_location)
    posting = resolve_posting_date(now=fetched_at, posted_at=posted_at, posted_text=posted_text)
    url = application_url.strip() if application_url else None
    resolved_ats = (
        AtsType(ats_type) if ats_type else (ats_type_from_url(url) if url else AtsType.OTHER)
    )
    currency = salary_currency.strip().upper() if salary_currency else None
    return NormalizedJob(
        source=source,
        source_job_id=source_job_id,
        company=clean_company,
        company_id=company_id,
        title=clean_title,
        description=text[:MAX_DESCRIPTION_CHARS],
        location=clean_location,
        country=COUNTRY_NAMES.get(code) if code else (clean_text(country) or None),
        country_code=code,
        remote_status=detect_remote_status(workplace, clean_location, clean_title),
        employment_type=parse_employment_type(employment_type),
        seniority=infer_seniority(clean_title),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        salary_period=salary_period,
        posted_at=posting.posted_at,
        posting_date_status=posting.status,
        posting_date_basis=posting.basis,
        application_url=url,
        canonical_url=canonical_url(url) if url else None,
        company_url=company_url,
        ats_type=resolved_ats,
        visa_information=clean_text(visa_information) or None,
        relocation_information=clean_text(relocation_information) or None,
        required_skills=_texts(required_skills),
        preferred_skills=_texts(preferred_skills),
        languages=_texts(languages),
        education_requirements=clean_text(education_requirements) or None,
        experience_requirements=clean_text(experience_requirements) or None,
        responsibilities=_texts(responsibilities),
        raw_content=dict(raw_content or {}),
        content_hash=content_hash(
            company=clean_company, title=clean_title, location=clean_location, description=text
        ),
    )
