"""System self-test executed by a worker and recorded as a DIAGNOSTIC automation run.

It proves the whole foundation end to end: API → broker → worker → database/Redis/storage →
run log → dashboard.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.models import EventLevel, RunStatus
from app.schemas.health import ComponentStatus
from app.services.audit import Actor, AuditAction, AuditService
from app.services.health import HealthService
from app.services.runs import RunRecorder

logger = get_logger(__name__)


class DiagnosticsService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        health: HealthService,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._health = health

    def execute(self, run_id: uuid.UUID, *, task_id: str | None = None) -> dict[str, Any]:
        passed: list[str] = []
        failed: list[str] = []
        with RunRecorder(self._session_factory, run_id, task_id=task_id) as recorder:
            self._audit(AuditAction.RUN_STARTED, run_id, {"task_id": task_id})

            warnings = self._settings.security_warnings()
            recorder.event(
                "diagnostic.configuration",
                "Configuration loaded",
                level=EventLevel.WARNING if warnings else EventLevel.INFO,
                data={
                    "environment": self._settings.app_env.value,
                    "mock_mode": self._settings.mock_mode,
                    "auto_submit": self._settings.auto_submit,
                    "warnings": warnings,
                },
            )

            checks = (
                self._health.check_database,
                self._health.check_migrations,
                self._health.check_redis,
                self._health.check_storage,
            )
            for check in checks:
                component = check()
                stage = f"diagnostic.{component.name}"
                if component.status is ComponentStatus.OK:
                    passed.append(component.name)
                    recorder.event(
                        stage,
                        f"{component.name} OK",
                        data={"detail": component.detail, "latency_ms": component.latency_ms},
                    )
                else:
                    failed.append(component.name)
                    recorder.error(
                        stage,
                        f"{component.name} {component.status.value}: {component.detail}",
                        data={"latency_ms": component.latency_ms},
                    )

            if not failed:
                status = RunStatus.SUCCEEDED
            elif passed:
                status = RunStatus.PARTIAL_SUCCESS
            else:
                status = RunStatus.FAILED
            summary: dict[str, Any] = {
                "checks_passed": passed,
                "checks_failed": failed,
                "mock_mode": self._settings.mock_mode,
            }
            recorder.finish(status, summary=summary)

        self._audit(AuditAction.RUN_FINISHED, run_id, {"status": status.value, **summary})
        logger.info("diagnostic.completed", run_id=str(run_id), status=status.value)
        return {"run_id": str(run_id), "status": status.value, **summary}

    def _audit(self, action: AuditAction, run_id: uuid.UUID, details: dict[str, Any]) -> None:
        with session_scope(self._session_factory) as session:
            AuditService(session).record(
                action=action,
                actor=Actor.WORKER,
                entity_type="automation_run",
                entity_id=str(run_id),
                details=details,
            )
