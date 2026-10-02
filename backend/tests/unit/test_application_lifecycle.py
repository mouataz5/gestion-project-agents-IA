import pytest

from app.applications.lifecycle import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    ApplicationStatus,
    InvalidTransitionError,
    can_transition,
    ensure_transition,
)

pytestmark = pytest.mark.feature("application-lifecycle")

S = ApplicationStatus


def test_every_status_from_the_specification_exists() -> None:
    assert {status.value for status in ApplicationStatus} == {
        "DISCOVERED",
        "ANALYZED",
        "QUALIFIED",
        "CV_GENERATED",
        "READY_FOR_REVIEW",
        "APPROVED",
        "SUBMITTED",
        "HR_SCREEN",
        "INTERVIEW",
        "OFFER",
        "REJECTED",
        "WITHDRAWN",
        "BLOCKED",
        "MANUAL_ACTION_REQUIRED",
    }
    assert set(ALLOWED_TRANSITIONS) == set(ApplicationStatus)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (S.DISCOVERED, S.ANALYZED),
        (S.ANALYZED, S.QUALIFIED),
        (S.QUALIFIED, S.CV_GENERATED),
        (S.CV_GENERATED, S.READY_FOR_REVIEW),
        (S.READY_FOR_REVIEW, S.APPROVED),
        (S.APPROVED, S.SUBMITTED),
        (S.APPROVED, S.MANUAL_ACTION_REQUIRED),
        (S.APPROVED, S.BLOCKED),
        (S.MANUAL_ACTION_REQUIRED, S.SUBMITTED),
        (S.BLOCKED, S.READY_FOR_REVIEW),
        (S.SUBMITTED, S.HR_SCREEN),
        (S.HR_SCREEN, S.INTERVIEW),
        (S.INTERVIEW, S.OFFER),
        (S.INTERVIEW, S.REJECTED),
    ],
)
def test_pipeline_transitions_are_allowed(
    source: ApplicationStatus, target: ApplicationStatus
) -> None:
    assert can_transition(source, target)
    ensure_transition(source, target)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (S.DISCOVERED, S.SUBMITTED),  # never submit without the review and approval steps
        (S.READY_FOR_REVIEW, S.SUBMITTED),
        (S.CV_GENERATED, S.APPROVED),
        (S.REJECTED, S.INTERVIEW),
        (S.WITHDRAWN, S.DISCOVERED),
    ],
)
def test_other_transitions_are_rejected(
    source: ApplicationStatus, target: ApplicationStatus
) -> None:
    assert not can_transition(source, target)
    with pytest.raises(InvalidTransitionError) as excinfo:
        ensure_transition(source, target)
    assert excinfo.value.status_code == 409


def test_withdrawing_is_possible_until_the_outcome_is_known() -> None:
    for status in ApplicationStatus:
        if status in TERMINAL_STATUSES:
            assert ALLOWED_TRANSITIONS[status] == frozenset()
        else:
            assert can_transition(status, S.WITHDRAWN), status
