"""Candidate profile: YAML loading/merging/validation, import/export and the candidate record.

The database holds the live profile (``candidates.profile``). ``candidate/profile.yaml`` plus
the optional git-ignored ``candidate/profile.local.yaml`` override are the seed and the
import/export format: they are read on first use and when the user asks for an import.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ConflictError, NotFoundError
from app.models import DEFAULT_CANDIDATE_SLUG, Candidate
from app.schemas.candidate import CandidateProfile
from app.services.skills import SkillService

PROFILE_FILE = "profile.yaml"
LOCAL_OVERRIDE_FILE = "profile.local.yaml"

# Fields the application answer engine needs. When empty they are reported as
# NEEDS_USER_INPUT; the system asks the user instead of guessing.
REQUIRED_INPUT_FIELDS: tuple[str, ...] = (
    "contact.email",
    "contact.phone",
    "identity.location.country_code",
    "work_authorization.visa_sponsorship_required",
    "relocation.willing_to_relocate",
    "targets.roles",
    "targets.countries.primary",
    "application_defaults.notice_period",
    "application_defaults.salary_expectations",
    "application_defaults.earliest_start_date",
    "application_defaults.languages",
    "application_defaults.preferred_work_modes",
)


class ProfileNotFoundError(AppError):
    status_code = 404
    code = "profile_not_found"


class ProfileValidationError(AppError):
    status_code = 422
    code = "invalid_profile"

    def __init__(self, message: str, details: list[dict[str, Any]]) -> None:
        super().__init__(message, details=details)
        self.details: list[dict[str, Any]] = details


# ---------------------------------------------------------------------------------------------
# YAML documents
# ---------------------------------------------------------------------------------------------


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge mappings; lists and scalars from ``override`` replace ``base``."""
    merged = copy.deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def parse_profile(data: Any) -> CandidateProfile:
    """Validate a profile document; errors carry dotted field paths but never the input."""
    try:
        return CandidateProfile.model_validate(data)
    except ValidationError as exc:
        details = [
            {
                "loc": ".".join(str(part) for part in error["loc"]),
                "msg": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        raise ProfileValidationError("The candidate profile is invalid", details) from exc


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        raise ProfileValidationError(
            f"{path.name} is not valid YAML{where}",
            [{"loc": path.name, "msg": "invalid YAML", "type": "yaml_error"}],
        ) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ProfileValidationError(
            f"{path.name} must contain a mapping",
            [{"loc": path.name, "msg": "expected a mapping", "type": "type_error"}],
        )
    return data


def load_profile(candidate_dir: Path) -> CandidateProfile:
    """Load ``profile.yaml`` merged with the optional ``profile.local.yaml`` override."""
    path = candidate_dir / PROFILE_FILE
    if not path.is_file():
        raise ProfileNotFoundError(
            f"No {PROFILE_FILE} found in the candidate folder; create it from the template"
        )
    data = _read_yaml(path)
    override = candidate_dir / LOCAL_OVERRIDE_FILE
    if override.is_file():
        data = deep_merge(data, _read_yaml(override))
    return parse_profile(data)


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str | list | dict) and len(value) == 0)


def needs_user_input(profile: CandidateProfile) -> list[str]:
    """Required fields that are still empty, as dotted paths."""
    missing: list[str] = []
    for path in REQUIRED_INPUT_FIELDS:
        value: Any = profile
        for part in path.split("."):
            value = getattr(value, part, None)
        if _is_empty(value):
            missing.append(path)
    return missing


def profile_to_yaml(profile: CandidateProfile, *, include_private: bool = False) -> str:
    """YAML export. Private contact details are blanked unless explicitly requested."""
    data = profile.model_dump(mode="json")
    if not include_private:
        data["contact"] = dict.fromkeys(data["contact"])
    header = "# Candidate profile exported by the AI Job Application Agent.\n" + (
        "# Contains PRIVATE contact details: keep it out of Git (use profile.local.yaml).\n"
        if include_private
        else "# Private contact details are omitted from this export.\n"
    )
    return header + yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=False
    )


def changed_sections(before: CandidateProfile, after: CandidateProfile) -> list[str]:
    """Top-level profile sections that differ (for audit entries: names only, no values)."""
    old, new = before.model_dump(mode="json"), after.model_dump(mode="json")
    return sorted(key for key in new if old.get(key) != new.get(key))


# ---------------------------------------------------------------------------------------------
# Candidate records
# ---------------------------------------------------------------------------------------------


class CandidateService:
    def __init__(self, session: Session, *, candidate_dir: Path) -> None:
        self._session = session
        self._candidate_dir = candidate_dir

    @staticmethod
    def profile_of(candidate: Candidate) -> CandidateProfile:
        return CandidateProfile.model_validate(candidate.profile)

    def get_by_slug(self, slug: str) -> Candidate:
        candidate = self._session.scalar(select(Candidate).where(Candidate.slug == slug))
        if candidate is None:
            raise NotFoundError(f"Candidate {slug!r} not found")
        return candidate

    def get_or_import_default(self) -> tuple[Candidate, bool]:
        """The default candidate, imported from the YAML files on first use.

        Returns ``(candidate, created)``.
        """
        existing = self._session.scalar(
            select(Candidate).where(Candidate.slug == DEFAULT_CANDIDATE_SLUG)
        )
        if existing is not None:
            return existing, False
        profile = load_profile(self._candidate_dir)
        try:
            with self._session.begin_nested():
                candidate = self.create(DEFAULT_CANDIDATE_SLUG, profile)
        except IntegrityError:
            # Another request imported it concurrently.
            return self.get_by_slug(DEFAULT_CANDIDATE_SLUG), False
        return candidate, True

    def create(self, slug: str, profile: CandidateProfile) -> Candidate:
        candidate = Candidate(slug=slug, profile_version=1)
        _apply_profile(candidate, profile)
        self._session.add(candidate)
        self._session.flush()
        SkillService(self._session).refresh(candidate)
        return candidate

    def lock(self, candidate: Candidate) -> Candidate:
        """Re-read the candidate row with ``FOR UPDATE`` (serialises concurrent edits)."""
        self._session.refresh(candidate, with_for_update=True)
        return candidate

    def update_profile(
        self, candidate: Candidate, profile: CandidateProfile, *, expected_version: int
    ) -> list[str]:
        """Replace the profile (optimistic concurrency). Returns the changed sections."""
        self.lock(candidate)
        if candidate.profile_version != expected_version:
            raise ConflictError(
                "The profile was changed by someone else; reload it and apply your edits again",
                details={
                    "expected_version": expected_version,
                    "current_version": candidate.profile_version,
                },
            )
        return self._replace(candidate, profile)

    def import_from_files(self, candidate: Candidate) -> list[str]:
        """Reload the profile from the YAML files (explicit user action)."""
        profile = load_profile(self._candidate_dir)
        self.lock(candidate)
        return self._replace(candidate, profile)

    def _replace(self, candidate: Candidate, profile: CandidateProfile) -> list[str]:
        changed = changed_sections(self.profile_of(candidate), profile)
        _apply_profile(candidate, profile)
        candidate.profile_version += 1
        self._session.flush()
        if "core_skills" in changed:
            SkillService(self._session).refresh(candidate)
        return changed


def _apply_profile(candidate: Candidate, profile: CandidateProfile) -> None:
    candidate.profile = profile.model_dump(mode="json")
    identity = profile.identity
    candidate.full_name = identity.full_name
    candidate.headline = identity.headline
    candidate.nationality = identity.nationality
    candidate.city = identity.location.city
    candidate.country = identity.location.country
    candidate.country_code = identity.location.country_code
    candidate.visa_sponsorship_required = profile.work_authorization.visa_sponsorship_required
    candidate.willing_to_relocate = profile.relocation.willing_to_relocate


def export_filename(candidate: Candidate, *, today: date) -> str:
    return f"profile-{candidate.slug}-{today.isoformat()}.yaml"
