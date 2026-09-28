"""Fixtures for the worker tests (shared fixtures live in the repository-root conftest.py)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pytest

from app.core.config import Settings
from job_agent_workers.celery_app import celery_app
from job_agent_workers.runtime import WorkerRuntime, reset_runtime, set_runtime


class EagerTaskQueue:
    """Runs tasks synchronously in-process with Celery's ``apply()`` (no broker needed)."""

    def enqueue(
        self,
        task_name: str,
        *,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        queue: str | None = None,
    ) -> str:
        result = celery_app.tasks[task_name].apply(args=list(args), kwargs=dict(kwargs or {}))
        result.get(propagate=True)
        return str(result.id)

    def ping_workers(self, timeout: float = 1.0) -> list[str]:
        return ["celery@eager"]


@pytest.fixture
def eager_queue() -> EagerTaskQueue:
    return EagerTaskQueue()


@pytest.fixture
def worker_runtime(integration_settings: Settings) -> Iterator[WorkerRuntime]:
    runtime = WorkerRuntime.from_settings(integration_settings)
    set_runtime(runtime)
    yield runtime
    reset_runtime()
