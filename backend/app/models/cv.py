"""CV versions and the fact base built from the confirmed master CV."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin, str_enum


class CvKind(StrEnum):
    MASTER = "MASTER"
    TAILORED = "TAILORED"  # Phase 5


class CvStatus(StrEnum):
    PARSED = "PARSED"  # draft: editable, not used by any later phase
    CONFIRMED = "CONFIRMED"  # the active master CV (at most one per candidate), read-only
    SUPERSEDED = "SUPERSEDED"  # a previously confirmed version, read-only


class DatePrecision(StrEnum):
    YEAR = "YEAR"
    MONTH = "MONTH"


class CvVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cv_versions"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "kind", "version", name="uq_cv_versions_candidate_kind_version"
        ),
        # At most one confirmed master CV per candidate: the active one.
        Index(
            "uq_cv_versions_active_master",
            "candidate_id",
            unique=True,
            postgresql_where=text("kind = 'MASTER' AND status = 'CONFIRMED'"),
        ),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[CvKind] = mapped_column(str_enum(CvKind, "cv_kind"))
    version: Mapped[int]
    status: Mapped[CvStatus] = mapped_column(str_enum(CvStatus, "cv_status"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(500))
    extracted_text: Mapped[str] = mapped_column(Text)
    structure: Mapped[dict[str, Any]]
    parse_warnings: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    parser_version: Mapped[str] = mapped_column(String(50))
    revised_from_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cv_versions.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None]

    @property
    def warning_count(self) -> int:
        warnings = self.structure.get("warnings") if isinstance(self.structure, dict) else None
        return len(warnings) if isinstance(warnings, list) else 0


class _FactMixin:
    """Columns shared by the fact tables rebuilt when a master CV is confirmed."""

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    cv_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cv_versions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    date_text: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[date | None]
    start_precision: Mapped[DatePrecision | None] = mapped_column(
        str_enum(DatePrecision, "start_precision")
    )
    end_date: Mapped[date | None]
    end_precision: Mapped[DatePrecision | None] = mapped_column(
        str_enum(DatePrecision, "end_precision")
    )
    is_current: Mapped[bool] = mapped_column(default=False, server_default="false")
    bullets: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    details: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    technologies: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))


class Experience(UUIDPrimaryKeyMixin, CreatedAtMixin, _FactMixin, Base):
    __tablename__ = "experiences"

    title: Mapped[str] = mapped_column(String(300))
    employer: Mapped[str | None] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(200))


class Education(UUIDPrimaryKeyMixin, CreatedAtMixin, _FactMixin, Base):
    __tablename__ = "educations"

    degree: Mapped[str] = mapped_column(String(300))
    institution: Mapped[str | None] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(200))


class Project(UUIDPrimaryKeyMixin, CreatedAtMixin, _FactMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(300))
