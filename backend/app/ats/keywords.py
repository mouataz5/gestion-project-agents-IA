"""Where a CV document mentions each job keyword, and whether the master CV backs it.

Zones of a document (a ``ParsedCV``, the master or a tailored version):

    SUM  the summary                        SKL  skill names and skills-section labels
    EXP  experience titles, bullets and detail lines; project names, bullets and detail lines
    LNG  the languages section              EDU  degrees, education bullets, certifications
    TTL  the headline lines, the summary and the most recent experience title

A keyword is *present* when a zone mentions it (synonym-aware, see ``taxonomy.mentions``),
*prominent* in SUM or SKL (in LNG too for a spoken language), *listed* in SKL and *demonstrated*
in EXP. It is *supported* when the master CV mentions it (``sources.master_texts``).

Classes: MATCHED (present and supported), AVAILABLE (supported, not used yet), MISSING (a genuine
gap: reported to the candidate, never added) and UNSUPPORTED (present without support: must be
zero, and never scores).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from fractions import Fraction

from pydantic import BaseModel, ConfigDict

from app.analysis.facts import years_since
from app.ats.requirements import JobRequirements, Keyword, education_from_text
from app.ats.sources import Source, build_sources, headline_lines, master_texts
from app.ats.taxonomy import TECH_CATEGORIES, Category, mentions
from app.ats.types import (
    EDUCATION_RANK,
    SENIORITY_RANK,
    EducationLevel,
    Importance,
    KeywordClass,
)
from app.cv.models import ExperienceEntry, ParsedCV
from app.jobs.normalize import infer_seniority

PRESENT = Fraction(4, 5)  # in the document, outside the summary and the skills section
PROMINENT = Fraction(1)
IMPORTANCE_WEIGHTS: dict[Importance, Fraction] = {
    Importance.REQUIRED: Fraction(1),
    Importance.PREFERRED: Fraction(1, 2),
}
_WORK_ENTRY = re.compile(r"[EP]\d+")  # experiences and projects, not education ("ED1")


@dataclass(frozen=True)
class Zones:
    summary: tuple[str, ...]
    skills: tuple[str, ...]
    experience: tuple[str, ...]
    languages: tuple[str, ...]
    education: tuple[str, ...]
    headline: tuple[str, ...]
    title: tuple[str, ...]

    @property
    def outside_skills(self) -> tuple[str, ...]:
        """Every text once, except the skills section (TTL repeats texts of other zones)."""
        return self.summary + self.experience + self.languages + self.education + self.headline

    @property
    def everywhere(self) -> tuple[str, ...]:
        return self.skills + self.outside_skills


@dataclass(frozen=True)
class WorkLine:
    """A bullet or detail line of an experience or a project: what the candidate did."""

    entry: str  # "E1", "P2"
    path: str  # "experiences.0.bullets.1"
    text: str


def most_recent_experience(cv: ParsedCV) -> ExperienceEntry | None:
    """The current role, else the latest start; ties (and undated CVs) keep the CV's order."""

    def rank(item: tuple[int, ExperienceEntry]) -> tuple[bool, int, int, int]:
        index, experience = item
        dates = experience.dates
        start = dates.start if dates else None
        return (
            bool(dates and dates.is_current),
            start.year if start else 0,
            (start.month or 0) if start else 0,
            -index,
        )

    if not cv.experiences:
        return None
    return max(enumerate(cv.experiences), key=rank)[1]


def zones_of(cv: ParsedCV) -> Zones:
    labels = tuple(dict.fromkeys(skill.category for skill in cv.skills if skill.category))
    experience: list[str] = []
    for item in cv.experiences:
        experience.extend((item.title, *item.bullets, *item.details))
    for project in cv.projects:
        experience.extend((project.name, *project.bullets, *project.details))
    education = [text for item in cv.education for text in (item.degree, *item.bullets)]
    education.extend(cv.certifications)
    summary = (cv.summary,) if cv.summary else ()
    headline = tuple(headline_lines(cv))
    recent = most_recent_experience(cv)
    return Zones(
        summary=summary,
        skills=tuple(skill.name for skill in cv.skills) + labels,
        experience=tuple(text for text in experience if text),
        languages=tuple(cv.languages),
        education=tuple(text for text in education if text),
        headline=headline,
        title=headline + summary + ((recent.title,) if recent and recent.title else ()),
    )


def work_lines(cv: ParsedCV) -> list[WorkLine]:
    lines: list[WorkLine] = []
    for kind, entries in (("E", cv.experiences), ("P", cv.projects)):
        base = "experiences" if kind == "E" else "projects"
        for i, entry in enumerate(entries):
            for field in ("bullets", "details"):
                for j, text in enumerate(getattr(entry, field)):
                    lines.append(WorkLine(f"{kind}{i + 1}", f"{base}.{i}.{field}.{j}", text))
    return lines


def mentioned(texts: Sequence[str], term: str) -> bool:
    """Whether one of ``texts`` mentions ``term`` (texts are matched one by one, so a term never
    spans two of them)."""
    return any(mentions(text, term) for text in texts)


def education_level(texts: Sequence[str]) -> EducationLevel:
    """The highest degree level the texts state."""
    levels = [education_from_text(text).level for text in texts]
    return max(levels, key=EDUCATION_RANK.__getitem__, default=EducationLevel.NONE_STATED)


def candidate_seniority(cv: ParsedCV, years: int | None) -> str:
    """The seniority of the most recent title; without a seniority word, the years decide
    (5+ SENIOR, 2+ MID, else JUNIOR). UNKNOWN when neither is known (never guessed)."""
    recent = most_recent_experience(cv)
    if recent is not None:
        seniority = infer_seniority(recent.title).value
        if seniority in SENIORITY_RANK:
            return seniority
    if years is None:
        return "UNKNOWN"
    return "SENIOR" if years >= 5 else "MID" if years >= 2 else "JUNIOR"


@dataclass(frozen=True)
class MasterEvidence:
    """What the confirmed master CV proves. Candidate properties (years, seniority) come from
    here, never from a tailored document."""

    cv: ParsedCV
    sources: dict[str, Source]
    texts: tuple[str, ...]  # everything a keyword can be supported by
    zones: Zones
    years: int | None
    seniority: str
    education_level: EducationLevel

    def supports(self, term: str) -> bool:
        return mentioned(self.texts, term)

    def demonstrates(self, term: str) -> bool:
        return mentioned(self.zones.experience, term)

    def evidence(self, term: str) -> list[str]:
        """Source ids whose text mentions ``term``, in master order."""
        return [source.id for source in self.sources.values() if mentions(source.text, term)]

    def work_evidence(self, term: str) -> list[str]:
        """Bullets and detail lines of experiences and projects that mention ``term``."""
        return [
            source.id
            for source in self.sources.values()
            if _WORK_ENTRY.fullmatch(source.entry)
            and (".B" in source.id or ".D" in source.id)
            and mentions(source.text, term)
        ]


def master_evidence(cv: ParsedCV, today: date) -> MasterEvidence:
    starts = [
        date(item.dates.start.year, item.dates.start.month or 1, 1)
        for item in cv.experiences
        if item.dates and item.dates.start
    ]
    years = years_since(starts, today)
    zones = zones_of(cv)
    return MasterEvidence(
        cv=cv,
        sources=build_sources(cv),
        texts=tuple(master_texts(cv)),
        zones=zones,
        years=years,
        seniority=candidate_seniority(cv, years),
        education_level=education_level(zones.education),
    )


def is_technical(keyword: Keyword) -> bool:
    """Technical skills (the "skills" component): taxonomy categories of tools and methods, and
    listed skills the taxonomy does not know."""
    return keyword.category is None or keyword.category in TECH_CATEGORIES


class KeywordResult(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    term: str
    key: str
    category: Category | None
    importance: Importance
    status: KeywordClass
    present: bool
    prominent: bool
    listed: bool
    demonstrated: bool
    supported: bool
    technical: bool
    score: float  # 0, 0.8 or 1; an unsupported keyword never scores
    evidence: list[str]  # master source ids that mention it


def keyword_value(result: KeywordResult) -> Fraction:
    if result.status is not KeywordClass.MATCHED:
        return Fraction(0)
    return PROMINENT if result.prominent else PRESENT


def classify_keywords(
    zones: Zones, master: MasterEvidence, requirements: JobRequirements
) -> list[KeywordResult]:
    results: list[KeywordResult] = []
    for keyword in requirements.keywords:
        term = keyword.term
        supported = master.supports(term)
        present = mentioned(zones.everywhere, term)
        listed = mentioned(zones.skills, term)
        prominent_zones = zones.summary + zones.skills
        if keyword.category is Category.SPOKEN_LANGUAGE:
            prominent_zones += zones.languages
        if present and supported:
            status = KeywordClass.MATCHED
        elif present:
            status = KeywordClass.UNSUPPORTED
        elif supported:
            status = KeywordClass.AVAILABLE
        else:
            status = KeywordClass.MISSING
        result = KeywordResult(
            term=term,
            key=keyword.key,
            category=keyword.category,
            importance=keyword.importance,
            status=status,
            present=present,
            prominent=mentioned(prominent_zones, term),
            listed=listed,
            demonstrated=mentioned(zones.experience, term),
            supported=supported,
            technical=is_technical(keyword),
            score=0.0,
            evidence=master.evidence(term) if supported else [],
        )
        result.score = float(keyword_value(result))
        results.append(result)
    return results
