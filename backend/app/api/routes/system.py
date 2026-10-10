"""System information and detailed component status (authenticated)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import __version__
from app.api.deps import HealthServiceDep, SettingsDep, require_api_token
from app.ats.scoring import SCORING_VERSION
from app.core.clock import utcnow
from app.core.phases import PHASES
from app.llm.factory import effective_llm_provider
from app.schemas.system import PhaseInfo, SecretsStatus, SystemConfig, SystemInfo, SystemStatus
from app.services.health import aggregate_status

router = APIRouter(prefix="/system", tags=["system"], dependencies=[Depends(require_api_token)])


@router.get("/info", response_model=SystemInfo, summary="Safe configuration and roadmap")
def system_info(settings: SettingsDep) -> SystemInfo:
    summary = settings.safe_summary()
    effective = effective_llm_provider(settings)
    summary["llm_effective_provider"] = effective.name
    summary["llm_effective_reason"] = effective.reason
    summary["ats_scoring_version"] = SCORING_VERSION
    return SystemInfo(
        name=settings.app_name,
        version=__version__,
        environment=settings.app_env.value,
        api_prefix=settings.api_prefix,
        mock_mode=settings.mock_mode,
        auto_submit=settings.auto_submit,
        auth_enabled=settings.auth_enabled,
        config=SystemConfig.model_validate(summary),
        secrets=SecretsStatus.model_validate(summary["secrets_configured"]),
        phases=[
            PhaseInfo(number=p.number, name=p.name, status=p.status, summary=p.summary)
            for p in PHASES
        ],
        warnings=settings.security_warnings(),
    )


@router.get("/status", response_model=SystemStatus, summary="Detailed component health")
def system_status(health: HealthServiceDep) -> SystemStatus:
    components = health.full_status()
    return SystemStatus(
        status=aggregate_status(components), components=components, checked_at=utcnow()
    )
