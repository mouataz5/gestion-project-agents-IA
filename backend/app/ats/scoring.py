"""ATS score ``ats-score.v1``: deterministic, explainable and versioned (the model never grades
its own work).

    score = 100 x sum(weight x component) / sum(applicable weights), rounded half-up to one
            decimal, minus the stuffing penalty (5 points per signal type, at most 15), in 0..100

Components, each 0..1 (REQUIRED keywords weigh 1, PREFERRED 0.5):

    keywords (30)          0 absent, 0.8 present, 1 prominent (summary or skills section; the
                           languages section too for a spoken language); unsupported scores 0
    skills (20)            technical keywords: 0.5 listed in the skills section + 0.5 shown in
                           an experience or project
    experience (15)        min(1, candidate years / required years)
    responsibilities (15)  mean over the job's responsibilities of the best single bullet or
                           detail line's share of the responsibility's content terms
    title (10)             0.8 x share of the job-title terms in the headline, summary and most
                           recent title + 0.2 x candidate seniority >= the job's
    education (5)          0.8 x level met (0.5 when equivalent experience is accepted and the
                           years are met) + 0.2 x a stated field named; the level alone if the
                           job names no field
    formatting (5)         share of the structural checks F1-F6 passed

A component that does not apply (no keywords, no stated years, no responsibilities, no title
terms, no stated degree) leaves the formula and its weight is redistributed; ``assessed_weight``
says how many of the 100 points the posting let us assess, so a thin posting's score is never
mistaken for a strong match.

The *ceiling* is the best score any document built only from the master CV's evidence can reach
(``score_document <= ceiling`` for every truthful tailoring): gaps that would need untrue content
are reported as gaps for the candidate, never closed.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.ats.keywords import (
    IMPORTANCE_WEIGHTS,
    KeywordResult,
    MasterEvidence,
    WorkLine,
    Zones,
    classify_keywords,
    education_level,
    is_technical,
    keyword_value,
    mentioned,
    work_lines,
    zones_of,
)
from app.ats.requirements import JobRequirements
from app.ats.taxonomy import canonical_key, fold, scan_terms, skill_regex
from app.ats.text import NEUTRAL_TERMS, content_terms, term_words
from app.ats.types import (
    EDUCATION_RANK,
    SENIORITY_RANK,
    EducationLevel,
    Importance,
    KeywordClass,
)
from app.ats.weights import COMPONENTS, DEFAULT_WEIGHTS, validate_weights
from app.cv.models import ParsedCV

SCORING_VERSION = "ats-score.v1"

SUMMARY_MAX_WORDS = 80
SKILLS_RANGE = (3, 40)
BULLETS_PER_ROLE = (1, 6)
BULLET_CHARS = (20, 300)
DOCUMENT_MAX_WORDS = 900
FORMAT_CHECKS: dict[str, str] = {
    "F1": f"A summary of at most {SUMMARY_MAX_WORDS} words",
    "F2": f"{SKILLS_RANGE[0]} to {SKILLS_RANGE[1]} skills, no duplicates",
    "F3": "Every role has a title and a start date",
    "F4": f"{BULLETS_PER_ROLE[0]} to {BULLETS_PER_ROLE[1]} bullets per role",
    "F5": f"Bullets of {BULLET_CHARS[0]} to {BULLET_CHARS[1]} characters",
    "F6": f"At most {DOCUMENT_MAX_WORDS} words in all",
}

PENALTY_PER_SIGNAL = 5
MAX_PENALTY = 15
REPEAT_MIN = 3  # T1: mentions outside the skills section ...
REPEAT_MARGIN = 1  # ... and more than the master's own count + this margin
SUMMARY_MAX_DENSITY = Fraction(2, 5)  # T3: keyword mentions per summary word ...
SUMMARY_MAX_MENTIONS = 8  # ... or keyword mentions in all
BULLET_MIN_KEYWORDS = 4  # T4: keywords in one bullet ...
BULLET_MAX_SHARE = Fraction(3, 5)  # ... covering at least this share of its words


class _Result(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class ComponentScore(_Result):
    name: str
    weight: int
    applicable: bool
    score: float | None  # 0..1 (4 decimals); None when the component does not apply
    details: dict[str, Any] = {}


class StuffingCode(StrEnum):
    REPEATED_KEYWORD = "REPEATED_KEYWORD"  # T1
    SKILL_LIST = "SKILL_LIST"  # T2
    DENSE_SUMMARY = "DENSE_SUMMARY"  # T3
    DENSE_BULLET = "DENSE_BULLET"  # T4


class StuffingSignal(_Result):
    code: StuffingCode
    detail: str


class ScoreReport(_Result):
    scoring_version: str = SCORING_VERSION
    score: float
    assessed_weight: int  # points of 100 the posting lets us assess (applicable components)
    penalty: int = 0
    components: list[ComponentScore]
    keywords: list[KeywordResult]
    stuffing: list[StuffingSignal] = []

    def component(self, name: str) -> ComponentScore:
        return next(component for component in self.components if component.name == name)

    def keywords_with(self, status: KeywordClass) -> list[KeywordResult]:
        return [keyword for keyword in self.keywords if keyword.status is status]


class CeilingReport(_Result):
    scoring_version: str = SCORING_VERSION
    score: float
    assessed_weight: int
    components: list[ComponentScore]


class KeywordHint(_Result):
    term: str
    importance: Importance
    sources: list[str]  # master source ids that mention it


class Feedback(_Result):
    """What the next tailoring iteration may still improve, and what it must never add."""

    available: list[KeywordHint] = []  # backed by the master CV, not used yet
    not_listed: list[str] = []  # technical keywords used but missing from the skills section
    not_prominent: list[str] = []  # used, but neither in the summary nor the skills section
    not_demonstrated: list[KeywordHint] = []  # shown by the master's roles, not by this version
    title_terms: list[str] = []  # job-title words the master CV backs, missing from the top
    formatting: list[str] = []  # failed checks that a truthful version can pass
    forbidden: list[str] = []  # genuine gaps (and unsupported keywords): never add them
    violations: list[str] = []  # the previous iteration's guard violations


class GapKind(StrEnum):
    MISSING_KEYWORD = "MISSING_KEYWORD"
    NOT_DEMONSTRATED = "NOT_DEMONSTRATED"
    RESPONSIBILITY = "RESPONSIBILITY"
    TITLE_TERMS = "TITLE_TERMS"


class Gap(_Result):
    """A gap only the candidate can close, in the master CV, and only if it is true."""

    kind: GapKind
    subject: str
    importance: Importance | None = None
    terms: list[str] = []
    message: str


# --- parts ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Part:
    value: Fraction | None  # None: does not apply
    details: dict[str, Any] = field(default_factory=dict)


_NOT_APPLICABLE = _Part(None)


def _ratio(value: Fraction) -> float:
    return float(round(value, 4))


def _weighted(items: Sequence[tuple[Importance, Fraction]]) -> Fraction | None:
    total = sum((IMPORTANCE_WEIGHTS[importance] for importance, _ in items), Fraction(0))
    if not total:
        return None
    return sum((IMPORTANCE_WEIGHTS[imp] * value for imp, value in items), Fraction(0)) / total


def _keywords_part(results: Sequence[KeywordResult]) -> _Part:
    value = _weighted([(result.importance, keyword_value(result)) for result in results])
    if value is None:
        return _NOT_APPLICABLE
    counts = {status.value: 0 for status in KeywordClass}
    for result in results:
        counts[result.status.value] += 1
    return _Part(value, {"counts": counts})


def _skill_value(listed: bool, demonstrated: bool) -> Fraction:
    return Fraction(int(listed) + int(demonstrated), 2)


def _skills_part(results: Sequence[KeywordResult]) -> _Part:
    technical = [result for result in results if result.technical]
    value = _weighted(
        [
            (
                result.importance,
                (
                    _skill_value(result.listed, result.demonstrated)
                    if result.supported
                    else Fraction(0)
                ),
            )
            for result in technical
        ]
    )
    if value is None:
        return _NOT_APPLICABLE
    return _Part(
        value,
        {
            "listed": [result.term for result in technical if result.supported and result.listed],
            "demonstrated": [
                result.term for result in technical if result.supported and result.demonstrated
            ],
        },
    )


def _years_met(master: MasterEvidence, requirements: JobRequirements) -> bool:
    if master.years is None:
        return False
    return requirements.min_years is None or master.years >= requirements.min_years


def _experience_part(master: MasterEvidence, requirements: JobRequirements) -> _Part:
    required = requirements.min_years
    if required is None or required <= 0:
        return _NOT_APPLICABLE
    years = master.years
    value = Fraction(0) if years is None else min(Fraction(1), Fraction(years, required))
    return _Part(value, {"required_years": required, "candidate_years": years})


def responsibility_terms(text: str) -> frozenset[str]:
    return content_terms(text) - NEUTRAL_TERMS


@dataclass(frozen=True)
class _Coverage:
    responsibility: str
    terms: frozenset[str]
    value: Fraction
    covered: frozenset[str]
    best: str | None  # the path (document) or the entry (ceiling) that covers it best

    @property
    def missing(self) -> list[str]:
        return term_words(self.responsibility, self.terms - self.covered)


def _coverages(
    requirements: JobRequirements, candidates: Sequence[tuple[str, frozenset[str]]]
) -> list[_Coverage]:
    """Best coverage of each responsibility by one of ``candidates`` (label, terms); the first
    candidate wins a tie. Responsibilities without content terms are left out."""
    coverages: list[_Coverage] = []
    for responsibility in requirements.responsibilities:
        terms = responsibility_terms(responsibility)
        if not terms:
            continue
        best = _Coverage(responsibility, terms, Fraction(0), frozenset(), None)
        for label, candidate in candidates:
            covered = terms & candidate
            value = Fraction(len(covered), len(terms))
            if value > best.value:
                best = _Coverage(responsibility, terms, value, covered, label)
        coverages.append(best)
    return coverages


def _responsibilities_part(coverages: Sequence[_Coverage]) -> _Part:
    if not coverages:
        return _NOT_APPLICABLE
    value = sum((coverage.value for coverage in coverages), Fraction(0)) / len(coverages)
    return _Part(
        value,
        {
            "responsibilities": [
                {
                    "text": coverage.responsibility,
                    "coverage": _ratio(coverage.value),
                    "best_match": coverage.best,
                    "missing": coverage.missing,
                }
                for coverage in coverages
            ]
        },
    )


def _line_terms(lines: Sequence[WorkLine]) -> list[tuple[str, frozenset[str]]]:
    return [(line.path, content_terms(line.text)) for line in lines]


def _entry_terms(lines: Sequence[WorkLine]) -> list[tuple[str, frozenset[str]]]:
    """Each entry's bullets and detail lines together: everything a rewritten bullet of that
    entry may draw on."""
    entries: dict[str, frozenset[str]] = {}
    for line in lines:
        entries[line.entry] = entries.get(line.entry, frozenset()) | content_terms(line.text)
    return list(entries.items())


def _terms_of(texts: Sequence[str]) -> frozenset[str]:
    return frozenset().union(*(content_terms(text) for text in texts))


def _reachable_title_terms(master: MasterEvidence) -> frozenset[str]:
    """Terms a tailored version can put at the top: the headline is copied, and the summary may
    use the words of any source it cites (skills-section labels are not citable)."""
    return _terms_of([*(source.text for source in master.sources.values()), *master.zones.headline])


def seniority_met(candidate: str, job: str) -> bool:
    if job not in SENIORITY_RANK:
        return True  # the job states none
    return candidate in SENIORITY_RANK and SENIORITY_RANK[candidate] >= SENIORITY_RANK[job]


def _title_part(
    found_terms: frozenset[str], master: MasterEvidence, requirements: JobRequirements
) -> _Part:
    terms = requirements.title_terms
    if not terms:
        return _NOT_APPLICABLE
    found = [term for term in terms if term in found_terms]
    met = seniority_met(master.seniority, requirements.seniority)
    value = Fraction(4, 5) * Fraction(len(found), len(terms)) + Fraction(1, 5) * int(met)
    return _Part(
        value,
        {
            "found": term_words(requirements.title, found),
            "missing": term_words(requirements.title, set(terms) - set(found)),
            "candidate_seniority": master.seniority,
            "job_seniority": requirements.seniority,
            "seniority_met": met,
        },
    )


def _education_part(
    level: EducationLevel,
    texts: Sequence[str],
    master: MasterEvidence,
    requirements: JobRequirements,
) -> _Part:
    needed = requirements.education
    if needed.level is EducationLevel.NONE_STATED:
        return _NOT_APPLICABLE
    if EDUCATION_RANK[level] >= EDUCATION_RANK[needed.level]:
        level_value = Fraction(1)
    elif needed.equivalent_experience_accepted and _years_met(master, requirements):
        level_value = Fraction(1, 2)
    else:
        level_value = Fraction(0)
    details: dict[str, Any] = {
        "required_level": needed.level.value,
        "candidate_level": level.value,
        "level_score": _ratio(level_value),
    }
    if not needed.fields:
        return _Part(level_value, details)
    field_named = any(mentioned(texts, name) for name in needed.fields)
    details["field_named"] = field_named
    return _Part(Fraction(4, 5) * level_value + Fraction(1, 5) * int(field_named), details)


def word_count(text: str) -> int:
    return len(text.split())


def document_texts(cv: ParsedCV) -> list[str]:
    """Every text a rendering of ``cv`` shows."""
    texts = [*cv.header_lines, cv.summary or ""]
    for experience in cv.experiences:
        texts.extend((experience.title, experience.employer or "", experience.location or ""))
        texts.extend((experience.dates.text if experience.dates else "", *experience.bullets))
        texts.extend(experience.details)
    for education in cv.education:
        texts.extend((education.degree, education.institution or "", education.location or ""))
        texts.extend((education.dates.text if education.dates else "", *education.bullets))
        texts.extend(education.details)
    for project in cv.projects:
        texts.extend((project.name, project.dates.text if project.dates else ""))
        texts.extend((*project.bullets, *project.details))
    texts.extend(skill.name for skill in cv.skills)
    texts.extend(dict.fromkeys(skill.category for skill in cv.skills if skill.category))
    texts.extend((*cv.certifications, *cv.languages))
    for section in cv.other_sections:
        texts.extend((section.heading, *section.lines))
    return [text for text in texts if text]


def work_bullets(cv: ParsedCV) -> list[str]:
    """The bullets of every experience and project."""
    bullets = [bullet for item in cv.experiences for bullet in item.bullets]
    bullets.extend(bullet for item in cv.projects for bullet in item.bullets)
    return bullets


def formatting_checks(cv: ParsedCV) -> dict[str, bool]:
    keys = [canonical_key(skill.name) for skill in cv.skills]
    bullets = work_bullets(cv)
    return {
        "F1": bool(cv.summary) and word_count(cv.summary or "") <= SUMMARY_MAX_WORDS,
        "F2": SKILLS_RANGE[0] <= len(keys) <= SKILLS_RANGE[1] and len(set(keys)) == len(keys),
        "F3": all(
            item.title.strip() and item.dates is not None and item.dates.start is not None
            for item in cv.experiences
        ),
        "F4": all(
            BULLETS_PER_ROLE[0] <= len(item.bullets) <= BULLETS_PER_ROLE[1]
            for item in cv.experiences
        ),
        "F5": all(BULLET_CHARS[0] <= len(bullet) <= BULLET_CHARS[1] for bullet in bullets),
        "F6": sum(word_count(text) for text in document_texts(cv)) <= DOCUMENT_MAX_WORDS,
    }


def _formatting_part(checks: Mapping[str, bool]) -> _Part:
    return _Part(
        Fraction(sum(checks.values()), len(checks)),
        {
            "checks": [
                {"code": code, "label": FORMAT_CHECKS[code], "passed": passed}
                for code, passed in checks.items()
            ]
        },
    )


def _round_half_up(value: Fraction) -> Decimal:
    return Decimal(math.floor(value * 10 + Fraction(1, 2))) / 10


def _assessed(parts: Mapping[str, _Part], weights: Mapping[str, int]) -> int:
    return sum(weights[name] for name in COMPONENTS if parts[name].value is not None)


def _total(parts: Mapping[str, _Part], weights: Mapping[str, int]) -> Decimal:
    applicable = [name for name in COMPONENTS if parts[name].value is not None]
    denominator = _assessed(parts, weights)
    if not denominator:
        return Decimal(0)
    numerator = sum(
        (weights[name] * (parts[name].value or Fraction(0)) for name in applicable), Fraction(0)
    )
    return _round_half_up(100 * numerator / denominator)


def _components(parts: Mapping[str, _Part], weights: Mapping[str, int]) -> list[ComponentScore]:
    return [
        ComponentScore(
            name=name,
            weight=weights[name],
            applicable=parts[name].value is not None,
            score=None if parts[name].value is None else _ratio(parts[name].value or Fraction(0)),
            details=parts[name].details,
        )
        for name in COMPONENTS
    ]


# --- keyword stuffing (tailored documents only) ------------------------------------------------


def _count(texts: Sequence[str], term: str) -> int:
    regex = skill_regex(term)
    return sum(len(regex.findall(fold(text))) for text in texts)


def _covered_share(text: str, terms: Sequence[str]) -> Fraction:
    folded = fold(text)
    covered = [False] * len(folded)
    for term in terms:
        for match in skill_regex(term).finditer(folded):
            covered[match.start() : match.end()] = [True] * (match.end() - match.start())
    spans = [match.span() for match in re.finditer(r"\S+", folded)]
    if not spans:
        return Fraction(0)
    hit = sum(1 for start, end in spans if any(covered[start:end]))
    return Fraction(hit, len(spans))


def stuffing_signals(
    document: ParsedCV, zones: Zones, master: MasterEvidence, requirements: JobRequirements
) -> list[StuffingSignal]:
    """Signals of keyword stuffing that the master CV's own text does not already show (a dense
    master summary kept verbatim is the candidate's writing, not stuffing by the tailoring)."""
    own = {key for key, _ in _stuffing(master.cv, master.zones, master, requirements)}
    return [
        signal for key, signal in _stuffing(document, zones, master, requirements) if key not in own
    ]


def _stuffing(
    document: ParsedCV, zones: Zones, master: MasterEvidence, requirements: JobRequirements
) -> list[tuple[tuple[str, str], StuffingSignal]]:
    """(key, signal) pairs; the key names what the signal is about (a term, the summary text, a
    bullet), so a signal the master CV shows too is recognised."""
    terms = [keyword.term for keyword in requirements.keywords]
    signals: list[tuple[tuple[str, str], StuffingSignal]] = []

    def add(code: StuffingCode, subject: str, detail: str) -> None:
        signals.append(((code.value, subject), StuffingSignal(code=code, detail=detail)))

    for term in terms:  # T1
        count = _count(zones.outside_skills, term)
        if (
            count >= REPEAT_MIN
            and count > _count(master.zones.outside_skills, term) + REPEAT_MARGIN
        ):
            add(
                StuffingCode.REPEATED_KEYWORD,
                term,
                f"{term} appears {count} times outside the skills section",
            )
    keys = [canonical_key(skill.name) for skill in document.skills]  # T2
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        add(
            StuffingCode.SKILL_LIST,
            ",".join(duplicates),
            f"duplicate skills: {', '.join(duplicates)}",
        )
    elif len(keys) > SKILLS_RANGE[1]:
        add(
            StuffingCode.SKILL_LIST,
            str(len(keys)),
            f"{len(keys)} skills (at most {SKILLS_RANGE[1]})",
        )
    if document.summary:  # T3
        summary_mentions = sum(_count([document.summary], term) for term in terms)
        words = word_count(document.summary)
        if summary_mentions > SUMMARY_MAX_MENTIONS or (
            words and Fraction(summary_mentions, words) > SUMMARY_MAX_DENSITY
        ):
            add(
                StuffingCode.DENSE_SUMMARY,
                document.summary.strip(),
                f"{summary_mentions} keyword mentions in a {words}-word summary",
            )
    for bullet in work_bullets(document):  # T4
        found = [term for term in terms if mentioned([bullet], term)]
        if len(found) >= BULLET_MIN_KEYWORDS and _covered_share(bullet, found) >= BULLET_MAX_SHARE:
            add(
                StuffingCode.DENSE_BULLET,
                bullet.strip(),
                f"{len(found)} keywords make up most of: {bullet}",
            )
    return signals


# --- scores --------------------------------------------------------------------------------------


def score_document(
    document: ParsedCV,
    master: MasterEvidence,
    requirements: JobRequirements,
    *,
    weights: Mapping[str, int] = DEFAULT_WEIGHTS,
    is_master: bool = False,
) -> ScoreReport:
    """Score ``document`` (the master CV itself, or a tailored version of it) against the job.
    The master CV is never penalised for stuffing: it is the candidate's own text."""
    weights = validate_weights(weights)
    zones = zones_of(document)
    keywords = classify_keywords(zones, master, requirements)
    parts = {
        "keywords": _keywords_part(keywords),
        "skills": _skills_part(keywords),
        "experience": _experience_part(master, requirements),
        "responsibilities": _responsibilities_part(
            _coverages(requirements, _line_terms(work_lines(document)))
        ),
        "title": _title_part(_terms_of(zones.title), master, requirements),
        "education": _education_part(
            education_level(zones.education), zones.education, master, requirements
        ),
        "formatting": _formatting_part(formatting_checks(document)),
    }
    stuffing = [] if is_master else stuffing_signals(document, zones, master, requirements)
    penalty = min(MAX_PENALTY, PENALTY_PER_SIGNAL * len({signal.code for signal in stuffing}))
    score = max(Decimal(0), min(Decimal(100), _total(parts, weights) - penalty))
    return ScoreReport(
        score=float(score),
        assessed_weight=_assessed(parts, weights),
        penalty=penalty,
        components=_components(parts, weights),
        keywords=keywords,
        stuffing=stuffing,
    )


def _feasible_checks(master: MasterEvidence, requirements: JobRequirements) -> dict[str, bool]:
    """The formatting checks a truthful version can pass: titles and dates are copied from the
    master (F3), a role needs something to write its bullets from (F4); the rest is optimistic."""
    cv = master.cv
    skills = {canonical_key(skill.name) for skill in cv.skills}
    skills.update(
        keyword.key
        for keyword in requirements.keywords
        if is_technical(keyword) and master.supports(keyword.term)
    )
    skills.update(canonical_key(term.name) for text in master.texts for term in scan_terms(text))
    return {
        "F1": bool(master.sources),
        "F2": len(skills) >= SKILLS_RANGE[0],
        "F3": formatting_checks(cv)["F3"],
        "F4": all(item.bullets or item.details for item in cv.experiences),
        "F5": True,
        "F6": True,
    }


def ceiling(
    master: MasterEvidence,
    requirements: JobRequirements,
    *,
    weights: Mapping[str, int] = DEFAULT_WEIGHTS,
) -> CeilingReport:
    """The best score a version built only from the master CV's evidence can reach: every
    supported keyword prominent, every supported skill listed, shown where the master shows it,
    each responsibility covered as far as one entry's own lines allow, every title term a source
    or the headline holds; years, seniority and education are the master's."""
    weights = validate_weights(weights)
    keywords = requirements.keywords
    supported = {keyword.key: master.supports(keyword.term) for keyword in keywords}
    keyword_value = _weighted(
        [(keyword.importance, Fraction(int(supported[keyword.key]))) for keyword in keywords]
    )
    skill_value = _weighted(
        [
            (
                keyword.importance,
                _skill_value(supported[keyword.key], master.demonstrates(keyword.term)),
            )
            for keyword in keywords
            if is_technical(keyword)
        ]
    )
    parts = {
        "keywords": _NOT_APPLICABLE if keyword_value is None else _Part(keyword_value),
        "skills": _NOT_APPLICABLE if skill_value is None else _Part(skill_value),
        "experience": _experience_part(master, requirements),
        "responsibilities": _responsibilities_part(
            _coverages(requirements, _entry_terms(work_lines(master.cv)))
        ),
        "title": _title_part(_reachable_title_terms(master), master, requirements),
        "education": _education_part(
            master.education_level, master.zones.education, master, requirements
        ),
        "formatting": _formatting_part(_feasible_checks(master, requirements)),
    }
    return CeilingReport(
        score=float(_total(parts, weights)),
        assessed_weight=_assessed(parts, weights),
        components=_components(parts, weights),
    )


def feedback(
    document: ParsedCV,
    report: ScoreReport,
    master: MasterEvidence,
    requirements: JobRequirements,
) -> Feedback:
    """Deterministic hints for the next tailoring iteration (built from ``report``)."""
    matched = report.keywords_with(KeywordClass.MATCHED)
    title_found = _terms_of(zones_of(document).title)
    reachable = _reachable_title_terms(master)
    feasible = _feasible_checks(master, requirements)
    checks = formatting_checks(document)
    return Feedback(
        available=[
            KeywordHint(term=result.term, importance=result.importance, sources=result.evidence)
            for result in report.keywords_with(KeywordClass.AVAILABLE)
        ],
        not_listed=[result.term for result in matched if result.technical and not result.listed],
        not_prominent=[result.term for result in matched if not result.prominent],
        not_demonstrated=[
            KeywordHint(
                term=result.term,
                importance=result.importance,
                sources=master.work_evidence(result.term),
            )
            for result in matched
            if result.technical and not result.demonstrated and master.work_evidence(result.term)
        ],
        title_terms=term_words(
            requirements.title,
            [
                term
                for term in requirements.title_terms
                if term in reachable and term not in title_found
            ],
        ),
        formatting=[
            FORMAT_CHECKS[code] for code, passed in checks.items() if not passed and feasible[code]
        ],
        forbidden=[
            result.term
            for result in report.keywords
            if result.status in (KeywordClass.MISSING, KeywordClass.UNSUPPORTED)
        ],
    )


def gaps(master: MasterEvidence, requirements: JobRequirements) -> list[Gap]:
    """Gaps a truthful tailoring cannot close: the candidate may close them in the master CV,
    if they are true. Never acted on automatically."""
    items: list[Gap] = []
    for keyword in requirements.keywords:
        if not master.supports(keyword.term):
            items.append(
                Gap(
                    kind=GapKind.MISSING_KEYWORD,
                    subject=keyword.term,
                    importance=keyword.importance,
                    message=(
                        f"{keyword.term} ({keyword.importance.value.lower()}) is not in your "
                        "master CV. Add it there if it is true: a tailored CV never adds it."
                    ),
                )
            )
    for keyword in requirements.keywords:
        if (
            is_technical(keyword)
            and master.supports(keyword.term)
            and not master.demonstrates(keyword.term)
        ):
            items.append(
                Gap(
                    kind=GapKind.NOT_DEMONSTRATED,
                    subject=keyword.term,
                    importance=keyword.importance,
                    message=(
                        f"{keyword.term} is in your master CV, but no experience or project "
                        "shows it. If you used it in a role, add a bullet there saying how."
                    ),
                )
            )
    for coverage in _coverages(requirements, _entry_terms(work_lines(master.cv))):
        if coverage.value < 1:
            missing = coverage.missing
            items.append(
                Gap(
                    kind=GapKind.RESPONSIBILITY,
                    subject=coverage.responsibility,
                    terms=missing,
                    message=(
                        f"No role in your master CV covers “{coverage.responsibility}” "
                        f"(missing: {', '.join(missing)}). If you have done this, describe it "
                        "in the role where you did."
                    ),
                )
            )
    master_terms = _terms_of(master.texts)
    absent = [term for term in requirements.title_terms if term not in master_terms]
    if absent:
        words = term_words(requirements.title, absent)
        items.append(
            Gap(
                kind=GapKind.TITLE_TERMS,
                subject=requirements.title,
                terms=words,
                message=(
                    f"Your master CV never uses the job-title words {', '.join(words)}. "
                    "Add them only if they describe your work."
                ),
            )
        )
    return items
