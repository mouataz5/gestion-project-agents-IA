"""Job sources, normalized jobs (spec §7) and their skills."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.crawlers.base import SourceKind, SourcePolicy
from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.jobs.types import (
    AtsType,
    EmploymentType,
    PostingDateStatus,
    RemoteStatus,
    Seniority,
    SkillImportance,
)


class JobSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Runtime mirror of ``crawler/sources.yaml`` (the policy) plus the last run status."""

    __tablename__ = "job_sources"

    key: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[SourceKind] = mapped_column(str_enum(SourceKind, "source_kind"))
    policy: Mapped[SourcePolicy] = mapped_column(str_enum(SourcePolicy, "source_policy"))
    enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    is_mock: Mapped[bool] = mapped_column(default=False, server_default="false")
    priority: Mapped[int] = mapped_column(default=10, server_default="10")
    rate_limit_per_minute: Mapped[int] = mapped_column(default=30, server_default="30")
    description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None]
    last_status: Mapped[str | None] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_counts: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # The same posting from the same source is one row (re-seen postings are updated).
        Index(
            "uq_jobs_source_job",
            "source",
            "source_job_id",
            unique=True,
            postgresql_where=text("source_job_id IS NOT NULL"),
        ),
        Index("ix_jobs_posted_at", "posted_at"),
        Index("ix_jobs_discovered_at", "discovered_at"),
    )

    source: Mapped[str] = mapped_column(
        ForeignKey("job_sources.key", onupdate="CASCADE"), index=True
    )
    source_job_id: Mapped[str | None] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(300))
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    location: Mapped[str | None] = mapped_column(String(300))
    country: Mapped[str | None] = mapped_column(String(100))
    country_code: Mapped[str | None] = mapped_column(String(2), index=True)
    remote_status: Mapped[RemoteStatus] = mapped_column(str_enum(RemoteStatus, "remote_status"))
    employment_type: Mapped[EmploymentType] = mapped_column(
        str_enum(EmploymentType, "employment_type")
    )
    seniority: Mapped[Seniority] = mapped_column(str_enum(Seniority, "seniority"))
    salary_min: Mapped[int | None]
    salary_max: Mapped[int | None]
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[str | None] = mapped_column(String(10))
    posted_at: Mapped[datetime | None]
    posting_date_status: Mapped[PostingDateStatus] = mapped_column(
        str_enum(PostingDateStatus, "posting_date_status"), index=True
    )
    posting_date_basis: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    application_url: Mapped[str | None] = mapped_column(String(2048))
    canonical_url: Mapped[str | None] = mapped_column(String(2048), index=True)
    company_url: Mapped[str | None] = mapped_column(String(2048))
    ats_type: Mapped[AtsType] = mapped_column(str_enum(AtsType, "job_ats_type"))
    visa_information: Mapped[str | None] = mapped_column(Text)
    relocation_information: Mapped[str | None] = mapped_column(Text)
    required_skills: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    preferred_skills: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    languages: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    education_requirements: Mapped[str | None] = mapped_column(Text)
    experience_requirements: Mapped[str | None] = mapped_column(Text)
    responsibilities: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    raw_content: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    discovery_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("automation_runs.id", ondelete="SET NULL"), index=True
    )


class JobSkill(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "job_skills"
    __table_args__ = (
        UniqueConstraint("job_id", "normalized_name", name="uq_job_skills_job_skill"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    importance: Mapped[SkillImportance] = mapped_column(
        str_enum(SkillImportance, "skill_importance")
    )
