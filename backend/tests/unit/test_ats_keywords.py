"""Job keywords in a CV document: where they appear, and whether the master CV backs them."""

from collections.abc import Callable
from datetime import date

import pytest

from app.ats.keywords import (
    classify_keywords,
    master_evidence,
    most_recent_experience,
    zones_of,
)
from app.ats.requirements import JobRequirements, Keyword, build_requirements, posting_of
from app.ats.taxonomy import canonical_key, canonical_name, category_of
from app.ats.types import EducationLevel, Importance, KeywordClass, KeywordSource
from app.cv.models import DateRange, ExperienceEntry, ParsedCV, SkillItem, YearMonth
from app.models import Job

pytestmark = pytest.mark.feature("ats-engine")

TODAY = date(2026, 10, 6)
JobFactory = Callable[[str, str], Job]


def _keyword(term: str, importance: Importance = Importance.REQUIRED) -> Keyword:
    return Keyword(
        term=canonical_name(term),
        key=canonical_key(term),
        category=category_of(term),
        importance=importance,
        sources=[KeywordSource.LISTED],
    )


def _requirements(*keywords: Keyword) -> JobRequirements:
    return JobRequirements(
        title="Engineer", title_terms=["engin"], seniority="UNKNOWN", keywords=list(keywords)
    )


def _role(title: str, start: int, *, current: bool = False) -> ExperienceEntry:
    return ExperienceEntry(
        title=title,
        dates=DateRange(text=str(start), start=YearMonth(year=start), is_current=current),
    )


def test_the_zones_of_a_cv(sample_master_cv: ParsedCV) -> None:
    zones = zones_of(sample_master_cv)

    assert zones.summary == ("AI engineer building LLM and RAG systems in production.",)
    assert zones.skills[-3:] == ("Languages", "ML", "Cloud")  # names, then the labels
    assert "Job Agent" in zones.experience
    assert "personal project" in zones.experience
    assert zones.education == ("MSc in Computer Science", "Azure AI Engineer Associate (2023)")
    assert zones.headline == ("AI Engineer",)  # not the name, not the contact line
    assert zones.title == (
        "AI Engineer",
        "AI engineer building LLM and RAG systems in production.",
        "Senior AI Engineer",
    )


def test_the_most_recent_experience() -> None:
    old, newer = _role("Data Analyst", 2015), _role("ML Engineer", 2019)
    current = _role("AI Lead", 2018, current=True)

    def title(*roles: ExperienceEntry) -> str | None:
        recent = most_recent_experience(ParsedCV(parser_version="1", experiences=list(roles)))
        return recent.title if recent else None

    assert title(old, newer) == "ML Engineer"
    assert title(old, current, newer) == "AI Lead"  # a current role comes first
    assert title(ExperienceEntry(title="A"), ExperienceEntry(title="B")) == "A"
    assert title() is None


def test_the_candidate_facts_come_from_the_master_cv(sample_master_cv: ParsedCV) -> None:
    master = master_evidence(sample_master_cv, TODAY)

    assert (master.years, master.seniority) == (7, "SENIOR")  # since Sep 2019
    assert master.education_level is EducationLevel.MASTER
    assert master.supports("ML")  # the "ML:" label of the skills section
    assert not master.supports("Kafka")


@pytest.mark.parametrize(
    ("start", "seniority"), [(2019, "SENIOR"), (2023, "MID"), (2025, "JUNIOR"), (None, "UNKNOWN")]
)
def test_without_a_seniority_word_the_years_decide(start: int | None, seniority: str) -> None:
    role = _role("AI Engineer", start) if start else ExperienceEntry(title="AI Engineer")
    cv = ParsedCV(parser_version="1", experiences=[role])

    assert master_evidence(cv, TODAY).seniority == seniority


def test_every_nova_keyword_is_matched_by_the_master_cv(
    sample_master_cv: ParsedCV, board_job: JobFactory
) -> None:
    requirements = build_requirements(posting_of(board_job("nova-ai", "nova-1001")))
    master = master_evidence(sample_master_cv, TODAY)

    results = classify_keywords(zones_of(sample_master_cv), master, requirements)

    by_term = {result.term: result for result in results}
    assert {result.status for result in results} == {KeywordClass.MATCHED}
    flags = {
        term: (result.prominent, result.listed, result.demonstrated, result.score)
        for term, result in by_term.items()
    }
    assert flags["Python"] == (True, True, False, 1.0)  # listed, never shown in a role
    assert flags["LangGraph"] == (False, False, True, 0.8)
    assert flags["Machine Learning"] == (True, True, True, 1.0)  # the "ML:" label, the E2 title
    assert flags["English"] == (True, False, False, 1.0)  # the languages section is prominent
    assert by_term["LLMs"].evidence == ["S", "P1.B1", "K5"]
    assert by_term["MCP"].evidence == ["P1.B1"]
    assert not by_term["English"].technical
    assert by_term["FastAPI"].technical


def test_dropping_a_project_makes_its_keywords_available(
    sample_master_cv: ParsedCV, board_job: JobFactory
) -> None:
    requirements = build_requirements(posting_of(board_job("nova-ai", "nova-1001")))
    master = master_evidence(sample_master_cv, TODAY)
    document = sample_master_cv.model_copy(update={"projects": []})

    by_term = {r.term: r for r in classify_keywords(zones_of(document), master, requirements)}

    assert by_term["MCP"].status is KeywordClass.AVAILABLE
    assert by_term["MCP"].score == 0
    assert by_term["LLMs"].status is KeywordClass.MATCHED  # still in the summary and skills
    assert by_term["LLMs"].demonstrated is False  # the project was the only role showing it


def test_a_keyword_without_master_evidence_is_unsupported(sample_master_cv: ParsedCV) -> None:
    requirements = _requirements(_keyword("Kafka"), _keyword("Deep Learning", Importance.PREFERRED))
    master = master_evidence(sample_master_cv, TODAY)
    document = sample_master_cv.model_copy(
        update={"skills": [*sample_master_cv.skills, SkillItem(name="Kafka")]}
    )

    by_term = {r.term: r for r in classify_keywords(zones_of(document), master, requirements)}

    kafka = by_term["Kafka"]
    assert kafka.status is KeywordClass.UNSUPPORTED
    assert (kafka.present, kafka.supported, kafka.score) == (True, False, 0)  # never scores
    assert kafka.evidence == []
    assert by_term["Deep Learning"].status is KeywordClass.MISSING


def test_a_genuine_gap_is_missing(sample_master_cv: ParsedCV, board_job: JobFactory) -> None:
    requirements = build_requirements(posting_of(board_job("sandstone", "sa-4001")))
    master = master_evidence(sample_master_cv, TODAY)

    results = classify_keywords(zones_of(sample_master_cv), master, requirements)

    assert {r.term: r.status for r in results} == {
        "LLMs": KeywordClass.MATCHED,
        "Deep Learning": KeywordClass.MISSING,
        "Python": KeywordClass.MATCHED,
        "English": KeywordClass.MATCHED,
        "Arabic": KeywordClass.MATCHED,
        "Agentic AI": KeywordClass.MISSING,
    }


def test_spoken_languages_match_in_any_language() -> None:
    cv = ParsedCV(parser_version="1", languages=["Arabe, Français, Anglais"])
    requirements = _requirements(_keyword("French"), _keyword("German"))

    by_term = {
        r.term: r for r in classify_keywords(zones_of(cv), master_evidence(cv, TODAY), requirements)
    }

    assert by_term["French"].status is KeywordClass.MATCHED
    assert by_term["French"].prominent
    assert by_term["German"].status is KeywordClass.MISSING
