"""Offline, deterministic answer to the ``job_analysis`` task (mock provider).

It plays the model's part with simple rules on the same structured inputs: title versus target
roles, years of experience versus the stated seniority, listed skills versus CV evidence, the
visa phrase rules. The verification and qualification rules then run exactly as for Claude.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.analysis.visa import find_visa_signals
from app.cv.evidence import canonical_key, mentions, technologies_in
from app.jobs.relevance import title_matches

_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:years|yrs|ans|jahre)", re.IGNORECASE)
_SENIORITY_YEARS = {"INTERN": 0, "JUNIOR": 0, "MID": 2, "SENIOR": 5, "LEAD": 7, "PRINCIPAL": 10}


def _seniority(job: Mapping[str, Any], years: float | None) -> tuple[str, str]:
    needed: list[int] = []
    if job["seniority"] in _SENIORITY_YEARS and job["seniority"] not in ("INTERN", "JUNIOR"):
        needed.append(_SENIORITY_YEARS[job["seniority"]])
    needed.extend(int(found) for found in _YEARS.findall(job.get("experience_requirements") or ""))
    if years is None:
        return "UNKNOWN", "Your CV has no dated experience to compare with."
    if job["seniority"] in ("INTERN", "JUNIOR") and years >= 5:
        return "OVER_QUALIFIED", f"A junior role; your CV shows {years} years of experience."
    if not needed:
        return "UNKNOWN", "The posting does not state the seniority or years of experience."
    if years >= max(needed):
        return "MATCH", f"About {max(needed)} years asked; your CV shows {years}."
    return "UNDER_QUALIFIED", f"About {max(needed)} years asked; your CV shows {years}."


def mock_job_analysis(context: Mapping[str, Any]) -> dict[str, Any]:
    job = context["job"]
    candidate = context["candidate"]
    title: str = job["title"]
    roles: list[str] = candidate["target_roles"]

    matching_role = next((role for role in roles if mentions(title, role)), None)
    if matching_role:
        relevance, relevance_reason = "HIGH", f"The title matches your target role {matching_role}."
    elif title_matches(title):
        relevance, relevance_reason = "MEDIUM", "An AI/ML role, but not one of your target roles."
    else:
        relevance, relevance_reason = "LOW", "Not an AI/ML role."
    seniority, seniority_reason = _seniority(job, candidate["experience_years"])

    backed = [s["name"] for s in candidate["skills"] if s["strength"] in ("DEMONSTRATED", "LISTED")]
    listed = [(skill, "REQUIRED") for skill in job["required_skills"]] + [
        (skill, "PREFERRED") for skill in job["preferred_skills"]
    ]
    if not listed:  # no structured requirements: candidate skills named in the posting
        all_names = [s["name"] for s in candidate["skills"]]
        listed = [(name, "REQUIRED") for name in technologies_in(job["posting_text"], all_names)]
    skills = [
        {
            "job_skill": skill,
            "importance": importance,
            "candidate_skill": next(
                (name for name in backed if canonical_key(name) == canonical_key(skill)), None
            ),
        }
        for skill, importance in listed
    ]

    signals = find_visa_signals(job["posting_text"])
    visa: dict[str, str | None]
    if signals.negative:
        visa = {"status": "SPONSORSHIP_NOT_AVAILABLE", "quote": signals.negative[0]}
    elif signals.positive:
        visa = {"status": "SPONSORSHIP_CONFIRMED", "quote": signals.positive[0]}
    elif signals.likely:
        visa = {"status": "SPONSORSHIP_LIKELY", "quote": signals.likely[0]}
    else:
        visa = {"status": "SPONSORSHIP_UNKNOWN", "quote": None}
    visa["relocation_quote"] = signals.relocation[0] if signals.relocation else None

    concerns: list[str] = []
    if job["employment_type"] in ("CONTRACT", "TEMPORARY"):
        concerns.append("Fixed-term or contract position.")
    if job["employment_type"] == "INTERNSHIP":
        concerns.append("Internship.")

    return {
        "role_relevance": relevance,
        "role_relevance_reason": relevance_reason,
        "seniority_fit": seniority,
        "seniority_reason": seniority_reason,
        "skills": skills,
        "language_requirements": [
            {"language": language, "required": True, "level": None} for language in job["languages"]
        ],
        "visa": visa,
        "concerns": concerns,
        "recommendation": {"HIGH": "APPLY", "MEDIUM": "REVIEW"}.get(relevance, "SKIP"),
        "explanation": (
            f"Offline mock analysis (no language model): {relevance_reason} " f"{seniority_reason}"
        ),
    }
