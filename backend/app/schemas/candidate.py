"""Candidate profile document (validated YAML/JSON) and candidate API schemas.

The profile holds identity, preferences and constraints. Experience, skills and dates come
from the confirmed master CV only. Unknown values stay ``null``: they are reported as
NEEDS_USER_INPUT and never guessed. Unknown keys are rejected so typos surface immediately.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.cv.models import EvidenceItem, SkillSource, SkillStrength
from app.schemas.cv import CvVersionSummary


def _upper_if_str(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


CountryCode = Annotated[
    str,
    BeforeValidator(_upper_if_str),
    StringConstraints(pattern=r"^[A-Z]{2}$"),
    Field(description="ISO 3166-1 alpha-2 country code", examples=["FR"]),
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Email = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
]


class _Strict(BaseModel):
    # Serialization schemas list defaulted fields as required: responses always include them.
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, json_schema_serialization_defaults_required=True
    )


class Location(_Strict):
    city: ShortText | None = None
    country: ShortText | None = None
    country_code: CountryCode | None = None


class Identity(_Strict):
    full_name: ShortText
    headline: ShortText | None = None
    nationality: ShortText | None = None
    location: Location = Field(default_factory=Location)


class Contact(_Strict):
    """Private: stored in the database, never committed to Git, hidden from default exports."""

    email: Email | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    linkedin_url: Annotated[str, StringConstraints(max_length=300)] | None = None
    github_url: Annotated[str, StringConstraints(max_length=300)] | None = None
    portfolio_url: Annotated[str, StringConstraints(max_length=300)] | None = None


class AuthorizationStatus(StrEnum):
    CITIZEN = "citizen"
    PERMANENT_RESIDENT = "permanent_resident"
    WORK_PERMIT = "work_permit"
    OTHER = "other"


class WorkAuthorizationEntry(_Strict):
    country_code: CountryCode
    status: AuthorizationStatus


class WorkAuthorization(_Strict):
    visa_sponsorship_required: bool | None = None
    sponsorship_required_when: Literal["always", "work_permit_needed", "never"] | None = None
    current_work_authorizations: list[WorkAuthorizationEntry] = Field(default_factory=list)


class Relocation(_Strict):
    willing_to_relocate: bool | None = None


class TargetCountry(_Strict):
    name: ShortText
    code: CountryCode


class TargetCountries(_Strict):
    primary: list[TargetCountry] = Field(default_factory=list)
    secondary: list[TargetCountry] = Field(default_factory=list)


class Targets(_Strict):
    roles: list[ShortText] = Field(default_factory=list, max_length=50)
    countries: TargetCountries = Field(default_factory=TargetCountries)


class LanguageLevel(StrEnum):
    NATIVE = "native"
    FLUENT = "fluent"
    PROFESSIONAL = "professional"
    INTERMEDIATE = "intermediate"
    BASIC = "basic"


class SpokenLanguage(_Strict):
    language: ShortText
    level: LanguageLevel


class WorkMode(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"


class SalaryExpectation(_Strict):
    currency: Annotated[
        str, BeforeValidator(_upper_if_str), StringConstraints(pattern=r"^[A-Z]{3}$")
    ]
    minimum: int = Field(ge=0)
    maximum: int | None = Field(default=None, ge=0)
    period: Literal["year", "month"] = "year"
    country_code: CountryCode | None = Field(
        default=None, description="Applies to this country only; null = default"
    )
    note: Annotated[str, StringConstraints(max_length=200)] | None = None

    @model_validator(mode="after")
    def _check_range(self) -> SalaryExpectation:
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("maximum must be greater than or equal to minimum")
        return self


class ApplicationDefaults(_Strict):
    notice_period: ShortText | None = None
    salary_expectations: list[SalaryExpectation] | None = None
    earliest_start_date: date | None = None
    languages: list[SpokenLanguage] | None = None
    preferred_work_modes: list[WorkMode] | None = None


class CvPolicy(_Strict):
    allow_title_changes: bool = False


class CandidateProfile(_Strict):
    schema_version: Literal[1] = 1
    identity: Identity
    contact: Contact = Field(default_factory=Contact)
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    relocation: Relocation = Field(default_factory=Relocation)
    targets: Targets = Field(default_factory=Targets)
    core_skills: list[ShortText] = Field(default_factory=list, max_length=100)
    application_defaults: ApplicationDefaults = Field(default_factory=ApplicationDefaults)
    cv_policy: CvPolicy = Field(default_factory=CvPolicy)


# ---------------------------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------------------------


class CandidateRead(BaseModel):
    id: uuid.UUID
    slug: str
    profile: CandidateProfile
    profile_version: int
    needs_user_input: list[str] = Field(
        description="Profile fields that are empty and must be provided by the user"
    )
    active_master_cv: CvVersionSummary | None
    created_at: datetime
    updated_at: datetime


class CandidateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_version: int = Field(
        ge=1, description="The version being edited; a stale version is rejected with 409"
    )
    profile: CandidateProfile


class CandidateSkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    normalized_name: str
    category: str | None
    strength: SkillStrength
    sources: list[SkillSource]
    evidence: list[EvidenceItem]
