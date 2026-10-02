"""Applications (spec §18): one per candidate and job, tracked through the whole pipeline."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.analysis.types import Recommendation
from app.applications.lifecycle import ApplicationStatus
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum


class Application(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """``updated_at`` is the spec's ``last_updated``. Company, role, country, URL and source are
    copied from the job when the application is created: they record what was applied to."""

    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_id", name="uq_applications_candidate_job"),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    company: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(300))
    country: Mapped[str | None] = mapped_column(String(100))
    application_url: Mapped[str | None] = mapped_column(String(2048))
    source: Mapped[str] = mapped_column(String(50))
    status: Mapped[ApplicationStatus] = mapped_column(
        str_enum(ApplicationStatus, "application_status"), index=True
    )
    status_reason: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None]
    cv_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cv_versions.id", ondelete="SET NULL")
    )
    ats_score: Mapped[float | None]
    visa_status: Mapped[str | None] = mapped_column(String(40))
    # Latest analysis decision (Phase 4); the full history is in ``job_analyses``.
    recommendation: Mapped[Recommendation | None] = mapped_column(
        str_enum(Recommendation, "application_recommendation"), index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    recruiter: Mapped[str | None] = mapped_column(String(200))
    follow_up_date: Mapped[date | None]
    approved_at: Mapped[datetime | None]
    approved_by: Mapped[str | None] = mapped_column(String(100))
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("automation_runs.id", ondelete="SET NULL"), index=True
    )
