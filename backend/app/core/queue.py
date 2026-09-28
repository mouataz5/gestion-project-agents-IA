"""Celery configuration shared by the API and the workers, plus the `TaskQueue` abstraction.

The API depends on the small `TaskQueue` protocol rather than on Celery directly, which keeps
routes testable (tests inject recording/unavailable/eager queues).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from celery import Celery
from kombu.exceptions import KombuError
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.errors import QueueUnavailableError
from app.core.tasks import QueueName

# Failures that mean "the broker cannot be reached" when publishing or broadcasting.
_BROKER_ERRORS: tuple[type[BaseException], ...] = (KombuError, RedisError, OSError)


def create_celery(settings: Settings, *, include: Sequence[str] = ()) -> Celery:
    app = Celery(
        "job_agent",
        broker=settings.broker_url,
        backend=settings.result_backend_url,
        include=list(include),
    )
    app.conf.update(
        # Security: JSON only, never pickle.
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        result_accept_content=["json"],
        # Time
        timezone=settings.timezone,
        enable_utc=True,
        # Reliability: a task is acknowledged only after it finished; one task at a time per
        # worker process so long pipeline steps do not starve others.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        # Tasks are fire-and-forget: outcomes are recorded as automation runs in PostgreSQL.
        # (A Redis result backend would also make publishing block for ~20 s when Redis is down.)
        task_ignore_result=True,
        task_time_limit=60 * 60,
        task_soft_time_limit=55 * 60,
        broker_transport_options={"visibility_timeout": 2 * 60 * 60},
        result_expires=24 * 60 * 60,
        task_default_queue=QueueName.DEFAULT.value,
        # Fail fast when the broker is down instead of blocking API requests.
        broker_connection_retry_on_startup=True,
        broker_connection_timeout=3,
        task_publish_retry_policy={
            "max_retries": 2,
            "interval_start": 0,
            "interval_step": 0.2,
            "interval_max": 0.5,
        },
        redis_socket_connect_timeout=3,
        redis_socket_timeout=5,
        # Logging is configured by the application (structlog), not by Celery.
        worker_hijack_root_logger=False,
        worker_redirect_stdouts=False,
    )
    return app


class TaskQueue(Protocol):
    def enqueue(
        self,
        task_name: str,
        *,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        queue: str | None = None,
    ) -> str:
        """Publish a task and return its id; raise `QueueUnavailableError` if impossible."""
        ...

    def ping_workers(self, timeout: float = 1.0) -> list[str]:
        """Return the names of workers that answered a ping."""
        ...


class CeleryTaskQueue:
    def __init__(self, celery: Celery) -> None:
        self._celery = celery

    def enqueue(
        self,
        task_name: str,
        *,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        queue: str | None = None,
    ) -> str:
        options: dict[str, Any] = {"retry": True, "ignore_result": True}
        if queue is not None:
            options["queue"] = queue
        try:
            result = self._celery.send_task(
                task_name, args=list(args), kwargs=dict(kwargs or {}), **options
            )
        except _BROKER_ERRORS as exc:
            raise QueueUnavailableError("The task queue (broker) is unavailable") from exc
        return str(result.id)

    def ping_workers(self, timeout: float = 1.0) -> list[str]:
        try:
            replies = self._celery.control.ping(timeout=timeout) or []
        except _BROKER_ERRORS as exc:
            raise QueueUnavailableError("The task queue (broker) is unavailable") from exc
        return sorted(name for reply in replies for name in reply)
