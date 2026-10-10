"""Tailoring: the model's structured answer, assembled by code into a truthful CV version with an
evidence ledger (``app.ats.ledger``).

The model never writes an immutable fact. It returns only a summary, a skill choice and order,
rewritten bullets per role and project (each citing source ids) and a project subset and order.
Code copies everything else from the master CV: the header and contact details, every role's
employer, location, dates, title (unless the candidate allows retitling) and detail lines, all
education, certifications, languages and other sections.

Assembly applies the guard to every generated text and repairs what fails: a bullet goes back to
the master bullet it cites (or is dropped), the summary to the master summary, a title to the
master title; each repair is recorded. A role the answer leaves out, or whose bullets are all
rejected, keeps its master bullets verbatim.

The facts the model sees (``tailoring_facts``) leave out the name, contact details, employers,
schools, locations, detail lines and other sections.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.ats.guard import (
    GUARD_VERSION,
    NEW_TERMS_PER_BULLET,
    NEW_TERMS_PER_SUMMARY,
    GuardContext,
    TextKind,
    allowed_labels,
    check_sourced,
    check_title,
)
from app.ats.keywords import MasterEvidence
from app.ats.ledger import Ledger, LedgerItem, Origin, Repair, Violation, ViolationCode
from app.ats.requirements import JobRequirements
from app.ats.scoring import (
    BULLET_CHARS,
    BULLETS_PER_ROLE,
    SKILLS_RANGE,
    SUMMARY_MAX_WORDS,
    Feedback,
)
from app.ats.taxonomy import (
    CATEGORY_LABELS,
    canonical_key,
    category_of,
    mentions,
    scan_terms,
)
from app.cv.models import (
    DateRange,
    ExperienceEntry,
    ParsedCV,
    ProjectEntry,
    SkillItem,
    YearMonth,
)

TAILORED_PARSER_VERSION = "tailored-cv.v1"
FACTS_VERSION = "tailoring-facts.v1"

_PROJECT_ID = re.compile(r"P(\d+)")


# --- the model's answer (structured output: no length or range constraints, the guard enforces
# every limit) ---------------------------------------------------------------------------------


class SourcedText(BaseModel):
    text: str
    sources: list[str]


class ExperienceTailoring(BaseModel):
    id: str
    title: str | None
    bullets: list[SourcedText]


class ProjectTailoring(BaseModel):
    id: str
    bullets: list[SourcedText]


class SkillChoice(BaseModel):
    name: str
    category: str | None


class TailoringOutput(BaseModel):
    summary: SourcedText | None
    skills: list[SkillChoice]
    experiences: list[ExperienceTailoring]
    projects: list[ProjectTailoring]


@dataclass(frozen=True)
class Assembly:
    document: ParsedCV
    ledger: Ledger


# --- assembly ------------------------------------------------------------------------------------


class _Assembler:
    def __init__(self, context: GuardContext) -> None:
        self.context = context
        self.master = context.master
        self.items: list[LedgerItem] = []
        self.repairs: list[Repair] = []

    def record(self, path: str, origin: Origin, sources: list[str], text: str) -> None:
        keywords = [
            keyword.term
            for keyword in self.context.requirements.keywords
            if mentions(text, keyword.term)
        ]
        self.items.append(LedgerItem(path=path, origin=origin, sources=sources, keywords=keywords))

    def repair(self, path: str, text: str, violations: list[Violation]) -> None:
        self.repairs.append(Repair(path=path, rejected_text=text, violations=violations))

    def summary(self, proposal: SourcedText | None) -> str | None:
        original = self.master.cv.summary
        text = proposal.text.strip() if proposal else ""
        if proposal is None or not text or (original and text == original.strip()):
            if original:
                self.record("summary", Origin.VERBATIM, ["S"], original)
            return original
        valid, violations = check_sourced(
            text, proposal.sources, entry="S", kind=TextKind.SUMMARY, context=self.context
        )
        if not violations:
            verbatim = len(valid) == 1 and valid[0].text.strip() == text
            origin = Origin.VERBATIM if verbatim else Origin.REWRITTEN
            self.record("summary", origin, [source.id for source in valid], text)
            return text
        self.repair("summary", text, violations)
        if original:
            self.record("summary", Origin.REVERTED, ["S"], original)
        return original

    def _verbatim(self, entry: str, base: str, bullets: Sequence[str]) -> list[str]:
        for j, bullet in enumerate(bullets):
            self.record(f"{base}.bullets.{j}", Origin.VERBATIM, [f"{entry}.B{j + 1}"], bullet)
        return list(bullets)

    def bullets(
        self,
        entry: str,
        base: str,
        proposals: Sequence[SourcedText] | None,
        originals: Sequence[str],
    ) -> list[str]:
        """The bullets of one role or project (``entry`` in the master, ``base`` in the version)."""
        if not proposals:
            return self._verbatim(entry, base, originals)
        own = {
            source.text.strip(): source
            for source in self.master.sources.values()
            if source.entry == entry and (".B" in source.id or ".D" in source.id)
        }
        kept: dict[str, tuple[Origin, list[str]]] = {}
        for j, proposal in enumerate(proposals):
            text = proposal.text.strip()
            if text in own:
                kept.setdefault(text, (Origin.VERBATIM, [own[text].id]))
                continue
            valid, violations = check_sourced(
                text, proposal.sources, entry=entry, kind=TextKind.BULLET, context=self.context
            )
            if not violations:
                kept.setdefault(text, (Origin.REWRITTEN, [source.id for source in valid]))
                continue
            self.repair(f"{base}.bullets.{j}", proposal.text, violations)
            fallback = next((source for source in valid if ".B" in source.id), None)
            if fallback is not None:
                kept.setdefault(fallback.text.strip(), (Origin.REVERTED, [fallback.id]))
        if not kept:
            return self._verbatim(entry, base, originals)
        for j, (text, (origin, sources)) in enumerate(kept.items()):
            self.record(f"{base}.bullets.{j}", origin, sources, text)
        return list(kept)

    def title(self, index: int, proposal: str | None) -> str:
        original = self.master.cv.experiences[index].title
        entry, path = f"E{index + 1}", f"experiences.{index}.title"
        title = (proposal or "").strip()
        if title and title != original.strip():
            if not self.context.allow_title_changes:
                violation = Violation(
                    code=ViolationCode.TITLE_CHANGED,
                    detail="the candidate does not allow title changes",
                )
                self.repair(path, title, [violation])
            elif violations := check_title(title, index, self.context):
                self.repair(path, title, violations)
            else:
                self.record(path, Origin.RETITLED, [f"{entry}.T"], title)
                return title
        self.record(path, Origin.COPIED, [f"{entry}.T"], original)
        return original

    def skills(self, proposals: Sequence[SkillChoice]) -> list[SkillItem]:
        cv = self.master.cv
        if not proposals:
            proposals = [
                SkillChoice(name=skill.name, category=skill.category) for skill in cv.skills
            ]
        master_labels = {canonical_key(skill.name): skill.category for skill in cv.skills}
        chosen: list[SkillItem] = []
        keys: set[str] = set()
        for i, proposal in enumerate(proposals):
            name = proposal.name.strip()
            key = canonical_key(name)
            if not name or key in keys:
                continue
            if len(chosen) >= SKILLS_RANGE[1]:
                violation = Violation(code=ViolationCode.STUFFING, detail="more than 40 skills")
                self.repair(f"skills.{i}.name", name, [violation])
                break
            if not self.context.skill_backed(name):
                violation = Violation(
                    code=ViolationCode.UNSUPPORTED_SKILL, detail=f"{name} is not in the master CV"
                )
                self.repair(f"skills.{i}.name", name, [violation])
                continue
            category = (proposal.category or "").strip() or None
            if category is not None and category not in self.context.labels:
                violation = Violation(
                    code=ViolationCode.CATEGORY_INVALID, detail=f"{category} is not a known label"
                )
                self.repair(f"skills.{i}.category", category, [violation])
                category = master_labels.get(key) or _taxonomy_label(name)
            keys.add(key)
            chosen.append(SkillItem(name=name, category=category))
        if not chosen and cv.skills:
            chosen = [skill.model_copy() for skill in cv.skills]
        for i, skill in enumerate(chosen):
            self.record(
                f"skills.{i}.name", Origin.SELECTED, self.master.evidence(skill.name), skill.name
            )
        return chosen


def _taxonomy_label(name: str) -> str | None:
    category = category_of(name)
    return CATEGORY_LABELS[category] if category else None


def assemble(
    output: TailoringOutput, context: GuardContext, *, base_version_id: str | None = None
) -> Assembly:
    """Build a version from the model's answer: generated texts are checked and repaired, every
    immutable fact is copied from the master CV, and every text gets a ledger entry."""
    master = context.master.cv
    work = _Assembler(context)
    summary = work.summary(output.summary)

    proposals: dict[str, ExperienceTailoring] = {}
    for experience in output.experiences:
        proposals.setdefault(experience.id.strip().upper(), experience)
    experiences: list[ExperienceEntry] = []
    for i, original in enumerate(master.experiences):
        entry, base = f"E{i + 1}", f"experiences.{i}"
        proposal = proposals.get(entry)
        title = work.title(i, proposal.title if proposal else None)
        bullets = work.bullets(
            entry, base, proposal.bullets if proposal else None, original.bullets
        )
        for j, detail in enumerate(original.details):
            work.record(f"{base}.details.{j}", Origin.COPIED, [f"{entry}.D{j + 1}"], detail)
        experiences.append(original.model_copy(update={"title": title, "bullets": bullets}))

    projects: list[ProjectEntry] = []
    seen: set[int] = set()
    for project in output.projects:
        match = _PROJECT_ID.fullmatch(project.id.strip().upper())
        index = int(match.group(1)) - 1 if match else -1
        if not 0 <= index < len(master.projects) or index in seen:
            continue  # unknown or repeated ids are ignored
        seen.add(index)
        known = master.projects[index]
        entry, base = f"P{index + 1}", f"projects.{len(projects)}"
        work.record(f"{base}.name", Origin.COPIED, [f"{entry}.N"], known.name)
        bullets = work.bullets(entry, base, project.bullets, known.bullets)
        for j, detail in enumerate(known.details):
            work.record(f"{base}.details.{j}", Origin.COPIED, [f"{entry}.D{j + 1}"], detail)
        projects.append(known.model_copy(update={"bullets": bullets}))

    skills = work.skills(output.skills)
    for i, education in enumerate(master.education):
        work.record(f"education.{i}.degree", Origin.COPIED, [f"ED{i + 1}"], education.degree)
        for j, bullet in enumerate(education.bullets):
            work.record(
                f"education.{i}.bullets.{j}", Origin.COPIED, [f"ED{i + 1}.B{j + 1}"], bullet
            )
    for i, certification in enumerate(master.certifications):
        work.record(f"certifications.{i}", Origin.COPIED, [f"C{i + 1}"], certification)
    for i, language in enumerate(master.languages):
        work.record(f"languages.{i}", Origin.COPIED, [f"L{i + 1}"], language)

    document = master.model_copy(
        update={
            "parser_version": TAILORED_PARSER_VERSION,
            "summary": summary,
            "experiences": experiences,
            "projects": projects,
            "skills": skills,
            "warnings": [],
        },
        deep=True,
    )
    # Facts whose text the version shows (a selected skill shows its skills-section item, not
    # the bullets that back it).
    used = {
        source
        for item in work.items
        for source in item.sources
        if item.origin is not Origin.SELECTED or source.startswith("K")
    }
    ledger = Ledger(
        base_version_id=base_version_id,
        items=work.items,
        unused_sources=[source for source in context.master.sources if source not in used],
        repairs=work.repairs,
    )
    return Assembly(document=document, ledger=ledger)


def master_output(master: MasterEvidence) -> TailoringOutput:
    """The master CV as an answer: assembling it gives the master copy, every text verbatim."""
    cv = master.cv
    return TailoringOutput(
        summary=SourcedText(text=cv.summary, sources=["S"]) if cv.summary else None,
        skills=[SkillChoice(name=skill.name, category=skill.category) for skill in cv.skills],
        experiences=[
            ExperienceTailoring(
                id=f"E{i}",
                title=None,
                bullets=[
                    SourcedText(text=bullet, sources=[f"E{i}.B{j}"])
                    for j, bullet in enumerate(item.bullets, start=1)
                ],
            )
            for i, item in enumerate(cv.experiences, start=1)
        ],
        projects=[
            ProjectTailoring(
                id=f"P{k}",
                bullets=[
                    SourcedText(text=bullet, sources=[f"P{k}.B{j}"])
                    for j, bullet in enumerate(item.bullets, start=1)
                ],
            )
            for k, item in enumerate(cv.projects, start=1)
        ],
    )


def as_output(assembly: Assembly) -> TailoringOutput:
    """A version in the model's own format, with its sources (the "current best" it improves)."""
    document, ledger = assembly.document, assembly.ledger
    items = {item.path: item for item in ledger.items}

    def sourced(path: str, text: str) -> SourcedText:
        item = items.get(path)
        return SourcedText(text=text, sources=list(item.sources) if item else [])

    return TailoringOutput(
        summary=sourced("summary", document.summary) if document.summary else None,
        skills=[SkillChoice(name=skill.name, category=skill.category) for skill in document.skills],
        experiences=[
            ExperienceTailoring(
                id=f"E{i + 1}",
                title=(
                    item.title
                    if items[f"experiences.{i}.title"].origin is Origin.RETITLED
                    else None
                ),
                bullets=[
                    sourced(f"experiences.{i}.bullets.{j}", bullet)
                    for j, bullet in enumerate(item.bullets)
                ],
            )
            for i, item in enumerate(document.experiences)
        ],
        projects=[
            ProjectTailoring(
                id=items[f"projects.{k}.name"].sources[0].split(".")[0],
                bullets=[
                    sourced(f"projects.{k}.bullets.{j}", bullet)
                    for j, bullet in enumerate(item.bullets)
                ],
            )
            for k, item in enumerate(document.projects)
        ],
    )


# --- what the model sees -------------------------------------------------------------------------


def _month(value: YearMonth | None) -> str:
    if value is None:
        return "unknown"
    return f"{value.year}-{value.month:02d}" if value.month else str(value.year)


def _period(dates: DateRange | None) -> str:
    if dates is None or dates.start is None:
        return "unknown"
    return f"{_month(dates.start)} to {'present' if dates.is_current else _month(dates.end)}"


def backed_skills(master: MasterEvidence, declared: Sequence[str] = ()) -> list[dict[str, Any]]:
    """Skills a version may list, with their strength and the sources that show them: the
    master's skills section, declared skills the master CV mentions, and taxonomy terms it
    mentions."""
    labels = {canonical_key(skill.name): skill.category for skill in master.cv.skills}
    names: dict[str, str] = {}
    for name in (
        *(skill.name for skill in master.cv.skills),
        *declared,
        *(term.name for text in master.texts for term in scan_terms(text)),
    ):
        key = canonical_key(name)
        if name.strip() and key not in names and master.supports(name):
            names[key] = name.strip()
    return [
        {
            "name": name,
            "category": labels.get(key) or _taxonomy_label(name),
            "strength": "DEMONSTRATED" if master.demonstrates(name) else "LISTED",
            "sources": master.evidence(name),
        }
        for key, name in names.items()
    ]


@dataclass(frozen=True)
class TailoringFacts:
    data: dict[str, Any]
    text: str
    sha256: str


def tailoring_facts(
    master: MasterEvidence,
    *,
    declared_skills: Sequence[str] = (),
    allow_title_changes: bool = False,
) -> TailoringFacts:
    """The cached, job-independent part of the tailoring request: the master CV's facts with
    their source ids. No name, contact details, employer, school, location, detail line or other
    section; deterministic (sorted JSON), so the prompt prefix stays byte-identical."""
    cv = master.cv
    data: dict[str, Any] = {
        "version": FACTS_VERSION,
        "summary": {"id": "S", "text": cv.summary} if cv.summary else None,
        "experiences": [
            {
                "id": f"E{i}",
                "title": item.title,
                "period": _period(item.dates),
                "bullets": [
                    {"id": f"E{i}.B{j}", "text": bullet}
                    for j, bullet in enumerate(item.bullets, start=1)
                ],
            }
            for i, item in enumerate(cv.experiences, start=1)
        ],
        "projects": [
            {
                "id": f"P{k}",
                "name": item.name,
                "bullets": [
                    {"id": f"P{k}.B{j}", "text": bullet}
                    for j, bullet in enumerate(item.bullets, start=1)
                ],
            }
            for k, item in enumerate(cv.projects, start=1)
        ],
        "education": [
            {"id": f"ED{i}", "degree": item.degree} for i, item in enumerate(cv.education, start=1)
        ],
        "certifications": [
            {"id": f"C{i}", "text": text} for i, text in enumerate(cv.certifications, start=1)
        ],
        "languages": [
            {"id": f"L{i}", "text": text} for i, text in enumerate(cv.languages, start=1)
        ],
        "skills": backed_skills(master, declared_skills),
        "skill_labels": list(allowed_labels(cv)),
        "rules": {
            "allow_title_changes": allow_title_changes,
            "bullets_per_role": list(BULLETS_PER_ROLE),
            "bullet_characters": list(BULLET_CHARS),
            "summary_max_words": SUMMARY_MAX_WORDS,
            "max_skills": SKILLS_RANGE[1],
            "new_words_per_bullet": NEW_TERMS_PER_BULLET,
            "new_words_per_summary": NEW_TERMS_PER_SUMMARY,
            "guard": GUARD_VERSION,
        },
    }
    text = "Master CV facts (JSON):\n" + json.dumps(data, sort_keys=True, ensure_ascii=False)
    return TailoringFacts(
        data=data, text=text, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest()
    )


def requirements_brief(requirements: JobRequirements) -> dict[str, Any]:
    """The grounded requirements the tailoring call sees (never the raw posting)."""
    return {
        "title": requirements.title,
        "seniority": requirements.seniority,
        "min_years": requirements.min_years,
        "keywords": [
            {
                "term": keyword.term,
                "importance": keyword.importance.value,
                "category": keyword.category.value if keyword.category else None,
            }
            for keyword in requirements.keywords
        ],
        "responsibilities": list(requirements.responsibilities),
        "education": {
            "level": requirements.education.level.value,
            "fields": list(requirements.education.fields),
        },
    }


def _json_block(tag: str, data: Any) -> str:
    body = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1)
    return f"<{tag}>\n{body}\n</{tag}>"


def tailoring_user_turn(
    requirements: JobRequirements,
    current: TailoringOutput,
    hints: Feedback,
    *,
    iteration: int,
    max_iterations: int,
) -> str:
    """The user turn of a tailoring request: the grounded requirements (never the raw posting),
    the best version so far with its source ids, and the deterministic feedback."""
    return "\n\n".join(
        (
            _json_block("job_requirements", requirements_brief(requirements)),
            _json_block("current_version", current.model_dump(mode="json")),
            _json_block("feedback", hints.model_dump(mode="json")),
            f"Iteration {iteration} of {max_iterations}: return the improved version.",
        )
    )


# --- plain text ----------------------------------------------------------------------------------

_HEADINGS = {
    "en": (
        "Summary",
        "Experience",
        "Education",
        "Projects",
        "Skills",
        "Certifications",
        "Languages",
    ),
    "fr": (
        "Profil",
        "Expérience professionnelle",
        "Formation",
        "Projets",
        "Compétences",
        "Certifications",
        "Langues",
    ),
}


def render_text(cv: ParsedCV) -> str:
    """A deterministic plain-text rendering (the stored text of a tailored version)."""
    summary_h, experience_h, education_h, projects_h, skills_h, certs_h, languages_h = (
        _HEADINGS.get(cv.language, _HEADINGS["en"])
    )
    lines: list[str] = [*cv.header_lines]

    def section(heading: str, body: list[str]) -> None:
        if body:
            lines.extend(("", heading.upper(), *body))

    section(summary_h, [cv.summary] if cv.summary else [])
    body: list[str] = []
    for experience in cv.experiences:
        head = " — ".join(part for part in (experience.title, experience.employer) if part)
        body.append(f"{head} | {experience.location}" if experience.location else head)
        if experience.dates:
            body.append(experience.dates.text)
        body.extend(experience.details)
        body.extend(f"• {bullet}" for bullet in experience.bullets)
    section(experience_h, body)
    body = []
    for education in cv.education:
        head = " — ".join(part for part in (education.degree, education.institution) if part)
        body.append(f"{head} | {education.location}" if education.location else head)
        if education.dates:
            body.append(education.dates.text)
        body.extend(education.details)
        body.extend(f"• {bullet}" for bullet in education.bullets)
    section(education_h, body)
    body = []
    for project in cv.projects:
        body.append(project.name)
        if project.dates:
            body.append(project.dates.text)
        body.extend(project.details)
        body.extend(f"• {bullet}" for bullet in project.bullets)
    section(projects_h, body)
    groups: dict[str | None, list[str]] = {}
    for skill in cv.skills:
        groups.setdefault(skill.category, []).append(skill.name)
    section(
        skills_h,
        [
            f"{label}: {', '.join(names)}" if label else ", ".join(names)
            for label, names in groups.items()
        ],
    )
    section(certs_h, [f"• {item}" for item in cv.certifications])
    section(languages_h, list(cv.languages))
    for other in cv.other_sections:
        section(other.heading, list(other.lines))
    return "\n".join(lines).strip() + "\n"
