"""Per-process resources used by tasks (settings, database, storage, error tracking).

Created lazily on first use, so each forked worker process opens its own database connections.
Tests replace the runtime with ``set_runtime()``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.error_tracking import ErrorTracker, create_error_tracker
from app.core.storage import StorageProvider, create_storage
from app.db.session import create_db_engine, create_session_factory
from app.services.health import HealthService


@dataclass
class WorkerRuntime:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    storage: StorageProvider
    error_tracker: ErrorTracker
    health: HealthService

    @classmethod
    def from_settings(cls, settings: Settings) -> WorkerRuntime:
        engine = create_db_engine(settings, application_name="job-agent-worker")
        storage = create_storage(settings)
        return cls(
            settings=settings,
            engine=engine,
            session_factory=create_session_factory(engine),
            storage=storage,
            error_tracker=create_error_tracker(settings),
            health=HealthService(engine=engine, storage=storage, redis_url=settings.redis_dsn),
        )


_runtime: WorkerRuntime | None = None
_lock = threading.Lock()


def get_runtime() -> WorkerRuntime:
    global _runtime
    with _lock:
        if _runtime is None:
            _runtime = WorkerRuntime.from_settings(get_settings())
        return _runtime


def set_runtime(runtime: WorkerRuntime) -> None:
    global _runtime
    with _lock:
        _runtime = runtime


def reset_runtime(*, close_connections: bool = True) -> None:
    """Drop the current runtime.

    In a freshly forked child process pass ``close_connections=False``: connections inherited
    from the parent must be abandoned, not closed (closing them would break the parent's).
    """
    global _runtime
    with _lock:
        if _runtime is not None:
            _runtime.engine.dispose(close=close_connections)
        _runtime = None
