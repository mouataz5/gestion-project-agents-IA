"""Shared vocabulary of the ATS engine."""

from __future__ import annotations

from enum import StrEnum


class Importance(StrEnum):
    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"


class KeywordSource(StrEnum):
    LISTED = "LISTED"  # in the posting's structured skill lists
    LANGUAGE = "LANGUAGE"  # in the posting's language list
    SCANNED = "SCANNED"  # a taxonomy term found in the posting text
    EXTRACTED = "EXTRACTED"  # read by the model, grounded in the posting text


class EducationLevel(StrEnum):
    NONE_STATED = "NONE_STATED"
    BACHELOR = "BACHELOR"
    MASTER = "MASTER"
    PHD = "PHD"


EDUCATION_RANK: dict[EducationLevel, int] = {
    EducationLevel.NONE_STATED: 0,
    EducationLevel.BACHELOR: 1,
    EducationLevel.MASTER: 2,
    EducationLevel.PHD: 3,
}

SENIORITY_RANK: dict[str, int] = {
    "INTERN": 0,
    "JUNIOR": 1,
    "MID": 2,
    "SENIOR": 3,
    "LEAD": 4,
    "PRINCIPAL": 5,
}


class KeywordClass(StrEnum):
    MATCHED = "MATCHED"  # in the document and backed by the master CV
    AVAILABLE = "AVAILABLE"  # backed by the master CV but not (yet) in the document
    MISSING = "MISSING"  # a genuine gap: not in the master CV - reported, never added
    UNSUPPORTED = "UNSUPPORTED"  # in the document without master CV evidence - must be zero


class StopReason(StrEnum):
    TARGET_REACHED = "TARGET_REACHED"
    ONLY_UNSUPPORTED_GAINS = "ONLY_UNSUPPORTED_GAINS"
    NO_IMPROVEMENT = "NO_IMPROVEMENT"
    MAX_ITERATIONS = "MAX_ITERATIONS"
    GUARD_REJECTED = "GUARD_REJECTED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
