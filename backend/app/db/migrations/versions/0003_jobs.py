"""job sources, company watchlist, jobs with deduplication, job skills and applications

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-02 14:47:43.056683+00:00
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

ATS_TYPES = (
    "GREENHOUSE",
    "LEVER",
    "ASHBY",
    "SMARTRECRUITERS",
    "WORKDAY",
    "LINKEDIN",
    "INDEED",
    "GENERIC",
    "OTHER",
)
SOURCE_KINDS = ("ATS_API", "CAREER_PAGE", "FEED", "MANUAL")
SOURCE_POLICIES = ("api_only", "allowed", "manual_only", "disabled")
REMOTE_STATUSES = ("REMOTE", "HYBRID", "ONSITE", "UNKNOWN")
EMPLOYMENT_TYPES = ("FULL_TIME", "PART_TIME", "CONTRACT", "TEMPORARY", "INTERNSHIP", "UNKNOWN")
SENIORITIES = ("INTERN", "JUNIOR", "MID", "SENIOR", "LEAD", "PRINCIPAL", "UNKNOWN")
POSTING_DATE_STATUSES = ("KNOWN", "ESTIMATED", "UNKNOWN")
SKILL_IMPORTANCES = ("REQUIRED", "PREFERRED")
APPLICATION_STATUSES = (
    "DISCOVERED",
    "ANALYZED",
    "QUALIFIED",
    "CV_GENERATED",
    "READY_FOR_REVIEW",
    "APPROVED",
    "SUBMITTED",
    "HR_SCREEN",
    "INTERVIEW",
    "OFFER",
    "REJECTED",
    "WITHDRAWN",
    "BLOCKED",
    "MANUAL_ACTION_REQUIRED",
)


def _enum(values: tuple[str, ...], name: str) -> sa.Enum:
    # VARCHAR + CHECK constraint named "ck_<table>_<name>" through the naming convention.
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def _timestamp(name: str) -> sa.Column[datetime]:
    # clock_timestamp(): real insertion time (now() is the transaction start time)
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("clock_timestamp()"),
        nullable=False,
    )


def _json(name: str, default: str) -> sa.Column[Any]:
    return sa.Column(name, JSONB, server_default=sa.text(f"'{default}'::jsonb"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("career_url", sa.String(length=500), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("ats_type", _enum(ATS_TYPES, "company_ats_type"), nullable=False),
        sa.Column("board_token", sa.String(length=200), nullable=True),
        _json("target_roles", "[]"),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check_status", sa.String(length=300), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
        sa.UniqueConstraint("normalized_name", name=op.f("uq_companies_normalized_name")),
    )

    op.create_table(
        "job_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("kind", _enum(SOURCE_KINDS, "source_kind"), nullable=False),
        sa.Column("policy", _enum(SOURCE_POLICIES, "source_policy"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_mock", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="10", nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), server_default="30", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        _json("last_counts", "{}"),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_sources")),
        sa.UniqueConstraint("key", name=op.f("uq_job_sources_key")),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_job_id", sa.String(length=200), nullable=True),
        sa.Column("company", sa.String(length=300), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("remote_status", _enum(REMOTE_STATUSES, "remote_status"), nullable=False),
        sa.Column("employment_type", _enum(EMPLOYMENT_TYPES, "employment_type"), nullable=False),
        sa.Column("seniority", _enum(SENIORITIES, "seniority"), nullable=False),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("salary_currency", sa.String(length=3), nullable=True),
        sa.Column("salary_period", sa.String(length=10), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "posting_date_status",
            _enum(POSTING_DATE_STATUSES, "posting_date_status"),
            nullable=False,
        ),
        sa.Column("posting_date_basis", sa.Text(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("application_url", sa.String(length=2048), nullable=True),
        sa.Column("canonical_url", sa.String(length=2048), nullable=True),
        sa.Column("company_url", sa.String(length=2048), nullable=True),
        sa.Column("ats_type", _enum(ATS_TYPES, "job_ats_type"), nullable=False),
        sa.Column("visa_information", sa.Text(), nullable=True),
        sa.Column("relocation_information", sa.Text(), nullable=True),
        _json("required_skills", "[]"),
        _json("preferred_skills", "[]"),
        _json("languages", "[]"),
        sa.Column("education_requirements", sa.Text(), nullable=True),
        sa.Column("experience_requirements", sa.Text(), nullable=True),
        _json("responsibilities", "[]"),
        _json("raw_content", "{}"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("duplicate_of_id", sa.Uuid(), nullable=True),
        sa.Column("discovery_run_id", sa.Uuid(), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["source"],
            ["job_sources.key"],
            name=op.f("fk_jobs_source_job_sources"),
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_jobs_company_id_companies"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_id"],
            ["jobs.id"],
            name=op.f("fk_jobs_duplicate_of_id_jobs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["discovery_run_id"],
            ["automation_runs.id"],
            name=op.f("fk_jobs_discovery_run_id_automation_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    for column in (
        "source",
        "company_id",
        "country_code",
        "posting_date_status",
        "canonical_url",
        "content_hash",
        "duplicate_of_id",
        "discovery_run_id",
    ):
        op.create_index(op.f(f"ix_jobs_{column}"), "jobs", [column])
    op.create_index("ix_jobs_posted_at", "jobs", ["posted_at"])
    op.create_index("ix_jobs_discovered_at", "jobs", ["discovered_at"])
    # The same posting from the same source is one row (postings without a source id, i.e.
    # manual imports, are matched by canonical URL in the service instead).
    op.create_index(
        "uq_jobs_source_job",
        "jobs",
        ["source", "source_job_id"],
        unique=True,
        postgresql_where=sa.text("source_job_id IS NOT NULL"),
    )

    op.create_table(
        "job_skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("importance", _enum(SKILL_IMPORTANCES, "skill_importance"), nullable=False),
        _timestamp("created_at"),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_skills_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_skills")),
        sa.UniqueConstraint("job_id", "normalized_name", name="uq_job_skills_job_skill"),
    )
    op.create_index(op.f("ix_job_skills_job_id"), "job_skills", ["job_id"])
    op.create_index(op.f("ix_job_skills_normalized_name"), "job_skills", ["normalized_name"])

    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("company", sa.String(length=300), nullable=False),
        sa.Column("role", sa.String(length=300), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("application_url", sa.String(length=2048), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", _enum(APPLICATION_STATUSES, "application_status"), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cv_version_id", sa.Uuid(), nullable=True),
        sa.Column("ats_score", sa.Double(), nullable=True),
        sa.Column("visa_status", sa.String(length=40), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recruiter", sa.String(length=200), nullable=True),
        sa.Column("follow_up_date", sa.Date(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=100), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_applications_candidate_id_candidates"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_applications_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["cv_version_id"],
            ["cv_versions.id"],
            name=op.f("fk_applications_cv_version_id_cv_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["automation_runs.id"],
            name=op.f("fk_applications_run_id_automation_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_applications")),
        sa.UniqueConstraint("candidate_id", "job_id", name="uq_applications_candidate_job"),
    )
    for column in ("candidate_id", "job_id", "status", "run_id"):
        op.create_index(op.f(f"ix_applications_{column}"), "applications", [column])


def downgrade() -> None:
    op.drop_table("applications")  # drops its indexes and constraints
    op.drop_table("job_skills")
    op.drop_table("jobs")
    op.drop_table("job_sources")
    op.drop_table("companies")
