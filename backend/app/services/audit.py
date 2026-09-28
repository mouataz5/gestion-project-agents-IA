"""Append-only audit trail of user and system actions."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.context import get_request_id
from app.core.redaction import redact
from app.models import AuditLog


class AuditAction(StrEnum):
    RUN_REQUESTED = "run.requested"
    RUN_ENQUEUE_FAILED = "run.enqueue_failed"
    RUN_STARTED = "run.started"
    RUN_FINISHED = "run.finished"


class Actor(StrEnum):
    USER = "user"
    SYSTEM = "system"
    WORKER = "worker"
    SCHEDULER = "scheduler"


class AuditService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        action: str,
        actor: str = Actor.SYSTEM,
        entity_type: str | None = None,
        entity_id: str | None = None,
        details: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            action=str(action),
            actor=str(actor),
            entity_type=entity_type,
            entity_id=entity_id,
            request_id=request_id or get_request_id(),
            details=redact(dict(details or {})),
        )
        self._session.add(entry)
        self._session.flush()
        return entry

    def list(
        self,
        *,
        limit: int,
        offset: int,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> tuple[list[AuditLog], int]:
        query = select(AuditLog)
        if action is not None:
            query = query.where(AuditLog.action == action)
        if entity_type is not None:
            query = query.where(AuditLog.entity_type == entity_type)
        if entity_id is not None:
            query = query.where(AuditLog.entity_id == entity_id)
        total = self._session.scalar(select(func.count()).select_from(query.subquery())) or 0
        items = self._session.scalars(
            query.order_by(AuditLog.sequence.desc()).limit(limit).offset(offset)
        ).all()
        return list(items), total
