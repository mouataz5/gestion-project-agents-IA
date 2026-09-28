import time
from collections.abc import Callable

import pytest

from app.core.config import Settings
from app.core.errors import QueueUnavailableError
from app.core.queue import CeleryTaskQueue, create_celery

pytestmark = pytest.mark.feature("task-queue")


def test_celery_is_configured_for_safe_serialization(
    make_settings: Callable[..., Settings],
) -> None:
    celery = create_celery(make_settings(redis_url="redis://cache:6379/3"))

    assert celery.conf.broker_url == "redis://cache:6379/3"
    assert celery.conf.task_serializer == "json"
    assert celery.conf.result_serializer == "json"
    assert list(celery.conf.accept_content) == ["json"]
    assert celery.conf.timezone == "Africa/Tunis"
    assert celery.conf.enable_utc is True


def test_celery_reliability_settings(make_settings: Callable[..., Settings]) -> None:
    conf = create_celery(make_settings()).conf

    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.task_ignore_result is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.worker_hijack_root_logger is False
    assert conf.worker_redirect_stdouts is False
    assert conf.task_default_queue == "default"


def test_enqueue_fails_fast_when_broker_is_down(
    make_settings: Callable[..., Settings],
) -> None:
    queue = CeleryTaskQueue(create_celery(make_settings()))  # broker points to 127.0.0.1:1

    started = time.monotonic()
    with pytest.raises(QueueUnavailableError):
        queue.enqueue("system.ping")

    assert time.monotonic() - started < 5, "an outage must not block API requests"


def test_worker_ping_raises_queue_unavailable_when_broker_is_down(
    make_settings: Callable[..., Settings],
) -> None:
    queue = CeleryTaskQueue(create_celery(make_settings()))

    with pytest.raises(QueueUnavailableError):
        queue.ping_workers(timeout=0.5)
