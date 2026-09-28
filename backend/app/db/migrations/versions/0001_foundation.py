"""foundation: automation runs, run events, append-only audit log

Revision ID: 0001
Revises:
Create Date: 2026-09-28 11:10:25.670807+00:00
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

RUN_TYPES = (
    "DIAGNOSTIC",
    "DAILY_PIPELINE",
    "DISCOVERY",
    "ANALYSIS",
    "CV_GENERATION",
    "APPLICATION_PREPARATION",
    "SUBMISSION",
)
RUN_TRIGGERS = ("MANUAL", "SCHEDULED", "API", "SYSTEM")
RUN_STATUSES = ("PENDING", "RUNNING", "SUCCEEDED", "PARTIAL_SUCCESS", "FAILED", "CANCELLED")
EVENT_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


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


def upgrade() -> None:
    op.create_table(
        "automation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_type", _enum(RUN_TYPES, "run_type"), nullable=False),
        sa.Column("trigger", _enum(RUN_TRIGGERS, "run_trigger"), nullable=False),
        sa.Column("status", _enum(RUN_STATUSES, "run_status"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("jobs_discovered", sa.Integer(), server_default="0", nullable=False),
        sa.Column("jobs_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("jobs_qualified", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cv_generated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("applications_prepared", sa.Integer(), server_default="0", nullable=False),
        sa.Column("applications_submitted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errors", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("parameters", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("summary", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_runs")),
    )
    op.create_index("ix_automation_runs_created_at", "automation_runs", ["created_at"])
    op.create_index(op.f("ix_automation_runs_run_type"), "automation_runs", ["run_type"])
    op.create_index(op.f("ix_automation_runs_status"), "automation_runs", ["status"])

    op.create_table(
        "automation_run_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("level", _enum(EVENT_LEVELS, "event_level"), nullable=False),
        sa.Column("stage", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        _timestamp("created_at"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["automation_runs.id"],
            name=op.f("fk_automation_run_events_run_id_automation_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_run_events")),
        sa.UniqueConstraint("sequence", name=op.f("uq_automation_run_events_sequence")),
    )
    op.create_index(op.f("ix_automation_run_events_run_id"), "automation_run_events", ["run_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=True),
        sa.Column("entity_id", sa.String(length=100), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("details", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        _timestamp("created_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
        sa.UniqueConstraint("sequence", name=op.f("uq_audit_logs_sequence")),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])

    # The audit log is append-only: reject UPDATE and DELETE at the database level.
    op.execute("""
        CREATE FUNCTION audit_logs_reject_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only (% is not allowed)', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """)
    op.execute("""
        CREATE TRIGGER audit_logs_append_only
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_reject_mutation()
        """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_append_only ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_reject_mutation()")
    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(op.f("ix_automation_run_events_run_id"), table_name="automation_run_events")
    op.drop_table("automation_run_events")
    op.drop_index(op.f("ix_automation_runs_status"), table_name="automation_runs")
    op.drop_index(op.f("ix_automation_runs_run_type"), table_name="automation_runs")
    op.drop_index("ix_automation_runs_created_at", table_name="automation_runs")
    op.drop_table("automation_runs")
