"""ATS engine: job requirements, CV tailorings, ATS analyses and tailored CV versions

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07 13:20:00.000000+00:00
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

CALL_STATUSES = ("SUCCEEDED", "REFUSED", "FAILED")
STOP_REASONS = (
    "TARGET_REACHED",
    "ONLY_UNSUPPORTED_GAINS",
    "NO_IMPROVEMENT",
    "MAX_ITERATIONS",
    "GUARD_REJECTED",
    "PROVIDER_ERROR",
)
DOCUMENT_KINDS = ("MASTER", "TAILORED")
ITERATION_STATUSES = ("SCORED", "REPAIRED", "REJECTED", "FAILED", "REFUSED")
CV_STATUSES_BEFORE = ("PARSED", "CONFIRMED", "SUPERSEDED")
CV_STATUSES = (*CV_STATUSES_BEFORE, "GENERATED")
FILE_COLUMNS = ("original_filename", "content_type", "size_bytes", "sha256", "storage_key")
FILE_TYPES: dict[str, Any] = {
    "original_filename": sa.String(length=255),
    "content_type": sa.String(length=100),
    "size_bytes": sa.Integer(),
    "sha256": sa.String(length=64),
    "storage_key": sa.String(length=500),
}


def _enum(values: tuple[str, ...], name: str) -> sa.Enum:
    # VARCHAR + CHECK constraint named "ck_<table>_<name>" through the naming convention.
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def _timestamp(name: str) -> sa.Column[datetime]:
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


def _model_call() -> list[sa.Column[Any]]:
    """Provenance and cost of a model call."""
    return [
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("requested_model", sa.String(length=100), nullable=False),
        sa.Column("served_model", sa.String(length=100), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("prompt_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        _count("input_tokens"),
        _count("output_tokens"),
        _count("cache_read_input_tokens"),
        _count("cache_creation_input_tokens"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    ]


def _fk(table: str, column: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f"{target}.id"],
        name=op.f(f"fk_{table}_{column}_{target}"),
        ondelete=ondelete,
    )


def upgrade() -> None:
    # --- tailored versions in cv_versions -------------------------------------------------------
    for column in FILE_COLUMNS:  # tailored versions have no uploaded file
        op.alter_column(
            "cv_versions",
            column,
            existing_type=FILE_TYPES[column],
            existing_nullable=False,
            nullable=True,
        )
    op.drop_constraint(op.f("ck_cv_versions_cv_status"), "cv_versions", type_="check")
    op.create_check_constraint(
        op.f("ck_cv_versions_cv_status"),
        "cv_versions",
        "status IN (" + ", ".join(f"'{status}'" for status in CV_STATUSES) + ")",
    )
    op.add_column("cv_versions", sa.Column("application_id", sa.Uuid(), nullable=True))
    op.add_column("cv_versions", sa.Column("job_id", sa.Uuid(), nullable=True))
    op.add_column("cv_versions", sa.Column("base_version_id", sa.Uuid(), nullable=True))
    op.add_column("cv_versions", sa.Column("run_id", sa.Uuid(), nullable=True))
    op.add_column("cv_versions", _json("evidence", "{}"))
    op.add_column("cv_versions", sa.Column("ats_score", sa.Float(), nullable=True))
    op.create_foreign_key(
        op.f("fk_cv_versions_application_id_applications"),
        "cv_versions",
        "applications",
        ["application_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_cv_versions_job_id_jobs"),
        "cv_versions",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_cv_versions_base_version_id_cv_versions"),
        "cv_versions",
        "cv_versions",
        ["base_version_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_cv_versions_run_id_automation_runs"),
        "cv_versions",
        "automation_runs",
        ["run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for column in ("application_id", "job_id", "run_id"):
        op.create_index(op.f(f"ix_cv_versions_{column}"), "cv_versions", [column])
    op.create_index(
        "uq_cv_versions_current_tailored",
        "cv_versions",
        ["application_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'TAILORED' AND status = 'GENERATED'"),
    )
    op.create_check_constraint(
        op.f("ck_cv_versions_master_file"),
        "cv_versions",
        "kind <> 'MASTER' OR (original_filename IS NOT NULL AND content_type IS NOT NULL"
        " AND size_bytes IS NOT NULL AND sha256 IS NOT NULL AND storage_key IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_cv_versions_kind_status"),
        "cv_versions",
        "(kind = 'MASTER' AND status IN ('PARSED', 'CONFIRMED', 'SUPERSEDED'))"
        " OR (kind = 'TAILORED' AND status IN ('GENERATED', 'SUPERSEDED'))",
    )
    op.create_check_constraint(
        op.f("ck_cv_versions_tailored_links"),
        "cv_versions",
        "kind <> 'TAILORED' OR (application_id IS NOT NULL AND base_version_id IS NOT NULL)",
    )

    # --- job requirements (candidate-independent extraction cache) ------------------------------
    op.create_table(
        "job_requirements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("status", _enum(CALL_STATUSES, "requirements_status"), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        _json("extraction", "{}"),
        *_model_call(),
        _timestamp("created_at"),
        _fk("job_requirements", "job_id", "jobs", "CASCADE"),
        _fk("job_requirements", "run_id", "automation_runs", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_requirements")),
    )
    for column in ("job_id", "run_id"):
        op.create_index(op.f(f"ix_job_requirements_{column}"), "job_requirements", [column])
    op.create_index(
        "uq_job_requirements_job_input",
        "job_requirements",
        ["job_id", "input_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'SUCCEEDED'"),
    )

    # --- tailoring attempts ---------------------------------------------------------------------
    op.create_table(
        "cv_tailorings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("master_version_id", sa.Uuid(), nullable=True),
        sa.Column("requirements_id", sa.Uuid(), nullable=True),
        sa.Column("cv_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", _enum(CALL_STATUSES, "tailoring_status"), nullable=False),
        sa.Column("stop_reason", _enum(STOP_REASONS, "tailoring_stop_reason"), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("scoring_version", sa.String(length=30), nullable=False),
        _json("weights", "{}"),
        sa.Column("target_score", sa.Float(), nullable=False),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("baseline_score", sa.Float(), nullable=True),
        sa.Column("final_score", sa.Float(), nullable=True),
        sa.Column("ceiling_score", sa.Float(), nullable=True),
        _count("iterations_used"),
        sa.Column("best_iteration", sa.Integer(), nullable=True),
        _json("requirements", "{}"),
        _json("gaps", "[]"),
        *_model_call(),
        _timestamp("created_at"),
        _fk("cv_tailorings", "application_id", "applications", "CASCADE"),
        _fk("cv_tailorings", "candidate_id", "candidates", "CASCADE"),
        _fk("cv_tailorings", "job_id", "jobs", "SET NULL"),
        _fk("cv_tailorings", "run_id", "automation_runs", "SET NULL"),
        sa.ForeignKeyConstraint(
            ["master_version_id"],
            ["cv_versions.id"],
            name=op.f("fk_cv_tailorings_master_version_id_cv_versions"),
            ondelete="SET NULL",
        ),
        _fk("cv_tailorings", "requirements_id", "job_requirements", "SET NULL"),
        _fk("cv_tailorings", "cv_version_id", "cv_versions", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cv_tailorings")),
    )
    op.create_index(
        "ix_cv_tailorings_application_created", "cv_tailorings", ["application_id", "created_at"]
    )
    for column in ("candidate_id", "job_id", "run_id", "input_hash"):
        op.create_index(op.f(f"ix_cv_tailorings_{column}"), "cv_tailorings", [column])

    # --- the score of every version a tailoring looked at --------------------------------------
    op.create_table(
        "ats_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tailoring_id", sa.Uuid(), nullable=False),
        sa.Column("cv_version_id", sa.Uuid(), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("document_kind", _enum(DOCUMENT_KINDS, "ats_document_kind"), nullable=False),
        sa.Column("status", _enum(ITERATION_STATUSES, "ats_analysis_status"), nullable=False),
        sa.Column("selected", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("scoring_version", sa.String(length=30), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("assessed_weight", sa.Integer(), nullable=True),
        _count("penalty"),
        _json("components", "[]"),
        _json("keywords", "[]"),
        _json("stuffing", "[]"),
        _json("violations", "[]"),
        _json("feedback", "{}"),
        _count("repairs_count"),
        _json("document", "{}"),
        _json("ledger", "{}"),
        sa.Column("served_model", sa.String(length=100), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        _count("input_tokens"),
        _count("output_tokens"),
        _count("cache_read_input_tokens"),
        _count("cache_creation_input_tokens"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _timestamp("created_at"),
        _fk("ats_analyses", "tailoring_id", "cv_tailorings", "CASCADE"),
        _fk("ats_analyses", "cv_version_id", "cv_versions", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ats_analyses")),
        sa.UniqueConstraint(
            "tailoring_id", "iteration", name="uq_ats_analyses_tailoring_iteration"
        ),
    )


def downgrade() -> None:
    op.drop_table("ats_analyses")
    op.drop_table("cv_tailorings")
    op.drop_table("job_requirements")

    # Tailored versions cannot be represented before this revision: they are deleted
    # (applications.cv_version_id is set to NULL by its foreign key).
    op.execute("DELETE FROM cv_versions WHERE kind = 'TAILORED'")
    for name in ("tailored_links", "kind_status", "master_file"):
        op.drop_constraint(op.f(f"ck_cv_versions_{name}"), "cv_versions", type_="check")
    op.drop_index("uq_cv_versions_current_tailored", table_name="cv_versions")
    for column in ("application_id", "job_id", "run_id"):
        op.drop_index(op.f(f"ix_cv_versions_{column}"), table_name="cv_versions")
    for name in (
        "fk_cv_versions_application_id_applications",
        "fk_cv_versions_job_id_jobs",
        "fk_cv_versions_base_version_id_cv_versions",
        "fk_cv_versions_run_id_automation_runs",
    ):
        op.drop_constraint(op.f(name), "cv_versions", type_="foreignkey")
    for column in (
        "ats_score",
        "evidence",
        "run_id",
        "base_version_id",
        "job_id",
        "application_id",
    ):
        op.drop_column("cv_versions", column)
    op.drop_constraint(op.f("ck_cv_versions_cv_status"), "cv_versions", type_="check")
    op.create_check_constraint(
        op.f("ck_cv_versions_cv_status"),
        "cv_versions",
        "status IN (" + ", ".join(f"'{status}'" for status in CV_STATUSES_BEFORE) + ")",
    )
    for column in FILE_COLUMNS:
        op.alter_column(
            "cv_versions",
            column,
            existing_type=FILE_TYPES[column],
            existing_nullable=True,
            nullable=False,
        )
