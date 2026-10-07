"""The candidate facts block sent to the model (and cached across the jobs of a run).

Deterministic (sorted JSON, no timestamps) so the prompt prefix stays byte-identical, and minimal:
targets, work authorisation, languages, skills with their CV evidence, and the confirmed CV's
experience, projects, education and certifications. Contact details, employer and school names are
never included. Unknown values are written as "unknown", never guessed.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from app.analysis.languages import LEVEL_NAMES, CandidateLanguage, candidate_languages
from app.analysis.skills import BACKED, CandidateSkillEvidence
from app.cv.models import ParsedCV
from app.schemas.candidate import CandidateProfile, WorkAuthorization

UNKNOWN = "unknown"


class _Experience(Protocol):
    title: str
    start_date: date | None
    end_date: date | None
    is_current: bool
    bullets: list[str]
    technologies: list[str]


class _Project(Protocol):
    name: str
    bullets: list[str]
    technologies: list[str]


class _Education(Protocol):
    degree: str


class _Skill(Protocol):
    name: str
    strength: Any  # SkillStrength (StrEnum) or its value


@dataclass(frozen=True)
class CandidateFacts:
    text: str
    sha256: str
    cv_version_id: uuid.UUID | None
    target_roles: tuple[str, ...]
    skills: tuple[CandidateSkillEvidence, ...]
    languages: tuple[CandidateLanguage, ...] | None
    experience_years: int | None
    work_authorization: WorkAuthorization
    willing_to_relocate: bool | None


def _month(value: date | None) -> str:
    return value.strftime("%Y-%m") if value else UNKNOWN


def years_since(starts: Iterable[date | None], today: date) -> int | None:
    """Whole years since the earliest start: stable from day to day, so the facts (and the
    analyses and ATS scores cached on their hash) only change when the CV, the profile or the year
    changes. ``None`` when no start is known (never guessed)."""
    known = [start for start in starts if start is not None]
    if not known:
        return None
    return int((today - min(known)).days // 365.25)


def _experience_years(experiences: Sequence[_Experience], today: date) -> int | None:
    return years_since((item.start_date for item in experiences), today)


def build_candidate_facts(
    *,
    profile: CandidateProfile,
    cv: ParsedCV,
    cv_version_id: uuid.UUID | None,
    experiences: Sequence[_Experience],
    projects: Sequence[_Project],
    education: Sequence[_Education],
    skills: Sequence[_Skill],
    today: date,
) -> CandidateFacts:
    evidence = tuple(
        CandidateSkillEvidence(skill.name, str(getattr(skill.strength, "value", skill.strength)))
        for skill in skills
    )
    languages = candidate_languages(profile.application_defaults.languages, cv.languages)
    years = _experience_years(experiences, today)
    authorization = profile.work_authorization
    countries = profile.targets.countries
    data: dict[str, Any] = {
        "headline": profile.identity.headline or UNKNOWN,
        "target_roles": list(profile.targets.roles),
        "target_countries": {
            "primary": [country.code for country in countries.primary],
            "secondary": [country.code for country in countries.secondary],
        },
        "work_authorization": {
            "authorized_countries": [
                entry.country_code for entry in authorization.current_work_authorizations
            ],
            "visa_sponsorship_required": (
                UNKNOWN
                if authorization.visa_sponsorship_required is None
                else authorization.visa_sponsorship_required
            ),
        },
        "willing_to_relocate": (
            UNKNOWN
            if profile.relocation.willing_to_relocate is None
            else profile.relocation.willing_to_relocate
        ),
        "preferred_work_modes": (
            [mode.value for mode in profile.application_defaults.preferred_work_modes]
            if profile.application_defaults.preferred_work_modes
            else UNKNOWN
        ),
        "languages": (
            [
                {"language": item.language, "level": LEVEL_NAMES.get(item.level or 0, UNKNOWN)}
                for item in languages
            ]
            if languages
            else UNKNOWN
        ),
        "experience_years": years if years is not None else UNKNOWN,
        "skills": [
            {"name": item.name, "evidence": item.strength}
            for item in evidence
            if item.strength in BACKED
        ],
        "declared_without_cv_evidence": [
            item.name for item in evidence if item.strength not in BACKED
        ],
        "experience": [
            {
                "title": item.title,
                "period": f"{_month(item.start_date)} to "
                + ("present" if item.is_current else _month(item.end_date)),
                "highlights": list(item.bullets),
                "technologies": list(item.technologies),
            }
            for item in experiences
        ],
        "projects": [
            {
                "name": item.name,
                "highlights": list(item.bullets),
                "technologies": list(item.technologies),
            }
            for item in projects
        ],
        "education": [{"degree": item.degree} for item in education],
        "certifications": list(cv.certifications),
    }
    text = "Candidate facts (JSON):\n" + json.dumps(data, sort_keys=True, ensure_ascii=False)
    return CandidateFacts(
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        cv_version_id=cv_version_id,
        target_roles=tuple(profile.targets.roles),
        skills=evidence,
        languages=tuple(languages) if languages else None,
        experience_years=years,
        work_authorization=authorization,
        willing_to_relocate=profile.relocation.willing_to_relocate,
    )
