"""Tailored CVs and their ATS scores: API schemas (Phase 5)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.ats.keywords import KeywordResult
from app.ats.ledger import Origin, Repair, Violation
from app.ats.requirements import JobRequirements
from app.ats.scoring import ComponentScore, Gap, StuffingSignal
from app.ats.types import CallStatus, DocumentKind, IterationStatus, StopReason
from app.cv.models import ParsedCV
from app.models.cv import CvStatus
from app.schemas.common import AnalysisUsage, PromptInfo


class _Read(BaseModel):
    # Defaults are always serialized: generated TypeScript types mark these fields required.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class AtsIterationRead(_Read):
    """One version a tailoring looked at: iteration 0 is the master CV."""

    iteration: int
    document_kind: DocumentKind
    status: IterationStatus
    selected: bool = Field(description="The version that was stored")
    score: float | None = Field(description="None for a version the guard rejected")
    assessed_weight: int | None = Field(
        description="Points of 100 the posting let the score assess"
    )
    penalty: int
    components: list[ComponentScore]
    keywords: list[KeywordResult]
    stuffing: list[StuffingSignal]
    violations: list[Violation]
    repairs_count: int
    served_model: str | None
    request_id: str | None
    usage: AnalysisUsage
    duration_ms: int | None
    error_code: str | None
    error_message: str | None


class TailoringRead(_Read):
    """One tailoring attempt: provenance, scores against the target and the supported ceiling,
    why it stopped, the gaps only the candidate can close, and every version it scored."""

    id: uuid.UUID
    created_at: datetime
    status: CallStatus
    stop_reason: StopReason | None
    run_id: uuid.UUID | None
    provider: str
    is_mock: bool = Field(description="Produced offline by the mock provider, not by a model")
    requested_model: str
    served_model: str | None
    fallback_used: bool
    prompt: PromptInfo
    usage: AnalysisUsage
    duration_ms: int | None
    scoring_version: str
    weights: dict[str, int]
    target_score: float = Field(description="A target for the loop, never a promise")
    max_iterations: int
    baseline_score: float | None = Field(description="The master CV's score")
    final_score: float | None = Field(description="The stored version's score")
    ceiling_score: float | None = Field(
        description="The best score a version built only from the master CV can reach"
    )
    assessed_weight: int | None
    iterations_used: int
    best_iteration: int | None
    requirements: JobRequirements
    gaps: list[Gap]
    cv_version_id: uuid.UUID | None
    stale: bool = Field(description="Built from a master CV that is no longer the active one")
    error_code: str | None
    error_message: str | None
    iterations: list[AtsIterationRead]


class TailoredCvSummary(_Read):
    id: uuid.UUID
    version: int
    status: CvStatus
    application_id: uuid.UUID | None
    job_id: uuid.UUID | None
    job_title: str | None
    company: str | None
    base_version_id: uuid.UUID | None
    ats_score: float | None
    stale: bool = Field(description="Built from a master CV that is no longer the active one")
    created_at: datetime


class LedgerSource(_Read):
    """A fact of the base (master) CV, resolved from its source id."""

    id: str
    label: str = Field(description='For people: "Experience 1 · bullet 1"')
    text: str
    path: str | None


class LedgerEntry(_Read):
    path: str = Field(description='In the tailored structure: "experiences.0.bullets.0"')
    origin: Origin
    sources: list[LedgerSource]
    keywords: list[str]


class TailoredCvDetail(TailoredCvSummary):
    structure: ParsedCV
    extracted_text: str
    ledger: list[LedgerEntry]
    unused_sources: list[LedgerSource]
    repairs: list[Repair]
    tailoring: TailoringRead | None
