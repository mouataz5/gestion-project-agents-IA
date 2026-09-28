"""Celery application for the workers.

Start a worker (from the repository root):

    uv run celery -A job_agent_workers.celery_app:celery_app worker --loglevel=INFO
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.queue import create_celery
from job_agent_workers import signals  # noqa: F401  (connects the signal handlers)

settings = get_settings()
configure_logging(settings, component="worker")

celery_app = create_celery(settings, include=["job_agent_workers.tasks.system"])
