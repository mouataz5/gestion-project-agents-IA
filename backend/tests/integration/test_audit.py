import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.services.audit import AuditService

pytestmark = [pytest.mark.feature("audit-log"), pytest.mark.integration]


def test_entries_are_redacted_and_carry_the_request_id(
    session_factory: sessionmaker[Session],
) -> None:
    structlog.contextvars.bind_contextvars(request_id="req-42")

    with session_factory() as session:
        entry = AuditService(session).record(
            action="run.requested",
            actor="user",
            entity_type="automation_run",
            entity_id="123",
            details={"token": "abc", "note": "ok"},
        )
        session.commit()

        assert entry.request_id == "req-42"
        assert entry.details == {"token": "[REDACTED]", "note": "ok"}
        assert entry.sequence >= 1


def test_audit_log_api_lists_newest_first_and_filters(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        audit = AuditService(session)
        audit.record(action="run.requested", entity_type="automation_run", entity_id="a")
        audit.record(action="run.started", entity_type="automation_run", entity_id="a")
        audit.record(action="run.requested", entity_type="automation_run", entity_id="b")
        session.commit()

    page = client.get("/api/v1/audit-logs").json()
    assert page["total"] == 3
    assert [(item["action"], item["entity_id"]) for item in page["items"]] == [
        ("run.requested", "b"),
        ("run.started", "a"),
        ("run.requested", "a"),
    ]

    requested = client.get("/api/v1/audit-logs", params={"action": "run.requested"}).json()
    assert requested["total"] == 2

    entity = client.get(
        "/api/v1/audit-logs", params={"entity_type": "automation_run", "entity_id": "a"}
    ).json()
    assert entity["total"] == 2
