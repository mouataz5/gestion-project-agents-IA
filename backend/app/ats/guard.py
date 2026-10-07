"""The truthfulness guard: a tailored CV may reword the master CV, never add to it.

Every generated text (the summary, a bullet, a retitled role) is checked against the master facts
it cites (``sources.may_cite`` scopes them: a bullet of E1 may cite only E1's bullets and detail
lines, the summary may cite any fact):

    G1 SOURCE_INVALID          an unknown id, an id of another entry, or no source at all
    G2 UNSUPPORTED_TECHNOLOGY  a skill or technology (taxonomy terms, the job's keywords, the
                               candidate's skills) or a name-shaped token (CamelCase, ACRONYM, S3,
                               C++, a capitalised word inside a sentence) its sources lack
    G3 UNSUPPORTED_NUMBER      a number (value and unit, with the noun that follows) its sources do
                               not state; the summary may state the years of experience computed
                               from the master CV's dates
    G4 UNSUPPORTED_TERM        a word of the job's requirements (title, keywords, responsibilities)
                               its sources do not contain
    G5 UNSUPPORTED_CLAIM       a seniority, leadership or outcome word (senior, led, managed,
                               mentored, improved, reduced, launched...) its sources do not contain;
                               a retitled role never gains a seniority word
    G6 NEW_CONTENT             more than 2 other new content words in a bullet or title (4 in the
                               summary)
    G7 TEXT_TOO_LONG           a bullet or title over 300 characters, a summary over 80 words

A failing text is repaired by the assembly (reverted to the master text it replaces) and the repair
is recorded. ``validate_tailored`` is the final gate on the assembled version: immutable facts
unchanged, a ledger entry for every text, every skill backed, no unsupported keyword, no keyword
stuffing. Any violation left rejects the iteration.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.ats.keywords import MasterEvidence, classify_keywords, mentioned, zones_of
from app.ats.ledger import Ledger, Origin, Violation, ViolationCode
from app.ats.requirements import SENIORITY_WORDS, JobRequirements
from app.ats.scoring import BULLET_CHARS, SUMMARY_MAX_WORDS, stuffing_signals, word_count
from app.ats.sources import Source, may_cite
from app.ats.taxonomy import (
    CATEGORY_LABELS,
    TERMS,
    Category,
    canonical_key,
    find_term,
    fold,
    mentions,
    scan_terms,
)
from app.ats.text import (
    NEUTRAL_TERMS,
    Quantity,
    content_terms,
    proper_noun_tokens,
    quantities,
    quantity_supported,
    stem,
    term_words,
    token_in,
    words,
)
from app.ats.types import KeywordClass
from app.cv.models import ParsedCV
from app.jobs.normalize import infer_seniority
from app.jobs.types import Seniority

GUARD_VERSION = "cv-guard.v1"

NEW_TERMS_PER_BULLET = 2
NEW_TERMS_PER_SUMMARY = 4

# Seniority, leadership and outcome claims: a group is supported when the sources use any of its
# words ("Led" supports "leadership").
_CLAIM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("senior",),
    ("lead", "led", "leader", "leadership"),
    ("manage", "managed", "manager", "management"),
    ("mentor", "mentored", "mentoring", "coach", "coached"),
    ("supervise", "supervisor", "supervision"),
    ("owned", "owner", "ownership"),
    ("architect", "architected"),
    ("spearhead", "spearheaded"),
    ("improve", "improved", "improvement"),
    ("increase", "increased"),
    ("reduce", "reduced", "reduction"),
    ("optimise", "optimize", "optimised", "optimized", "optimisation", "optimization"),
    ("launch", "launched"),
    ("ship", "shipped"),
    ("award", "awarded"),
    ("oversee", "oversaw", "overseen"),
    ("direct", "directed"),
    ("head", "headed"),
    ("coordinate", "coordinated", "coordination"),
    ("pioneer", "pioneered"),
    ("champion", "championed"),
    ("recruit", "recruited", "hire", "hired", "hiring"),
    ("promote", "promoted", "promotion"),
    ("patent", "patented"),
    ("win", "won", "winner"),
    ("double", "doubled"),
    ("triple", "tripled"),
    ("halve", "halved"),
    ("budget",),
    # vague quantities claim a scale the sources must state
    ("dozens",),
    ("hundreds", "centaines"),
    ("thousands", "milliers"),
    ("millions",),
    ("billions",),
    ("decade", "decades", "décennie"),
    ("encadrer", "encadré", "encadrement"),
    ("diriger", "dirigé"),
    ("gérer", "géré"),
    ("piloter", "piloté", "pilotage"),
    ("superviser", "supervisé"),
    ("améliorer", "amélioré", "amélioration"),
    ("augmenter", "augmenté"),
    ("réduire", "réduit"),
    ("optimiser", "optimisé"),
    ("lancer", "lancé"),
)
_CLAIMS: dict[str, frozenset[str]] = {}
for _group in _CLAIM_GROUPS:
    _stems = frozenset(stem(word) for word in _group)
    for _stem in _stems:
        _CLAIMS[_stem] = _CLAIMS.get(_stem, frozenset()) | _stems
_YEAR_NOUNS = frozenset(stem(word) for word in ("years", "yrs", "ans", "jahre"))


class TextKind(StrEnum):
    SUMMARY = "summary"
    BULLET = "bullet"
    TITLE = "title"


@dataclass(frozen=True)
class GuardContext:
    """Everything the guard compares generated text with, built once per tailoring."""

    master: MasterEvidence
    requirements: JobRequirements
    vocabulary: tuple[str, ...]  # skills and technologies checked by G2
    job_terms: frozenset[str]  # stems of the job's requirement text checked by G4
    skill_keys: frozenset[str]  # known skill names: master skills, declared skills, job keywords
    labels: tuple[str, ...]  # skills-section labels a version may use
    allow_title_changes: bool = False

    def skill_backed(self, name: str) -> bool:
        """A skill a version may list: a known skill name that the master CV mentions."""
        known = find_term(name) is not None or canonical_key(name) in self.skill_keys
        return known and self.master.supports(name)


def allowed_labels(cv: ParsedCV) -> tuple[str, ...]:
    """Skills-section labels a version may use: the master CV's own, and the taxonomy's (which
    never name a term)."""
    master_labels = (skill.category for skill in cv.skills if skill.category)
    return tuple(dict.fromkeys((*master_labels, *CATEGORY_LABELS.values())))


def guard_context(
    master: MasterEvidence,
    requirements: JobRequirements,
    *,
    declared_skills: Sequence[str] = (),
    allow_title_changes: bool = False,
) -> GuardContext:
    names = [
        term.name
        for term in TERMS
        if term.scan or term.category in (Category.SPOKEN_LANGUAGE, Category.DOMAIN)
    ]
    names.extend(keyword.term for keyword in requirements.keywords)
    names.extend(skill.name for skill in master.cv.skills)
    names.extend(declared_skills)
    vocabulary: dict[str, str] = {}
    for name in names:
        if name.strip():
            vocabulary.setdefault(canonical_key(name), name.strip())
    job_texts = [  # what the tailoring call sees of the job (never the raw posting)
        requirements.title,
        *requirements.responsibilities,
        *(keyword.term for keyword in requirements.keywords),
        *requirements.education.fields,
    ]
    job_terms = frozenset(
        term
        for text in job_texts
        for term in content_terms(text)
        if not term.startswith("term:") and term not in NEUTRAL_TERMS
    )
    skill_keys = frozenset(
        canonical_key(name)
        for name in (
            *(skill.name for skill in master.cv.skills),
            *declared_skills,
            *(keyword.term for keyword in requirements.keywords),
        )
    )
    return GuardContext(
        master=master,
        requirements=requirements,
        vocabulary=tuple(vocabulary.values()),
        job_terms=job_terms,
        skill_keys=skill_keys,
        labels=allowed_labels(master.cv),
        allow_title_changes=allow_title_changes,
    )


def normalize_ids(ids: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item.strip().upper() for item in ids if item and item.strip()))


def resolve_sources(
    ids: Iterable[str], entry: str, master: MasterEvidence
) -> tuple[list[Source], list[str]]:
    """(valid sources, rejected ids) for text written for ``entry``."""
    valid: list[Source] = []
    rejected: list[str] = []
    for source_id in normalize_ids(ids):
        source = master.sources.get(source_id)
        if source is not None and may_cite(entry, source):
            valid.append(source)
        else:
            rejected.append(source_id)
    return valid, rejected


def _terms_of(texts: Sequence[str]) -> frozenset[str]:
    return frozenset().union(*(content_terms(text) for text in texts))


def _years_claim(master: MasterEvidence, quantity: Quantity) -> bool:
    """Whether "7 years" (or "5+ years") in the summary is what the master CV's dates say."""
    years = master.years
    return (
        years is not None
        and quantity.unit is None
        and quantity.noun in _YEAR_NOUNS
        and 1 <= quantity.value <= years
    )


def check_text(
    text: str,
    cited: Sequence[str],
    *,
    kind: TextKind,
    context: GuardContext,
    original: str | None = None,
) -> list[Violation]:
    """G2-G7 for ``text`` against the texts it cites (G1 is checked by ``check_sourced``).
    ``original``: the master title a retitled role replaces."""
    violations: list[Violation] = []

    def flag(code: ViolationCode, detail: str) -> None:
        violations.append(Violation(code=code, detail=detail))

    clean = text.strip()
    if not clean:
        flag(ViolationCode.EMPTY_TEXT, "empty text")
        return violations
    if kind is TextKind.SUMMARY and word_count(clean) > SUMMARY_MAX_WORDS:
        flag(ViolationCode.TEXT_TOO_LONG, f"{word_count(clean)} words (at most 80)")
    elif kind is not TextKind.SUMMARY and len(clean) > BULLET_CHARS[1]:
        flag(ViolationCode.TEXT_TOO_LONG, f"{len(clean)} characters (at most 300)")

    # G2: skills and technologies, then name-shaped tokens
    checked: set[str] = set()
    for name in context.vocabulary:
        if mentions(clean, name) and not mentioned(cited, name):
            flag(ViolationCode.UNSUPPORTED_TECHNOLOGY, name)
            checked.add(canonical_key(name))
    for token in proper_noun_tokens(clean):
        term = find_term(token)
        if canonical_key(token) in checked or token_in(token, cited):
            continue
        if term is not None and mentioned(cited, term.name):
            continue  # "LLM" for "large language models"
        flag(ViolationCode.UNSUPPORTED_TECHNOLOGY, token)

    # G3: numbers
    for quantity in quantities(clean):
        if quantity_supported(quantity, list(cited)):
            continue
        if kind is TextKind.SUMMARY and _years_claim(context.master, quantity):
            continue
        written = clean[quantity.start : quantity.end] if len(fold(clean)) == len(clean) else ""
        flag(ViolationCode.UNSUPPORTED_NUMBER, written.strip() or str(quantity.value))

    # G4-G6: words
    terms = content_terms(clean)
    cited_terms = _terms_of(cited)
    new = {term for term in terms - cited_terms - NEUTRAL_TERMS if not term.startswith("term:")}
    claims = {term for term in new if term in _CLAIMS and not (_CLAIMS[term] & cited_terms)}
    supported_claims = {term for term in new if term in _CLAIMS and term not in claims}
    job = {term for term in new if term in context.job_terms} - claims - supported_claims
    if claims:
        flag(ViolationCode.UNSUPPORTED_CLAIM, ", ".join(term_words(clean, claims)))
    if job:
        flag(ViolationCode.UNSUPPORTED_TERM, ", ".join(term_words(clean, job)))
    if kind is TextKind.TITLE and original is not None:
        before = {stem(word) for word in words(original)}
        added = [word for word in words(clean) if stem(word) in SENIORITY_WORDS]
        added = [word for word in added if stem(word) not in before]
        level = infer_seniority(clean)
        if added:
            flag(ViolationCode.UNSUPPORTED_CLAIM, f"seniority added to the title: {added[0]}")
        elif level is not Seniority.UNKNOWN and level is not infer_seniority(original):
            flag(ViolationCode.UNSUPPORTED_CLAIM, f"the title now reads {level.value.lower()}")
    rest = new - job - claims - supported_claims
    cap = NEW_TERMS_PER_SUMMARY if kind is TextKind.SUMMARY else NEW_TERMS_PER_BULLET
    if len(rest) > cap:
        flag(ViolationCode.NEW_CONTENT, ", ".join(term_words(clean, rest)))
    return violations


def check_sourced(
    text: str,
    source_ids: Sequence[str],
    *,
    entry: str,
    kind: TextKind,
    context: GuardContext,
) -> tuple[list[Source], list[Violation]]:
    """G1-G7 for a generated summary or bullet: (its valid sources, violations)."""
    valid, rejected = resolve_sources(source_ids, entry, context.master)
    violations: list[Violation] = []
    if rejected:
        violations.append(
            Violation(
                code=ViolationCode.SOURCE_INVALID,
                detail=f"cannot cite {', '.join(rejected)} here",
            )
        )
    if not valid:
        violations.append(Violation(code=ViolationCode.SOURCE_INVALID, detail="no valid source"))
        return valid, violations
    cited = [source.text for source in valid]
    violations.extend(check_text(text, cited, kind=kind, context=context))
    return valid, violations


def check_title(title: str, index: int, context: GuardContext) -> list[Violation]:
    """A retitled role (only when the candidate allows it): checked against the master title and
    the role's own lines; never a new seniority word."""
    entry = context.master.cv.experiences[index]
    cited = [entry.title, *entry.bullets, *entry.details]
    return check_text(title, cited, kind=TextKind.TITLE, context=context, original=entry.title)


# --- the final gate ------------------------------------------------------------------------------


def content_paths(document: ParsedCV) -> list[str]:
    """Every text of a version that needs a ledger entry."""
    paths = ["summary"] if document.summary else []
    for i, experience in enumerate(document.experiences):
        paths.append(f"experiences.{i}.title")
        paths.extend(f"experiences.{i}.bullets.{j}" for j in range(len(experience.bullets)))
        paths.extend(f"experiences.{i}.details.{j}" for j in range(len(experience.details)))
    for i, project in enumerate(document.projects):
        paths.append(f"projects.{i}.name")
        paths.extend(f"projects.{i}.bullets.{j}" for j in range(len(project.bullets)))
        paths.extend(f"projects.{i}.details.{j}" for j in range(len(project.details)))
    for i, education in enumerate(document.education):
        paths.append(f"education.{i}.degree")
        paths.extend(f"education.{i}.bullets.{j}" for j in range(len(education.bullets)))
    paths.extend(f"skills.{i}.name" for i in range(len(document.skills)))
    paths.extend(f"certifications.{i}" for i in range(len(document.certifications)))
    paths.extend(f"languages.{i}" for i in range(len(document.languages)))
    return paths


def text_at(document: ParsedCV, path: str) -> str:
    value: Any = document
    for part in path.split("."):
        value = value[int(part)] if part.isdigit() else getattr(value, part)
    return str(value)


def _generated(path: str, project_ids: Sequence[str]) -> tuple[str, TextKind] | None:
    """(entry, kind) of a text the model may have written: the summary and role bullets."""
    parts = path.split(".")
    if path == "summary":
        return "S", TextKind.SUMMARY
    if len(parts) == 4 and parts[2] == "bullets":
        if parts[0] == "experiences":
            return f"E{int(parts[1]) + 1}", TextKind.BULLET
        if parts[0] == "projects":
            return project_ids[int(parts[1])], TextKind.BULLET
    return None


def validate_tailored(document: ParsedCV, ledger: Ledger, context: GuardContext) -> list[Violation]:
    """The final gate: an empty list means the version may be scored and stored."""
    master = context.master.cv
    violations: list[Violation] = []

    def flag(code: ViolationCode, detail: str, path: str | None = None) -> None:
        violations.append(Violation(code=code, detail=detail, path=path))

    if document.header_lines != master.header_lines or document.contact != master.contact:
        flag(ViolationCode.CONTACT_CHANGED, "the header and contact details are the master's")
    if len(document.experiences) < len(master.experiences):
        flag(ViolationCode.EXPERIENCE_MISSING, "every role of the master CV stays")
    if len(document.experiences) > len(master.experiences):
        flag(ViolationCode.EXPERIENCE_ADDED, "no role is added")
    for i, (mine, theirs) in enumerate(zip(document.experiences, master.experiences, strict=False)):
        base = f"experiences.{i}"
        if mine.employer != theirs.employer:
            flag(ViolationCode.EMPLOYER_CHANGED, theirs.employer or "", f"{base}.employer")
        if mine.location != theirs.location:
            flag(ViolationCode.LOCATION_CHANGED, theirs.location or "", f"{base}.location")
        if mine.dates != theirs.dates:
            flag(ViolationCode.DATES_CHANGED, theirs.dates.text if theirs.dates else "", base)
        if mine.details != theirs.details:
            flag(ViolationCode.DETAILS_CHANGED, "detail lines are copied", f"{base}.details")
        if mine.title != theirs.title:
            if not context.allow_title_changes:
                flag(ViolationCode.TITLE_CHANGED, theirs.title, f"{base}.title")
            else:
                for violation in check_title(mine.title, i, context):
                    flag(violation.code, violation.detail, f"{base}.title")
    if document.education != master.education:
        flag(ViolationCode.EDUCATION_CHANGED, "education is copied")
    if document.certifications != master.certifications:
        flag(ViolationCode.CERTIFICATIONS_CHANGED, "certifications are copied")
    if document.languages != master.languages:
        flag(ViolationCode.LANGUAGES_CHANGED, "languages are copied")
    if document.other_sections != master.other_sections:
        flag(ViolationCode.SECTIONS_CHANGED, "other sections are copied")

    project_ids: list[str] = []
    for i, project in enumerate(document.projects):
        match = next(
            (
                f"P{k + 1}"
                for k, known in enumerate(master.projects)
                if (known.name, known.dates, known.details)
                == (project.name, project.dates, project.details)
            ),
            None,
        )
        if match is None or match in project_ids:
            flag(ViolationCode.PROJECT_UNKNOWN, project.name, f"projects.{i}")
        project_ids.append(match or f"P{i + 1}")

    items = {item.path: item for item in ledger.items}
    for path in content_paths(document):
        item = items.get(path)
        if item is None:
            flag(ViolationCode.LEDGER_MISSING, "no ledger entry", path)
            continue
        generated = _generated(path, project_ids)
        if generated is None:
            continue
        entry, kind = generated
        text = text_at(document, path)
        if item.origin in (Origin.VERBATIM, Origin.REVERTED):
            valid, rejected = resolve_sources(item.sources, entry, context.master)
            if rejected or len(valid) != 1 or valid[0].text.strip() != text.strip():
                flag(ViolationCode.SOURCE_INVALID, "not the text of its cited source", path)
            continue
        _, problems = check_sourced(text, item.sources, entry=entry, kind=kind, context=context)
        for problem in problems:
            flag(problem.code, problem.detail, path)

    for i, skill in enumerate(document.skills):
        if not context.skill_backed(skill.name):
            flag(ViolationCode.UNSUPPORTED_SKILL, skill.name, f"skills.{i}.name")
        if skill.category is not None and skill.category not in context.labels:
            flag(ViolationCode.CATEGORY_INVALID, skill.category, f"skills.{i}.category")

    zones = zones_of(document)
    for result in classify_keywords(zones, context.master, context.requirements):
        if result.status is KeywordClass.UNSUPPORTED:
            flag(ViolationCode.UNSUPPORTED_KEYWORD, result.term)
    for signal in stuffing_signals(document, zones, context.master, context.requirements):
        flag(ViolationCode.STUFFING, signal.detail)
    for label in dict.fromkeys(skill.category for skill in document.skills if skill.category):
        for term in scan_terms(label):
            if not context.master.supports(term.name):
                flag(ViolationCode.CATEGORY_INVALID, f"{label} names {term.name}")
    return violations
