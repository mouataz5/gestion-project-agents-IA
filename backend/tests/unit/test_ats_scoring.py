"""ATS score ``ats-score.v1``: the formula, its golden values on the sample CV, keyword stuffing,
the supported ceiling, the feedback for the next iteration and the candidate's gaps."""

import random
from collections.abc import Callable
from datetime import date

import pytest

from app.ats.keywords import MasterEvidence, is_technical, master_evidence
from app.ats.requirements import (
    EducationRequirement,
    JobRequirements,
    build_requirements,
    posting_of,
    title_terms,
)
from app.ats.scoring import (
    DEFAULT_WEIGHTS,
    GapKind,
    ScoreReport,
    StuffingCode,
    ceiling,
    feedback,
    gaps,
    score_document,
    validate_weights,
)
from app.ats.types import EducationLevel, Importance, KeywordClass
from app.cv.models import OtherSection, ParsedCV, SkillItem
from app.models import Job

pytestmark = pytest.mark.feature("ats-engine")

TODAY = date(2026, 10, 6)
JobFactory = Callable[[str, str], Job]


@pytest.fixture
def master(sample_master_cv: ParsedCV) -> MasterEvidence:
    return master_evidence(sample_master_cv, TODAY)


@pytest.fixture
def nova(board_job: JobFactory) -> JobRequirements:
    return build_requirements(posting_of(board_job("nova-ai", "nova-1001")))


@pytest.fixture
def sandstone(board_job: JobFactory) -> JobRequirements:
    return build_requirements(posting_of(board_job("sandstone", "sa-4001")))


def _scores(report: ScoreReport) -> dict[str, float | None]:
    return {component.name: component.score for component in report.components}


def _with(cv: ParsedCV, **changes: object) -> ParsedCV:
    return cv.model_copy(update=changes)


def _codes(report: ScoreReport) -> list[StuffingCode]:
    return [signal.code for signal in report.stuffing]


# --- golden values -------------------------------------------------------------------------------


def test_the_nova_master_cv_scores_82_3(
    sample_master_cv: ParsedCV, master: MasterEvidence, nova: JobRequirements
) -> None:
    report = score_document(sample_master_cv, master, nova, is_master=True)

    assert _scores(report) == {
        "keywords": 0.9375,  # LangGraph, Kubernetes, MCP and FastAPI only appear in roles
        "skills": 0.7083,  # Python listed, never shown; four keywords shown, not listed
        "experience": 1.0,  # 7 years for 5
        "responsibilities": 0.3333,  # 2/3 + 1/3 + 0 over three responsibilities
        "title": 1.0,
        "education": 1.0,
        "formatting": 1.0,
    }
    assert report.score == 82.3
    assert (report.penalty, report.stuffing) == (0, [])
    assert report.scoring_version == "ats-score.v1"
    assert report.keywords_with(KeywordClass.UNSUPPORTED) == []


def test_the_nova_ceiling_is_88_3(master: MasterEvidence, nova: JobRequirements) -> None:
    reachable = ceiling(master, nova)

    assert reachable.score == 88.3
    scores = {component.name: component.score for component in reachable.components}
    assert scores["keywords"] == 1.0  # every keyword is backed by the master CV
    assert scores["skills"] == 0.9167  # Python can be listed, but no role shows it
    assert scores["responsibilities"] == 0.3333  # no role mentions pipelines or mentoring


def test_listing_the_keywords_the_roles_show_reaches_the_ceiling(
    sample_master_cv: ParsedCV, master: MasterEvidence, nova: JobRequirements
) -> None:
    extra = [SkillItem(name=name) for name in ("LangGraph", "Kubernetes", "MCP", "FastAPI")]
    document = _with(sample_master_cv, skills=[*sample_master_cv.skills, *extra])

    report = score_document(document, master, nova)

    assert _scores(report)["keywords"] == 1.0
    assert _scores(report)["skills"] == 0.9167
    assert report.score == 88.3 == ceiling(master, nova).score
    assert report.stuffing == []


def test_sandstone_scores_65_7_and_cannot_do_better(
    sample_master_cv: ParsedCV, master: MasterEvidence, sandstone: JobRequirements
) -> None:
    report = score_document(sample_master_cv, master, sandstone, is_master=True)

    assert _scores(report) == {
        "keywords": 0.7273,  # Deep Learning and Agentic AI are genuine gaps
        "skills": 0.4286,
        "experience": None,  # no stated years
        "responsibilities": None,
        "title": 0.7333,  # "Research" is not in the master CV; no stated seniority
        "education": None,
        "formatting": 1.0,
    }
    assert report.assessed_weight == 65
    assert report.score == 65.7  # 42.72 of 65 applicable points
    assert ceiling(master, sandstone).score == 65.7


# --- the formula ---------------------------------------------------------------------------------


def test_weights_name_every_component_and_sum_to_100() -> None:
    assert validate_weights(DEFAULT_WEIGHTS) == DEFAULT_WEIGHTS
    without_title = {name: value for name, value in DEFAULT_WEIGHTS.items() if name != "title"}
    for weights in (
        {**DEFAULT_WEIGHTS, "keywords": 31},
        without_title,
        {**DEFAULT_WEIGHTS, "salary": 0},
        {**DEFAULT_WEIGHTS, "keywords": -5, "skills": 55},
        {**DEFAULT_WEIGHTS, "keywords": 30.0},
        {**DEFAULT_WEIGHTS, "formatting": True, "education": 9},
    ):
        with pytest.raises(ValueError, match="ATS weight"):
            validate_weights(weights)


def test_scores_are_rounded_half_up(
    sample_master_cv: ParsedCV, master: MasterEvidence, nova: JobRequirements
) -> None:
    weights = dict.fromkeys(DEFAULT_WEIGHTS, 0) | {"keywords": 60, "formatting": 40}

    report = score_document(sample_master_cv, master, nova, weights=weights, is_master=True)

    assert report.score == 96.3  # 96.25 exactly: half-up, not half-even


def test_the_report_is_deterministic(
    sample_master_cv: ParsedCV, master: MasterEvidence, nova: JobRequirements
) -> None:
    first = score_document(sample_master_cv, master, nova).model_dump_json()

    assert score_document(sample_master_cv, master, nova).model_dump_json() == first
    reordered = nova.model_copy(update={"keywords": list(reversed(nova.keywords))})
    assert score_document(sample_master_cv, master, reordered).score == 82.3
    shuffled = _with(sample_master_cv, skills=list(reversed(sample_master_cv.skills)))
    assert score_document(shuffled, master, nova).score == 82.3


def test_a_job_without_keywords_scores_the_other_components(
    sample_master_cv: ParsedCV, master: MasterEvidence, nova: JobRequirements
) -> None:
    report = score_document(sample_master_cv, master, nova.model_copy(update={"keywords": []}))

    assert _scores(report)["keywords"] is None
    assert _scores(report)["skills"] is None
    assert report.assessed_weight == 50
    assert report.score == 80.0  # (15 + 5 + 10 + 5 + 5) of 50 applicable points


def test_a_posting_that_states_nothing_is_assessed_on_15_points(
    sample_master_cv: ParsedCV, master: MasterEvidence
) -> None:
    requirements = JobRequirements(
        title="AI Engineer", title_terms=title_terms("AI Engineer"), seniority="UNKNOWN"
    )

    report = score_document(sample_master_cv, master, requirements, is_master=True)

    assert report.score == 100.0
    assert report.assessed_weight == 15  # title and formatting only: say so next to the score
    assert ceiling(master, requirements).assessed_weight == 15


@pytest.mark.parametrize(
    ("min_years", "expected"), [(5, 1.0), (10, 0.7), (None, None), (0, None), (-3, None)]
)
def test_the_experience_component(
    sample_master_cv: ParsedCV,
    master: MasterEvidence,
    nova: JobRequirements,
    min_years: int | None,
    expected: float | None,
) -> None:
    requirements = nova.model_copy(update={"min_years": min_years})

    report = score_document(sample_master_cv, master, requirements, is_master=True)

    assert _scores(report)["experience"] == expected


@pytest.mark.parametrize(
    ("education", "min_years", "expected"),
    [
        (EducationRequirement(level=EducationLevel.MASTER, fields=["Computer Science"]), 5, 1.0),
        (EducationRequirement(level=EducationLevel.MASTER), 5, 1.0),  # the level alone
        (EducationRequirement(level=EducationLevel.BACHELOR, fields=["Physics"]), 5, 0.8),
        (EducationRequirement(level=EducationLevel.PHD, fields=["Computer Science"]), 5, 0.2),
        (
            EducationRequirement(
                level=EducationLevel.PHD,
                fields=["Computer Science"],
                equivalent_experience_accepted=True,
            ),
            5,
            0.6,  # 0.8 x 0.5 for equivalent experience (7 years for 5) + 0.2 for the field
        ),
        (
            EducationRequirement(level=EducationLevel.PHD, equivalent_experience_accepted=True),
            10,
            0.0,  # the years are not met
        ),
        (EducationRequirement(), 5, None),
    ],
)
def test_the_education_component(
    sample_master_cv: ParsedCV,
    master: MasterEvidence,
    nova: JobRequirements,
    education: EducationRequirement,
    min_years: int,
    expected: float | None,
) -> None:
    requirements = nova.model_copy(update={"education": education, "min_years": min_years})

    report = score_document(sample_master_cv, master, requirements, is_master=True)

    assert _scores(report)["education"] == expected


@pytest.mark.parametrize(
    ("title", "seniority", "expected"),
    [
        ("Senior AI Engineer", "SENIOR", 1.0),
        ("Lead AI Engineer", "LEAD", 0.8),  # the candidate is SENIOR
        ("Research Scientist", "UNKNOWN", 0.2),  # no title word; no stated seniority
        ("Senior", "SENIOR", None),  # nothing but a seniority word
    ],
)
def test_the_title_component(
    sample_master_cv: ParsedCV,
    master: MasterEvidence,
    nova: JobRequirements,
    title: str,
    seniority: str,
    expected: float | None,
) -> None:
    requirements = nova.model_copy(
        update={"title": title, "title_terms": title_terms(title), "seniority": seniority}
    )

    report = score_document(sample_master_cv, master, requirements, is_master=True)

    assert _scores(report)["title"] == expected


@pytest.mark.parametrize("failing", ["F1", "F2", "F3", "F4", "F5", "F6"])
def test_each_formatting_check(
    sample_master_cv: ParsedCV, master: MasterEvidence, nova: JobRequirements, failing: str
) -> None:
    cv = sample_master_cv
    first, *others = cv.experiences
    documents = {
        "F1": lambda: _with(cv, summary=None),
        "F2": lambda: _with(cv, skills=cv.skills[:2]),
        "F3": lambda: _with(cv, experiences=[first.model_copy(update={"dates": None}), *others]),
        "F4": lambda: _with(
            cv, experiences=[first.model_copy(update={"bullets": first.bullets * 4}), *others]
        ),
        "F5": lambda: _with(
            cv, experiences=[first.model_copy(update={"bullets": ["Shipped RAG."]}), *others]
        ),
        "F6": lambda: _with(
            cv, other_sections=[OtherSection(heading="Talks", lines=["word " * 900])]
        ),
    }

    report = score_document(documents[failing](), master, nova, is_master=True)

    formatting = report.component("formatting")
    assert formatting.score == 0.8333
    assert [c["code"] for c in formatting.details["checks"] if not c["passed"]] == [failing]


# --- keyword stuffing ----------------------------------------------------------------------------


def test_a_keyword_repeated_outside_the_skills_section_is_stuffing(
    sample_master_cv: ParsedCV, master: MasterEvidence, nova: JobRequirements
) -> None:
    summary = (
        "Engineer who builds RAG systems, ships RAG features and evaluates RAG quality in "
        "production every day."
    )

    report = score_document(_with(sample_master_cv, summary=summary), master, nova)

    assert _codes(report) == [StuffingCode.REPEATED_KEYWORD]  # 4 times, the master has 2
    assert report.penalty == 5


def test_duplicate_or_too_many_skills_are_stuffing(
    sample_master_cv: ParsedCV, master: MasterEvidence, nova: JobRequirements
) -> None:
    cv = sample_master_cv
    duplicate = _with(cv, skills=[*cv.skills, SkillItem(name="python")])
    crowded = _with(cv, skills=[SkillItem(name=f"Skill {i}") for i in range(41)])

    assert _codes(score_document(duplicate, master, nova)) == [StuffingCode.SKILL_LIST]
    assert _codes(score_document(crowded, master, nova)) == [StuffingCode.SKILL_LIST]


@pytest.mark.parametrize(
    "summary",
    [
        "Python, LLMs, RAG, LangGraph, FastAPI, Kubernetes and MCP.",  # 7 mentions in 8 words
        "Built RAG systems with LLMs; shipped LangGraph agents; deployed FastAPI services on "
        "Kubernetes; integrated MCP tools; wrote Python; studied Machine Learning; worked with "
        "RAG, LLMs and Python across many different teams and products for several years in "
        "demanding production settings.",  # 11 mentions
    ],
)
def test_a_summary_full_of_keywords_is_stuffing(
    sample_master_cv: ParsedCV, master: MasterEvidence, nova: JobRequirements, summary: str
) -> None:
    report = score_document(_with(sample_master_cv, summary=summary), master, nova)

    assert _codes(report) == [StuffingCode.DENSE_SUMMARY]


def test_a_bullet_made_of_keywords_is_stuffing(
    sample_master_cv: ParsedCV, master: MasterEvidence, nova: JobRequirements
) -> None:
    first, *others = sample_master_cv.experiences
    stuffed = first.model_copy(
        update={"bullets": [*first.bullets, "LangGraph, RAG, LLMs, FastAPI and Kubernetes."]}
    )

    report = score_document(_with(sample_master_cv, experiences=[stuffed, *others]), master, nova)

    assert _codes(report) == [StuffingCode.DENSE_BULLET]


def test_stuffing_the_master_cv_already_shows_is_not_the_tailoring(
    sample_master_cv: ParsedCV, nova: JobRequirements
) -> None:
    dense = _with(sample_master_cv, summary="Python, LLMs, RAG, LangGraph, FastAPI and MCP.")
    master = master_evidence(dense, TODAY)

    assert score_document(dense, master, nova).stuffing == []  # kept verbatim
    other = _with(dense, summary="LLMs, RAG, LangGraph, FastAPI, MCP and Python.")
    assert _codes(score_document(other, master, nova)) == [StuffingCode.DENSE_SUMMARY]


def test_the_penalty_is_5_points_per_signal_and_at_most_15(
    sample_master_cv: ParsedCV, master: MasterEvidence, nova: JobRequirements
) -> None:
    first, *others = sample_master_cv.experiences
    stuffed = _with(
        sample_master_cv,
        summary="RAG, RAG, RAG and RAG with LLMs, LangGraph, FastAPI and Python.",
        skills=[*sample_master_cv.skills, SkillItem(name="Python")],
        experiences=[
            first.model_copy(
                update={"bullets": [*first.bullets, "LangGraph, RAG, LLMs, FastAPI, Kubernetes."]}
            ),
            *others,
        ],
    )

    report = score_document(stuffed, master, nova)
    unpenalised = score_document(stuffed, master, nova, is_master=True)

    assert set(_codes(report)) == set(StuffingCode)
    assert report.penalty == 15
    assert unpenalised.stuffing == []  # the master CV is the candidate's own text
    assert report.score == round(unpenalised.score - 15, 1)


# --- ceiling, feedback and gaps -----------------------------------------------------------------


def test_no_truthful_version_scores_above_the_ceiling(
    sample_master_cv: ParsedCV,
    master: MasterEvidence,
    board_job: JobFactory,
    mock_board_ids: list[tuple[str, str]],
) -> None:
    """Versions built only from the master CV's own facts (any summary of its sources, any skills
    it backs, each role's own lines in any order, any projects) never beat the ceiling."""
    rng = random.Random(5)
    cv = sample_master_cv
    sources = [source.text for source in master.sources.values()]
    for board, job_id in mock_board_ids:
        requirements = build_requirements(posting_of(board_job(board, job_id)))
        reachable = ceiling(master, requirements).score
        assert score_document(cv, master, requirements, is_master=True).score <= reachable
        backed = [
            SkillItem(name=keyword.term)
            for keyword in requirements.keywords
            if is_technical(keyword) and master.supports(keyword.term)
        ]
        for _ in range(25):
            skills = [*cv.skills, *backed]
            experiences = [
                item.model_copy(update={"bullets": rng.sample(lines, rng.randint(0, len(lines)))})
                for item in cv.experiences
                for lines in [[*item.bullets, *item.details]]
            ]
            projects = [
                item.model_copy(update={"bullets": rng.sample(item.bullets, len(item.bullets))})
                for item in rng.sample(cv.projects, rng.randint(0, len(cv.projects)))
            ]
            document = _with(
                cv,
                summary=" ".join(rng.sample(sources, rng.randint(1, 3))),
                skills=rng.sample(skills, rng.randint(0, len(skills))),
                experiences=experiences,
                projects=projects,
            )

            report = score_document(document, master, requirements)

            assert report.score <= reachable, (job_id, document.summary)
            assert report.keywords_with(KeywordClass.UNSUPPORTED) == [], job_id


def test_feedback_points_at_unused_evidence(
    sample_master_cv: ParsedCV, master: MasterEvidence, nova: JobRequirements
) -> None:
    document = _with(sample_master_cv, projects=[])
    report = score_document(document, master, nova)

    hints = feedback(document, report, master, nova)

    assert [(hint.term, hint.sources) for hint in hints.available] == [("MCP", ["P1.B1"])]
    assert hints.not_listed == ["LangGraph", "Kubernetes", "FastAPI"]
    assert hints.not_prominent == ["LangGraph", "Kubernetes", "FastAPI"]
    assert [(hint.term, hint.sources) for hint in hints.not_demonstrated] == [("LLMs", ["P1.B1"])]
    assert (hints.title_terms, hints.formatting, hints.forbidden) == ([], [], [])


def test_feedback_forbids_genuine_gaps(
    sample_master_cv: ParsedCV, master: MasterEvidence, sandstone: JobRequirements
) -> None:
    document = _with(sample_master_cv, summary=None)
    report = score_document(document, master, sandstone)

    hints = feedback(document, report, master, sandstone)

    assert hints.forbidden == ["Deep Learning", "Agentic AI"]
    assert hints.title_terms == []  # "Research" is not backed: it is a gap instead
    assert hints.formatting == ["A summary of at most 80 words"]


def test_gaps_for_nova(master: MasterEvidence, nova: JobRequirements) -> None:
    items = gaps(master, nova)

    assert [(item.kind, item.subject, item.terms) for item in items] == [
        (GapKind.NOT_DEMONSTRATED, "Python", []),
        (GapKind.RESPONSIBILITY, "Design RAG pipelines", ["pipelines"]),
        (GapKind.RESPONSIBILITY, "Evaluate LLM quality", ["Evaluate", "quality"]),
        (GapKind.RESPONSIBILITY, "Mentor engineers", ["Mentor", "engineers"]),
    ]
    assert all("master CV" in item.message for item in items)


def test_gaps_for_sandstone(master: MasterEvidence, sandstone: JobRequirements) -> None:
    items = gaps(master, sandstone)

    assert [(item.kind, item.subject, item.importance, item.terms) for item in items] == [
        (GapKind.MISSING_KEYWORD, "Deep Learning", Importance.REQUIRED, []),
        (GapKind.MISSING_KEYWORD, "Agentic AI", Importance.PREFERRED, []),
        (GapKind.NOT_DEMONSTRATED, "Python", Importance.REQUIRED, []),
        (GapKind.TITLE_TERMS, "AI Research Engineer", None, ["Research"]),
    ]
