"""Offline, deterministic answers for the ATS tasks (mock provider).

``mock_job_requirements`` plays the extraction model with the same deterministic rules the
grounding uses (taxonomy scan, years and degree patterns), so mock results are reproducible and
every quote is verbatim.

``mock_cv_tailoring`` plays the tailoring model without writing a single new word: it lists the
backed keywords the feedback points at, adds one cited sentence to the summary for a keyword the
version no longer uses, and puts the bullets that mention the most job keywords first. Every text
stays verbatim, so it passes the guard without a repair.
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
from app.ats.taxonomy import (
    CATEGORY_LABELS,
    TECH_CATEGORIES,
    Category,
    canonical_key,
    category_of,
    mentions,
    scan_terms,
)


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


def _technical(category: str | None) -> bool:
    return category is None or Category(category) in TECH_CATEGORIES


def _source_texts(facts: Mapping[str, Any]) -> dict[str, str]:
    texts: dict[str, str] = {}
    if facts.get("summary"):
        texts["S"] = facts["summary"]["text"]
    for entry in (*facts["experiences"], *facts["projects"]):
        texts.update((bullet["id"], bullet["text"]) for bullet in entry["bullets"])
    return texts


def mock_cv_tailoring(context: Mapping[str, Any]) -> dict[str, Any]:
    current = context["current"]
    feedback = context["feedback"]
    keywords = context["requirements"]["keywords"]
    terms = [keyword["term"] for keyword in keywords]
    technical = {keyword["term"] for keyword in keywords if _technical(keyword["category"])}

    skills = [dict(skill) for skill in current["skills"]]
    listed = {canonical_key(skill["name"]) for skill in skills}
    wanted = [*feedback["not_listed"], *(hint["term"] for hint in feedback["available"])]
    for term in wanted:
        if term in technical and canonical_key(term) not in listed:
            category = category_of(term)
            skills.append(
                {"name": term, "category": CATEGORY_LABELS[category] if category else None}
            )
            listed.add(canonical_key(term))

    summary = dict(current["summary"]) if current["summary"] else None
    if summary is not None:
        texts = _source_texts(context["facts"])
        for hint in feedback["available"]:
            source = next((item for item in hint["sources"] if item in texts), None)
            if source is not None and texts[source] not in summary["text"]:
                summary = {
                    "text": f"{summary['text'].rstrip()} {texts[source]}",
                    "sources": [*summary["sources"], source],
                }
                break

    def ranked(bullets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(bullets, key=lambda bullet: -sum(mentions(bullet["text"], t) for t in terms))

    return {
        "summary": summary,
        "skills": skills,
        "experiences": [
            {"id": item["id"], "title": None, "bullets": ranked(item["bullets"])}
            for item in current["experiences"]
        ],
        "projects": [
            {"id": item["id"], "bullets": ranked(item["bullets"])} for item in current["projects"]
        ],
    }
