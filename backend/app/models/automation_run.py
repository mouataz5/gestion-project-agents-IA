"""Automation runs and their event timelines (job execution logs)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Identity, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin, str_enum


class RunType(StrEnum):
    DIAGNOSTIC = "DIAGNOSTIC"
    DAILY_PIPELINE = "DAILY_PIPELINE"
    DISCOVERY = "DISCOVERY"
    ANALYSIS = "ANALYSIS"
    CV_GENERATION = "CV_GENERATION"
    APPLICATION_PREPARATION = "APPLICATION_PREPARATION"
    SUBMISSION = "SUBMISSION"


class RunTrigger(StrEnum):
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"
    API = "API"
    SYSTEM = "SYSTEM"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATUSES


_TERMINAL_STATUSES = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.PARTIAL_SUCCESS, RunStatus.FAILED, RunStatus.CANCELLED}
)


class EventLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


# Counters every automation run reports (specification §25).
RUN_COUNTERS: tuple[str, ...] = (
    "jobs_discovered",
    "jobs_processed",
    "jobs_qualified",
    "cv_generated",
    "applications_prepared",
    "applications_submitted",
)


class AutomationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "automation_runs"
    __table_args__ = (Index("ix_automation_runs_created_at", "created_at"),)

    run_type: Mapped[RunType] = mapped_column(str_enum(RunType, "run_type"), index=True)
    trigger: Mapped[RunTrigger] = mapped_column(str_enum(RunTrigger, "run_trigger"))
    status: Mapped[RunStatus] = mapped_column(
        str_enum(RunStatus, "run_status"), index=True, default=RunStatus.PENDING
    )
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    jobs_discovered: Mapped[int] = mapped_column(default=0, server_default="0")
    jobs_processed: Mapped[int] = mapped_column(default=0, server_default="0")
    jobs_qualified: Mapped[int] = mapped_column(default=0, server_default="0")
    cv_generated: Mapped[int] = mapped_column(default=0, server_default="0")
    applications_prepared: Mapped[int] = mapped_column(default=0, server_default="0")
    applications_submitted: Mapped[int] = mapped_column(default=0, server_default="0")

    error_count: Mapped[int] = mapped_column(default=0, server_default="0")
    errors: Mapped[list[dict[str, Any]]] = mapped_column(
        default=list, server_default=text("'[]'::jsonb")
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(
        default=dict, server_default=text("'{}'::jsonb")
    )
    summary: Mapped[dict[str, Any]] = mapped_column(
        default=dict, server_default=text("'{}'::jsonb")
    )
    task_id: Mapped[str | None] = mapped_column(String(255))

    events: Mapped[list[RunEvent]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RunEvent.sequence",
        lazy="selectin",
    )

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()


class RunEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "automation_run_events"

    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automation_runs.id", ondelete="CASCADE"), index=True
    )
    level: Mapped[EventLevel] = mapped_column(str_enum(EventLevel, "event_level"))
    stage: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))

    run: Mapped[AutomationRun] = relationship(back_populates="events")
