"""The candidate facts sent to the LLM: deterministic, minimal, no contact data or employer names."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.analysis.facts import build_candidate_facts
from app.analysis.languages import CandidateLanguage
from app.core.config import REPO_ROOT
from app.cv.models import ParsedCV
from app.services.candidate_profile import load_profile

pytestmark = pytest.mark.feature("job-analysis")

TODAY = date(2026, 10, 2)


def _facts(**overrides: object):  # type: ignore[no-untyped-def]
    profile = load_profile(REPO_ROOT / "candidate").model_copy(deep=True)
    profile.contact.email = "alex.example@example.com"
    profile.contact.phone = "+33 6 12 34 56 78"
    values: dict[str, object] = {
        "profile": profile,
        "cv": ParsedCV(
            parser_version="test",
            languages=["Arabic (native), French (fluent), English (professional)"],
            certifications=["Azure AI Engineer Associate (2023)"],
        ),
        "cv_version_id": None,
        "experiences": [
            SimpleNamespace(
                title="Senior AI Engineer",
                employer="Acme Analytics",
                start_date=date(2022, 1, 1),
                end_date=None,
                is_current=True,
                bullets=["Designed a RAG platform with LangGraph."],
                technologies=["LangGraph", "RAG"],
            ),
            SimpleNamespace(
                title="Machine Learning Engineer",
                employer="Beta Labs",
                start_date=date(2019, 9, 1),
                end_date=date(2021, 12, 1),
                is_current=False,
                bullets=["Built forecasting models with Spark."],
                technologies=["Spark"],
            ),
        ],
        "projects": [
            SimpleNamespace(
                name="Job Agent", bullets=["Multi-agent system with MCP."], technologies=["MCP"]
            )
        ],
        "education": [
            SimpleNamespace(degree="MSc in Computer Science", institution="Université de Tunis")
        ],
        "skills": [
            SimpleNamespace(name="LangGraph", strength="DEMONSTRATED"),
            SimpleNamespace(name="Python", strength="LISTED"),
            SimpleNamespace(name="Deep Learning", strength="NONE"),
        ],
        "today": TODAY,
    }
    values.update(overrides)
    return build_candidate_facts(**values)  # type: ignore[arg-type]


def test_facts_are_deterministic() -> None:
    first, second = _facts(), _facts()

    assert first.text == second.text
    assert first.sha256 == second.sha256
    assert len(first.sha256) == 64


def test_contact_data_and_employer_names_are_never_included() -> None:
    text = _facts().text

    for private in (
        "alex.example@example.com",
        "+33 6 12 34 56 78",
        "Acme Analytics",
        "Beta Labs",
        "Université de Tunis",
    ):
        assert private not in text
    assert "Senior AI Engineer" in text
    assert "Designed a RAG platform with LangGraph." in text


def test_skills_without_cv_evidence_are_separated() -> None:
    facts = _facts()

    assert [(s.name, s.strength) for s in facts.skills] == [
        ("LangGraph", "DEMONSTRATED"),
        ("Python", "LISTED"),
        ("Deep Learning", "NONE"),
    ]
    assert '"declared_without_cv_evidence": ["Deep Learning"]' in facts.text


def test_experience_years_and_languages_are_derived() -> None:
    facts = _facts()

    assert facts.experience_years == 7  # whole years since September 2019
    assert facts.languages == (
        CandidateLanguage("Arabic", 5),
        CandidateLanguage("French", 4),
        CandidateLanguage("English", 3),
    )
    assert facts.target_roles[0] == "AI Engineer"


def test_unknown_values_stay_unknown() -> None:
    facts = _facts(experiences=[], cv=ParsedCV(parser_version="test"))

    assert facts.experience_years is None
    assert facts.languages is None
    assert '"languages": "unknown"' in facts.text
