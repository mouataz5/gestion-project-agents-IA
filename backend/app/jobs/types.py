"""Enumerations shared by the job model, the sources and the API."""

from __future__ import annotations

from enum import StrEnum


class PostingDateStatus(StrEnum):
    KNOWN = "KNOWN"  # timestamp provided by the source
    ESTIMATED = "ESTIMATED"  # derived from relative text ("2 days ago"); basis recorded
    UNKNOWN = "UNKNOWN"  # never counted as "posted in the last 24 hours"


class WindowStatus(StrEnum):
    IN_WINDOW = "IN_WINDOW"
    OUT_OF_WINDOW = "OUT_OF_WINDOW"
    UNKNOWN_DATE = "UNKNOWN_DATE"


class RemoteStatus(StrEnum):
    REMOTE = "REMOTE"
    HYBRID = "HYBRID"
    ONSITE = "ONSITE"
    UNKNOWN = "UNKNOWN"


class EmploymentType(StrEnum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    CONTRACT = "CONTRACT"
    TEMPORARY = "TEMPORARY"
    INTERNSHIP = "INTERNSHIP"
    UNKNOWN = "UNKNOWN"


class Seniority(StrEnum):
    INTERN = "INTERN"
    JUNIOR = "JUNIOR"
    MID = "MID"
    SENIOR = "SENIOR"
    LEAD = "LEAD"
    PRINCIPAL = "PRINCIPAL"
    UNKNOWN = "UNKNOWN"


class AtsType(StrEnum):
    GREENHOUSE = "GREENHOUSE"
    LEVER = "LEVER"
    ASHBY = "ASHBY"
    SMARTRECRUITERS = "SMARTRECRUITERS"
    WORKDAY = "WORKDAY"
    LINKEDIN = "LINKEDIN"
    INDEED = "INDEED"
    GENERIC = "GENERIC"
    OTHER = "OTHER"


class SkillImportance(StrEnum):
    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
