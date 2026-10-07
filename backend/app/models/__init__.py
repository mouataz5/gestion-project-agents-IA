"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from app.models.analysis import JobAnalysis
from app.models.application import Application
from app.models.ats import AtsAnalysis, CvTailoring, RequirementsExtraction
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
from app.models.company import Company
from app.models.cv import (
    CvKind,
    CvStatus,
    CvVersion,
    DatePrecision,
    Education,
    Experience,
    Project,
)
from app.models.job import Job, JobSkill, JobSource

__all__ = [
    "DEFAULT_CANDIDATE_SLUG",
    "RUN_COUNTERS",
    "Application",
    "AtsAnalysis",
    "AuditLog",
    "AutomationRun",
    "Candidate",
    "CandidateSkill",
    "Company",
    "CvKind",
    "CvStatus",
    "CvTailoring",
    "CvVersion",
    "DatePrecision",
    "Education",
    "EventLevel",
    "Experience",
    "Job",
    "JobAnalysis",
    "JobSkill",
    "JobSource",
    "Project",
    "RequirementsExtraction",
    "RunEvent",
    "RunStatus",
    "RunTrigger",
    "RunType",
]
