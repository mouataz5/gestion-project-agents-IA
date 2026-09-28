"""FastAPI dependencies: settings, database session, services from app state, authentication."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.core.queue import TaskQueue
from app.core.security import tokens_match
from app.core.storage import StorageProvider
from app.models import Candidate
from app.services.audit import Actor, AuditAction, AuditService
from app.services.candidate_profile import CandidateService
from app.services.health import HealthService

_bearer = HTTPBearer(auto_error=False, description="API token (API_AUTH_TOKEN)")


def get_settings_from_app(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_task_queue(request: Request) -> TaskQueue:
    queue: TaskQueue = request.app.state.task_queue
    return queue


def get_storage(request: Request) -> StorageProvider:
    storage: StorageProvider = request.app.state.storage
    return storage


def get_health_service(request: Request) -> HealthService:
    service: HealthService = request.app.state.health_service
    return service


def require_api_token(
    settings: Annotated[Settings, Depends(get_settings_from_app)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """Require ``Authorization: Bearer <API_AUTH_TOKEN>`` when a token is configured."""
    if settings.api_auth_token is None:
        return  # auth disabled (only possible outside production, see Settings validation)
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError()
    if not tokens_match(credentials.credentials, settings.api_auth_token.get_secret_value()):
        raise AuthenticationError()


def get_current_candidate(
    settings: Annotated[Settings, Depends(get_settings_from_app)],
    db: Annotated[Session, Depends(get_db)],
) -> Candidate:
    """The candidate the request acts on (the default one, imported from YAML on first use)."""
    candidate, created = CandidateService(
        db, candidate_dir=settings.candidate_dir
    ).get_or_import_default()
    if created:
        AuditService(db).record(
            action=AuditAction.CANDIDATE_IMPORTED,
            actor=Actor.SYSTEM,
            entity_type="candidate",
            entity_id=str(candidate.id),
            details={"source": "yaml", "reason": "first_use", "profile_version": 1},
        )
        db.commit()
    return candidate


SettingsDep = Annotated[Settings, Depends(get_settings_from_app)]
DbSession = Annotated[Session, Depends(get_db)]
TaskQueueDep = Annotated[TaskQueue, Depends(get_task_queue)]
HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
StorageDep = Annotated[StorageProvider, Depends(get_storage)]
CurrentCandidate = Annotated[Candidate, Depends(get_current_candidate)]
