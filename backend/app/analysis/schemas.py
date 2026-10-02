"""What the model must return (``JobAnalysisOutput``) and the verified results stored and exposed.

The output model is sent as a JSON schema through structured outputs, so it stays within the
supported subset: enums as literals, plain lists, nullable strings. Field descriptions guide the
model; the rules in this package verify and decide.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.analysis.types import VisaStatus

RoleRelevance = Literal["HIGH", "MEDIUM", "LOW"]
SeniorityFit = Literal["UNDER_QUALIFIED", "MATCH", "OVER_QUALIFIED", "UNKNOWN"]
Importance = Literal["REQUIRED", "PREFERRED"]
Strength = Literal["DEMONSTRATED", "LISTED"]
VisaSignal = Literal["POSITIVE", "LIKELY", "NEGATIVE", "RELOCATION"]

# --- model output ---------------------------------------------------------------------------------


class SkillAssessment(BaseModel):
    job_skill: str = Field(description="A skill the posting asks for, as written in the posting")
    importance: Importance
    candidate_skill: str | None = Field(
        description=(
            "Exact name of the candidate skill (from the candidate facts) that covers it, or null"
        )
    )


class LanguageRequirementOutput(BaseModel):
    language: str = Field(description="Language named in the posting")
    required: bool = Field(description="True when the posting makes it mandatory")
    level: str | None = Field(description="Level as stated (e.g. 'fluent', 'C1'), or null")


class VisaClaim(BaseModel):
    status: VisaStatus
    quote: str | None = Field(
        description="Verbatim sentence from the posting supporting the status, or null"
    )
    relocation_quote: str | None = Field(
        description="Verbatim sentence about relocation support, or null"
    )


class JobAnalysisOutput(BaseModel):
    role_relevance: RoleRelevance
    role_relevance_reason: str
    seniority_fit: SeniorityFit
    seniority_reason: str
    skills: list[SkillAssessment]
    language_requirements: list[LanguageRequirementOutput]
    visa: VisaClaim
    concerns: list[str]
    recommendation: Literal["APPLY", "REVIEW", "SKIP"]
    explanation: str = Field(
        description="2-4 sentences for the candidate: why the job fits or does not"
    )


# --- verified results (stored as JSON and returned by the API) -------------------------------------


class _Result(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class VisaEvidence(_Result):
    quote: str
    signal: VisaSignal
    source: Literal["RULE", "LLM"]


class VisaResult(_Result):
    status: VisaStatus
    evidence: list[VisaEvidence] = Field(default_factory=list)
    relocation_available: bool = False
    country_code: str | None = None
    sponsorship_needed: bool | None = Field(
        default=None, description="Whether the candidate needs sponsorship there (null: unknown)"
    )
    conflicting: bool = Field(
        default=False, description="The posting contains both positive and negative statements"
    )
    discarded_quotes: list[str] = Field(
        default_factory=list,
        description="Quotes the model gave that are not in the posting (ignored)",
    )


class SkillMatch(_Result):
    job_skill: str
    candidate_skill: str
    strength: Strength
    source: Literal["EXACT", "LLM"]


class LanguageCheck(_Result):
    language: str
    required: bool
    level: str | None = None
    candidate_level: str | None = None
    met: bool | None = None


class RelevanceResult(_Result):
    role_relevance: RoleRelevance
    role_relevance_reason: str
    seniority_fit: SeniorityFit
    seniority_reason: str
    required_skill_matches: list[SkillMatch] = Field(default_factory=list)
    preferred_skill_matches: list[SkillMatch] = Field(default_factory=list)
    skill_gaps: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(
        default_factory=list,
        description="Matches the model claimed without CV evidence (removed)",
    )
    required_count: int = 0
    required_coverage: float | None = None
    language_requirements: list[LanguageCheck] = Field(default_factory=list)
    languages_met: bool | None = None
    concerns: list[str] = Field(default_factory=list)
    reasoning: str = ""
