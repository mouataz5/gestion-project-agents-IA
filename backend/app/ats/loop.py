"""The optimisation loop: tailor, guard, score, repeat - towards a target that is never a promise.

    0. Score the master CV (the baseline) and compute the supported ceiling. No call is made when
       the baseline reaches the target (TARGET_REACHED) or is within EPS of the ceiling
       (ONLY_UNSUPPORTED_GAINS): the master copy is the result.
    1..N. Ask for a tailoring (the best version so far and deterministic feedback), assemble it
       (immutable facts copied, rejected texts repaired), pass the final gate, score it.
       - A version the gate rejects is recorded unscored; two in a row end the loop
         (GUARD_REJECTED).
       - The best version changes only on a strictly higher score (a tie keeps the earlier).
       - After each scored version: TARGET_REACHED, then ONLY_UNSUPPORTED_GAINS, then
         NO_IMPROVEMENT (gain below EPS); after the last one, MAX_ITERATIONS.
       - A refusal or a provider error ends the loop (PROVIDER_ERROR); the best version is kept
         only when a tailored version was scored, so a failed first call stores nothing and the
         application stays as it was.

The tailoring call is injected (``tailor``), so the loop is pure and runs offline in tests.
Scores are compared in tenths: they are rounded to one decimal.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.ats.guard import GuardContext, validate_tailored
from app.ats.ledger import Violation
from app.ats.scoring import (
    CeilingReport,
    Feedback,
    Recommendation,
    ScoreReport,
    ceiling,
    feedback,
    recommendations,
    score_document,
)
from app.ats.tailoring import Assembly, TailoringOutput, as_output, assemble, master_output
from app.ats.types import DocumentKind, IterationStatus, StopReason
from app.ats.weights import DEFAULT_WEIGHTS

EPS = 0.5


class TailoringCallError(Exception):
    """The tailoring call did not return an answer (``refused``: the model declined)."""

    def __init__(
        self,
        message: str,
        *,
        refused: bool = False,
        code: str = "provider_error",
        usage: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.refused = refused
        self.code = code
        self.usage = dict(usage or {})


@dataclass(frozen=True)
class TailoringPrompt:
    iteration: int
    current: TailoringOutput  # the best version so far, in the answer format, with its sources
    feedback: Feedback


@dataclass(frozen=True)
class TailoringReply:
    output: TailoringOutput
    usage: Mapping[str, Any] = field(default_factory=dict)  # provider metadata, stored as is


Tailor = Callable[[TailoringPrompt], TailoringReply]


@dataclass(frozen=True)
class Iteration:
    number: int  # 0: the master CV
    kind: DocumentKind
    status: IterationStatus
    assembly: Assembly | None = None
    report: ScoreReport | None = None
    violations: tuple[Violation, ...] = ()
    usage: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None
    feedback: Feedback | None = None  # what the tailoring call was told (iterations 1..N)

    @property
    def score(self) -> float | None:
        return self.report.score if self.report else None


@dataclass(frozen=True)
class OptimisationResult:
    stop_reason: StopReason
    baseline: ScoreReport
    ceiling: CeilingReport
    iterations: tuple[Iteration, ...]
    best: Iteration | None  # None: nothing to store (a failed first call)
    recommendations: tuple[Recommendation, ...]

    @property
    def calls(self) -> int:
        return sum(1 for iteration in self.iterations if iteration.kind is DocumentKind.TAILORED)

    @property
    def final_score(self) -> float | None:
        return self.best.score if self.best else None


def _tenths(score: float) -> int:
    return round(score * 10)


def _violation_notes(violations: tuple[Violation, ...] | list[Violation]) -> list[str]:
    return [f"{violation.code.value}: {violation.detail}" for violation in violations]


def optimise(
    context: GuardContext,
    tailor: Tailor,
    *,
    target: float,
    max_iterations: int,
    weights: Mapping[str, int] = DEFAULT_WEIGHTS,
    base_version_id: str | None = None,
) -> OptimisationResult:
    master, requirements = context.master, context.requirements
    copy = assemble(master_output(master), context, base_version_id=base_version_id)
    baseline = score_document(copy.document, master, requirements, weights=weights, is_master=True)
    reachable = ceiling(master, requirements, weights=weights)
    start = Iteration(0, DocumentKind.MASTER, IterationStatus.SCORED, copy, baseline)
    iterations: list[Iteration] = [start]
    advice = tuple(recommendations(master, requirements))

    def finish(reason: StopReason, best: Iteration | None) -> OptimisationResult:
        return OptimisationResult(
            stop_reason=reason,
            baseline=baseline,
            ceiling=reachable,
            iterations=tuple(iterations),
            best=best,
            recommendations=advice,
        )

    target_tenths, ceiling_tenths, eps_tenths = _tenths(target), _tenths(reachable.score), 5
    if _tenths(baseline.score) >= target_tenths:
        return finish(StopReason.TARGET_REACHED, start)
    if _tenths(baseline.score) >= ceiling_tenths - eps_tenths:
        return finish(StopReason.ONLY_UNSUPPORTED_GAINS, start)

    best, best_assembly, best_report = start, copy, baseline
    scored = False
    rejections = 0
    last_violations: list[Violation] = []
    for number in range(1, max_iterations + 1):
        hints = feedback(best_assembly.document, best_report, master, requirements)
        hints = hints.model_copy(update={"violations": _violation_notes(last_violations)})
        prompt = TailoringPrompt(iteration=number, current=as_output(best_assembly), feedback=hints)
        try:
            reply = tailor(prompt)
        except TailoringCallError as exc:
            status = IterationStatus.REFUSED if exc.refused else IterationStatus.FAILED
            iterations.append(
                Iteration(
                    number,
                    DocumentKind.TAILORED,
                    status,
                    usage=exc.usage,
                    error=exc.message,
                    error_code=exc.code,
                    feedback=hints,
                )
            )
            return finish(StopReason.PROVIDER_ERROR, best if scored else None)

        assembly = assemble(reply.output, context, base_version_id=base_version_id)
        violations = validate_tailored(assembly.document, assembly.ledger, context)
        if violations:
            iterations.append(
                Iteration(
                    number,
                    DocumentKind.TAILORED,
                    IterationStatus.REJECTED,
                    assembly,
                    violations=tuple(violations),
                    usage=reply.usage,
                    feedback=hints,
                )
            )
            rejections += 1
            last_violations = violations
            if rejections >= 2:
                return finish(StopReason.GUARD_REJECTED, best)
            continue

        rejections = 0
        last_violations = [v for repair in assembly.ledger.repairs for v in repair.violations]
        report = score_document(assembly.document, master, requirements, weights=weights)
        status = IterationStatus.REPAIRED if assembly.ledger.repairs else IterationStatus.SCORED
        current = Iteration(
            number,
            DocumentKind.TAILORED,
            status,
            assembly,
            report,
            usage=reply.usage,
            feedback=hints,
        )
        iterations.append(current)
        scored = True
        previous = _tenths(best_report.score)
        if _tenths(report.score) > previous:
            best, best_assembly, best_report = current, assembly, report
        best_tenths = _tenths(best_report.score)
        if best_tenths >= target_tenths:
            return finish(StopReason.TARGET_REACHED, best)
        if best_tenths >= ceiling_tenths - eps_tenths:
            return finish(StopReason.ONLY_UNSUPPORTED_GAINS, best)
        if _tenths(report.score) - previous < eps_tenths:
            return finish(StopReason.NO_IMPROVEMENT, best)
    return finish(StopReason.MAX_ITERATIONS, best)
