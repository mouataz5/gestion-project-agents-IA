"""The optimisation loop: no call when nothing can be gained, the best valid version wins, every
stop reason, and no stored version after a failed first call."""

from collections.abc import Callable
from datetime import date

import pytest

from app.ats.guard import GuardContext, guard_context
from app.ats.keywords import master_evidence
from app.ats.ledger import ViolationCode
from app.ats.loop import (
    OptimisationResult,
    TailoringCallError,
    TailoringPrompt,
    TailoringReply,
    optimise,
)
from app.ats.mock_responder import mock_cv_tailoring
from app.ats.requirements import Keyword, build_requirements, posting_of
from app.ats.scoring import GapKind
from app.ats.tailoring import (
    SkillChoice,
    SourcedText,
    TailoringOutput,
    requirements_brief,
    tailoring_facts,
)
from app.ats.taxonomy import Category
from app.ats.types import (
    DocumentKind,
    Importance,
    IterationStatus,
    KeywordClass,
    KeywordSource,
    StopReason,
)
from app.cv.models import ParsedCV
from app.models import Job

pytestmark = pytest.mark.feature("ats-loop")

TODAY = date(2026, 10, 6)
JobFactory = Callable[[str, str], Job]
Step = Callable[[TailoringPrompt], TailoringOutput | TailoringCallError]


def _context(cv: ParsedCV, job: Job) -> GuardContext:
    return guard_context(master_evidence(cv, TODAY), build_requirements(posting_of(job)))


@pytest.fixture
def nova(sample_master_cv: ParsedCV, board_job: JobFactory) -> GuardContext:
    return _context(sample_master_cv, board_job("nova-ai", "nova-1001"))


class Script:
    """A tailoring model that plays one scripted step per call."""

    def __init__(self, *steps: Step) -> None:
        self.steps = steps
        self.prompts: list[TailoringPrompt] = []

    def __call__(self, prompt: TailoringPrompt) -> TailoringReply:
        self.prompts.append(prompt)
        answer = self.steps[len(self.prompts) - 1](prompt)
        if isinstance(answer, TailoringCallError):
            raise answer
        return TailoringReply(output=answer, usage={"request_id": f"req_{prompt.iteration}"})


def add(*names: str) -> Step:
    def step(prompt: TailoringPrompt) -> TailoringOutput:
        skills = [*prompt.current.skills, *(SkillChoice(name=n, category=None) for n in names)]
        return prompt.current.model_copy(update={"skills": skills})

    return step


def same(prompt: TailoringPrompt) -> TailoringOutput:
    return prompt.current


def stuffed(prompt: TailoringPrompt) -> TailoringOutput:
    summary = SourcedText(
        text="LLMs, RAG, LangGraph, Kubernetes, FastAPI, MCP and Python.",
        sources=["S", "E1.B1", "E1.B2", "P1.B1", "K1"],
    )
    return prompt.current.model_copy(update={"summary": summary})


def fail(*, refused: bool = False) -> Step:
    def step(prompt: TailoringPrompt) -> TailoringCallError:
        return TailoringCallError("The model is unavailable", refused=refused)

    return step


def mock(context: GuardContext) -> Step:
    def step(prompt: TailoringPrompt) -> TailoringOutput:
        request = {
            "facts": tailoring_facts(context.master).data,
            "requirements": requirements_brief(context.requirements),
            "current": prompt.current.model_dump(),
            "feedback": prompt.feedback.model_dump(),
        }
        return TailoringOutput.model_validate(mock_cv_tailoring(request))

    return step


def _run(context: GuardContext, script: Script, target: float = 95) -> OptimisationResult:
    return optimise(context, script, target=target, max_iterations=3)


def _trace(result: OptimisationResult) -> list[tuple[IterationStatus, float | None]]:
    return [(iteration.status, iteration.score) for iteration in result.iterations]


# --- stop reasons ------------------------------------------------------------------------------


def test_the_mock_tailoring_stops_at_the_nova_ceiling(nova: GuardContext) -> None:
    result = _run(nova, Script(mock(nova)))

    assert (result.baseline.score, result.ceiling.score, result.final_score) == (82.3, 88.3, 88.3)
    assert result.stop_reason is StopReason.ONLY_UNSUPPORTED_GAINS
    assert result.calls == 1
    assert result.best is not None
    assert result.best.number == 1
    assert result.best.status is IterationStatus.SCORED
    assert result.best.report is not None
    assert result.best.report.keywords_with(KeywordClass.UNSUPPORTED) == []
    assert result.best.usage == {"request_id": "req_1"}
    kinds = {item.kind for item in result.gaps}
    assert kinds == {GapKind.NOT_DEMONSTRATED, GapKind.RESPONSIBILITY}


def test_no_call_when_the_master_cv_reaches_the_target(nova: GuardContext) -> None:
    script = Script()

    result = _run(nova, script, target=80)

    assert result.stop_reason is StopReason.TARGET_REACHED
    assert (result.calls, script.prompts) == (0, [])
    assert result.best is not None
    assert result.best.kind is DocumentKind.MASTER


def test_no_call_when_only_unsupported_gains_remain(
    sample_master_cv: ParsedCV, board_job: JobFactory
) -> None:
    context = _context(sample_master_cv, board_job("sandstone", "sa-4001"))

    result = _run(context, Script())

    assert result.stop_reason is StopReason.ONLY_UNSUPPORTED_GAINS
    assert (result.calls, result.final_score, result.ceiling.score) == (0, 65.7, 65.7)
    assert [item.subject for item in result.gaps][:2] == ["Deep Learning", "Agentic AI"]


def test_the_target_is_reached_at_the_first_iteration(nova: GuardContext) -> None:
    result = _run(nova, Script(mock(nova)), target=85)

    assert result.stop_reason is StopReason.TARGET_REACHED
    assert (result.calls, result.final_score) == (1, 88.3)


def test_steady_gains_run_every_iteration(nova: GuardContext) -> None:
    script = Script(add("LangGraph"), add("Kubernetes"), add("MCP"))

    result = _run(nova, script)

    assert result.stop_reason is StopReason.MAX_ITERATIONS
    assert _trace(result) == [
        (IterationStatus.SCORED, 82.3),
        (IterationStatus.SCORED, 84.7),
        (IterationStatus.SCORED, 85.9),
        (IterationStatus.SCORED, 87.1),
    ]
    assert result.best is not None
    assert result.best.number == 3
    assert [skill.name for skill in script.prompts[1].current.skills][-1] == "LangGraph"


def test_a_gain_below_half_a_point_stops_the_loop_and_a_tie_keeps_the_earlier(
    nova: GuardContext,
) -> None:
    result = _run(nova, Script(add("LangGraph"), same))

    assert result.stop_reason is StopReason.NO_IMPROVEMENT
    assert _trace(result)[1:] == [(IterationStatus.SCORED, 84.7), (IterationStatus.SCORED, 84.7)]
    assert result.best is not None
    assert result.best.number == 1


def test_a_version_no_better_than_the_master_keeps_the_master_copy(nova: GuardContext) -> None:
    result = _run(nova, Script(same))

    assert result.stop_reason is StopReason.NO_IMPROVEMENT
    assert result.best is not None
    assert result.best.kind is DocumentKind.MASTER


# --- the guard inside the loop -------------------------------------------------------------------


def test_an_injected_unsupported_keyword_is_repaired_and_never_counted(
    nova: GuardContext,
) -> None:
    kafka = Keyword(
        term="Kafka",
        key="kafka",
        category=Category.DATA,
        importance=Importance.REQUIRED,
        sources=[KeywordSource.LISTED],
    )
    requirements = nova.requirements.model_copy(
        update={"keywords": [*nova.requirements.keywords, kafka]}
    )
    context = guard_context(nova.master, requirements)

    def inject(prompt: TailoringPrompt) -> TailoringOutput:
        summary = SourcedText(text=f"{nova.master.cv.summary} Expert in Kafka.", sources=["S"])
        skills = [
            *prompt.current.skills,
            SkillChoice(name="Kafka", category="Data"),
            SkillChoice(name="LangGraph", category=None),
        ]
        return prompt.current.model_copy(update={"summary": summary, "skills": skills})

    script = Script(inject, same)
    result = optimise(context, script, target=95, max_iterations=2)

    first = result.iterations[1]
    assert first.status is IterationStatus.REPAIRED
    assert first.report is not None
    assert {k.term: k.status for k in first.report.keywords}["Kafka"] is KeywordClass.MISSING
    assert first.report.keywords_with(KeywordClass.UNSUPPORTED) == []
    assert first.assembly is not None
    assert "Kafka" not in {skill.name for skill in first.assembly.document.skills}
    assert first.assembly.document.summary == nova.master.cv.summary
    notes = script.prompts[1].feedback.violations
    assert any(note.startswith(ViolationCode.UNSUPPORTED_SKILL.value) for note in notes)
    assert "Kafka" in script.prompts[1].feedback.forbidden


def test_two_rejected_versions_end_the_loop_with_the_master_copy(nova: GuardContext) -> None:
    script = Script(stuffed, stuffed)

    result = _run(nova, script)

    assert result.stop_reason is StopReason.GUARD_REJECTED
    assert [item.status for item in result.iterations] == [
        IterationStatus.SCORED,
        IterationStatus.REJECTED,
        IterationStatus.REJECTED,
    ]
    assert result.iterations[1].score is None  # a rejected version is never scored
    assert {v.code for v in result.iterations[1].violations} == {ViolationCode.STUFFING}
    assert result.best is not None
    assert result.best.kind is DocumentKind.MASTER
    assert any(note.startswith("STUFFING") for note in script.prompts[1].feedback.violations)


def test_one_rejection_does_not_stop_the_loop(nova: GuardContext) -> None:
    result = _run(nova, Script(stuffed, add("LangGraph", "Kubernetes", "MCP", "FastAPI")))

    assert result.stop_reason is StopReason.ONLY_UNSUPPORTED_GAINS
    assert _trace(result)[1:] == [
        (IterationStatus.REJECTED, None),
        (IterationStatus.SCORED, 88.3),
    ]


# --- provider failures ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("refused", "status"), [(False, IterationStatus.FAILED), (True, IterationStatus.REFUSED)]
)
def test_a_failed_first_call_stores_nothing(
    nova: GuardContext, refused: bool, status: IterationStatus
) -> None:
    result = _run(nova, Script(fail(refused=refused)))

    assert result.stop_reason is StopReason.PROVIDER_ERROR
    assert result.best is None
    assert [item.status for item in result.iterations] == [IterationStatus.SCORED, status]
    assert result.iterations[1].error == "The model is unavailable"


def test_a_failure_after_a_scored_version_keeps_the_best(nova: GuardContext) -> None:
    result = _run(nova, Script(add("LangGraph"), fail()))

    assert result.stop_reason is StopReason.PROVIDER_ERROR
    assert result.best is not None
    assert (result.best.number, result.final_score) == (1, 84.7)


def test_a_failure_after_a_rejection_stores_nothing(nova: GuardContext) -> None:
    result = _run(nova, Script(stuffed, fail()))

    assert result.stop_reason is StopReason.PROVIDER_ERROR
    assert result.best is None


def test_the_first_prompt_carries_the_master_version_and_its_feedback(
    nova: GuardContext,
) -> None:
    script = Script(same)

    _run(nova, script)

    prompt = script.prompts[0]
    assert prompt.iteration == 1
    assert prompt.current.summary is not None
    assert prompt.current.summary.sources == ["S"]
    assert prompt.current.experiences[0].bullets[0].sources == ["E1.B1"]
    assert prompt.feedback.not_listed == ["LangGraph", "Kubernetes", "MCP", "FastAPI"]
    assert prompt.feedback.violations == []
