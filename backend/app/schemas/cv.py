"""Master CV version API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.cv.models import ParsedCV
from app.models.cv import CvKind, CvStatus


class CvVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: CvKind
    version: int
    status: CvStatus
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    parser_version: str
    warning_count: int = Field(description="Warnings to review in the parsed structure")
    revised_from_id: uuid.UUID | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CvVersionDetail(CvVersionSummary):
    structure: ParsedCV
    extracted_text: str = Field(description="Plain text extracted from the uploaded file")
