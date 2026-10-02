"""Enumerations of the job analysis (stored, exposed by the API and shown in the dashboard)."""

from __future__ import annotations

from enum import StrEnum


class VisaStatus(StrEnum):
    SPONSORSHIP_CONFIRMED = "SPONSORSHIP_CONFIRMED"
    SPONSORSHIP_LIKELY = "SPONSORSHIP_LIKELY"
    SPONSORSHIP_UNKNOWN = "SPONSORSHIP_UNKNOWN"
    SPONSORSHIP_NOT_AVAILABLE = "SPONSORSHIP_NOT_AVAILABLE"


class Recommendation(StrEnum):
    APPLY = "APPLY"
    REVIEW = "REVIEW"
    SKIP = "SKIP"


class AnalysisStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    REFUSED = "REFUSED"  # the model declined (safety classifier), even after the fallback
    FAILED = "FAILED"  # provider error, invalid output, timeout...
