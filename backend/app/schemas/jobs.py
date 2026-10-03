"""Jobs API: list items, detail, statistics, imports and job sources."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.analysis.schemas import RelevanceResult, VisaResult
from app.analysis.types import AnalysisStatus, Recommendation, VisaStatus
from app.applications.lifecycle import ApplicationStatus
from app.crawlers.base import SourceKind, SourcePolicy
from app.jobs.types import (
    AtsType,
    EmploymentType,
    PostingDateStatus,
    RemoteStatus,
    Seniority,
    WindowStatus,
)
from app.models import RunStatus

MAX_EMAIL_CHARS = 1_000_000


class WindowRead(BaseModel):
    lookback_hours: int
    posted_after: datetime
    posted_before: datetime


class JobRead(BaseModel):
    # Defaults are always serialized: generated TypeScript types mark these fields required.
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: uuid.UUID
    source: str
    source_job_id: str | None
    company: str
    company_id: uuid.UUID | None
    title: str
    location: str | None
    country: str | None
    country_code: str | None
    remote_status: RemoteStatus
    employment_type: EmploymentType
    seniority: Seniority
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    salary_period: str | None
    posted_at: datetime | None
    posting_date_status: PostingDateStatus
    posting_date_basis: str | None
    window_status: WindowStatus
    discovered_at: datetime
    last_seen_at: datetime
    application_url: str | None
    canonical_url: str | None
    ats_type: AtsType
    duplicate_of_id: uuid.UUID | None
    duplicate_count: int = 0
    application_status: ApplicationStatus | None = Field(
        default=None, description="Pipeline status for the candidate, when the job is queued"
    )
    recommendation: Recommendation | None = Field(
        default=None, description="Decision of the latest analysis (APPLY / REVIEW / SKIP)"
    )
    visa_status: VisaStatus | None = Field(
        default=None, description="Visa sponsorship status from the latest analysis"
    )


class JobPage(BaseModel):
    items: list[JobRead]
    total: int
    limit: int
    offset: int
    window: WindowRead


class JobListing(BaseModel):
    """Another listing of the same job (a duplicate record from another source)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    title: str
    company: str
    application_url: str | None
    posting_date_status: PostingDateStatus
    posted_at: datetime | None
    discovered_at: datetime


class JobApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    status: ApplicationStatus
    created_at: datetime
    updated_at: datetime


class JobSkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    importance: str


class JobDetail(JobRead):
    description: str
    company_url: str | None
    visa_information: str | None
    relocation_information: str | None
    required_skills: list[str]
    preferred_skills: list[str]
    languages: list[str]
    education_requirements: str | None
    experience_requirements: str | None
    responsibilities: list[str]
    raw_content: dict[str, Any]
    discovery_run_id: uuid.UUID | None
    primary: JobListing | None = Field(
        default=None, description="The primary record, when this listing is a duplicate"
    )
    duplicates: list[JobListing] = Field(default_factory=list)
    applications: list[JobApplicationRead] = Field(default_factory=list)
    analysis: JobAnalysisRead | None = Field(
        default=None, description="The latest analysis of this job for the candidate"
    )


class PromptInfo(BaseModel):
    name: str
    version: int


class AnalysisUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int


class JobAnalysisRead(BaseModel):
    """One analysis: provenance, cost, the verified result and the decision with its reasons."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: uuid.UUID
    created_at: datetime
    status: AnalysisStatus
    run_id: uuid.UUID | None
    provider: str
    is_mock: bool = Field(description="Produced offline by the mock provider, not by a model")
    requested_model: str
    served_model: str | None
    fallback_used: bool
    prompt: PromptInfo
    usage: AnalysisUsage
    duration_ms: int | None
    recommendation: Recommendation | None
    llm_recommendation: Recommendation | None = Field(
        description="What the model suggested (the decision comes from the explicit rules)"
    )
    rule_reasons: list[str]
    visa: VisaResult | None
    relevance: RelevanceResult | None
    error_code: str | None
    error_message: str | None


class LastRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: RunStatus
    created_at: datetime
    finished_at: datetime | None
    jobs_discovered: int
    jobs_processed: int
    jobs_qualified: int


class JobStats(BaseModel):
    total: int = Field(description="Primary job records (duplicates excluded)")
    found_today: int = Field(description="Jobs discovered since midnight (TIMEZONE)")
    in_window: int = Field(description="Jobs posted within JOB_LOOKBACK_HOURS")
    unknown_date: int
    duplicates: int = Field(description="Duplicate listings linked to a primary record")
    by_source: dict[str, int]
    window: WindowRead
    last_discovery: LastRun | None
    analysed: int = Field(description="Jobs with an analysis decision")
    qualified: int = Field(description="Jobs analysed as APPLY or REVIEW")
    by_recommendation: dict[str, int]
    last_analysis: LastRun | None
    awaiting_analysis: int = Field(description="Queued jobs not analysed yet (DISCOVERED)")


class JobImportRequest(BaseModel):
    """A job the user found (e.g. a LinkedIn posting). The URL is stored, never fetched."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=100_000)
    posted_text: str | None = Field(
        default=None, max_length=100, description='Relative date as shown, e.g. "2 hours ago"'
    )
    posted_at: datetime | None = None


class JobImportResult(BaseModel):
    job: JobRead
    created: bool
    duplicate: bool
    application_created: bool


class EmailImportRequest(BaseModel):
    """A job-alert email (forwarded by n8n or pasted). Only job links are extracted."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(default="", max_length=1000)
    text: str = Field(max_length=MAX_EMAIL_CHARS, description="HTML or plain-text body")
    sender: str | None = Field(default=None, max_length=320)
    received_at: str | None = Field(default=None, max_length=100)


class EmailImportResult(BaseModel):
    links_found: int
    results: list[JobImportResult]


class JobSourceRead(BaseModel):
    key: str
    name: str
    kind: SourceKind
    policy: SourcePolicy
    enabled: bool
    is_mock: bool
    priority: int
    rate_limit_per_minute: int
    description: str | None
    notes: str | None
    runnable: bool
    skip_reason: str | None
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None
    last_counts: dict[str, Any]
