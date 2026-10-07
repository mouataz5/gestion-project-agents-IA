"""Source ids: every fact of the confirmed master CV that a tailored CV may cite.

Ids are 1-based positions in the immutable master ``structure`` (never fact-table rows, which are
rebuilt on every confirmation):

    S        summary                 K3      skills item 3
    E1.T     title of experience 1   C1      certification 1
    E1.B2    bullet 2 of experience 1        L2      language 2
    E1.D1    detail line 1 of experience 1   ED1     education 1 (degree)
    P1.N     name of project 1       ED1.B1  bullet 1 of education 1
    P1.B1    bullet 1 of project 1   P1.D1   detail line 1 of project 1

Citations are scoped to their entry: a bullet of experience 1 may cite only the bullets and
detail lines of experience 1 (``E1.B*``, ``E1.D*``), so a metric or a technology can never move
from one role to another. The summary may cite any fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.cv.models import ParsedCV


@dataclass(frozen=True)
class Source:
    id: str
    entry: str  # "S", "E1", "P2", "ED1", "K", "C", "L"
    text: str
    label: str  # for people: "Experience 1 · bullet 2"
    path: str  # in the master structure: "experiences.0.bullets.1"


def build_sources(cv: ParsedCV) -> dict[str, Source]:
    sources: list[Source] = []
    if cv.summary:
        sources.append(Source("S", "S", cv.summary, "Summary", "summary"))
    for i, experience in enumerate(cv.experiences, start=1):
        entry, base = f"E{i}", f"experiences.{i - 1}"
        sources.append(
            Source(
                f"{entry}.T", entry, experience.title, f"Experience {i} · title", f"{base}.title"
            )
        )
        for j, bullet in enumerate(experience.bullets, start=1):
            sources.append(
                Source(
                    f"{entry}.B{j}",
                    entry,
                    bullet,
                    f"Experience {i} · bullet {j}",
                    f"{base}.bullets.{j - 1}",
                )
            )
        for j, detail in enumerate(experience.details, start=1):
            sources.append(
                Source(
                    f"{entry}.D{j}",
                    entry,
                    detail,
                    f"Experience {i} · detail {j}",
                    f"{base}.details.{j - 1}",
                )
            )
    for i, project in enumerate(cv.projects, start=1):
        entry, base = f"P{i}", f"projects.{i - 1}"
        sources.append(
            Source(f"{entry}.N", entry, project.name, f"Project {i} · name", f"{base}.name")
        )
        for j, bullet in enumerate(project.bullets, start=1):
            sources.append(
                Source(
                    f"{entry}.B{j}",
                    entry,
                    bullet,
                    f"Project {i} · bullet {j}",
                    f"{base}.bullets.{j - 1}",
                )
            )
        for j, detail in enumerate(project.details, start=1):
            sources.append(
                Source(
                    f"{entry}.D{j}",
                    entry,
                    detail,
                    f"Project {i} · detail {j}",
                    f"{base}.details.{j - 1}",
                )
            )
    for i, education in enumerate(cv.education, start=1):
        entry, base = f"ED{i}", f"education.{i - 1}"
        sources.append(Source(entry, entry, education.degree, f"Education {i}", f"{base}.degree"))
        for j, bullet in enumerate(education.bullets, start=1):
            sources.append(
                Source(
                    f"{entry}.B{j}",
                    entry,
                    bullet,
                    f"Education {i} · bullet {j}",
                    f"{base}.bullets.{j - 1}",
                )
            )
    for i, skill in enumerate(cv.skills, start=1):
        sources.append(Source(f"K{i}", "K", skill.name, f"Skill {i}", f"skills.{i - 1}.name"))
    for i, certification in enumerate(cv.certifications, start=1):
        sources.append(
            Source(f"C{i}", "C", certification, f"Certification {i}", f"certifications.{i - 1}")
        )
    for i, language in enumerate(cv.languages, start=1):
        sources.append(Source(f"L{i}", "L", language, f"Language {i}", f"languages.{i - 1}"))
    return {source.id: source for source in sources}


def may_cite(entry: str, source: Source) -> bool:
    """Whether text written for ``entry`` ("S", "E1", "P2") may cite ``source``.

    The summary may cite any fact. A bullet may cite only the bullets and detail lines of its own
    entry - never another role, and never a title or a project name (a title is not something
    the candidate did: "Engineer" in a title does not support "mentored engineers")."""
    if entry == "S":
        return True
    return source.entry == entry and (".B" in source.id or ".D" in source.id)


_CONTACT_SHAPE = re.compile(r"@|https?://|www\.|linkedin|github|\+?\d[\d .()-]{7,}\d", re.I)


def headline_lines(cv: ParsedCV) -> list[str]:
    """Header lines that describe the candidate ("AI Engineer"): the first line (the name) and
    every line carrying contact data are left out."""
    contact = [*cv.contact.emails, *cv.contact.phones, *cv.contact.links]
    return [
        line
        for line in cv.header_lines[1:]
        if line.strip()
        and not _CONTACT_SHAPE.search(line)
        and not any(item and item in line for item in contact)
    ]


def master_texts(cv: ParsedCV) -> list[str]:
    """Every fact of the master CV a keyword can be supported by: the source texts, the headline
    lines and the skills-section labels ("ML: PyTorch" claims machine learning). No name, contact
    data, employers, schools or locations."""
    parts = [source.text for source in build_sources(cv).values()]
    parts.extend(headline_lines(cv))
    parts.extend(dict.fromkeys(skill.category for skill in cv.skills if skill.category))
    return [part for part in parts if part]


def master_text(cv: ParsedCV) -> str:
    return "\n".join(master_texts(cv))
