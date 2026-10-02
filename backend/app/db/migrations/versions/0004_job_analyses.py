"""job analyses (visa classification, relevance, decision) and applications.recommendation

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-02 20:58:35.651679+00:00
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

ANALYSIS_STATUSES = ("SUCCEEDED", "REFUSED", "FAILED")
RECOMMENDATIONS = ("APPLY", "REVIEW", "SKIP")
VISA_STATUSES = (
    "SPONSORSHIP_CONFIRMED",
    "SPONSORSHIP_LIKELY",
    "SPONSORSHIP_UNKNOWN",
    "SPONSORSHIP_NOT_AVAILABLE",
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


def _count(name: str) -> sa.Column[int]:
    return sa.Column(name, sa.Integer(), server_default="0", nullable=False)


def upgrade() -> None:
    op.create_table(
        "job_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("cv_version_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("status", _enum(ANALYSIS_STATUSES, "analysis_status"), nullable=False),
        # Provenance: who answered, with which prompt, from which inputs.
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("requested_model", sa.String(length=100), nullable=False),
        sa.Column("served_model", sa.String(length=100), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("prompt_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        # Cost.
        _count("input_tokens"),
        _count("output_tokens"),
        _count("cache_read_input_tokens"),
        _count("cache_creation_input_tokens"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        # Result and decision.
        sa.Column(
            "recommendation", _enum(RECOMMENDATIONS, "analysis_recommendation"), nullable=True
        ),
        sa.Column(
            "llm_recommendation",
            _enum(RECOMMENDATIONS, "analysis_llm_recommendation"),
            nullable=True,
        ),
        _json("rule_reasons", "[]"),
        sa.Column("visa_status", _enum(VISA_STATUSES, "analysis_visa_status"), nullable=True),
        _json("visa", "{}"),
        _json("relevance", "{}"),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _timestamp("created_at"),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_job_analyses_application_id_applications"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_job_analyses_candidate_id_candidates"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_analyses_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["cv_version_id"],
            ["cv_versions.id"],
            name=op.f("fk_job_analyses_cv_version_id_cv_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["automation_runs.id"],
            name=op.f("fk_job_analyses_run_id_automation_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_analyses")),
    )
    op.create_index(
        "ix_job_analyses_application_created", "job_analyses", ["application_id", "created_at"]
    )
    for column in ("candidate_id", "job_id", "run_id", "input_hash"):
        op.create_index(op.f(f"ix_job_analyses_{column}"), "job_analyses", [column])

    op.add_column(
        "applications",
        sa.Column(
            "recommendation",
            _enum(RECOMMENDATIONS, "application_recommendation"),
            nullable=True,
        ),
    )
    op.create_index(op.f("ix_applications_recommendation"), "applications", ["recommendation"])


def downgrade() -> None:
    op.drop_index(op.f("ix_applications_recommendation"), table_name="applications")
    op.drop_column("applications", "recommendation")  # drops its CHECK constraint
    op.drop_table("job_analyses")  # drops its indexes and constraints
