"""Job analyses (Phase 4): one row per analysis attempt of an application, kept as history."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.analysis.types import AnalysisStatus, Recommendation, VisaStatus
from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, str_enum


class JobAnalysis(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """What was analysed (input hash, CV version, prompt version), by whom (provider, requested and
    served model), at what cost (tokens), and the verified result with the decision's reasons."""

    __tablename__ = "job_analyses"
    __table_args__ = (Index("ix_job_analyses_application_created", "application_id", "created_at"),)

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    cv_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cv_versions.id", ondelete="SET NULL")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("automation_runs.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[AnalysisStatus] = mapped_column(str_enum(AnalysisStatus, "analysis_status"))
    provider: Mapped[str] = mapped_column(String(20))
    requested_model: Mapped[str] = mapped_column(String(100))
    served_model: Mapped[str | None] = mapped_column(String(100))
    fallback_used: Mapped[bool] = mapped_column(default=False, server_default="false")
    prompt_name: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[int]
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    request_id: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    cache_read_input_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    cache_creation_input_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    duration_ms: Mapped[int | None]
    recommendation: Mapped[Recommendation | None] = mapped_column(
        str_enum(Recommendation, "analysis_recommendation")
    )
    llm_recommendation: Mapped[Recommendation | None] = mapped_column(
        str_enum(Recommendation, "analysis_llm_recommendation")
    )
    rule_reasons: Mapped[list[str]] = mapped_column(server_default=text("'[]'::jsonb"))
    visa_status: Mapped[VisaStatus | None] = mapped_column(
        str_enum(VisaStatus, "analysis_visa_status")
    )
    visa: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    relevance: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)
