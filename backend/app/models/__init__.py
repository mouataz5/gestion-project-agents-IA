"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from app.models.audit_log import AuditLog
from app.models.automation_run import (
    RUN_COUNTERS,
    AutomationRun,
    EventLevel,
    RunEvent,
    RunStatus,
    RunTrigger,
    RunType,
)
from app.models.candidate import DEFAULT_CANDIDATE_SLUG, Candidate, CandidateSkill
from app.models.cv import (
    CvKind,
    CvStatus,
    CvVersion,
    DatePrecision,
    Education,
    Experience,
    Project,
)

__all__ = [
    "DEFAULT_CANDIDATE_SLUG",
    "RUN_COUNTERS",
    "AuditLog",
    "AutomationRun",
    "Candidate",
    "CandidateSkill",
    "CvKind",
    "CvStatus",
    "CvVersion",
    "DatePrecision",
    "Education",
    "EventLevel",
    "Experience",
    "Project",
    "RunEvent",
    "RunStatus",
    "RunTrigger",
    "RunType",
]
