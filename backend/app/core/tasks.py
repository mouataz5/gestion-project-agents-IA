"""Names of Celery tasks and queues shared by the API (producer) and the workers (consumer).

The backend enqueues tasks by name and never imports the workers package.
"""

from enum import StrEnum


class TaskName(StrEnum):
    PING = "system.ping"
    RUN_DIAGNOSTIC = "system.run_diagnostic"
    RUN_DISCOVERY = "jobs.run_discovery"
    RUN_ANALYSIS = "jobs.run_analysis"


class QueueName(StrEnum):
    DEFAULT = "default"
