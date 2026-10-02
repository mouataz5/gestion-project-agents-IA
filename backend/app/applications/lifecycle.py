"""Application statuses (spec §18) and the allowed transitions (architecture §8.2).

Every status change goes through this table, so an application can never jump to SUBMITTED
without passing review and explicit approval.
"""

from __future__ import annotations

from enum import StrEnum

from app.core.errors import ConflictError


class ApplicationStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    ANALYZED = "ANALYZED"
    QUALIFIED = "QUALIFIED"
    CV_GENERATED = "CV_GENERATED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    HR_SCREEN = "HR_SCREEN"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    BLOCKED = "BLOCKED"
    MANUAL_ACTION_REQUIRED = "MANUAL_ACTION_REQUIRED"


S = ApplicationStatus

TERMINAL_STATUSES = frozenset({S.REJECTED, S.WITHDRAWN})

ALLOWED_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    S.DISCOVERED: frozenset({S.ANALYZED, S.WITHDRAWN}),
    S.ANALYZED: frozenset({S.QUALIFIED, S.WITHDRAWN}),
    S.QUALIFIED: frozenset({S.CV_GENERATED, S.WITHDRAWN}),
    S.CV_GENERATED: frozenset({S.READY_FOR_REVIEW, S.WITHDRAWN}),
    S.READY_FOR_REVIEW: frozenset({S.APPROVED, S.WITHDRAWN}),
    S.APPROVED: frozenset({S.SUBMITTED, S.MANUAL_ACTION_REQUIRED, S.BLOCKED, S.WITHDRAWN}),
    S.MANUAL_ACTION_REQUIRED: frozenset({S.SUBMITTED, S.WITHDRAWN}),
    S.BLOCKED: frozenset({S.READY_FOR_REVIEW, S.WITHDRAWN}),
    S.SUBMITTED: frozenset({S.HR_SCREEN, S.INTERVIEW, S.REJECTED, S.WITHDRAWN}),
    S.HR_SCREEN: frozenset({S.INTERVIEW, S.REJECTED, S.WITHDRAWN}),
    S.INTERVIEW: frozenset({S.OFFER, S.REJECTED, S.WITHDRAWN}),
    S.OFFER: frozenset({S.REJECTED, S.WITHDRAWN}),
    S.REJECTED: frozenset(),
    S.WITHDRAWN: frozenset(),
}


class InvalidTransitionError(ConflictError):
    code = "invalid_transition"


def can_transition(source: ApplicationStatus, target: ApplicationStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[source]


def ensure_transition(source: ApplicationStatus, target: ApplicationStatus) -> None:
    if not can_transition(source, target):
        raise InvalidTransitionError(
            f"An application cannot move from {source.value} to {target.value}",
            details={"from": source.value, "to": target.value},
        )
