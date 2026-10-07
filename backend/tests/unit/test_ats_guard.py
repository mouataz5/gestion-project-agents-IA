"""The truthfulness guard: generated text may reword the master CV's facts, never add to them; the
final gate keeps every immutable fact, a ledger entry for every text and zero unsupported
keywords."""

from collections.abc import Callable
from datetime import date

import pytest

from app.ats.guard import (
    GuardContext,
    TextKind,
    check_sourced,
    check_title,
    guard_context,
    validate_tailored,
)
from app.ats.keywords import master_evidence
from app.ats.ledger import ViolationCode
from app.ats.requirements import build_requirements, posting_of
from app.ats.tailoring import Assembly, assemble, master_output
from app.cv.models import (
    ContactInfo,
    DateRange,
    ExperienceEntry,
    OtherSection,
    ParsedCV,
    ProjectEntry,
    SkillItem,
    YearMonth,
)
from app.models import Job

pytestmark = pytest.mark.feature("cv-tailoring")

TODAY = date(2026, 10, 6)
JobFactory = Callable[[str, str], Job]
V = ViolationCode


def _context(cv: ParsedCV, job: Job, *, allow_title_changes: bool = False) -> GuardContext:
    return guard_context(
        master_evidence(cv, TODAY),
        build_requirements(posting_of(job)),
        allow_title_changes=allow_title_changes,
    )


@pytest.fixture
def nova(sample_master_cv: ParsedCV, board_job: JobFactory) -> GuardContext:
    return _context(sample_master_cv, board_job("nova-ai", "nova-1001"))


def _codes(
    context: GuardContext,
    text: str,
    sources: tuple[str, ...],
    entry: str = "E1",
    kind: TextKind = TextKind.BULLET,
) -> list[ViolationCode]:
    _, violations = check_sourced(text, list(sources), entry=entry, kind=kind, context=context)
    return [violation.code for violation in violations]


# --- generated texts -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "sources", "entry", "expected"),
    [
        # rewordings of the role's own facts pass
        (
            "Designed a RAG platform with LangGraph and a vector database serving 2,000 users.",
            ("E1.B1",),
            "E1",
            [],
        ),
        (
            "Designed a LangGraph RAG platform with a vector database for 2K users.",
            ("E1.B1",),
            "E1",
            [],
        ),
        ("Designed a RAG platform with LangGraph serving 2,000+ users.", ("E1.B1",), "E1", []),
        ("Deployed models on k8s with Docker and FastAPI.", ("E1.B2",), "E1", []),
        ("Reduced inference latency by 35%.", ("E2.B2",), "E2", []),
        # G1: sources
        ("Built time-series forecasting models with Spark.", ("E2.B1",), "E1", [V.SOURCE_INVALID]),
        ("Designed a RAG platform.", ("E1.B9",), "E1", [V.SOURCE_INVALID]),
        ("Designed a RAG platform.", (), "E1", [V.SOURCE_INVALID]),
        ("Senior AI Engineer building RAG.", ("E1.T",), "E1", [V.SOURCE_INVALID]),
        # G2: technologies and names
        (
            "Designed a RAG platform with LangGraph and Kafka.",
            ("E1.B1",),
            "E1",
            [V.UNSUPPORTED_TECHNOLOGY],
        ),
        ("Designed a RAG platform on Snowflake.", ("E1.B1",), "E1", [V.UNSUPPORTED_TECHNOLOGY]),
        ("Designed a RAG platform with Spark.", ("E1.B1",), "E1", [V.UNSUPPORTED_TECHNOLOGY]),
        ("Designed a RAG platform for Contoso.", ("E1.B1",), "E1", [V.UNSUPPORTED_TECHNOLOGY]),
        # G3: numbers
        (
            "Designed a RAG platform with LangGraph serving 2,000 teams.",
            ("E1.B1",),
            "E1",
            [V.UNSUPPORTED_NUMBER],
        ),
        (
            "Designed a RAG platform with LangGraph that cut costs by 40%.",
            ("E1.B1",),
            "E1",
            [V.UNSUPPORTED_NUMBER],
        ),
        ("Reduced inference latency by 35 times.", ("E2.B2",), "E2", [V.UNSUPPORTED_NUMBER]),
        # G4-G5: the job's words and claims
        ("Evaluated LLM quality in a multi-agent system.", ("P1.B1",), "P1", [V.UNSUPPORTED_TERM]),
        (
            "Mentored engineers on the RAG platform.",
            ("E1.B1",),
            "E1",
            [V.UNSUPPORTED_CLAIM, V.UNSUPPORTED_TERM],
        ),
        (
            "Led the design of a RAG platform with LangGraph.",
            ("E1.B1",),
            "E1",
            [V.UNSUPPORTED_CLAIM],
        ),
        ("Improved inference latency by 35%.", ("E2.B2",), "E2", [V.UNSUPPORTED_CLAIM]),
        ("Oversaw a RAG platform with LangGraph.", ("E1.B1",), "E1", [V.UNSUPPORTED_CLAIM]),
        (
            "Designed a RAG platform with LangGraph for thousands of users.",
            ("E1.B1",),
            "E1",
            [V.UNSUPPORTED_CLAIM],
        ),
        ("Halved inference latency.", ("E2.B2",), "E2", [V.UNSUPPORTED_CLAIM]),
        (
            "Designed a RAG platform with LangGraph for healthcare.",
            ("E1.B1",),
            "E1",
            [V.UNSUPPORTED_TECHNOLOGY],
        ),
        (
            "Designed a RAG platform with LangGraph for german users.",
            ("E1.B1",),
            "E1",
            [V.UNSUPPORTED_TECHNOLOGY],
        ),
        (
            "Designed a RAG platform applying computer science.",
            ("E1.B1",),
            "E1",
            [V.UNSUPPORTED_TERM],
        ),
        # G6-G7: new content and length
        (
            "Designed a secure, scalable, resilient, multilingual RAG platform with LangGraph.",
            ("E1.B1",),
            "E1",
            [V.NEW_CONTENT],
        ),
        (
            "Designed a RAG platform with LangGraph "
            + "and a vector database " * 14
            + "for users.",
            ("E1.B1",),
            "E1",
            [V.TEXT_TOO_LONG],
        ),
        ("   ", ("E1.B1",), "E1", [V.EMPTY_TEXT]),
    ],
)
def test_generated_bullets(
    nova: GuardContext,
    text: str,
    sources: tuple[str, ...],
    entry: str,
    expected: list[ViolationCode],
) -> None:
    assert sorted(set(_codes(nova, text, sources, entry))) == sorted(expected)


@pytest.mark.parametrize(
    ("text", "sources", "expected"),
    [
        ("AI engineer building LLM and RAG systems in production.", ("S",), []),
        (
            "AI engineer with 7 years of experience building LLM and RAG systems in production.",
            ("S",),
            [],  # the years the master CV's dates prove
        ),
        (
            "AI engineer with 5+ years building LLM and RAG systems in production.",
            ("S",),
            [],
        ),
        (
            "AI engineer with 10 years of experience building LLM and RAG systems.",
            ("S",),
            [V.UNSUPPORTED_NUMBER],
        ),
        (
            "AI engineer with a decade of experience building LLM and RAG systems.",
            ("S",),
            [V.UNSUPPORTED_CLAIM],
        ),
        (
            "AI engineer building RAG systems with LangGraph and Kubernetes.",
            ("S", "E1.B1", "E1.B2"),  # the summary may cite any fact
            [],
        ),
        ("AI engineer building RAG systems with LangGraph.", ("S",), [V.UNSUPPORTED_TECHNOLOGY]),
        ("Senior AI engineer building LLM and RAG systems.", ("S",), [V.UNSUPPORTED_CLAIM]),
        (
            "Senior AI engineer building LLM and RAG systems.",
            ("S", "E1.T"),  # the title says Senior
            [],
        ),
    ],
)
def test_the_generated_summary(
    nova: GuardContext, text: str, sources: tuple[str, ...], expected: list[ViolationCode]
) -> None:
    assert sorted(set(_codes(nova, text, sources, "S", TextKind.SUMMARY))) == sorted(expected)


def test_a_summary_over_80_words_is_too_long(nova: GuardContext) -> None:
    text = "AI engineer building LLM and RAG systems in production. " * 10

    assert V.TEXT_TOO_LONG in _codes(nova, text, ("S",), "S", TextKind.SUMMARY)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("AI Engineer", []),  # dropping a seniority word is allowed
        ("Senior AI Engineer (RAG platforms)", []),
        ("Lead AI Engineer", [V.UNSUPPORTED_CLAIM]),
        ("Head of AI Engineering", [V.UNSUPPORTED_CLAIM]),
        ("AI Engineering Director", [V.UNSUPPORTED_CLAIM]),
        ("Senior AI Engineer at Contoso", [V.UNSUPPORTED_TECHNOLOGY]),
    ],
)
def test_a_retitled_role_never_gains_seniority(
    sample_master_cv: ParsedCV, board_job: JobFactory, title: str, expected: list[ViolationCode]
) -> None:
    context = _context(
        sample_master_cv, board_job("nova-ai", "nova-1001"), allow_title_changes=True
    )

    codes = {violation.code for violation in check_title(title, 0, context)}
    assert set(expected) <= codes
    assert bool(codes) == bool(expected)


# --- the final gate ------------------------------------------------------------------------------


@pytest.fixture
def copy(nova: GuardContext) -> Assembly:
    return assemble(master_output(nova.master), nova)


def _gate(context: GuardContext, assembly: Assembly, **changes: object) -> list[ViolationCode]:
    document = assembly.document.model_copy(update=changes)
    return [violation.code for violation in validate_tailored(document, assembly.ledger, context)]


def test_the_master_copy_passes_the_final_gate(nova: GuardContext, copy: Assembly) -> None:
    assert copy.ledger.repairs == []
    assert validate_tailored(copy.document, copy.ledger, nova) == []


def test_every_immutable_fact_is_checked(nova: GuardContext, copy: Assembly) -> None:
    cv = copy.document
    first, second = cv.experiences

    def role(**changes: object) -> list[ExperienceEntry]:
        return [first.model_copy(update=changes), second]

    later = DateRange(text="Jan 2021 – Present", start=YearMonth(year=2021, month=1))
    assert _gate(nova, copy, experiences=role(employer="Google")) == [V.EMPLOYER_CHANGED]
    assert _gate(nova, copy, experiences=role(title="Lead AI Engineer")) == [V.TITLE_CHANGED]
    assert _gate(nova, copy, experiences=role(dates=later)) == [V.DATES_CHANGED]
    assert _gate(nova, copy, experiences=role(location="London")) == [V.LOCATION_CHANGED]
    assert V.DETAILS_CHANGED in _gate(nova, copy, experiences=role(details=["Team of 12"]))
    assert V.EXPERIENCE_MISSING in _gate(nova, copy, experiences=[first])
    extra = ExperienceEntry(title="Data Scientist", employer="Initech")
    assert V.EXPERIENCE_ADDED in _gate(nova, copy, experiences=[first, second, extra])
    changed_degree = [cv.education[0].model_copy(update={"degree": "PhD in Computer Science"})]
    assert _gate(nova, copy, education=changed_degree) == [V.EDUCATION_CHANGED]
    more_certs = [*cv.certifications, "AWS Certified ML Specialty"]
    assert V.CERTIFICATIONS_CHANGED in _gate(nova, copy, certifications=more_certs)
    assert V.LANGUAGES_CHANGED in _gate(nova, copy, languages=["English (native)"])
    other_contact = ContactInfo(emails=["someone@example.org"])
    assert _gate(nova, copy, contact=other_contact) == [V.CONTACT_CHANGED]
    sections = [OtherSection(heading="Awards", lines=["Best paper"])]
    assert _gate(nova, copy, other_sections=sections) == [V.SECTIONS_CHANGED]
    unknown = [ProjectEntry(name="Secret Project")]
    assert V.PROJECT_UNKNOWN in _gate(nova, copy, projects=unknown)


def test_a_text_must_match_its_ledger_entry(nova: GuardContext, copy: Assembly) -> None:
    first, second = copy.document.experiences
    edited = first.model_copy(
        update={"bullets": ["Designed a RAG platform with Kafka.", first.bullets[1]]}
    )

    assert _gate(nova, copy, experiences=[edited, second]) == [V.SOURCE_INVALID]
    without_summary_entry = copy.ledger.model_copy(
        update={"items": [item for item in copy.ledger.items if item.path != "summary"]}
    )
    codes = validate_tailored(copy.document, without_summary_entry, nova)
    assert [violation.code for violation in codes] == [V.LEDGER_MISSING]


def test_skills_must_be_backed_and_labels_known(
    sample_master_cv: ParsedCV, board_job: JobFactory
) -> None:
    context = _context(sample_master_cv, board_job("sandstone", "sa-4001"))
    copy = assemble(master_output(context.master), context)

    def gate(*skills: SkillItem) -> set[ViolationCode]:
        document = copy.document.model_copy(update={"skills": [*copy.document.skills, *skills]})
        return {violation.code for violation in validate_tailored(document, copy.ledger, context)}

    assert {V.UNSUPPORTED_SKILL, V.UNSUPPORTED_KEYWORD} <= gate(SkillItem(name="Deep Learning"))
    assert V.UNSUPPORTED_SKILL in gate(SkillItem(name="Kafka"))
    assert V.CATEGORY_INVALID in gate(SkillItem(name="Docker", category="Ninja skills"))
    assert V.UNSUPPORTED_SKILL not in gate(SkillItem(name="Docker", category="Tools"))


def test_keyword_stuffing_fails_the_gate(nova: GuardContext, copy: Assembly) -> None:
    summary = "Python, LLMs, RAG, LangGraph, FastAPI, Kubernetes and MCP."

    assert V.STUFFING in _gate(nova, copy, summary=summary)
