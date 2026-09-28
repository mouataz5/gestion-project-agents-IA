import pytest
from celery.signals import setup_logging

from app.core.tasks import TaskName
from job_agent_workers.celery_app import celery_app

pytestmark = pytest.mark.feature("task-queue")


def test_worker_uses_the_shared_safe_configuration() -> None:
    conf = celery_app.conf

    assert conf.task_serializer == "json"
    assert list(conf.accept_content) == ["json"]
    assert conf.task_acks_late is True
    assert conf.task_ignore_result is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.worker_hijack_root_logger is False


def test_system_tasks_are_registered() -> None:
    assert {TaskName.PING.value, TaskName.RUN_DIAGNOSTIC.value} <= set(celery_app.tasks)


def test_application_owns_logging_configuration() -> None:
    # A connected `setup_logging` receiver stops Celery from configuring logging itself.
    assert setup_logging.receivers
