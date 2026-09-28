"""candidate profile, master CV versions and the confirmed fact base

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28 23:23:04.123946+00:00
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

CV_KINDS = ("MASTER", "TAILORED")
CV_STATUSES = ("PARSED", "CONFIRMED", "SUPERSEDED")
SKILL_STRENGTHS = ("NONE", "LISTED", "DEMONSTRATED")
DATE_PRECISIONS = ("YEAR", "MONTH")
FACT_TABLES = ("experiences", "educations", "projects")


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


def _json_list(name: str) -> sa.Column[Any]:
    return sa.Column(name, JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False)


def _fact_columns(table: str) -> list[Any]:
    """Columns shared by experiences, educations and projects (see models.cv._FactMixin)."""
    return [
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("cv_version_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("date_text", sa.String(length=200), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("start_precision", _enum(DATE_PRECISIONS, "start_precision"), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("end_precision", _enum(DATE_PRECISIONS, "end_precision"), nullable=True),
        sa.Column("is_current", sa.Boolean(), server_default="false", nullable=False),
        _json_list("bullets"),
        _json_list("details"),
        _json_list("technologies"),
        _timestamp("created_at"),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f(f"fk_{table}_candidate_id_candidates"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cv_version_id"],
            ["cv_versions.id"],
            name=op.f(f"fk_{table}_cv_version_id_cv_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def upgrade() -> None:
    op.create_table(
        "candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("headline", sa.String(length=200), nullable=True),
        sa.Column("nationality", sa.String(length=200), nullable=True),
        sa.Column("city", sa.String(length=200), nullable=True),
        sa.Column("country", sa.String(length=200), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("visa_sponsorship_required", sa.Boolean(), nullable=True),
        sa.Column("willing_to_relocate", sa.Boolean(), nullable=True),
        sa.Column("profile", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("profile_version", sa.Integer(), server_default="1", nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidates")),
        sa.UniqueConstraint("slug", name=op.f("uq_candidates_slug")),
    )

    op.create_table(
        "cv_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("kind", _enum(CV_KINDS, "cv_kind"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", _enum(CV_STATUSES, "cv_status"), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("structure", JSONB, nullable=False),
        _json_list("parse_warnings"),
        sa.Column("parser_version", sa.String(length=50), nullable=False),
        sa.Column("revised_from_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_cv_versions_candidate_id_candidates"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revised_from_id"],
            ["cv_versions.id"],
            name=op.f("fk_cv_versions_revised_from_id_cv_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cv_versions")),
        sa.UniqueConstraint(
            "candidate_id", "kind", "version", name="uq_cv_versions_candidate_kind_version"
        ),
    )
    op.create_index(op.f("ix_cv_versions_candidate_id"), "cv_versions", ["candidate_id"])
    op.create_index(op.f("ix_cv_versions_status"), "cv_versions", ["status"])
    # At most one confirmed master CV per candidate: the active one.
    op.create_index(
        "uq_cv_versions_active_master",
        "cv_versions",
        ["candidate_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'MASTER' AND status = 'CONFIRMED'"),
    )

    op.create_table(
        "candidate_skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("cv_version_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("strength", _enum(SKILL_STRENGTHS, "skill_strength"), nullable=False),
        _json_list("sources"),
        _json_list("evidence"),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_candidate_skills_candidate_id_candidates"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cv_version_id"],
            ["cv_versions.id"],
            name=op.f("fk_candidate_skills_cv_version_id_cv_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_skills")),
        sa.UniqueConstraint(
            "candidate_id", "normalized_name", name="uq_candidate_skills_candidate_skill"
        ),
    )
    op.create_index(op.f("ix_candidate_skills_candidate_id"), "candidate_skills", ["candidate_id"])
    op.create_index(
        op.f("ix_candidate_skills_cv_version_id"), "candidate_skills", ["cv_version_id"]
    )

    op.create_table(
        "experiences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("employer", sa.String(length=300), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        *_fact_columns("experiences"),
    )
    op.create_table(
        "educations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("degree", sa.String(length=300), nullable=False),
        sa.Column("institution", sa.String(length=300), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        *_fact_columns("educations"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        *_fact_columns("projects"),
    )
    for table in FACT_TABLES:
        op.create_index(op.f(f"ix_{table}_candidate_id"), table, ["candidate_id"])
        op.create_index(op.f(f"ix_{table}_cv_version_id"), table, ["cv_version_id"])

    op.add_column("automation_runs", sa.Column("candidate_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_automation_runs_candidate_id"), "automation_runs", ["candidate_id"])
    op.create_foreign_key(
        op.f("fk_automation_runs_candidate_id_candidates"),
        "automation_runs",
        "candidates",
        ["candidate_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_automation_runs_candidate_id_candidates"), "automation_runs", type_="foreignkey"
    )
    op.drop_index(op.f("ix_automation_runs_candidate_id"), table_name="automation_runs")
    op.drop_column("automation_runs", "candidate_id")
    for table in reversed(FACT_TABLES):
        op.drop_table(table)  # drops its indexes and constraints
    op.drop_table("candidate_skills")
    op.drop_table("cv_versions")
    op.drop_table("candidates")
