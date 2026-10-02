"""Company watchlist (spec §6): companies whose career pages / ATS boards are checked each run."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from app.jobs.types import AtsType


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(200))
    # Case- and whitespace-insensitive key: unique, and used to link discovered jobs by name.
    normalized_name: Mapped[str] = mapped_column(String(200), unique=True)
    career_url: Mapped[str] = mapped_column(String(500))
    country: Mapped[str | None] = mapped_column(String(100))
    country_code: Mapped[str | None] = mapped_column(String(2))
    ats_type: Mapped[AtsType] = mapped_column(str_enum(AtsType, "company_ats_type"))
    board_token: Mapped[str | None] = mapped_column(String(200))
    target_roles: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    enabled: Mapped[bool] = mapped_column(default=True, server_default="true")
    last_checked_at: Mapped[datetime | None]
    last_check_status: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text)
