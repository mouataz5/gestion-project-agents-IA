"""Does the candidate need visa sponsorship to work in a given country? Computed from the profile's
declared work authorisations; never guessed (``None`` = unknown)."""

from __future__ import annotations

from app.schemas.candidate import AuthorizationStatus, WorkAuthorization

# EU/EEA member states and Switzerland: citizens of one may work in the others without a permit.
FREE_MOVEMENT = frozenset(
    {
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT",
        "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
        "IS", "LI", "NO", "CH",
    }
)  # fmt: skip


def sponsorship_needed(authorization: WorkAuthorization, country_code: str | None) -> bool | None:
    if authorization.sponsorship_required_when == "never" or (
        authorization.visa_sponsorship_required is False
    ):
        return False
    if country_code is None:
        return None
    entries = authorization.current_work_authorizations
    if any(entry.country_code == country_code for entry in entries):
        return False
    if country_code in FREE_MOVEMENT and any(
        entry.status is AuthorizationStatus.CITIZEN and entry.country_code in FREE_MOVEMENT
        for entry in entries
    ):
        return False
    if authorization.sponsorship_required_when in ("always", "work_permit_needed"):
        return True
    if authorization.visa_sponsorship_required is True:
        return True
    return None
