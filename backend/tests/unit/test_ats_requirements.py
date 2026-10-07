"""Job requirements for the ATS engine: merged, grounded in the posting, never invented; and the
source ids of the master CV that tailored text may cite."""

from collections.abc import Callable

import pytest

from app.analysis.visa import quote_in_text
from app.ats.mock_responder import mock_job_requirements
from app.ats.requirements import (
    ExtractedEducation,
    ExtractedKeyword,
    RequirementsOutput,
    build_requirements,
    education_from_text,
    posting_context,
    posting_of,
    years_from_text,
)
from app.ats.sources import build_sources, master_text, master_texts, may_cite
from app.ats.taxonomy import Category, mentions
from app.ats.types import EducationLevel, Importance, KeywordSource
from app.cv.models import ParsedCV
from app.models import Job

pytestmark = pytest.mark.feature("ats-engine")

JobFactory = Callable[[str, str], Job]


def test_the_nova_requirements(board_job: JobFactory) -> None:
    requirements = build_requirements(posting_of(board_job("nova-ai", "nova-1001")))

    keywords = {keyword.term: keyword for keyword in requirements.keywords}
    assert [keyword.term for keyword in requirements.keywords] == [
        "Python",
        "LLMs",
        "RAG",
        "LangGraph",
        "English",
        "French",
        "Kubernetes",
        "MCP",
        "Machine Learning",
        "FastAPI",
    ]
    assert {term for term, k in keywords.items() if k.importance is Importance.REQUIRED} == {
        "Python",
        "LLMs",
        "RAG",
        "LangGraph",
        "English",
        "French",
    }
    assert keywords["FastAPI"].sources == [KeywordSource.SCANNED]
    assert keywords["French"].category is Category.SPOKEN_LANGUAGE
    assert keywords["Machine Learning"].quote == (
        "5+ years building ML systems, including 2 years with LLMs in production."
    )
    assert (requirements.min_years, requirements.seniority) == (5, "SENIOR")
    assert requirements.education.level is EducationLevel.MASTER
    assert requirements.education.fields == ["Computer Science"]
    assert requirements.education.equivalent_experience_accepted is True
    assert requirements.responsibilities == [
        "Design RAG pipelines",
        "Evaluate LLM quality",
        "Mentor engineers",
    ]
    assert requirements.title_terms == ["ai", "engin"]  # "Senior" is the seniority, not a term


def test_a_job_without_stated_years_or_degree(board_job: JobFactory) -> None:
    requirements = build_requirements(posting_of(board_job("sandstone", "sa-4001")))

    assert [keyword.term for keyword in requirements.keywords] == [
        "LLMs",
        "Deep Learning",
        "Python",
        "English",
        "Arabic",
        "Agentic AI",  # "LLM agents" in the description
    ]
    assert requirements.min_years is None
    assert requirements.education.level is EducationLevel.NONE_STATED
    assert requirements.responsibilities == []
    assert requirements.title_terms == ["ai", "engin", "research"]


def test_generic_terms_are_never_keywords(board_job: JobFactory) -> None:
    posting = posting_of(board_job("nova-ai", "nova-1001"))
    extraction = RequirementsOutput(
        seniority="SENIOR",
        min_years_experience=None,
        years_quote=None,
        keywords=[
            ExtractedKeyword(
                term="AI", category=Category.AI_ML, importance="REQUIRED", quote="Nova AI"
            )
        ],
        responsibilities=[],
        education=ExtractedEducation(
            level="NONE_STATED", fields=[], equivalent_experience_accepted=None, quote=None
        ),
    )

    terms = [keyword.term for keyword in build_requirements(posting, extraction).keywords]

    assert "AI" not in terms


def test_the_extraction_is_grounded_in_the_posting(board_job: JobFactory) -> None:
    posting = posting_of(board_job("nova-ai", "nova-1001"))
    extraction = RequirementsOutput(
        seniority="SENIOR",
        min_years_experience=7,
        years_quote="7 years of experience",  # not in the posting
        keywords=[
            ExtractedKeyword(
                term="Kubernetes",
                category=Category.DEVOPS,
                importance="REQUIRED",
                quote="Strong Kubernetes skills",  # not verbatim
            ),
            ExtractedKeyword(
                term="Rust",
                category=Category.PROGRAMMING_LANGUAGE,
                importance="REQUIRED",
                quote="-",
            ),
            ExtractedKeyword(
                term="agents",
                category=Category.AI_ML,
                importance="PREFERRED",
                quote="You will design retrieval-augmented generation (RAG) pipelines and agents "
                "in production.",
            ),
        ],
        responsibilities=["Design RAG pipelines", "Lead the evaluation efforts"],
        education=ExtractedEducation(
            level="PHD",
            fields=["Physics"],
            equivalent_experience_accepted=False,
            quote="PhD in Physics",  # not in the posting
        ),
    )

    requirements = build_requirements(posting, extraction)

    keywords = {keyword.term: keyword for keyword in requirements.keywords}
    assert keywords["Kubernetes"].importance is Importance.REQUIRED  # the highest importance wins
    assert keywords["Kubernetes"].quote == "Kubernetes, MCP"  # replaced by the posting's words
    assert "Rust" not in keywords
    assert keywords["agents"].category is Category.AI_ML
    assert keywords["agents"].sources == [KeywordSource.EXTRACTED]
    assert requirements.min_years == 5
    assert requirements.education.level is EducationLevel.MASTER
    assert requirements.responsibilities == [
        "Design RAG pipelines",
        "Evaluate LLM quality",
        "Mentor engineers",
    ]
    assert requirements.discarded == [
        "Rust: not in the posting",
        "Lead the evaluation efforts: not quoted from the posting",
    ]


def test_the_mock_extraction_is_grounded_for_every_fixture_job(
    board_job: JobFactory, mock_board_ids: list[tuple[str, str]]
) -> None:
    assert len(mock_board_ids) >= 10
    for board, job_id in mock_board_ids:
        posting = posting_of(board_job(board, job_id))
        extraction = RequirementsOutput.model_validate(
            mock_job_requirements({"posting": posting_context(posting)})
        )

        requirements = build_requirements(posting, extraction)

        assert requirements.discarded == [], job_id
        for keyword in requirements.keywords:
            if keyword.quote is not None:
                assert quote_in_text(keyword.quote, posting.text), (job_id, keyword.term)
                assert mentions(keyword.quote, keyword.term), (job_id, keyword.term)
        assert {k.key for k in requirements.keywords} == {
            k.key for k in build_requirements(posting).keywords
        }, job_id


@pytest.mark.parametrize(
    ("texts", "years"),
    [
        (("5+ years building ML systems, including 2 years with LLMs.",), 5),
        (("Au moins 3 ans d'expérience en NLP.",), 3),
        ((None, "We expect 4 yrs of Python."), 4),
        (("No figure here.",), None),
    ],
)
def test_years_of_experience(texts: tuple[str | None, ...], years: int | None) -> None:
    assert years_from_text(*texts)[0] == years


@pytest.mark.parametrize(
    ("text", "level", "fields", "equivalent"),
    [
        ("MSc in Computer Science or equivalent experience.", "MASTER", ["Computer Science"], True),
        ("PhD in Applied Mathematics preferred.", "PHD", ["Applied Mathematics"], False),
        ("Bachelor's degree in Statistics.", "BACHELOR", ["Statistics"], False),
        ("Diplôme d'ingénieur ou Bac+5 en informatique.", "MASTER", ["Informatique"], False),
        ("A passion for AI.", "NONE_STATED", [], False),
    ],
)
def test_education_requirements(text: str, level: str, fields: list[str], equivalent: bool) -> None:
    education = education_from_text(text)

    assert education.level is EducationLevel(level)
    assert education.fields == fields
    assert education.equivalent_experience_accepted is equivalent


def test_source_ids_follow_the_master_cv(sample_master_cv: ParsedCV) -> None:
    sources = build_sources(sample_master_cv)

    assert list(sources)[:10] == [
        "S",
        "E1.T",
        "E1.B1",
        "E1.B2",
        "E2.T",
        "E2.B1",
        "E2.B2",
        "P1.N",
        "P1.B1",
        "P1.D1",
    ]
    assert sources["E1.B1"].text.startswith("Designed a RAG platform with LangGraph")
    assert sources["E1.B1"].label == "Experience 1 · bullet 1"
    assert sources["E1.B1"].path == "experiences.0.bullets.0"
    assert sources["ED1"].text == "MSc in Computer Science"
    assert sources["L2"].text == "French (fluent)"


def test_citations_are_scoped_to_their_entry(sample_master_cv: ParsedCV) -> None:
    sources = build_sources(sample_master_cv)

    assert may_cite("E1", sources["E1.B2"])
    assert may_cite("P1", sources["P1.D1"])
    assert not may_cite("E1", sources["E2.B1"])  # no moving facts between roles
    assert not may_cite("P1", sources["E1.B1"])
    assert not may_cite("E1", sources["E1.T"])  # a title is not something the candidate did
    assert not may_cite("P1", sources["P1.N"])
    assert not may_cite("E2", sources["E2.T"])
    assert all(may_cite("S", source) for source in sources.values())


def test_master_text_leaves_out_contact_data_and_employers(sample_master_cv: ParsedCV) -> None:
    text = master_text(sample_master_cv)

    assert "LangGraph" in text
    assert "ML" in master_texts(sample_master_cv)  # a skills-section label is the candidate's claim
    assert "alex.example@example.com" not in text
    assert "Acme Analytics" not in text
    assert "Université de Tunis" not in text
