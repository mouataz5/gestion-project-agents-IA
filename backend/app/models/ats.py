"""ATS engine records (Phase 5): requirement extractions, tailoring attempts and the score of
every version an attempt looked at."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.ats.types import CallStatus, DocumentKind, IterationStatus, StopReason
from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, str_enum


class _ModelCall:
    """Provenance and cost of one model call (or of every call of a tailoring)."""

    provider: Mapped[str] = mapped_column(String(20))
    requested_model: Mapped[str] = mapped_column(String(100))
    served_model: Mapped[str | None] = mapped_column(String(100))
    fallback_used: Mapped[bool] = mapped_column(default=False, server_default="false")
    prompt_name: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[int]
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    cache_read_input_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    cache_creation_input_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    duration_ms: Mapped[int | None]
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)


class RequirementsExtraction(UUIDPrimaryKeyMixin, CreatedAtMixin, _ModelCall, Base):
    """What a job asks for, read once per posting and prompt (candidate-independent cache): the
    grounded result (``app.ats.requirements.JobRequirements``) with what grounding discarded."""

    __tablename__ = "job_requirements"
    __table_args__ = (
        # One successful extraction per posting version and prompt: the cache key.
        Index(
            "uq_job_requirements_job_input",
            "job_id",
            "input_hash",
            unique=True,
            postgresql_where=text("status = 'SUCCEEDED'"),
        ),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("automation_runs.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[CallStatus] = mapped_column(str_enum(CallStatus, "requirements_status"))
    input_hash: Mapped[str] = mapped_column(String(64))
    extraction: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))


class CvTailoring(UUIDPrimaryKeyMixin, CreatedAtMixin, _ModelCall, Base):
    """One tailoring attempt of an application: inputs, scores, stop reason, the candidate's gaps
    and the stored version (if any). Usage and provenance sum up every call of the attempt."""

    __tablename__ = "cv_tailorings"
    __table_args__ = (
        Index("ix_cv_tailorings_application_created", "application_id", "created_at"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("automation_runs.id", ondelete="SET NULL"), index=True
    )
    master_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cv_versions.id", ondelete="SET NULL")
    )
    requirements_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_requirements.id", ondelete="SET NULL")
    )
    cv_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cv_versions.id", ondelete="SET NULL")
    )
    status: Mapped[CallStatus] = mapped_column(str_enum(CallStatus, "tailoring_status"))
    stop_reason: Mapped[StopReason | None] = mapped_column(
        str_enum(StopReason, "tailoring_stop_reason")
    )
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    scoring_version: Mapped[str] = mapped_column(String(30))
    weights: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    target_score: Mapped[float]
    max_iterations: Mapped[int]
    baseline_score: Mapped[float | None]
    final_score: Mapped[float | None]
    ceiling_score: Mapped[float | None]
    iterations_used: Mapped[int] = mapped_column(default=0, server_default="0")
    best_iteration: Mapped[int | None]
    requirements: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(server_default=text("'[]'::jsonb"))


class AtsAnalysis(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """The score of one version a tailoring looked at: iteration 0 is the master CV, then every
    tailored version (rejected ones unscored, with the guard's violations)."""

    __tablename__ = "ats_analyses"
    __table_args__ = (
        UniqueConstraint("tailoring_id", "iteration", name="uq_ats_analyses_tailoring_iteration"),
    )

    tailoring_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cv_tailorings.id", ondelete="CASCADE")
    )
    cv_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cv_versions.id", ondelete="SET NULL")
    )
    iteration: Mapped[int]
    document_kind: Mapped[DocumentKind] = mapped_column(str_enum(DocumentKind, "ats_document_kind"))
    status: Mapped[IterationStatus] = mapped_column(
        str_enum(IterationStatus, "ats_analysis_status")
    )
    selected: Mapped[bool] = mapped_column(default=False, server_default="false")
    scoring_version: Mapped[str] = mapped_column(String(30))
    score: Mapped[float | None]
    assessed_weight: Mapped[int | None]
    penalty: Mapped[int] = mapped_column(default=0, server_default="0")
    components: Mapped[list[dict[str, Any]]] = mapped_column(server_default=text("'[]'::jsonb"))
    keywords: Mapped[list[dict[str, Any]]] = mapped_column(server_default=text("'[]'::jsonb"))
    stuffing: Mapped[list[dict[str, Any]]] = mapped_column(server_default=text("'[]'::jsonb"))
    violations: Mapped[list[dict[str, Any]]] = mapped_column(server_default=text("'[]'::jsonb"))
    feedback: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    repairs_count: Mapped[int] = mapped_column(default=0, server_default="0")
    document: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    ledger: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    served_model: Mapped[str | None] = mapped_column(String(100))
    fallback_used: Mapped[bool] = mapped_column(default=False, server_default="false")
    request_id: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    cache_read_input_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    cache_creation_input_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    duration_ms: Mapped[int | None]
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)
