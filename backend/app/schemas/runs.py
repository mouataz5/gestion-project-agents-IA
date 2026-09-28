from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models import EventLevel, RunStatus, RunTrigger, RunType


class RunEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence: int
    created_at: datetime
    level: EventLevel
    stage: str
    message: str
    data: dict[str, Any]


class RunError(BaseModel):
    stage: str
    type: str
    message: str
    at: datetime


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_type: RunType
    trigger: RunTrigger
    status: RunStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None
    jobs_discovered: int
    jobs_processed: int
    jobs_qualified: int
    cv_generated: int
    applications_prepared: int
    applications_submitted: int
    error_count: int
    task_id: str | None


class RunDetail(RunSummary):
    errors: list[RunError]
    parameters: dict[str, Any]
    summary: dict[str, Any]
    events: list[RunEventOut]


class RunPage(BaseModel):
    items: list[RunSummary]
    total: int
    limit: int
    offset: int


class RunCreated(BaseModel):
    run_id: uuid.UUID
    status: RunStatus
    task_id: str | None
