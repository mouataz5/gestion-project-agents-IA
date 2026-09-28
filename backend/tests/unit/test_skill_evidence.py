from collections.abc import Callable

import pytest

from app.cv.evidence import compute_skill_evidence, normalize_skill, technologies_in
from app.cv.files import CvFileKind
from app.cv.models import SkillStrength
from app.cv.parser import parse_cv

pytestmark = pytest.mark.feature("candidate-skills")

DECLARED = [
    "Python",
    "Machine Learning",
    "Deep Learning",
    "LLMs",
    "RAG",
    "Agentic AI",
    "Multi-agent systems",
    "LangGraph",
    "MCP",
    "FastAPI",
    "Docker",
    "Kubernetes",
    "Vector databases",
    "Azure",
    "GCP",
    "Spark",
    "Time-series analysis",
]


@pytest.fixture
def evidence(
    cv_docx: Callable[[list[tuple[str, str]]], bytes], sample_cv_en: list[tuple[str, str]]
) -> dict[str, object]:
    parsed, _ = parse_cv(cv_docx(sample_cv_en), CvFileKind.DOCX)
    return {skill.name: skill for skill in compute_skill_evidence(parsed, DECLARED)}


def _strength(evidence: dict[str, object], name: str) -> SkillStrength:
    return evidence[name].strength  # type: ignore[attr-defined,no-any-return]


@pytest.mark.parametrize(
    "name",
    [
        "LangGraph",
        "Docker",
        "FastAPI",
        "Spark",
        "RAG",
        "MCP",
        "Machine Learning",  # in an experience title
        "Kubernetes",  # "Kubernetes (k8s)"
        "Vector databases",  # "a vector database"
        "Time-series analysis",  # "time-series forecasting"
        "Multi-agent systems",  # "Multi-agent system" in a project
        "LLMs",
    ],
)
def test_skills_used_in_experience_or_projects_are_demonstrated(
    evidence: dict[str, object], name: str
) -> None:
    assert _strength(evidence, name) is SkillStrength.DEMONSTRATED


@pytest.mark.parametrize("name", ["Python", "Azure", "GCP", "SQL", "PyTorch"])
def test_skills_only_listed_are_listed(evidence: dict[str, object], name: str) -> None:
    assert _strength(evidence, name) is SkillStrength.LISTED


@pytest.mark.parametrize("name", ["Deep Learning", "Agentic AI"])
def test_declared_skills_absent_from_the_cv_are_not_evidenced(
    evidence: dict[str, object], name: str
) -> None:
    skill = evidence[name]
    assert skill.strength is SkillStrength.NONE  # type: ignore[attr-defined]
    assert skill.evidence == []  # type: ignore[attr-defined]
    assert skill.sources == ["PROFILE_DECLARED"]  # type: ignore[attr-defined]


def test_sources_and_excerpts_are_recorded(evidence: dict[str, object]) -> None:
    langgraph = evidence["LangGraph"]
    assert langgraph.sources == ["PROFILE_DECLARED"]  # type: ignore[attr-defined]
    sections = {item.section for item in langgraph.evidence}  # type: ignore[attr-defined]
    assert "experience" in sections
    assert any("LangGraph" in item.excerpt for item in langgraph.evidence)  # type: ignore[attr-defined]
    python = evidence["Python"]
    assert python.sources == ["MASTER_CV", "PROFILE_DECLARED"]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("skill", "text", "found"),
    [
        ("Go", "Worked at Google on good things", False),
        ("Go", "Microservices in Go and Rust", True),
        ("R", "Built RAG pipelines", False),
        ("C++", "Optimised C++ kernels", True),
        ("Node.js", "APIs with Node.js", True),
        ("Kubernetes", "deployed on k8s clusters", True),
    ],
)
def test_matching_respects_word_boundaries_and_synonyms(skill: str, text: str, found: bool) -> None:
    assert (technologies_in(text, [skill]) == [skill]) is found


def test_normalization_is_case_and_punctuation_insensitive() -> None:
    assert normalize_skill("  Time-Series  Analysis ") == normalize_skill("time series analysis")
    assert normalize_skill("LLMs") == normalize_skill("llm")
