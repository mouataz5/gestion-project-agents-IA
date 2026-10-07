"""Offline, deterministic answers for the ATS tasks (mock provider).

``mock_job_requirements`` plays the extraction model with the same deterministic rules the
grounding uses (taxonomy scan, years and degree patterns), so mock results are reproducible and
every quote is verbatim.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, get_args

from app.ats.requirements import (
    SeniorityValue,
    education_from_text,
    sentence_mentioning,
    years_from_text,
)
from app.ats.taxonomy import canonical_key, scan_terms


def mock_job_requirements(context: Mapping[str, Any]) -> dict[str, Any]:
    posting = context["posting"]
    text: str = posting["text"]
    required = {canonical_key(skill) for skill in posting["required_skills"]}
    keywords = [
        {
            "term": term.name,
            "category": term.category.value,
            "importance": "REQUIRED" if canonical_key(term.name) in required else "PREFERRED",
            "quote": sentence_mentioning(text, term.name) or term.name,
        }
        for term in scan_terms(text)
    ]
    years, years_quote = years_from_text(posting["experience_requirements"], text)
    education = education_from_text(posting["education_requirements"], text)
    seniority = posting["seniority"]
    return {
        "seniority": seniority if seniority in get_args(SeniorityValue) else "UNKNOWN",
        "min_years_experience": years,
        "years_quote": years_quote,
        "keywords": keywords,
        "responsibilities": list(posting["responsibilities"]),
        "education": {
            "level": education.level.value,
            "fields": education.fields,
            "equivalent_experience_accepted": education.equivalent_experience_accepted,
            "quote": education.quote,
        },
    }
