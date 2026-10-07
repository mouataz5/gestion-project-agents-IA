"""Tailoring assembly: the model's answer becomes a version whose immutable facts come from the
master CV, whose rejected texts are repaired, and whose every text has a ledger entry; the facts
the model sees carry no personal data."""

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import anthropic
import pytest

from app.ats.guard import GuardContext, content_paths, guard_context, validate_tailored
from app.ats.keywords import master_evidence
from app.ats.ledger import Origin, ViolationCode
from app.ats.mock_responder import mock_cv_tailoring
from app.ats.requirements import RequirementsOutput, build_requirements, posting_of
from app.ats.scoring import feedback, score_document
from app.ats.tailoring import (
    Assembly,
    ExperienceTailoring,
    ProjectTailoring,
    SkillChoice,
    SourcedText,
    TailoringOutput,
    as_output,
    assemble,
    master_output,
    render_text,
    requirements_brief,
    tailoring_facts,
)
from app.ats.types import KeywordClass
from app.cv.models import ParsedCV
from app.models import Job

pytestmark = pytest.mark.feature("cv-tailoring")

TODAY = date(2026, 10, 6)
JobFactory = Callable[[str, str], Job]


def _context(cv: ParsedCV, job: Job) -> GuardContext:
    return guard_context(master_evidence(cv, TODAY), build_requirements(posting_of(job)))


@pytest.fixture
def nova(sample_master_cv: ParsedCV, board_job: JobFactory) -> GuardContext:
    return _context(sample_master_cv, board_job("nova-ai", "nova-1001"))


def _answer(context: GuardContext, **changes: Any) -> TailoringOutput:
    """The master CV as an answer, with some fields replaced."""
    return master_output(context.master).model_copy(update=changes)


def _mock_round(context: GuardContext, current: Assembly) -> Assembly:
    report = score_document(current.document, context.master, context.requirements)
    request = {
        "facts": tailoring_facts(context.master).data,
        "requirements": requirements_brief(context.requirements),
        "current": as_output(current).model_dump(),
        "feedback": feedback(
            current.document, report, context.master, context.requirements
        ).model_dump(),
    }
    return assemble(TailoringOutput.model_validate(mock_cv_tailoring(request)), context)


# --- assembly ------------------------------------------------------------------------------------


def test_the_mock_tailoring_reaches_the_nova_ceiling_without_a_repair(nova: GuardContext) -> None:
    copy = assemble(master_output(nova.master), nova)

    tailored = _mock_round(nova, copy)

    assert tailored.ledger.repairs == []
    assert validate_tailored(tailored.document, tailored.ledger, nova) == []
    report = score_document(tailored.document, nova.master, nova.requirements)
    assert report.score == 88.3
    assert report.keywords_with(KeywordClass.UNSUPPORTED) == []
    added = [skill.name for skill in tailored.document.skills[len(copy.document.skills) :]]
    assert added == ["LangGraph", "Kubernetes", "MCP", "FastAPI"]
    assert tailored.document.experiences == copy.document.experiences  # every bullet verbatim


def test_immutable_facts_always_come_from_the_master(nova: GuardContext) -> None:
    master = nova.master.cv
    answer = _answer(
        nova,
        experiences=[
            ExperienceTailoring(  # listed out of order, by id
                id="e2",
                title=None,
                bullets=[SourcedText(text="Reduced inference latency by 35%.", sources=["E2.B2"])],
            ),
            ExperienceTailoring(id="E7", title="CTO", bullets=[]),  # unknown: ignored
        ],
        projects=[
            ProjectTailoring(id="P9", bullets=[]),  # unknown: ignored
            ProjectTailoring(id="P1", bullets=[]),
            ProjectTailoring(id="P1", bullets=[]),  # repeated: ignored
        ],
    )

    document = assemble(answer, nova).document

    assert [item.employer for item in document.experiences] == ["Acme Analytics", "Beta Labs"]
    assert [item.dates for item in document.experiences] == [
        item.dates for item in master.experiences
    ]
    assert document.experiences[0].bullets == master.experiences[0].bullets  # left out: kept
    assert document.experiences[1].bullets == ["Reduced inference latency by 35%."]
    assert [project.name for project in document.projects] == ["Job Agent"]
    assert document.projects[0].details == ["personal project"]
    assert (document.education, document.certifications, document.languages) == (
        master.education,
        master.certifications,
        master.languages,
    )
    assert (document.header_lines, document.contact) == (master.header_lines, master.contact)
    assert document.other_sections == master.other_sections


def test_a_rejected_bullet_is_reverted_to_its_source(nova: GuardContext) -> None:
    invented = (
        "Designed a RAG platform with LangGraph serving 2,000 users and cutting costs by 40%."
    )
    answer = _answer(
        nova,
        experiences=[
            ExperienceTailoring(
                id="E1",
                title=None,
                bullets=[
                    SourcedText(text=invented, sources=["E1.B1"]),
                    SourcedText(
                        text="Deployed models on Kubernetes with Kafka.", sources=["E2.B1"]
                    ),
                ],
            )
        ],
    )

    assembly = assemble(answer, nova)

    first = assembly.document.experiences[0]
    assert first.bullets == [
        "Designed a RAG platform with LangGraph and a vector database serving 2,000 users."
    ]  # the second bullet cited another role: no source of its own to revert to
    assert assembly.ledger.item("experiences.0.bullets.0").origin is Origin.REVERTED
    assert [repair.path for repair in assembly.ledger.repairs] == [
        "experiences.0.bullets.0",
        "experiences.0.bullets.1",
    ]
    assert assembly.ledger.repairs[0].rejected_text == invented
    assert [v.code for v in assembly.ledger.repairs[0].violations] == [
        ViolationCode.UNSUPPORTED_NUMBER
    ]
    assert validate_tailored(assembly.document, assembly.ledger, nova) == []


def test_an_unsupported_keyword_never_reaches_the_version(
    sample_master_cv: ParsedCV, board_job: JobFactory
) -> None:
    context = _context(sample_master_cv, board_job("sandstone", "sa-4001"))
    answer = _answer(
        context,
        summary=SourcedText(
            text="AI engineer building LLM, RAG and Deep Learning systems in production.",
            sources=["S"],
        ),
        skills=[SkillChoice(name="Deep Learning", category="Artificial intelligence")],
    )

    assembly = assemble(answer, context)

    assert assembly.document.summary == sample_master_cv.summary  # reverted
    assert assembly.document.skills == sample_master_cv.skills  # nothing backed was chosen
    report = score_document(assembly.document, context.master, context.requirements)
    assert report.keywords_with(KeywordClass.UNSUPPORTED) == []
    assert report.score == 65.7
    assert {repair.path for repair in assembly.ledger.repairs} == {"summary", "skills.0.name"}


def test_skills_must_be_backed_deduplicated_and_labelled(nova: GuardContext) -> None:
    answer = _answer(
        nova,
        skills=[
            SkillChoice(name="LangGraph", category="Frameworks & libraries"),
            SkillChoice(name="langgraph", category=None),  # duplicate
            SkillChoice(name="Kafka", category="Data"),  # not in the master CV
            SkillChoice(name="FastAPI", category="Ninja tools"),  # invented label
            SkillChoice(name="Python", category="Languages"),
        ],
    )

    assembly = assemble(answer, nova)

    assert [(skill.name, skill.category) for skill in assembly.document.skills] == [
        ("LangGraph", "Frameworks & libraries"),
        ("FastAPI", "Frameworks & libraries"),  # the taxonomy label instead
        ("Python", "Languages"),
    ]
    assert [repair.violations[0].code for repair in assembly.ledger.repairs] == [
        ViolationCode.UNSUPPORTED_SKILL,
        ViolationCode.CATEGORY_INVALID,
    ]
    assert assembly.ledger.item("skills.0.name").sources == ["E1.B1"]
    assert validate_tailored(assembly.document, assembly.ledger, nova) == []


def test_title_changes_follow_the_candidate_policy(
    sample_master_cv: ParsedCV, board_job: JobFactory
) -> None:
    requirements = build_requirements(posting_of(board_job("nova-ai", "nova-1001")))
    master = master_evidence(sample_master_cv, TODAY)
    answer = master_output(master).model_copy(
        update={
            "experiences": [
                ExperienceTailoring(id="E1", title="Lead AI Engineer", bullets=[]),
                ExperienceTailoring(id="E2", title="ML Engineer (forecasting)", bullets=[]),
            ]
        }
    )

    locked = assemble(answer, guard_context(master, requirements))
    allowed_context = guard_context(master, requirements, allow_title_changes=True)
    allowed = assemble(answer, allowed_context)

    assert [item.title for item in locked.document.experiences] == [
        "Senior AI Engineer",
        "Machine Learning Engineer",
    ]
    assert {v.code for r in locked.ledger.repairs for v in r.violations} == {
        ViolationCode.TITLE_CHANGED
    }
    assert [item.title for item in allowed.document.experiences] == [
        "Senior AI Engineer",  # "Lead" would add seniority
        "ML Engineer (forecasting)",
    ]
    assert allowed.ledger.item("experiences.1.title").origin is Origin.RETITLED
    assert validate_tailored(allowed.document, allowed.ledger, allowed_context) == []
    assert as_output(allowed).experiences[1].title == "ML Engineer (forecasting)"


def test_every_text_has_a_ledger_entry(nova: GuardContext) -> None:
    for assembly in (
        assemble(master_output(nova.master), nova),
        _mock_round(nova, assemble(master_output(nova.master), nova)),
    ):
        paths = {item.path for item in assembly.ledger.items}
        assert set(content_paths(assembly.document)) <= paths
        assert all(item.sources for item in assembly.ledger.items)


def test_dropped_facts_are_listed_as_unused(nova: GuardContext) -> None:
    assembly = assemble(_answer(nova, projects=[]), nova)

    assert assembly.document.projects == []
    assert assembly.ledger.unused_sources == ["P1.N", "P1.B1", "P1.D1"]


def test_a_version_round_trips_through_the_answer_format(nova: GuardContext) -> None:
    tailored = _mock_round(nova, assemble(master_output(nova.master), nova))

    again = assemble(as_output(tailored), nova)

    assert again.document == tailored.document
    assert again.ledger.repairs == []


# --- what the model sees -------------------------------------------------------------------------


def test_the_facts_carry_no_personal_data(nova: GuardContext) -> None:
    facts = tailoring_facts(nova.master)

    for secret in (
        "Alex Example",
        "alex.example@example.com",
        "+33 6 12 34 56 78",
        "linkedin.com",
        "Acme Analytics",
        "Beta Labs",
        "Université de Tunis",
        "Paris",
        "personal project",  # a detail line
        "Chess",  # another section
    ):
        assert secret not in facts.text, secret
    assert "E1.B1" in facts.text
    assert facts.data["experiences"][0]["period"] == "2022-01 to present"


def test_the_facts_are_deterministic_and_job_independent(
    sample_master_cv: ParsedCV, board_job: JobFactory
) -> None:
    first = _context(sample_master_cv, board_job("nova-ai", "nova-1001"))
    second = _context(sample_master_cv, board_job("sandstone", "sa-4001"))

    assert tailoring_facts(first.master).sha256 == tailoring_facts(second.master).sha256
    assert tailoring_facts(first.master, allow_title_changes=True).sha256 != (
        tailoring_facts(first.master).sha256
    )
    skills = {item["name"]: item for item in tailoring_facts(first.master).data["skills"]}
    assert skills["Python"]["strength"] == "LISTED"
    assert skills["LangGraph"] == {
        "name": "LangGraph",
        "category": "Frameworks & libraries",
        "strength": "DEMONSTRATED",
        "sources": ["E1.B1"],
    }
    assert "Kafka" not in skills


def test_the_requirements_brief_is_grounded(nova: GuardContext) -> None:
    brief = requirements_brief(nova.requirements)

    assert brief["title"] == "Senior AI Engineer"
    assert [keyword["term"] for keyword in brief["keywords"]][:4] == [
        "Python",
        "LLMs",
        "RAG",
        "LangGraph",
    ]
    assert "Visa sponsorship" not in json.dumps(brief)  # never the raw posting


@pytest.mark.parametrize("model", [RequirementsOutput, TailoringOutput])
def test_the_answer_formats_are_valid_structured_output_schemas(model: type) -> None:
    schema = anthropic.transform_schema(model)

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False


def test_the_plain_text_rendering(nova: GuardContext) -> None:
    text = render_text(assemble(master_output(nova.master), nova).document)

    assert text.startswith("Alex Example\nAI Engineer\n")
    assert (
        "Senior AI Engineer — Acme Analytics | Paris, France\nJan 2022 – Present\n• Designed"
        in text
    )
    assert "Job Agent\npersonal project\n• Multi-agent system orchestrating LLMs with MCP." in text
    assert "ML: PyTorch, Scikit-learn, LLMs, RAG" in text
    assert render_text(nova.master.cv) == render_text(nova.master.cv)


def test_french_cvs_keep_french_headings() -> None:
    cv = ParsedCV(parser_version="1", language="fr", summary="Ingénieur IA.", skills=[])

    assert "PROFIL\nIngénieur IA." in render_text(cv)


def test_no_missing_keyword_survives_assembly(
    sample_master_cv: ParsedCV,
    board_job: JobFactory,
    mock_board_ids: list[tuple[str, str]],
) -> None:
    """Whatever the answer slips in - a genuine gap in the summary, in a bullet or in the skills
    section - the assembled version never contains it and passes the final gate."""
    for board, job_id in mock_board_ids:
        context = _context(sample_master_cv, board_job(board, job_id))
        missing = [
            keyword.term
            for keyword in context.requirements.keywords
            if not context.master.supports(keyword.term)
        ]
        for term in missing:
            answer = master_output(context.master)
            first = answer.experiences[0]
            injected = answer.model_copy(
                update={
                    "summary": SourcedText(
                        text=f"{sample_master_cv.summary} Skilled in {term}.", sources=["S"]
                    ),
                    "skills": [*answer.skills, SkillChoice(name=term, category=None)],
                    "experiences": [
                        first.model_copy(
                            update={
                                "bullets": [
                                    SourcedText(
                                        text=f"{first.bullets[0].text[:-1]} using {term}.",
                                        sources=["E1.B1"],
                                    ),
                                    *first.bullets[1:],
                                ]
                            }
                        ),
                        *answer.experiences[1:],
                    ],
                }
            )

            assembly = assemble(injected, context)

            report = score_document(assembly.document, context.master, context.requirements)
            assert report.keywords_with(KeywordClass.UNSUPPORTED) == [], (job_id, term)
            assert validate_tailored(assembly.document, assembly.ledger, context) == [], term
            assert len(assembly.ledger.repairs) == 3, (job_id, term)
