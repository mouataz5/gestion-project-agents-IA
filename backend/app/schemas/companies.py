"""Company watchlist (spec §6): field types shared by the API and ``crawler/companies.yaml``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)

from app.jobs.urls import UnsafeUrlError, validate_public_url


def _upper(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


def _public_url(value: str) -> str:
    try:
        return validate_public_url(value)
    except UnsafeUrlError as exc:
        raise ValueError(exc.message) from exc


CompanyAtsType = Literal[
    "GREENHOUSE", "LEVER", "ASHBY", "SMARTRECRUITERS", "WORKDAY", "GENERIC", "OTHER"
]
CompanyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
CareerUrl = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=500), AfterValidator(_public_url)
]
CountryCode = Annotated[str, BeforeValidator(_upper), StringConstraints(pattern=r"^[A-Z]{2}$")]
AtsTypeField = Annotated[CompanyAtsType, BeforeValidator(_upper)]
BoardToken = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
TargetRoles = list[
    Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompanyCreate(_Strict):
    name: CompanyName
    career_url: CareerUrl
    country_code: CountryCode | None = None
    ats_type: AtsTypeField = "GENERIC"
    board_token: BoardToken | None = None
    target_roles: TargetRoles = Field(default_factory=list, max_length=50)
    enabled: bool = True
    notes: Notes | None = None


class CompanyUpdate(_Strict):
    """Partial update: only the fields sent are changed (``null`` clears optional fields)."""

    name: CompanyName | None = None
    career_url: CareerUrl | None = None
    country_code: CountryCode | None = None
    ats_type: AtsTypeField | None = None
    board_token: BoardToken | None = None
    target_roles: TargetRoles | None = Field(default=None, max_length=50)
    enabled: bool | None = None
    notes: Notes | None = None


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    career_url: str
    country: str | None
    country_code: str | None
    ats_type: str
    board_token: str | None
    target_roles: list[str]
    enabled: bool
    notes: str | None
    last_checked_at: datetime | None
    last_check_status: str | None
    job_count: int = Field(description="Primary job records linked to this company")
    created_at: datetime
    updated_at: datetime


class CompanyImportResult(BaseModel):
    created: int
    updated: int
    unchanged: int
