"""Recognise CV section headings (English and French).

A heading is a short line made only of known section phrases ("experience", "compétences",
"work history") and qualifiers ("professional", "techniques", "personnels"). Matching ignores
case, accents and trailing punctuation, so "EXPÉRIENCES PROFESSIONNELLES" and
"Professional Experience:" are both experience headings.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum


class SectionKind(StrEnum):
    SUMMARY = "SUMMARY"
    EXPERIENCE = "EXPERIENCE"
    EDUCATION = "EDUCATION"
    PROJECTS = "PROJECTS"
    SKILLS = "SKILLS"
    CERTIFICATIONS = "CERTIFICATIONS"
    LANGUAGES = "LANGUAGES"
    CONTACT = "CONTACT"
    OTHER = "OTHER"


_PHRASES: dict[SectionKind, tuple[str, ...]] = {
    SectionKind.SUMMARY: (
        "summary",
        "profile",
        "profil",
        "about me",
        "about",
        "a propos",
        "a propos de moi",
        "objective",
        "career objective",
        "objectif",
        "objectifs",
        "personal statement",
        "overview",
        "presentation",
    ),
    SectionKind.EXPERIENCE: (
        "experience",
        "experiences",
        "work history",
        "employment",
        "employment history",
        "career history",
        "professional background",
        "parcours professionnel",
        "emplois",
        "internships",
        "internship",
        "stages",
    ),
    SectionKind.EDUCATION: (
        "education",
        "academic background",
        "formation",
        "formations",
        "diplomes",
        "etudes",
        "cursus",
        "parcours academique",
        "parcours scolaire",
    ),
    SectionKind.PROJECTS: ("projects", "project", "projets", "projet", "portfolio"),
    SectionKind.SKILLS: (
        "skills",
        "skill",
        "competencies",
        "competences",
        "technologies",
        "tech stack",
        "stack technique",
        "tools",
        "outils",
        "toolbox",
        "expertise",
        "areas of expertise",
        "savoir faire",
        "programming languages",
        "proficiencies",
    ),
    SectionKind.CERTIFICATIONS: (
        "certifications",
        "certification",
        "certificates",
        "certificats",
        "licenses",
        "licences",
        "accreditations",
    ),
    SectionKind.LANGUAGES: (
        "languages",
        "language",
        "langues",
        "langue",
        "language skills",
        "competences linguistiques",
        "spoken languages",
    ),
    SectionKind.CONTACT: (
        "contact",
        "contacts",
        "contact information",
        "contact details",
        "coordonnees",
        "informations personnelles",
        "personal details",
        "personal information",
    ),
    SectionKind.OTHER: (
        "interests",
        "hobbies",
        "centres d interet",
        "centre d interet",
        "centres d interets",
        "loisirs",
        "publications",
        "awards",
        "honors",
        "honours",
        "achievements",
        "distinctions",
        "prix",
        "volunteering",
        "volunteer experience",
        "benevolat",
        "vie associative",
        "activities",
        "extracurricular activities",
        "activites",
        "references",
        "additional information",
        "informations complementaires",
        "courses",
        "coursework",
        "conferences",
        "talks",
        "patents",
        "memberships",
        "associations",
        "divers",
        "miscellaneous",
    ),
}

_QUALIFIERS = frozenset(
    {
        "professional",
        "professionnel",
        "professionnels",
        "professionnelle",
        "professionnelles",
        "work",
        "relevant",
        "technical",
        "technique",
        "techniques",
        "key",
        "core",
        "main",
        "personal",
        "personnel",
        "personnels",
        "personnelle",
        "personnelles",
        "selected",
        "academic",
        "academique",
        "academiques",
        "universitaire",
        "universitaires",
        "additional",
        "other",
        "autres",
        "recent",
        "industry",
        "research",
        "notable",
        "cles",
        "principales",
        "principaux",
        "my",
        "mes",
        "and",
        "et",
        "de",
        "des",
        "du",
        "d",
        "la",
        "le",
        "les",
        "l",
    }
)

# phrase (as a tuple of words) -> kind; longest phrases are tried first.
_PHRASE_INDEX: dict[tuple[str, ...], SectionKind] = {
    tuple(phrase.split()): kind for kind, phrases in _PHRASES.items() for phrase in phrases
}
_MAX_PHRASE_WORDS = max(len(words) for words in _PHRASE_INDEX)
_MAX_HEADING_WORDS = 6
_MAX_HEADING_CHARS = 60


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def match_section(text: str) -> SectionKind | None:
    """Return the section a heading line introduces, or None if the line is not a heading."""
    stripped = text.strip().rstrip(":：").strip()
    if not stripped or len(stripped) > _MAX_HEADING_CHARS or stripped.endswith("."):
        return None
    words = [word for word in re.split(r"[^a-z0-9+#]+", _normalize(stripped)) if word]
    if not words or len(words) > _MAX_HEADING_WORDS:
        return None

    kind: SectionKind | None = None
    index = 0
    while index < len(words):
        for size in range(min(_MAX_PHRASE_WORDS, len(words) - index), 0, -1):
            phrase_kind = _PHRASE_INDEX.get(tuple(words[index : index + size]))
            if phrase_kind is not None:
                kind = kind or phrase_kind
                index += size
                break
        else:
            if words[index] not in _QUALIFIERS:
                return None
            index += 1
    return kind
