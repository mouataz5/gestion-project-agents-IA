"""Skill evidence: which skills the confirmed master CV actually supports, and where.

Strength rules (a skill is only as strong as its best evidence):
    DEMONSTRATED  the skill appears in an experience or a project (title, bullets, details)
    LISTED        it only appears in the skills section, summary, education or certifications
    NONE          declared in the profile but absent from the CV - never used for tailoring

Matching is case-insensitive (except for names of one or two characters such as "Go" or
"R"), accent-insensitive, respects word boundaries ("Go" does not match "Google") and knows
common synonyms ("k8s" -> Kubernetes, "large language models" -> LLMs).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from functools import lru_cache

from app.cv.models import (
    EvidenceItem,
    ParsedCV,
    SkillEvidence,
    SkillSource,
    SkillStrength,
)

MAX_EVIDENCE_PER_SKILL = 5
_EXCERPT_CHARS = 220

# The first spelling is the canonical display name of the group.
_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("Kubernetes", "k8s"),
    ("LLMs", "LLM", "large language model", "grand modèle de langage", "grands modèles de langage"),
    ("RAG", "retrieval augmented generation"),
    ("Machine Learning", "ML", "apprentissage automatique"),
    ("Deep Learning", "neural network", "apprentissage profond", "réseaux de neurones"),
    ("NLP", "natural language processing", "traitement automatique du langage", "TALN"),
    ("Computer Vision", "vision par ordinateur"),
    (
        "Agentic AI",
        "agentic",
        "AI agent",
        "LLM agent",
        "autonomous agent",
        "agents IA",
        "agent IA",
        "agents LLM",
        "agent LLM",
        "IA agentique",
    ),
    ("Multi-agent systems", "multi-agent", "multi agents", "systèmes multi-agents"),
    ("MCP", "Model Context Protocol"),
    (
        "Vector databases",
        "vector database",
        "vector DB",
        "vector store",
        "vector search",
        "base de données vectorielle",
        "bases de données vectorielles",
    ),
    ("Time-series analysis", "time series", "séries temporelles", "série temporelle"),
    ("MLOps", "ML Ops"),
    ("Generative AI", "GenAI", "Gen AI", "IA générative"),
    ("GCP", "Google Cloud", "Google Cloud Platform"),
    ("AWS", "Amazon Web Services"),
    ("Azure", "Microsoft Azure"),
    ("Spark", "Apache Spark", "PySpark"),
    ("Scikit-learn", "sklearn"),
    ("PostgreSQL", "Postgres"),
    ("JavaScript", "JS"),
    ("TypeScript", "TS"),
    ("Node.js", "NodeJS"),
    ("Go", "Golang"),
    ("Hugging Face", "HuggingFace"),
    ("CI/CD", "CICD", "continuous integration"),
)

# Where a skill was found -> does it demonstrate practical use?
_DEMONSTRATING_SECTIONS = frozenset({"experience", "projects"})


def _fold(text: str) -> str:
    """Accent-insensitive form that keeps the string length stable for ASCII input."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_skill(name: str) -> str:
    """Comparison key: case, accents, hyphens/underscores/slashes and a final plural ignored."""
    text = _fold(name).casefold()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[\s\-_/]+", " ", text).strip()
    words = text.split(" ")
    last = words[-1]
    if len(last) > 3 and last.endswith("s") and not last.endswith(("ss", "us", "is")):
        words[-1] = last[:-1]
    return " ".join(words)


_GROUP_BY_KEY: dict[str, tuple[str, ...]] = {
    normalize_skill(spelling): group for group in _SYNONYM_GROUPS for spelling in group
}


def canonical_key(name: str) -> str:
    key = normalize_skill(name)
    group = _GROUP_BY_KEY.get(key)
    return normalize_skill(group[0]) if group else key


def _spellings(name: str) -> tuple[str, ...]:
    group = _GROUP_BY_KEY.get(normalize_skill(name), ())
    return tuple(dict.fromkeys((name, *group)))


def _spelling_pattern(spelling: str) -> str:
    tokens = [token for token in re.split(r"[\s\-_]+", _fold(spelling).strip()) if token]
    last = tokens[-1]
    plural = ""
    if last.isalpha() and len(last) >= 3:
        if (
            len(last) > 3
            and last.lower().endswith("s")
            and not last.lower().endswith(("ss", "us", "is"))
        ):
            tokens[-1] = last[:-1]
        plural = "(?:e?s)?"
    body = r"[\s\-]*".join(re.escape(token) for token in tokens) + plural
    flags = "-i" if len(spelling.strip()) <= 2 else "i"
    return f"(?{flags}:{body})"


@lru_cache(maxsize=1024)
def _skill_regex(name: str) -> re.Pattern[str]:
    alternatives = "|".join(_spelling_pattern(spelling) for spelling in _spellings(name))
    return re.compile(rf"(?<![\w+#])(?:{alternatives})(?![\w+#])")


def mentions(text: str, skill: str) -> bool:
    return _skill_regex(skill).search(_fold(text)) is not None


def technologies_in(text: str, skills: Iterable[str]) -> list[str]:
    """The skills (as given, in order) that ``text`` mentions."""
    return [skill for skill in skills if mentions(text, skill)]


# ---------------------------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------------------------


def evidence_texts(cv: ParsedCV) -> Iterator[tuple[str, str]]:
    """(section, text) pairs searched for evidence. Employers and locations are excluded."""
    for experience in cv.experiences:
        for text in (experience.title, *experience.details, *experience.bullets):
            yield "experience", text
    for project in cv.projects:
        for text in (project.name, *project.details, *project.bullets):
            yield "projects", text
    for skill in cv.skills:
        yield "skills", skill.name
    if cv.summary:
        yield "summary", cv.summary
    for education in cv.education:
        for text in (education.degree, *education.details, *education.bullets):
            yield "education", text
    for certification in cv.certifications:
        yield "certifications", certification
    for section in cv.other_sections:
        for text in section.lines:
            yield "other", text


def _excerpt(text: str, skill: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= _EXCERPT_CHARS:
        return compact
    match = _skill_regex(skill).search(_fold(compact))
    center = match.start() if match else 0
    start = max(0, center - _EXCERPT_CHARS // 2)
    end = min(len(compact), start + _EXCERPT_CHARS)
    return ("…" if start else "") + compact[start:end].strip() + ("…" if end < len(compact) else "")


@dataclass
class _Skill:
    name: str
    key: str
    category: str | None = None
    sources: set[SkillSource] = field(default_factory=set)
    aliases: list[str] = field(default_factory=list)


def _display_name(name: str) -> str:
    # "Python (pandas, numpy)" -> "Python"; the full text stays in the evidence excerpt.
    stripped = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    return stripped or name.strip()


def _skill_universe(cv: ParsedCV, declared: Sequence[str]) -> list[_Skill]:
    skills: dict[str, _Skill] = {}

    def add(name: str, source: SkillSource, category: str | None = None) -> None:
        display = _display_name(name)
        if not display or len(display) > 100:
            return
        key = canonical_key(display)
        if not key:
            return
        skill = skills.setdefault(key, _Skill(name=display, key=key, category=category))
        skill.sources.add(source)
        if display not in skill.aliases:
            skill.aliases.append(display)
        if skill.category is None:
            skill.category = category

    for name in declared:
        add(name, SkillSource.PROFILE_DECLARED)
    for item in cv.skills:
        add(item.name, SkillSource.MASTER_CV, item.category)
    return list(skills.values())


def compute_skill_evidence(cv: ParsedCV, declared: Sequence[str]) -> list[SkillEvidence]:
    """Evidence for every declared skill and every skill listed in the CV."""
    texts = list(evidence_texts(cv))
    results: list[SkillEvidence] = []
    for skill in _skill_universe(cv, declared):
        items: list[EvidenceItem] = []
        seen: set[tuple[str, str]] = set()
        demonstrated = False
        for section, text in texts:
            if not text or not any(mentions(text, alias) for alias in skill.aliases):
                continue
            demonstrated = demonstrated or section in _DEMONSTRATING_SECTIONS
            excerpt = _excerpt(text, skill.aliases[0])
            if (section, excerpt) not in seen:
                seen.add((section, excerpt))
                items.append(EvidenceItem(section=section, excerpt=excerpt))
        items.sort(key=lambda item: item.section not in _DEMONSTRATING_SECTIONS)
        if demonstrated:
            strength = SkillStrength.DEMONSTRATED
        elif items:
            strength = SkillStrength.LISTED
        else:
            strength = SkillStrength.NONE
        results.append(
            SkillEvidence(
                name=skill.name,
                normalized_name=skill.key,
                category=skill.category,
                strength=strength,
                sources=sorted(skill.sources),
                evidence=items[:MAX_EVIDENCE_PER_SKILL],
            )
        )
    return results
