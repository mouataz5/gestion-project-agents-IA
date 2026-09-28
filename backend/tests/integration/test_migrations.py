import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.migrate import downgrade, head_revisions, upgrade
from app.models import AuditLog

pytestmark = [pytest.mark.feature("database-migrations"), pytest.mark.integration]

FOUNDATION_TABLES = {"automation_runs", "automation_run_events", "audit_logs"}


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_there_is_a_single_head_revision() -> None:
    assert len(head_revisions()) == 1


def test_upgrade_creates_the_foundation_tables(empty_database_url: str) -> None:
    upgrade(empty_database_url)

    assert FOUNDATION_TABLES | {"alembic_version"} <= _tables(empty_database_url)


def test_models_and_migrations_are_in_sync(empty_database_url: str) -> None:
    upgrade(empty_database_url)
    engine = create_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            differences = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert differences == []


def test_downgrade_and_upgrade_roundtrip(empty_database_url: str) -> None:
    upgrade(empty_database_url)
    downgrade(empty_database_url, "base")

    assert _tables(empty_database_url) & FOUNDATION_TABLES == set()

    upgrade(empty_database_url)
    assert _tables(empty_database_url) >= FOUNDATION_TABLES


def test_audit_log_is_append_only(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        entry = AuditLog(actor="system", action="test.created", details={})
        session.add(entry)
        session.commit()
        entry_id = entry.id

    with session_factory() as session, pytest.raises(DBAPIError, match="append-only"):
        session.execute(
            text("UPDATE audit_logs SET action = 'tampered' WHERE id = :id"), {"id": entry_id}
        )

    with session_factory() as session, pytest.raises(DBAPIError, match="append-only"):
        session.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": entry_id})


def test_check_constraints_reject_unknown_enum_values(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session, pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO automation_runs (id, run_type, trigger, status) "
                "VALUES (:id, 'DIAGNOSTIC', 'API', 'NOT_A_STATUS')"
            ),
            {"id": uuid.uuid4()},
        )
