"""Shared pytest fixtures for the backend and workers test suites.

* Tests never read the developer's `.env` or exported variables (see `_isolated_environment`).
* Integration tests get a temporary PostgreSQL database, created and migrated once per session
  and dropped at the end. Tables are truncated after every test that uses it.
* When PostgreSQL/Redis are unreachable, integration tests are skipped with an explicit reason,
  unless `CI` or `REQUIRE_INTEGRATION` is set, in which case they fail.
* `--tests-json-report=PATH` writes per-test results (with their `feature` marker) that
  `scripts/update_tests_json.py` merges into `tests.json`.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

import pytest
import redis
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.errors import QueueUnavailableError
from app.db.base import Base
from app.db.migrate import upgrade
from app.db.session import create_db_engine, create_session_factory
from app.main import create_app

TEST_API_TOKEN = "test-api-token-0123456789abcdefghijklmnopqrstuvwxyz"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_API_TOKEN}"}
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://jobagent:jobagent@127.0.0.1:1/unreachable"
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"
DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://jobagent:jobagent@localhost:5432/jobagent"
DEFAULT_TEST_REDIS_URL = "redis://localhost:6379/15"


def _dotenv_value(key: str) -> str | None:
    """Read one value from the repository `.env` (used only to locate the test database)."""
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"') or None
    return None


def _admin_database_url() -> str:
    """TEST_DATABASE_URL, else DATABASE_URL from `.env` (as created by `make env`), else default.

    Tests never touch that database's data: they create and drop their own temporary databases.
    """
    return (
        os.environ.get("TEST_DATABASE_URL")
        or _dotenv_value("DATABASE_URL")
        or DEFAULT_TEST_DATABASE_URL
    )


def _integration_required() -> bool:
    truthy = {"1", "true", "yes"}
    return (
        os.environ.get("CI", "").lower() in truthy
        or os.environ.get("REQUIRE_INTEGRATION", "").lower() in truthy
    )


def _unavailable(service: str, exc: BaseException) -> NoReturn:
    message = (
        f"{service} is not reachable ({type(exc).__name__}). Start it (e.g. `make infra-up`) "
        f"or point TEST_DATABASE_URL / TEST_REDIS_URL at a running instance."
    )
    if _integration_required():
        pytest.fail(message)
    pytest.skip(message)


# ---------------------------------------------------------------------------
# Environment isolation & settings
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove every Settings-related variable so tests are hermetic."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    structlog.contextvars.clear_contextvars()
    yield
    get_settings.cache_clear()
    structlog.contextvars.clear_contextvars()


@pytest.fixture
def api_token() -> str:
    return TEST_API_TOKEN


@pytest.fixture
def make_settings(tmp_path: Path) -> Callable[..., Settings]:
    """Build Settings without reading any `.env` file; keyword arguments override defaults."""

    def _make(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "app_env": "test",
            "log_format": "json",
            "log_level": "INFO",
            "database_url": UNREACHABLE_DATABASE_URL,
            "redis_url": UNREACHABLE_REDIS_URL,
            "storage_dir": tmp_path / "storage",
            "api_auth_token": TEST_API_TOKEN,
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)  # type: ignore[call-arg]

    return _make


# ---------------------------------------------------------------------------
# Task queue test doubles
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EnqueuedTask:
    name: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    queue: str | None
    task_id: str


@dataclass
class RecordingTaskQueue:
    """Records enqueued tasks instead of sending them to a broker."""

    workers: list[str] = field(default_factory=lambda: ["celery@test-worker"])
    calls: list[EnqueuedTask] = field(default_factory=list)

    def enqueue(
        self,
        task_name: str,
        *,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        queue: str | None = None,
    ) -> str:
        task_id = f"task-{len(self.calls) + 1}"
        self.calls.append(EnqueuedTask(task_name, tuple(args), dict(kwargs or {}), queue, task_id))
        return task_id

    def ping_workers(self, timeout: float = 1.0) -> list[str]:
        return list(self.workers)


class UnavailableTaskQueue:
    """Simulates a broker outage."""

    def enqueue(
        self,
        task_name: str,
        *,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        queue: str | None = None,
    ) -> str:
        raise QueueUnavailableError("Task queue unavailable")

    def ping_workers(self, timeout: float = 1.0) -> list[str]:
        raise QueueUnavailableError("Task queue unavailable")


@pytest.fixture
def recording_queue() -> RecordingTaskQueue:
    return RecordingTaskQueue()


@pytest.fixture
def unavailable_queue() -> UnavailableTaskQueue:
    return UnavailableTaskQueue()


# ---------------------------------------------------------------------------
# Apps & clients that do not need a database
# ---------------------------------------------------------------------------
@pytest.fixture
def unit_settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


@pytest.fixture
def unit_app(unit_settings: Settings, recording_queue: RecordingTaskQueue) -> FastAPI:
    return create_app(unit_settings, task_queue=recording_queue)


@pytest.fixture
def unit_client(unit_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(unit_app, headers=AUTH_HEADERS) as client:
        yield client


@pytest.fixture
def anonymous_client(unit_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(unit_app) as client:
        yield client


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------
@contextmanager
def _temporary_database(migrate: bool) -> Iterator[str]:
    admin_url = make_url(_admin_database_url())
    name = f"jobagent_test_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(
        admin_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        admin_engine.dispose()
        _unavailable("PostgreSQL", exc)
    url = admin_url.set(database=name).render_as_string(hide_password=False)
    try:
        if migrate:
            upgrade(url)
        yield url
    finally:
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin_engine.dispose()


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """URL of a migrated temporary database shared by the whole test session."""
    with _temporary_database(migrate=True) as url:
        yield url


@pytest.fixture
def empty_database_url() -> Iterator[str]:
    """URL of a brand-new, un-migrated database (for migration tests)."""
    with _temporary_database(migrate=False) as url:
        yield url


@pytest.fixture(scope="session")
def db_engine(postgres_url: str) -> Iterator[Engine]:
    engine = create_engine(postgres_url)
    yield engine
    engine.dispose()


@pytest.fixture
def clean_db(db_engine: Engine) -> Iterator[None]:
    yield
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with db_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def redis_url() -> str:
    url = os.environ.get("TEST_REDIS_URL", DEFAULT_TEST_REDIS_URL)
    client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
    try:
        client.ping()
    except redis.RedisError as exc:
        _unavailable("Redis", exc)
    finally:
        client.close()
    return url


@pytest.fixture
def db_settings(
    make_settings: Callable[..., Settings], postgres_url: str, clean_db: None
) -> Settings:
    """Settings with a real database (Redis stays unreachable unless a test overrides it)."""
    return make_settings(database_url=postgres_url)


@pytest.fixture
def integration_settings(
    make_settings: Callable[..., Settings], postgres_url: str, redis_url: str, clean_db: None
) -> Settings:
    """Settings with a real database and a real Redis."""
    return make_settings(database_url=postgres_url, redis_url=redis_url)


@pytest.fixture
def session_factory(db_settings: Settings) -> Iterator[sessionmaker[Session]]:
    engine = create_db_engine(db_settings)
    yield create_session_factory(engine)
    engine.dispose()


@pytest.fixture
def app(integration_settings: Settings, recording_queue: RecordingTaskQueue) -> FastAPI:
    return create_app(integration_settings, task_queue=recording_queue)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, headers=AUTH_HEADERS) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# tests.json reporting
# ---------------------------------------------------------------------------
def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--tests-json-report",
        action="store",
        default=None,
        help="Write per-test results with their feature marker to this JSON file.",
    )


_FEATURES: dict[str, str] = {}
_OUTCOMES: dict[str, str] = {}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        marker = item.get_closest_marker("feature")
        _FEATURES[item.nodeid] = str(marker.args[0]) if marker and marker.args else "unassigned"


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    previous = _OUTCOMES.get(report.nodeid)
    if report.failed:
        outcome = "failed" if report.when == "call" else "error"
    elif report.skipped:
        outcome = "skipped"
    else:
        outcome = "passed"
    # A failure/error/skip in any phase wins over a pass in another phase.
    if previous in (None, "passed"):
        _OUTCOMES[report.nodeid] = outcome


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    target = session.config.getoption("--tests-json-report")
    if not target:
        return
    results = [
        {
            "test": nodeid,
            "feature": _FEATURES.get(nodeid, "unassigned"),
            "suite": nodeid.split("/", 1)[0],
            "status": outcome,
        }
        for nodeid, outcome in sorted(_OUTCOMES.items())
    ]
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
