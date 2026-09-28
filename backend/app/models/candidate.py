"""Candidates and their skill evidence."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.cv.models import SkillStrength
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum

DEFAULT_CANDIDATE_SLUG = "default"


class Candidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A candidate. The validated profile document is the live source of truth (JSONB);
    identity columns are denormalised copies kept in sync for listing and filtering."""

    __tablename__ = "candidates"

    slug: Mapped[str] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    headline: Mapped[str | None] = mapped_column(String(200))
    nationality: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(200))
    country: Mapped[str | None] = mapped_column(String(200))
    country_code: Mapped[str | None] = mapped_column(String(2))
    visa_sponsorship_required: Mapped[bool | None]
    willing_to_relocate: Mapped[bool | None]
    profile: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    profile_version: Mapped[int] = mapped_column(default=1, server_default="1")


class CandidateSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A skill with its evidence in the confirmed master CV (derived data, rebuilt on change)."""

    __tablename__ = "candidate_skills"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "normalized_name", name="uq_candidate_skills_candidate_skill"
        ),
    )

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    cv_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cv_versions.id", ondelete="SET NULL"), index=True
    )
    position: Mapped[int]
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(100))
    strength: Mapped[SkillStrength] = mapped_column(str_enum(SkillStrength, "skill_strength"))
    sources: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(server_default=text("'[]'::jsonb"))
