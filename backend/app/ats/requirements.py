"""What a job asks for, as the ATS engine scores it.

``build_requirements`` merges, by canonical skill key (highest importance wins):

1. the posting's structured skill lists (LISTED),
2. its language list (LANGUAGE, required),
3. taxonomy terms that are safe to scan for in its text (SCANNED, preferred),
4. the model's extraction (EXTRACTED) - only terms the posting mentions; quotes must be verbatim
   (otherwise replaced by the posting sentence that names the term).

Years of experience and the education level come from the extraction only when its quote is in
the posting, otherwise from deterministic patterns. Generic terms ("AI") are never keywords.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.analysis.job_text import posting_text
from app.analysis.visa import quote_in_text
from app.ats.taxonomy import (
    Category,
    canonical_key,
    canonical_name,
    category_of,
    fold,
    is_generic,
    mentions,
    scan_terms,
)
from app.ats.text import content_terms, sentences, stem
from app.ats.types import EducationLevel, Importance, KeywordSource
from app.models import Job

REQUIREMENTS_VERSION = "job-requirements.v1"

# "5+ years", "3 yrs", "5 ans", "4 Jahre"
YEARS_PATTERN = re.compile(r"(\d{1,2})\s*\+?\s*(?:years|yrs|ans|jahre)", re.IGNORECASE)

_SENIORITY_WORDS = frozenset(
    stem(word)
    for word in (
        "senior",
        "junior",
        "lead",
        "principal",
        "staff",
        "intern",
        "sr",
        "jr",
        "confirmé",
        "expérimenté",
        "débutant",
        "stagiaire",
    )
)

_EDUCATION_PATTERNS: tuple[tuple[EducationLevel, re.Pattern[str]], ...] = (
    (EducationLevel.PHD, re.compile(r"\b(?:ph\.?\s?d|doctorate|doctorat)\b", re.IGNORECASE)),
    (
        EducationLevel.MASTER,
        re.compile(
            r"\b(?:m\.?\s?sc|master'?s?|mba|m\.?\s?eng|bac\s*\+\s*5|dipl[oô]me d'ing[ée]nieur|"
            r"ing[ée]nieur dipl[oô]m[ée])\b",
            re.IGNORECASE,
        ),
    ),
    (
        EducationLevel.BACHELOR,
        re.compile(
            r"\b(?:b\.?\s?sc|bachelor'?s?|b\.?\s?eng|b\.?\s?s|licence|bac\s*\+\s*3)\b",
            re.IGNORECASE,
        ),
    ),
)
_EQUIVALENT = re.compile(
    r"\b(?:or\s+equivalent|equivalent\s+(?:practical\s+)?experience|ou\s+[ée]quivalent)",
    re.IGNORECASE,
)
STUDY_FIELDS: tuple[str, ...] = (
    "Computer Science",
    "Software Engineering",
    "Data Science",
    "Applied Mathematics",
    "Mathematics",
    "Statistics",
    "Physics",
    "Electrical Engineering",
    "Engineering",
    "Informatique",
    "Mathématiques",
)

# --- the model's structured output ---------------------------------------------------------------
# Plain models without length or range constraints: structured outputs drop them, so every limit
# is enforced by the grounding below instead.

SeniorityValue = Literal["INTERN", "JUNIOR", "MID", "SENIOR", "LEAD", "PRINCIPAL", "UNKNOWN"]


class ExtractedKeyword(BaseModel):
    term: str
    category: Category
    importance: Literal["REQUIRED", "PREFERRED"]
    quote: str


class ExtractedEducation(BaseModel):
    level: Literal["NONE_STATED", "BACHELOR", "MASTER", "PHD"]
    fields: list[str]
    equivalent_experience_accepted: bool | None
    quote: str | None


class RequirementsOutput(BaseModel):
    seniority: SeniorityValue
    min_years_experience: int | None
    years_quote: str | None
    keywords: list[ExtractedKeyword]
    responsibilities: list[str]
    education: ExtractedEducation


# --- the stored, grounded result -----------------------------------------------------------------


class _Result(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class Keyword(_Result):
    term: str
    key: str
    category: Category | None
    importance: Importance
    sources: list[KeywordSource]
    quote: str | None = None


class EducationRequirement(_Result):
    level: EducationLevel = EducationLevel.NONE_STATED
    fields: list[str] = []
    equivalent_experience_accepted: bool = False
    quote: str | None = None


class JobRequirements(_Result):
    version: str = REQUIREMENTS_VERSION
    title: str
    title_terms: list[str]
    seniority: str
    min_years: int | None = None
    years_quote: str | None = None
    education: EducationRequirement = EducationRequirement()
    keywords: list[Keyword] = []
    responsibilities: list[str] = []
    discarded: list[str] = []

    def keyword(self, key: str) -> Keyword | None:
        return next((keyword for keyword in self.keywords if keyword.key == key), None)


@dataclass(frozen=True)
class Posting:
    title: str
    seniority: str
    required_skills: tuple[str, ...]
    preferred_skills: tuple[str, ...]
    languages: tuple[str, ...]
    responsibilities: tuple[str, ...]
    experience_requirements: str | None
    education_requirements: str | None
    text: str  # every text of the posting: quotes and extracted terms must come from here


def posting_of(job: Job) -> Posting:
    return Posting(
        title=job.title,
        seniority=job.seniority.value,
        required_skills=tuple(job.required_skills),
        preferred_skills=tuple(job.preferred_skills),
        languages=tuple(job.languages),
        responsibilities=tuple(job.responsibilities),
        experience_requirements=job.experience_requirements,
        education_requirements=job.education_requirements,
        text=posting_text(job),
    )


def posting_context(posting: Posting) -> dict[str, Any]:
    """Structured inputs of the extraction request (the mock provider works from these)."""
    return {
        "title": posting.title,
        "seniority": posting.seniority,
        "required_skills": list(posting.required_skills),
        "preferred_skills": list(posting.preferred_skills),
        "languages": list(posting.languages),
        "responsibilities": list(posting.responsibilities),
        "experience_requirements": posting.experience_requirements,
        "education_requirements": posting.education_requirements,
        "text": posting.text,
    }


def sentence_mentioning(text: str, term: str) -> str | None:
    return next((sentence for sentence in sentences(text) if mentions(sentence, term)), None)


def title_terms(title: str) -> list[str]:
    """Content terms of a job title without seniority words ("Senior AI Engineer" -> ai, engin)."""
    return sorted(term for term in content_terms(title) if term not in _SENIORITY_WORDS)


def years_from_text(*texts: str | None) -> tuple[int | None, str | None]:
    """The highest "N years" figure of the first text that states one, with its sentence."""
    for text in texts:
        if not text:
            continue
        found = [(int(match.group(1)), match) for match in YEARS_PATTERN.finditer(text)]
        if found:
            years, match = max(found, key=lambda item: item[0])
            sentence = next(
                (part for part in sentences(text) if match.group(0) in part), match.group(0)
            )
            return years, sentence
    return None, None


def education_from_text(*texts: str | None) -> EducationRequirement:
    for text in texts:
        if not text:
            continue
        for level, pattern in _EDUCATION_PATTERNS:
            match = pattern.search(fold(text))
            if not match:
                continue
            sentence = next((part for part in sentences(text) if pattern.search(fold(part))), text)
            fields = [field for field in STUDY_FIELDS if mentions(sentence, field)]
            # "Applied Mathematics" also mentions "Mathematics": keep the most specific.
            fields = [
                field
                for field in fields
                if not any(other != field and mentions(other, field) for other in fields)
            ]
            return EducationRequirement(
                level=level,
                fields=fields,
                equivalent_experience_accepted=bool(_EQUIVALENT.search(fold(sentence))),
                quote=sentence,
            )
    return EducationRequirement()


def _seniority(posting: Posting, extraction: RequirementsOutput | None) -> str:
    if posting.seniority != "UNKNOWN" or extraction is None:
        return posting.seniority
    level = extraction.seniority
    if level != "UNKNOWN" and stem(level.lower()) in content_terms(posting.text):
        return level
    return "UNKNOWN"


class _Merger:
    def __init__(self) -> None:
        self.keywords: dict[str, Keyword] = {}

    def add(
        self,
        term: str,
        importance: Importance,
        source: KeywordSource,
        *,
        category: Category | None = None,
        quote: str | None = None,
    ) -> None:
        name = canonical_name(term)
        if not name or is_generic(name):
            return
        key = canonical_key(name)
        known = self.keywords.get(key)
        if known is None:
            self.keywords[key] = Keyword(
                term=name,
                key=key,
                category=category_of(name) or category,
                importance=importance,
                sources=[source],
                quote=quote,
            )
            return
        if importance is Importance.REQUIRED:
            known.importance = Importance.REQUIRED
        if source not in known.sources:
            known.sources.append(source)
        if known.quote is None:
            known.quote = quote
        if known.category is None:
            known.category = category


def build_requirements(
    posting: Posting, extraction: RequirementsOutput | None = None
) -> JobRequirements:
    text = posting.text
    merger = _Merger()
    discarded: list[str] = []

    for skill in posting.required_skills:
        merger.add(skill, Importance.REQUIRED, KeywordSource.LISTED)
    for skill in posting.preferred_skills:
        merger.add(skill, Importance.PREFERRED, KeywordSource.LISTED)
    for language in posting.languages:
        merger.add(
            language,
            Importance.REQUIRED,
            KeywordSource.LANGUAGE,
            category=Category.SPOKEN_LANGUAGE,
        )
    for term in scan_terms(text):
        merger.add(
            term.name,
            Importance.PREFERRED,
            KeywordSource.SCANNED,
            quote=sentence_mentioning(text, term.name),
        )

    responsibilities = list(dict.fromkeys(item.strip() for item in posting.responsibilities))
    min_years, years_quote = years_from_text(posting.experience_requirements, text)
    education = education_from_text(posting.education_requirements, text)

    if extraction is not None:
        for item in extraction.keywords:
            name = item.term.strip()
            if not name or is_generic(name):
                continue
            if not mentions(text, name):
                discarded.append(f"{name}: not in the posting")
                continue
            quote = item.quote if quote_in_text(item.quote, text) else None
            if quote is None or not mentions(quote, name):
                quote = sentence_mentioning(text, name)
            merger.add(
                name,
                Importance(item.importance),
                KeywordSource.EXTRACTED,
                category=item.category,
                quote=quote,
            )
        for responsibility in extraction.responsibilities:
            if not quote_in_text(responsibility, text):
                discarded.append(f"{responsibility}: not quoted from the posting")
            elif responsibility.strip() not in responsibilities:
                responsibilities.append(responsibility.strip())
        years = extraction.min_years_experience
        if (
            years is not None
            and extraction.years_quote
            and quote_in_text(extraction.years_quote, text)
            and str(years) in extraction.years_quote
        ):
            min_years, years_quote = years, extraction.years_quote
        stated = extraction.education
        if (
            stated.level != "NONE_STATED"
            and stated.quote
            and quote_in_text(stated.quote, text)
            and education.level is EducationLevel.NONE_STATED
        ):
            education = EducationRequirement(
                level=EducationLevel(stated.level),
                fields=[field for field in stated.fields if mentions(stated.quote, field)],
                equivalent_experience_accepted=bool(stated.equivalent_experience_accepted),
                quote=stated.quote,
            )

    keywords = list(merger.keywords.values())
    keywords.sort(key=lambda keyword: keyword.importance is not Importance.REQUIRED)
    return JobRequirements(
        title=posting.title,
        title_terms=title_terms(posting.title),
        seniority=_seniority(posting, extraction),
        min_years=min_years,
        years_quote=years_quote,
        education=education,
        keywords=keywords,
        responsibilities=responsibilities,
        discarded=discarded,
    )
