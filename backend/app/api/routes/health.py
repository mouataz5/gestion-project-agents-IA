"""Public liveness/readiness probes (used by Docker health checks). No secrets, no details."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app import __version__
from app.api.deps import HealthServiceDep
from app.schemas.health import ComponentStatus, LivenessResponse, ReadinessResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LivenessResponse, summary="Liveness probe")
def live() -> LivenessResponse:
    """The process is up and serving requests."""
    return LivenessResponse(service="backend", version=__version__)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={503: {"model": ReadinessResponse, "description": "A critical dependency is down"}},
)
def ready(health: HealthServiceDep, response: Response) -> ReadinessResponse:
    """Database reachable, migrations at head, Redis reachable, storage writable.

    Public endpoint: failure details are hidden (see `/system/status` for details).
    """
    result = health.readiness(include_details=False)
    if result.status is not ComponentStatus.OK:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
