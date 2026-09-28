"""Component health checks used by the readiness probe, the system status page and diagnostics."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Literal

import redis
from sqlalchemy import Engine, text

from app.core.clock import utcnow
from app.core.queue import TaskQueue
from app.core.redaction import redact_text
from app.core.storage import StorageProvider
from app.db.migrate import current_revisions, head_revisions
from app.schemas.health import ComponentHealth, ComponentStatus, ReadinessResponse

CheckResult = str | tuple[ComponentStatus, str] | None
MAX_DETAIL_LENGTH = 240

ComponentName = Literal["database", "migrations", "redis", "storage", "worker"]


def run_check(name: str, *, critical: bool, check: Callable[[], CheckResult]) -> ComponentHealth:
    """Execute one check, measuring latency and turning exceptions into a redacted DOWN status."""
    started = time.perf_counter()
    try:
        result = check()
    except Exception as exc:  # a failing dependency must never break the health endpoint
        detail = redact_text(f"{type(exc).__name__}: {exc}")[:MAX_DETAIL_LENGTH]
        return ComponentHealth(
            name=name,
            status=ComponentStatus.DOWN,
            critical=critical,
            latency_ms=_elapsed_ms(started),
            detail=detail,
        )
    status: ComponentStatus = ComponentStatus.OK
    message: str | None = None
    if isinstance(result, tuple):
        status, message = result
    else:
        message = result
    return ComponentHealth(
        name=name,
        status=status,
        critical=critical,
        latency_ms=_elapsed_ms(started),
        detail=message,
    )


def aggregate_status(components: Sequence[ComponentHealth]) -> ComponentStatus:
    if any(c.critical and c.status is not ComponentStatus.OK for c in components):
        return ComponentStatus.DOWN
    if any(c.status is not ComponentStatus.OK for c in components):
        return ComponentStatus.DEGRADED
    return ComponentStatus.OK


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


class HealthService:
    def __init__(
        self,
        *,
        engine: Engine,
        storage: StorageProvider,
        redis_url: str,
        task_queue: TaskQueue | None = None,
    ) -> None:
        self._engine = engine
        self._storage = storage
        self._redis_url = redis_url
        self._task_queue = task_queue
        self._heads: set[str] | None = None

    # --- individual checks -----------------------------------------------------
    def check_database(self) -> ComponentHealth:
        def check() -> str:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return "connected"

        return run_check("database", critical=True, check=check)

    def check_migrations(self) -> ComponentHealth:
        def check() -> CheckResult:
            if self._heads is None:
                self._heads = head_revisions()
            with self._engine.connect() as connection:
                current = current_revisions(connection)
            if not current:
                return ComponentStatus.DOWN, "database schema not initialised: run migrations"
            if current != self._heads:
                return (
                    ComponentStatus.DOWN,
                    f"pending migrations: at {sorted(current)}, head is {sorted(self._heads)}",
                )
            return f"at head {', '.join(sorted(current))}"

        return run_check("migrations", critical=True, check=check)

    def check_redis(self) -> ComponentHealth:
        def check() -> str:
            client = redis.Redis.from_url(
                self._redis_url, socket_connect_timeout=1, socket_timeout=1
            )
            try:
                client.ping()
            finally:
                client.close()
            return "pong"

        return run_check("redis", critical=True, check=check)

    def check_storage(self) -> ComponentHealth:
        return run_check("storage", critical=True, check=self._storage.health_check)

    def check_worker(self) -> ComponentHealth:
        def check() -> CheckResult:
            if self._task_queue is None:
                return ComponentStatus.DEGRADED, "no task queue configured"
            workers = self._task_queue.ping_workers(timeout=1.0)
            if not workers:
                return ComponentStatus.DEGRADED, "no worker answered the ping"
            return f"{len(workers)} worker(s): {', '.join(workers)}"

        return run_check("worker", critical=False, check=check)

    # --- aggregates --------------------------------------------------------------
    def critical_components(self) -> list[ComponentHealth]:
        database = self.check_database()
        if database.status is ComponentStatus.OK:
            migrations = self.check_migrations()
        else:
            migrations = ComponentHealth(
                name="migrations",
                status=ComponentStatus.DOWN,
                critical=True,
                detail="skipped: database unreachable",
            )
        return [database, migrations, self.check_redis(), self.check_storage()]

    def readiness(self, *, include_details: bool = False) -> ReadinessResponse:
        components = self.critical_components()
        if not include_details:
            components = [c.model_copy(update={"detail": None}) for c in components]
        return ReadinessResponse(
            status=(
                ComponentStatus.OK
                if aggregate_status(components) is ComponentStatus.OK
                else ComponentStatus.DOWN
            ),
            components=components,
            checked_at=utcnow(),
        )

    def full_status(self) -> list[ComponentHealth]:
        return [*self.critical_components(), self.check_worker()]
