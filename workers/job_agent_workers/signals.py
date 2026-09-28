"""Celery signal handlers: logging ownership, task log context, error tracking, fork safety."""

from __future__ import annotations

from typing import Any

import structlog
from celery.signals import (
    setup_logging,
    task_failure,
    task_postrun,
    task_prerun,
    worker_process_init,
)

from app.core.config import get_settings
from app.core.logging import configure_logging
from job_agent_workers.runtime import get_runtime, reset_runtime


@setup_logging.connect
def _configure_logging(**_: Any) -> None:
    """Having a receiver here stops Celery from installing its own logging handlers."""
    configure_logging(get_settings(), component="worker")


@worker_process_init.connect
def _reset_after_fork(**_: Any) -> None:
    reset_runtime(close_connections=False)


@task_prerun.connect
def _bind_task_context(task_id: str | None = None, task: Any = None, **_: Any) -> None:
    structlog.contextvars.bind_contextvars(task_id=task_id, task_name=getattr(task, "name", None))


@task_postrun.connect
def _unbind_task_context(**_: Any) -> None:
    structlog.contextvars.unbind_contextvars("task_id", "task_name")


@task_failure.connect
def _report_task_failure(
    task_id: str | None = None,
    exception: BaseException | None = None,
    sender: Any = None,
    **_: Any,
) -> None:
    if exception is None:
        return
    get_runtime().error_tracker.capture_exception(
        exception, context={"task_id": task_id, "task_name": getattr(sender, "name", None)}
    )
