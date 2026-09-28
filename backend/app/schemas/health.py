from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class ComponentStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class ComponentHealth(BaseModel):
    name: str
    status: ComponentStatus
    critical: bool
    latency_ms: float | None = None
    detail: str | None = None


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: ComponentStatus
    components: list[ComponentHealth]
    checked_at: datetime
