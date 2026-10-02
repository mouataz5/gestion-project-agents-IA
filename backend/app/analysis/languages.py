"""Language requirements versus the candidate's languages (profile first, then the CV).

Levels are ranked 1 (basic) to 5 (native); CEFR codes map onto them. Languages the model reads in
free text must appear in the posting. Unknown candidate languages give ``None`` (never guessed).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from app.analysis.schemas import LanguageCheck, LanguageRequirementOutput
from app.cv.evidence import mentions
from app.schemas.candidate import SpokenLanguage

LEVEL_NAMES = {5: "native", 4: "fluent", 3: "professional", 2: "intermediate", 1: "basic"}
_PROFILE_LEVELS = {name: rank for rank, name in LEVEL_NAMES.items()}
_LEVEL_PATTERNS: tuple[tuple[int, re.Pattern[str]], ...] = (
    (5, re.compile(r"\b(native|mother\s+tongue|maternelle|natif|native|muttersprache)\b", re.I)),
    (4, re.compile(r"\b(fluent|fluency|bilingual|courant|bilingue|fließend|c1|c2)\b", re.I)),
    (3, re.compile(r"\b(professional|business|working|professionnel|b2)\b", re.I)),
    (2, re.compile(r"\b(intermediate|conversational|intermédiaire|b1)\b", re.I)),
    (1, re.compile(r"\b(basic|beginner|notions|débutant|grundkenntnisse|a1|a2)\b", re.I)),
)
_ALIASES: dict[str, tuple[str, ...]] = {
    "English": ("english", "anglais", "englisch", "inglés", "ingles"),
    "French": ("french", "français", "francais", "französisch", "francés"),
    "German": ("german", "allemand", "deutsch"),
    "Arabic": ("arabic", "arabe", "arabisch", "árabe"),
    "Spanish": ("spanish", "espagnol", "spanisch", "español", "espanol"),
    "Italian": ("italian", "italien", "italienisch", "italiano"),
    "Dutch": ("dutch", "néerlandais", "neerlandais", "niederländisch", "nederlands", "flemish"),
    "Portuguese": ("portuguese", "portugais", "portugiesisch", "português"),
    "Swedish": ("swedish", "suédois", "schwedisch", "svenska"),
    "Danish": ("danish", "danois", "dänisch", "dansk"),
    "Norwegian": ("norwegian", "norvégien", "norwegisch", "norsk"),
    "Finnish": ("finnish", "finnois", "finnisch", "suomi"),
    "Polish": ("polish", "polonais", "polnisch", "polski"),
    "Turkish": ("turkish", "turc", "türkisch", "türkçe"),
    "Russian": ("russian", "russe", "russisch"),
    "Chinese": ("chinese", "mandarin", "chinois", "chinesisch"),
    "Japanese": ("japanese", "japonais", "japanisch"),
}
_ALIAS_INDEX = {alias: name for name, aliases in _ALIASES.items() for alias in aliases}
_SPLIT = re.compile(r"[,;|/•·]|\s+-\s+|\n")


@dataclass(frozen=True)
class CandidateLanguage:
    language: str  # canonical English name
    level: int | None  # 1 (basic) .. 5 (native); None: not stated


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


def canonical_language(name: str) -> str:
    folded = _fold(name)
    if folded in _ALIAS_INDEX:
        return _ALIAS_INDEX[folded]
    for alias, canonical in _ALIAS_INDEX.items():
        if re.search(rf"\b{re.escape(alias)}\b", folded):
            return canonical
    return name.strip().title()


def parse_level(text: str | None) -> int | None:
    if not text:
        return None
    for rank, pattern in _LEVEL_PATTERNS:
        if pattern.search(text):
            return rank
    return None


def candidate_languages(
    profile_languages: Sequence[SpokenLanguage] | None, cv_languages: Sequence[str]
) -> list[CandidateLanguage] | None:
    """The profile's languages when filled in, else the ones parsed from the CV, else unknown."""
    if profile_languages:
        return [
            CandidateLanguage(canonical_language(item.language), _PROFILE_LEVELS[item.level.value])
            for item in profile_languages
        ]
    found: list[CandidateLanguage] = []
    for line in cv_languages:
        for part in _SPLIT.split(line):
            folded = _fold(part)
            name = next(
                (
                    canonical
                    for alias, canonical in _ALIAS_INDEX.items()
                    if re.search(rf"\b{re.escape(alias)}\b", folded)
                ),
                None,
            )
            if name and all(item.language != name for item in found):
                found.append(CandidateLanguage(name, parse_level(part)))
    return found or None


def check_languages(
    job_languages: Sequence[str],
    requirements: Sequence[LanguageRequirementOutput],
    candidate: Sequence[CandidateLanguage] | None,
    *,
    job_text: str,
) -> tuple[list[LanguageCheck], bool | None]:
    """Per-language checks and whether every *required* language is met (None: unknown)."""
    wanted: dict[str, tuple[bool, str | None]] = {}
    for name in job_languages:  # listed by the source: treated as required
        wanted.setdefault(canonical_language(name), (True, None))
    for requirement in requirements:
        if not mentions(job_text, requirement.language):
            continue  # not in the posting: an invented requirement is ignored
        wanted[canonical_language(requirement.language)] = (
            requirement.required,
            requirement.level,
        )

    checks: list[LanguageCheck] = []
    for language, (required, level_text) in wanted.items():
        needed = parse_level(level_text)
        own = (
            next((item for item in candidate if item.language == language), None)
            if candidate is not None
            else None
        )
        met: bool | None
        if candidate is None:
            met = None
        elif own is None:
            met = False
        elif needed is None:
            met = True
        elif own.level is None:
            met = None
        else:
            met = own.level >= needed
        checks.append(
            LanguageCheck(
                language=language,
                required=required,
                level=level_text,
                candidate_level=LEVEL_NAMES.get(own.level) if own and own.level else None,
                met=met,
            )
        )

    required_checks = [check for check in checks if check.required]
    if any(check.met is False for check in required_checks):
        return checks, False
    if any(check.met is None for check in required_checks):
        return checks, None
    return checks, True
