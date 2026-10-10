"""CV generation run (Phase 5): for each qualified application, read what the job asks for (one
cached extraction per posting version), tailor the confirmed master CV towards the ATS target under
the truthfulness guard, and store the best valid version with its evidence ledger and every score.

Executed by a worker, recorded as a CV_GENERATION automation run. Requires a confirmed master CV.
Model calls happen outside database transactions; each application is written in one short
transaction. Unchanged inputs are not tailored again unless forced. A refused or failed first
tailoring call stores nothing: the application stays QUALIFIED and the next run retries. A
configuration error stops the run, as do repeated consecutive failures.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.analysis.job_text import posting_digest, render_job_posting
from app.analysis.types import Recommendation
from app.applications.lifecycle import ApplicationStatus
from app.ats.guard import GUARD_VERSION, guard_context
from app.ats.keywords import MasterEvidence, master_evidence
from app.ats.loop import (
    Iteration,
    OptimisationResult,
    TailoringCallError,
    TailoringPrompt,
    TailoringReply,
    optimise,
)
from app.ats.mock_responder import mock_cv_tailoring, mock_job_requirements
from app.ats.requirements import (
    REQUIREMENTS_VERSION,
    JobRequirements,
    Posting,
    RequirementsOutput,
    build_requirements,
    posting_context,
    posting_of,
)
from app.ats.scoring import SCORING_VERSION
from app.ats.tailoring import (
    TAILORED_PARSER_VERSION,
    TailoringFacts,
    TailoringOutput,
    render_text,
    requirements_brief,
    tailoring_facts,
    tailoring_user_turn,
)
from app.ats.types import CallStatus, DocumentKind, IterationStatus, KeywordClass, StopReason
from app.core.clock import utcnow
from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.cv.models import ParsedCV
from app.db.session import session_scope
from app.llm.base import LLMProvider
from app.llm.errors import LLMConfigError, LLMError, LLMRefusalError
from app.llm.factory import create_llm_provider
from app.llm.prompts import Prompt, PromptRegistry
from app.llm.types import LLMRequest, LLMResult, LLMUsage, SystemBlock
from app.models import (
    Application,
    AtsAnalysis,
    Candidate,
    CvKind,
    CvStatus,
    CvTailoring,
    CvVersion,
    EventLevel,
    Job,
    RequirementsExtraction,
    RunStatus,
)
from app.services.applications import ApplicationService
from app.services.audit import Actor, AuditAction, AuditService
from app.services.candidate_profile import CandidateService
from app.services.cv_versions import find_active_master
from app.services.job_sources import JobSourceService
from app.services.runs import RunRecorder

logger = get_logger(__name__)

REQUIREMENTS_TASK = "job_requirements"
TAILORING_TASK = "cv_tailoring"
MAX_CONSECUTIVE_FAILURES = 3
TOTAL_KEYS: tuple[str, ...] = (
    "selected",
    "generated",
    "unchanged",
    "skipped",
    "refused",
    "failed",
)
MOVED_ON = "The application changed while its CV was being tailored"
# Applications that may be tailored; later stages keep the CV they were reviewed with.
TAILORABLE = (ApplicationStatus.QUALIFIED, ApplicationStatus.CV_GENERATED)
MOCK_RESPONDERS: Mapping[str, Any] = {
    REQUIREMENTS_TASK: mock_job_requirements,
    TAILORING_TASK: mock_cv_tailoring,
}
STOP_LABELS: Mapping[StopReason, str] = {
    StopReason.TARGET_REACHED: "target reached",
    StopReason.ONLY_UNSUPPORTED_GAINS: "only unsupported gains left",
    StopReason.NO_IMPROVEMENT: "no further improvement",
    StopReason.MAX_ITERATIONS: "iteration limit reached",
    StopReason.GUARD_REJECTED: "rewrites rejected by the truthfulness guard",
    StopReason.PROVIDER_ERROR: "the model did not answer",
}


@dataclass(frozen=True)
class _Prepared:
    candidate_id: uuid.UUID
    master_version_id: uuid.UUID
    master: MasterEvidence
    facts: TailoringFacts
    declared_skills: tuple[str, ...]
    allow_title_changes: bool


@dataclass(frozen=True)
class _Outcome:
    kind: str  # generated | unchanged | skipped | refused | failed
    usage: LLMUsage = field(default_factory=LLMUsage)


@dataclass(frozen=True)
class _Stored:
    version: CvVersion | None
    status: CallStatus
    error: str | None


@dataclass(frozen=True)
class _Snapshot:
    """What the per-application work needs from the database, read in one short transaction."""

    application_id: uuid.UUID
    job_id: uuid.UUID
    label: str
    posting: Posting
    posting_turn: str
    requirements_hash: str
    cached: JobRequirements | None
    cached_id: uuid.UUID | None
    latest_hash: str | None
    has_current: bool


class CvTailoringService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        provider: LLMProvider | None = None,
        prompts: PromptRegistry | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._provider = provider
        self._prompts = prompts or PromptRegistry(settings.prompts_dir)
        self._clock = clock or utcnow

    def execute(self, run_id: uuid.UUID, *, task_id: str | None = None) -> dict[str, Any]:
        settings = self._settings
        totals = dict.fromkeys(TOTAL_KEYS, 0)
        usage = LLMUsage()
        summary: dict[str, Any] = {"totals": totals}
        status = RunStatus.SUCCEEDED
        with RunRecorder(self._session_factory, run_id, task_id=task_id) as recorder:
            self._audit(AuditAction.RUN_STARTED, run_id, {"task_id": task_id})
            parameters = dict(recorder.run.parameters or {})
            job_ids = [uuid.UUID(str(value)) for value in parameters.get("job_ids") or []] or None
            force = bool(parameters.get("force", False))

            with session_scope(self._session_factory) as session:
                prepared = self._prepare(session, recorder)
            if prepared is None:
                recorder.finish(RunStatus.SUCCEEDED, summary=summary)
                return self._finished(run_id, RunStatus.SUCCEEDED, totals)

            try:
                provider = self._provider or create_llm_provider(
                    settings, mock_responders=MOCK_RESPONDERS
                )
            except LLMConfigError as exc:
                recorder.error("tailoring.provider", exc)
                recorder.finish(RunStatus.FAILED, summary=summary)
                return self._finished(run_id, RunStatus.FAILED, totals)
            prompts = (self._prompts.get(REQUIREMENTS_TASK), self._prompts.get(TAILORING_TASK))
            weights = dict(settings.ats_score_weights)
            provider_info = {
                "name": provider.name,
                "model": provider.model,
                "reason": getattr(provider, "reason", None),
            }
            summary.update(
                provider=provider_info,
                prompts=[prompt.ref for prompt in prompts],
                scoring_version=SCORING_VERSION,
                guard_version=GUARD_VERSION,
                weights=weights,
                target_score=settings.ats_target_score,
                max_iterations=settings.ats_max_iterations,
                effort=settings.llm_effort,
                cv_version_id=str(prepared.master_version_id),
            )
            mock_note = (
                " (offline mock: no language model wrote these CVs)"
                if provider.name == "mock"
                else ""
            )
            recorder.event(
                "tailoring.config",
                f"Tailoring with {provider.name} · {provider.model}, prompts "
                f"{prompts[0].ref} and {prompts[1].ref}, scoring {SCORING_VERSION}, target "
                f"{settings.ats_target_score} (a target, not a promise){mock_note}",
                data={
                    **provider_info,
                    "prompts": [prompt.ref for prompt in prompts],
                    "scoring_version": SCORING_VERSION,
                    "target_score": settings.ats_target_score,
                    "max_iterations": settings.ats_max_iterations,
                },
            )

            with session_scope(self._session_factory) as session:
                selected, remaining = self._select(
                    session, prepared.candidate_id, job_ids, recorder
                )
            totals["selected"] = len(selected)
            summary["pending_remaining"] = remaining
            if remaining:
                recorder.event(
                    "tailoring.selection",
                    f"{remaining} more job(s) wait for the next CV generation run "
                    f"(CV_GENERATION_MAX_JOBS_PER_RUN={settings.cv_generation_max_jobs_per_run})",
                    level=EventLevel.WARNING,
                )

            consecutive_failures = 0
            stopped_by_config = False
            for application_id in selected:
                try:
                    outcome = self._tailor_one(
                        application_id,
                        prepared,
                        provider,
                        prompts,
                        weights,
                        run_id,
                        force,
                        recorder,
                    )
                except LLMConfigError as exc:
                    recorder.error("tailoring.provider", exc)
                    stopped_by_config = True
                    break
                totals[outcome.kind] += 1
                usage = usage + outcome.usage
                consecutive_failures = consecutive_failures + 1 if outcome.kind == "failed" else 0
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    recorder.event(
                        "tailoring.provider",
                        f"Stopped after {MAX_CONSECUTIVE_FAILURES} consecutive failures; the "
                        "remaining jobs wait for the next run",
                        level=EventLevel.WARNING,
                    )
                    break

            summary["usage"] = usage.as_dict()
            recorder.event(
                "tailoring.summary",
                f"{totals['generated']} tailored CV(s) stored, {totals['unchanged']} unchanged, "
                f"{totals['refused']} refused, {totals['failed']} failed",
                data=totals,
            )
            recorder.increment(
                jobs_processed=totals["generated"] + totals["refused"] + totals["failed"],
                cv_generated=totals["generated"],
            )
            answered = totals["generated"] + totals["refused"]
            if stopped_by_config:
                status = RunStatus.PARTIAL_SUCCESS if totals["generated"] else RunStatus.FAILED
            elif totals["failed"]:
                # FAILED when every attempted job failed; a refusal is an answer, not a failure.
                status = RunStatus.PARTIAL_SUCCESS if answered else RunStatus.FAILED
            recorder.finish(status, summary=summary)
        return self._finished(run_id, status, totals)

    # --- preparation -------------------------------------------------------------------------
    def _prepare(self, session: Session, recorder: RunRecorder) -> _Prepared | None:
        candidates = CandidateService(session, candidate_dir=self._settings.candidate_dir)
        try:
            candidate, created = candidates.get_or_import_default()
        except AppError as exc:
            recorder.event(
                "tailoring.candidate",
                f"No candidate profile ({exc.message}): no CV was tailored.",
                level=EventLevel.WARNING,
            )
            return None
        if created:
            AuditService(session).record(
                action=AuditAction.CANDIDATE_IMPORTED,
                actor=Actor.WORKER,
                entity_type="candidate",
                entity_id=str(candidate.id),
                details={"source": "yaml", "reason": "cv_generation", "profile_version": 1},
            )
        master = find_active_master(session, candidate)
        if master is None:
            recorder.event(
                "tailoring.candidate",
                "No confirmed master CV: upload and confirm it on the CV page, then generate "
                "CVs again. No CV was tailored.",
                level=EventLevel.WARNING,
            )
            return None
        profile = CandidateService.profile_of(candidate)
        evidence = master_evidence(ParsedCV.model_validate(master.structure), self._clock().date())
        declared = tuple(profile.core_skills)
        allow = profile.cv_policy.allow_title_changes
        return _Prepared(
            candidate_id=candidate.id,
            master_version_id=master.id,
            master=evidence,
            facts=tailoring_facts(evidence, declared_skills=declared, allow_title_changes=allow),
            declared_skills=declared,
            allow_title_changes=allow,
        )

    def _select(
        self,
        session: Session,
        candidate_id: uuid.UUID,
        job_ids: Sequence[uuid.UUID] | None,
        recorder: RunRecorder,
    ) -> tuple[list[uuid.UUID], int]:
        settings = self._settings
        limit = settings.cv_generation_max_jobs_per_run
        hidden = () if settings.mock_mode else tuple(JobSourceService(session).mock_keys())
        if job_ids is None:
            wanted = [Recommendation.APPLY]
            if settings.cv_generation_include_review:
                wanted.append(Recommendation.REVIEW)
            query = (
                select(Application.id)
                .join(Job, Job.id == Application.job_id)
                .where(
                    Application.candidate_id == candidate_id,
                    Application.status == ApplicationStatus.QUALIFIED,
                    Application.recommendation.in_(wanted),
                    Job.duplicate_of_id.is_(None),
                )
                .order_by(
                    case((Application.recommendation == Recommendation.APPLY, 0), else_=1),
                    Job.posted_at.desc().nulls_last(),
                    Job.discovered_at.desc(),
                    Job.id,
                )
            )
            if hidden:
                query = query.where(Job.source.not_in(hidden))
            ids = list(session.scalars(query))
            return ids[:limit], max(0, len(ids) - limit)

        selected: list[uuid.UUID] = []
        for job_id in job_ids:
            job = session.get(Job, job_id)
            if job is not None and job.duplicate_of_id is not None:
                job = session.get(Job, job.duplicate_of_id)  # tailor for the primary record
            if job is None or job.source in hidden:
                recorder.event(
                    "tailoring.selection", f"Job {job_id} was not found", level=EventLevel.WARNING
                )
                continue
            application = session.scalar(
                select(Application).where(
                    Application.candidate_id == candidate_id, Application.job_id == job.id
                )
            )
            if application is None or application.status not in TAILORABLE:
                state = application.status.value if application else "not analysed"
                recorder.event(
                    "tailoring.selection",
                    f"{job.title}: {state}; only qualified jobs are tailored",
                    level=EventLevel.WARNING,
                )
                continue
            if application.recommendation is Recommendation.SKIP:
                recorder.event(
                    "tailoring.selection",
                    f"{job.title}: recommended SKIP; never tailored",
                    level=EventLevel.WARNING,
                )
                continue
            if application.id not in selected:
                selected.append(application.id)
        return selected[:limit], max(0, len(selected) - limit)

    # --- one application ---------------------------------------------------------------------
    def _requirements_hash(self, digest: str, prompt: Prompt, provider: LLMProvider) -> str:
        material = "|".join(
            (
                digest,
                prompt.sha256,
                provider.name,
                provider.model,
                self._settings.llm_effort,
                REQUIREMENTS_VERSION,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _tailoring_hash(
        self,
        prepared: _Prepared,
        requirements: JobRequirements,
        prompts: tuple[Prompt, Prompt],
        provider: LLMProvider,
        weights: Mapping[str, int],
    ) -> str:
        settings = self._settings
        snapshot = json.dumps(requirements.model_dump(mode="json"), sort_keys=True)
        material = "|".join(
            (
                str(prepared.master_version_id),
                prepared.facts.sha256,
                hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
                prompts[0].sha256,
                prompts[1].sha256,
                provider.name,
                provider.model,
                settings.llm_effort,
                SCORING_VERSION,
                GUARD_VERSION,
                json.dumps(dict(weights), sort_keys=True),
                str(settings.ats_target_score),
                str(settings.ats_max_iterations),
                str(prepared.master.years),
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _snapshot(
        self, application_id: uuid.UUID, prompt: Prompt, provider: LLMProvider
    ) -> _Snapshot | None:
        with session_scope(self._session_factory) as session:
            application = session.get(Application, application_id)
            job = session.get(Job, application.job_id) if application is not None else None
            if application is None or job is None or application.status not in TAILORABLE:
                return None
            requirements_hash = self._requirements_hash(posting_digest(job), prompt, provider)
            cached = session.scalar(
                select(RequirementsExtraction).where(
                    RequirementsExtraction.job_id == job.id,
                    RequirementsExtraction.input_hash == requirements_hash,
                    RequirementsExtraction.status == CallStatus.SUCCEEDED,
                )
            )
            latest_hash = session.scalar(
                select(CvTailoring.input_hash)
                .where(
                    CvTailoring.application_id == application.id,
                    CvTailoring.status == CallStatus.SUCCEEDED,
                )
                .order_by(CvTailoring.created_at.desc())
                .limit(1)
            )
            return _Snapshot(
                application_id=application.id,
                job_id=job.id,
                label=f"{job.title or 'Untitled job'} — {job.company or 'unknown company'}",
                posting=posting_of(job),
                posting_turn=render_job_posting(job),
                requirements_hash=requirements_hash,
                cached=(
                    JobRequirements.model_validate(cached.extraction["requirements"])
                    if cached is not None
                    else None
                ),
                cached_id=cached.id if cached is not None else None,
                latest_hash=latest_hash,
                has_current=application.cv_version_id is not None,
            )

    def _tailor_one(
        self,
        application_id: uuid.UUID,
        prepared: _Prepared,
        provider: LLMProvider,
        prompts: tuple[Prompt, Prompt],
        weights: Mapping[str, int],
        run_id: uuid.UUID,
        force: bool,
        recorder: RunRecorder,
    ) -> _Outcome:
        snapshot = self._snapshot(application_id, prompts[0], provider)
        if snapshot is None:  # gone, or no longer qualified since the selection
            return _Outcome("skipped")

        usage = LLMUsage()
        requirements, requirements_id = snapshot.cached, snapshot.cached_id
        if requirements is None:
            extracted = self._extract(snapshot, provider, prompts[0], run_id, recorder)
            if extracted is None:
                return _Outcome("failed")
            requirements, requirements_id, usage = extracted

        input_hash = self._tailoring_hash(prepared, requirements, prompts, provider, weights)
        if not force and snapshot.has_current and snapshot.latest_hash == input_hash:
            return _Outcome("unchanged", usage)

        context = guard_context(
            prepared.master,
            requirements,
            declared_skills=prepared.declared_skills,
            allow_title_changes=prepared.allow_title_changes,
        )
        calls: list[LLMResult[TailoringOutput]] = []
        tailor = self._tailor(provider, prompts[1], prepared, requirements, calls)
        result = optimise(
            context,
            tailor,
            target=self._settings.ats_target_score,
            max_iterations=self._settings.ats_max_iterations,
            weights=weights,
            base_version_id=str(prepared.master_version_id),
        )
        for call in calls:
            usage = usage + call.usage

        with session_scope(self._session_factory) as session:
            stored = self._store(
                session,
                snapshot=snapshot,
                prepared=prepared,
                provider=provider,
                prompt=prompts[1],
                weights=weights,
                run_id=run_id,
                input_hash=input_hash,
                requirements=requirements,
                requirements_id=requirements_id,
                result=result,
                calls=calls,
            )
        self._report(snapshot.label, result, stored, recorder)
        if stored.version is not None:
            return _Outcome("generated", usage)
        if stored.error == MOVED_ON:
            return _Outcome("skipped", usage)
        return _Outcome("refused" if stored.status is CallStatus.REFUSED else "failed", usage)

    def _extract(
        self,
        snapshot: _Snapshot,
        provider: LLMProvider,
        prompt: Prompt,
        run_id: uuid.UUID,
        recorder: RunRecorder,
    ) -> tuple[JobRequirements, uuid.UUID, LLMUsage] | None:
        """Read the posting's requirements (a cache miss). A refusal falls back to the
        deterministic requirements; a failure fails this job."""
        request = LLMRequest(
            task=REQUIREMENTS_TASK,
            system=(SystemBlock(prompt.text),),
            user=snapshot.posting_turn,
            prompt=prompt.reference(),
            context={"posting": posting_context(snapshot.posting)},
        )
        row = RequirementsExtraction(
            job_id=snapshot.job_id,
            run_id=run_id,
            input_hash=snapshot.requirements_hash,
            provider=provider.name,
            requested_model=provider.model,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            prompt_sha256=prompt.sha256,
            extraction={},
        )
        usage = LLMUsage()
        try:
            result = provider.generate_structured(request, RequirementsOutput)
        except LLMConfigError:
            raise
        except LLMRefusalError as exc:
            requirements = build_requirements(snapshot.posting)
            row.status = CallStatus.REFUSED
            row.error_code = (exc.category or "refusal")[:50]
            row.error_message = exc.message
            row.extraction = {
                "version": REQUIREMENTS_VERSION,
                "degraded": True,
                "requirements": requirements.model_dump(mode="json"),
            }
            recorder.event(
                "tailoring.requirements",
                f"{snapshot.label}: the model declined to read this posting; its listed skills "
                "and deterministic patterns are used instead",
                level=EventLevel.WARNING,
            )
        except LLMError as exc:
            row.status = CallStatus.FAILED
            row.error_code = exc.code[:50]
            row.error_message = exc.message
            with session_scope(self._session_factory) as session:
                session.add(row)
            recorder.error("tailoring.requirements", exc, data={"job": snapshot.label})
            return None
        else:
            requirements = build_requirements(snapshot.posting, result.output)
            usage = result.usage
            row.status = CallStatus.SUCCEEDED
            row.served_model = result.served_model
            row.fallback_used = result.fallback_used
            row.request_id = result.request_id
            row.input_tokens = result.usage.input_tokens
            row.output_tokens = result.usage.output_tokens
            row.cache_read_input_tokens = result.usage.cache_read_input_tokens
            row.cache_creation_input_tokens = result.usage.cache_creation_input_tokens
            row.duration_ms = result.duration_ms
            row.extraction = {
                "version": REQUIREMENTS_VERSION,
                "requirements": requirements.model_dump(mode="json"),
            }

        with session_scope(self._session_factory) as session:
            try:
                with session.begin_nested():
                    session.add(row)
            except IntegrityError:  # another run stored the same extraction meanwhile
                existing = session.scalar(
                    select(RequirementsExtraction).where(
                        RequirementsExtraction.job_id == snapshot.job_id,
                        RequirementsExtraction.input_hash == snapshot.requirements_hash,
                        RequirementsExtraction.status == CallStatus.SUCCEEDED,
                    )
                )
                if existing is None:
                    raise
                return (
                    JobRequirements.model_validate(existing.extraction["requirements"]),
                    existing.id,
                    usage,
                )
            if row.status is CallStatus.SUCCEEDED:
                AuditService(session).record(
                    action=AuditAction.REQUIREMENTS_EXTRACTED,
                    actor=Actor.WORKER,
                    entity_type="job",
                    entity_id=str(snapshot.job_id),
                    details={
                        "requirements_id": str(row.id),
                        "keywords": len(requirements.keywords),
                        "discarded": len(requirements.discarded),
                        "provider": row.provider,
                        "prompt": f"{prompt.name}.v{prompt.version}",
                    },
                )
            return requirements, row.id, usage

    def _tailor(
        self,
        provider: LLMProvider,
        prompt: Prompt,
        prepared: _Prepared,
        requirements: JobRequirements,
        calls: list[LLMResult[TailoringOutput]],
    ) -> Callable[[TailoringPrompt], TailoringReply]:
        """The tailoring call the loop makes: the cached facts, then the grounded requirements,
        the best version so far and the feedback (never the raw posting)."""
        brief = requirements_brief(requirements)
        max_iterations = self._settings.ats_max_iterations

        def tailor(request_prompt: TailoringPrompt) -> TailoringReply:
            request = LLMRequest(
                task=TAILORING_TASK,
                system=(SystemBlock(prompt.text), SystemBlock(prepared.facts.text, cache=True)),
                user=tailoring_user_turn(
                    requirements,
                    request_prompt.current,
                    request_prompt.feedback,
                    iteration=request_prompt.iteration,
                    max_iterations=max_iterations,
                ),
                prompt=prompt.reference(),
                context={
                    "facts": prepared.facts.data,
                    "requirements": brief,
                    "current": request_prompt.current.model_dump(mode="json"),
                    "feedback": request_prompt.feedback.model_dump(mode="json"),
                },
            )
            try:
                result = provider.generate_structured(request, TailoringOutput)
            except LLMConfigError:
                raise
            except LLMRefusalError as exc:
                raise TailoringCallError(
                    exc.message, refused=True, code=(exc.category or "refusal")[:50]
                ) from None
            except LLMError as exc:
                raise TailoringCallError(exc.message, code=exc.code[:50]) from None
            calls.append(result)
            return TailoringReply(
                output=result.output,
                usage={
                    "served_model": result.served_model,
                    "fallback_used": result.fallback_used,
                    "request_id": result.request_id,
                    "duration_ms": result.duration_ms,
                    **result.usage.as_dict(),
                },
            )

        return tailor

    def _store(
        self,
        session: Session,
        *,
        snapshot: _Snapshot,
        prepared: _Prepared,
        provider: LLMProvider,
        prompt: Prompt,
        weights: Mapping[str, int],
        run_id: uuid.UUID,
        input_hash: str,
        requirements: JobRequirements,
        requirements_id: uuid.UUID | None,
        result: OptimisationResult,
        calls: Sequence[LLMResult[TailoringOutput]],
    ) -> _Stored:
        """Write the attempt, its analyses and (if any) the new current version, in one
        transaction."""
        candidate = session.get(Candidate, prepared.candidate_id)
        application = session.get(Application, snapshot.application_id)
        if candidate is None or application is None:
            return _Stored(None, CallStatus.FAILED, MOVED_ON)
        session.refresh(candidate, with_for_update=True)  # serialises version numbering
        best = result.best
        last = result.iterations[-1]  # without a best version: the failed call
        if application.status not in TAILORABLE:  # moved on meanwhile: keep the history only
            best, status, error_code, error = None, CallStatus.FAILED, "moved_on", MOVED_ON
        elif best is not None:
            status, error_code, error = CallStatus.SUCCEEDED, None, None
        else:
            refused = last.status is IterationStatus.REFUSED
            status = CallStatus.REFUSED if refused else CallStatus.FAILED
            error_code, error = last.error_code, last.error
        usage = LLMUsage()
        for call in calls:
            usage = usage + call.usage
        last_call = calls[-1] if calls else None
        tailoring = CvTailoring(
            application_id=application.id,
            candidate_id=candidate.id,
            job_id=snapshot.job_id,
            run_id=run_id,
            master_version_id=prepared.master_version_id,
            requirements_id=requirements_id,
            status=status,
            stop_reason=result.stop_reason,
            input_hash=input_hash,
            scoring_version=SCORING_VERSION,
            weights=dict(weights),
            target_score=float(self._settings.ats_target_score),
            max_iterations=self._settings.ats_max_iterations,
            baseline_score=result.baseline.score,
            final_score=best.score if best is not None else None,
            ceiling_score=result.ceiling.score,
            iterations_used=result.calls,
            best_iteration=best.number if best is not None else None,
            requirements=requirements.model_dump(mode="json"),
            gaps=[item.model_dump(mode="json") for item in result.gaps],
            provider=provider.name,
            requested_model=provider.model,
            served_model=last_call.served_model if last_call else None,
            fallback_used=any(call.fallback_used for call in calls),
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            prompt_sha256=prompt.sha256,
            request_id=last_call.request_id if last_call else None,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens,
            duration_ms=sum(call.duration_ms for call in calls) if calls else None,
            error_code=error_code,
            error_message=error,
        )
        session.add(tailoring)
        session.flush()

        version: CvVersion | None = None
        if best is not None and best.assembly is not None:
            current = session.scalar(
                select(CvVersion).where(
                    CvVersion.application_id == application.id,
                    CvVersion.kind == CvKind.TAILORED,
                    CvVersion.status == CvStatus.GENERATED,
                )
            )
            if current is not None:
                current.status = CvStatus.SUPERSEDED
                session.flush()  # one current version per application (partial unique index)
            number = session.scalar(
                select(func.max(CvVersion.version)).where(
                    CvVersion.candidate_id == candidate.id, CvVersion.kind == CvKind.TAILORED
                )
            )
            document = best.assembly.document
            version = CvVersion(
                candidate_id=candidate.id,
                kind=CvKind.TAILORED,
                version=(number or 0) + 1,
                status=CvStatus.GENERATED,
                extracted_text=render_text(document),
                structure=document.model_dump(mode="json"),
                parse_warnings=[],
                parser_version=TAILORED_PARSER_VERSION,
                application_id=application.id,
                job_id=snapshot.job_id,
                base_version_id=prepared.master_version_id,
                run_id=run_id,
                evidence=best.assembly.ledger.model_dump(mode="json"),
                ats_score=best.score,
            )
            session.add(version)
            session.flush()
            tailoring.cv_version_id = version.id
            application.cv_version_id = version.id
            application.ats_score = best.score
            if application.status is ApplicationStatus.QUALIFIED:
                ApplicationService(session).transition(
                    application,
                    ApplicationStatus.CV_GENERATED,
                    reason=f"Tailored CV {version.id}: ATS score {best.score}",
                    actor=Actor.WORKER,
                )

        for iteration in result.iterations:
            selected = best is not None and iteration.number == best.number
            session.add(
                _analysis_row(
                    tailoring.id, iteration, selected, version.id if selected and version else None
                )
            )

        unsupported = (
            len(best.report.keywords_with(KeywordClass.UNSUPPORTED))
            if best is not None and best.report is not None
            else 0
        )
        details: dict[str, Any] = {
            "tailoring_id": str(tailoring.id),
            "application_id": str(application.id),
            "job_id": str(snapshot.job_id),
            "baseline_score": result.baseline.score,
            "final_score": tailoring.final_score,
            "ceiling_score": result.ceiling.score,
            "stop_reason": result.stop_reason.value,
            "calls": result.calls,
            "unsupported_keywords": unsupported,
            "provider": provider.name,
            "prompt": f"{prompt.name}.v{prompt.version}",
        }
        audit = AuditService(session)
        if version is not None:
            audit.record(
                action=AuditAction.CV_TAILORED,
                actor=Actor.WORKER,
                entity_type="cv_version",
                entity_id=str(version.id),
                details=details,
            )
        else:
            audit.record(
                action=(
                    AuditAction.CV_TAILORING_REFUSED
                    if status is CallStatus.REFUSED
                    else AuditAction.CV_TAILORING_FAILED
                ),
                actor=Actor.WORKER,
                entity_type="application",
                entity_id=str(application.id),
                details={**details, "error_code": tailoring.error_code},
            )
        session.flush()
        return _Stored(version, status, error)

    def _report(
        self,
        label: str,
        result: OptimisationResult,
        stored: _Stored,
        recorder: RunRecorder,
    ) -> None:
        reason = STOP_LABELS[result.stop_reason]
        target = self._settings.ats_target_score
        best, version = result.best, stored.version
        if version is None or best is None:
            detail = f": {stored.error}" if stored.error else ""
            recorder.event(
                "tailoring.job",
                f"{label}: no tailored CV stored ({reason}){detail}; it stays queued",
                level=EventLevel.WARNING,
                data={"stop_reason": result.stop_reason.value},
            )
            return
        unsupported = len(best.report.keywords_with(KeywordClass.UNSUPPORTED)) if best.report else 0
        if best.kind is DocumentKind.MASTER:
            headline = f"{result.baseline.score} with the master CV as it is"
        else:
            headline = f"{result.baseline.score} → {best.score}"
        recorder.event(
            "tailoring.job",
            f"{label}: {headline} (target {target}, reachable {result.ceiling.score}), "
            f"{reason}, {unsupported} unsupported keywords, {result.calls} call(s)",
            data={
                "cv_version_id": str(version.id),
                "baseline_score": result.baseline.score,
                "final_score": best.score,
                "ceiling_score": result.ceiling.score,
                "stop_reason": result.stop_reason.value,
                "calls": result.calls,
            },
        )

    # --- helpers -----------------------------------------------------------------------------
    def _finished(
        self, run_id: uuid.UUID, status: RunStatus, totals: Mapping[str, int]
    ) -> dict[str, Any]:
        self._audit(
            AuditAction.RUN_FINISHED, run_id, {"status": status.value, "totals": dict(totals)}
        )
        logger.info("tailoring.completed", run_id=str(run_id), status=status.value, **totals)
        return {
            "run_id": str(run_id),
            "status": status.value,
            "cv_generated": totals["generated"],
            "jobs_processed": totals["generated"] + totals["refused"] + totals["failed"],
            "totals": dict(totals),
        }

    def _audit(self, action: AuditAction, run_id: uuid.UUID, details: dict[str, Any]) -> None:
        with session_scope(self._session_factory) as session:
            AuditService(session).record(
                action=action,
                actor=Actor.WORKER,
                entity_type="automation_run",
                entity_id=str(run_id),
                details=details,
            )


def _analysis_row(
    tailoring_id: uuid.UUID, iteration: Iteration, selected: bool, cv_version_id: uuid.UUID | None
) -> AtsAnalysis:
    report, assembly, usage = iteration.report, iteration.assembly, iteration.usage
    return AtsAnalysis(
        tailoring_id=tailoring_id,
        cv_version_id=cv_version_id,
        iteration=iteration.number,
        document_kind=iteration.kind,
        status=iteration.status,
        selected=selected,
        scoring_version=SCORING_VERSION,
        score=report.score if report else None,
        assessed_weight=report.assessed_weight if report else None,
        penalty=report.penalty if report else 0,
        components=[item.model_dump(mode="json") for item in report.components] if report else [],
        keywords=[item.model_dump(mode="json") for item in report.keywords] if report else [],
        stuffing=[item.model_dump(mode="json") for item in report.stuffing] if report else [],
        violations=[item.model_dump(mode="json") for item in iteration.violations],
        feedback=iteration.feedback.model_dump(mode="json") if iteration.feedback else {},
        repairs_count=len(assembly.ledger.repairs) if assembly else 0,
        document=assembly.document.model_dump(mode="json") if assembly else {},
        ledger=assembly.ledger.model_dump(mode="json") if assembly else {},
        served_model=usage.get("served_model"),
        fallback_used=bool(usage.get("fallback_used", False)),
        request_id=usage.get("request_id"),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_read_input_tokens=int(usage.get("cache_read_input_tokens", 0)),
        cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens", 0)),
        duration_ms=usage.get("duration_ms"),
        error_code=iteration.error_code,
        error_message=iteration.error,
    )
