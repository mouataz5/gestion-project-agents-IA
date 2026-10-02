"""Explicit qualification rules: APPLY / REVIEW / SKIP from the verified analysis fields.

No opaque score: every decision lists its reasons. SKIP only for clear blockers; APPLY only when
everything that can be checked is positive; everything else is REVIEW (a human decides).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis.types import Recommendation, VisaStatus

APPLY_MIN_REQUIRED_COVERAGE = 0.6


@dataclass(frozen=True)
class QualificationInput:
    role_relevance: str  # HIGH | MEDIUM | LOW
    seniority_fit: str  # MATCH | UNDER_QUALIFIED | OVER_QUALIFIED | UNKNOWN
    required_count: int
    required_coverage: float | None
    languages_met: bool | None
    visa_status: VisaStatus
    sponsorship_needed: bool | None


@dataclass(frozen=True)
class Qualification:
    recommendation: Recommendation
    reasons: list[str]


def qualify(data: QualificationInput) -> Qualification:
    blockers: list[str] = []
    if data.sponsorship_needed is True and data.visa_status is VisaStatus.SPONSORSHIP_NOT_AVAILABLE:
        blockers.append(
            "The posting rules out visa sponsorship, which you need to work in this country."
        )
    if data.role_relevance == "LOW":
        blockers.append("The role is not a match for your target roles.")
    if data.languages_met is False:
        blockers.append("A required language is missing from your profile and CV.")
    if blockers:
        return Qualification(Recommendation.SKIP, blockers)

    checks: list[str] = []  # what to verify before applying
    positives: list[str] = []

    if data.role_relevance == "HIGH":
        positives.append("Strong match for your target roles.")
    else:
        checks.append("The role only partly matches your target roles.")

    if data.seniority_fit == "MATCH":
        positives.append("Your experience matches the seniority asked for.")
    elif data.seniority_fit == "UNKNOWN":
        positives.append("The seniority is not stated in the posting.")
    elif data.seniority_fit == "UNDER_QUALIFIED":
        checks.append("The role asks for a more senior profile than your CV shows.")
    else:
        checks.append("The role looks more junior than your experience.")

    if data.required_count == 0 or data.required_coverage is None:
        checks.append("The posting lists no required skills to check against your CV.")
    else:
        matched = round(data.required_coverage * data.required_count)
        text = f"{matched} of {data.required_count} required skills are backed by your CV."
        if data.required_coverage >= APPLY_MIN_REQUIRED_COVERAGE:
            positives.append(text)
        else:
            checks.append(text)

    if data.sponsorship_needed is False:
        positives.append("You do not need sponsorship to work there.")
    elif data.visa_status is VisaStatus.SPONSORSHIP_CONFIRMED:
        positives.append("Visa sponsorship is confirmed by the posting.")
    elif data.visa_status is VisaStatus.SPONSORSHIP_LIKELY and data.sponsorship_needed is True:
        positives.append(
            "Visa sponsorship is likely: the posting is open to international candidates."
        )
    elif data.sponsorship_needed is True:
        checks.append("Visa sponsorship is not mentioned: check with the employer before applying.")
    else:
        checks.append(
            "Your work authorization for this location is unclear (no country or no "
            "sponsorship statement)."
        )

    if data.languages_met is None:
        checks.append("Add your languages to the profile so language requirements can be checked.")
    else:
        positives.append("No required language is missing.")

    if checks:
        return Qualification(Recommendation.REVIEW, checks + positives)
    return Qualification(Recommendation.APPLY, positives)
