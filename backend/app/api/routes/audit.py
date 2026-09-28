"""Audit trail (read-only, authenticated)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_api_token
from app.schemas.audit import AuditLogEntry, AuditLogPage
from app.services.audit import AuditService

router = APIRouter(prefix="/audit-logs", tags=["audit"], dependencies=[Depends(require_api_token)])


@router.get("", response_model=AuditLogPage, summary="List audit entries (newest first)")
def list_audit_logs(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> AuditLogPage:
    entries, total = AuditService(db).list(
        limit=limit,
        offset=offset,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    return AuditLogPage(
        items=[AuditLogEntry.model_validate(entry) for entry in entries],
        total=total,
        limit=limit,
        offset=offset,
    )
