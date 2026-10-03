"""Job analysis run (Phase 4): for each queued application, ask the LLM provider for a structured
assessment, verify it against the posting and the confirmed CV, decide APPLY / REVIEW / SKIP with
explicit rules, store the analysis and move the application through its lifecycle.

Executed by a worker, recorded as an ANALYSIS automation run. Requires a confirmed master CV.
Unchanged inputs (job content, candidate facts, prompt, model, effort) are not re-analysed unless
forced. Refusals and provider failures are isolated per job; a configuration error (no key,
rejected key, unknown model) stops the run, as do repeated consecutive failures.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.analysis.assemble import assemble_analysis
from app.analysis.facts import CandidateFacts, build_candidate_facts
from app.analysis.job_text import job_context, render_job_posting
from app.analysis.mock_responder import mock_job_analysis
from app.analysis.schemas import JobAnalysisOutput
from app.analysis.types import AnalysisStatus, Recommendation
from app.applications.lifecycle import ApplicationStatus
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
from app.llm.types import LLMRequest, LLMUsage, SystemBlock
from app.models import (
    Application,
    Education,
    EventLevel,
    Experience,
    Job,
    JobAnalysis,
    Project,
    RunStatus,
)
from app.services.applications import ApplicationService
from app.services.audit import Actor, AuditAction, AuditService
from app.services.candidate_profile import CandidateService
from app.services.cv_versions import find_active_master
from app.services.job_sources import JobSourceService
from app.services.runs import RunRecorder
from app.services.skills import SkillService

logger = get_logger(__name__)

TASK = "job_analysis"
MAX_CONSECUTIVE_FAILURES = 3
TOTAL_KEYS: tuple[str, ...] = (
    "selected",
    "analysed",
    "unchanged",
    "refused",
    "failed",
    "apply",
    "review",
    "skip",
)
# Applications whose analysis can be (re)done; later stages keep their own state.
ANALYSABLE = (ApplicationStatus.DISCOVERED, ApplicationStatus.ANALYZED, ApplicationStatus.QUALIFIED)
MOCK_RESPONDERS: Mapping[str, Any] = {TASK: mock_job_analysis}


@dataclass(frozen=True)
class _Outcome:
    kind: str  # analysed | unchanged | refused | failed
    recommendation: Recommendation | None = None
    visa_status: str | None = None
    usage: LLMUsage = field(default_factory=LLMUsage)


class AnalysisService:
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
        totals = dict.fromkeys(TOTAL_KEYS, 0)
        usage = LLMUsage()
        visa_counts: Counter[str] = Counter()
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
            candidate_id, facts = prepared

            try:
                provider = self._provider or create_llm_provider(
                    self._settings, mock_responders=MOCK_RESPONDERS
                )
            except LLMConfigError as exc:
                recorder.error("analysis.provider", exc)
                recorder.finish(RunStatus.FAILED, summary=summary)
                return self._finished(run_id, RunStatus.FAILED, totals)
            prompt = self._prompts.get(TASK)
            provider_info = {
                "name": provider.name,
                "model": provider.model,
                "reason": getattr(provider, "reason", None),
            }
            summary.update(
                provider=provider_info,
                prompt=prompt.ref,
                effort=self._settings.llm_effort,
                cv_version_id=str(facts.cv_version_id) if facts.cv_version_id else None,
            )
            mock_note = (
                " (offline mock: results are not from a language model)"
                if provider.name == "mock"
                else ""
            )
            recorder.event(
                "analysis.config",
                f"Analysing with {provider.name} · {provider.model}, prompt {prompt.ref}{mock_note}",
                data={**provider_info, "prompt": prompt.ref, "effort": self._settings.llm_effort},
            )

            with session_scope(self._session_factory) as session:
                selected, remaining = self._select(session, candidate_id, job_ids, recorder)
            totals["selected"] = len(selected)
            summary["pending_remaining"] = remaining
            if remaining:
                recorder.event(
                    "analysis.selection",
                    f"{remaining} more job(s) wait for the next analysis run "
                    f"(ANALYSIS_MAX_JOBS_PER_RUN={self._settings.analysis_max_jobs_per_run})",
                    level=EventLevel.WARNING,
                )

            consecutive_failures = 0
            stopped_by_config = False
            for application_id in selected:
                try:
                    outcome = self._analyse_one(
                        application_id, facts, provider, prompt, run_id, force, recorder
                    )
                except LLMConfigError as exc:
                    recorder.error("analysis.provider", exc)
                    stopped_by_config = True
                    break
                totals[outcome.kind] += 1
                usage = usage + outcome.usage
                if outcome.kind == "analysed" and outcome.recommendation is not None:
                    totals[outcome.recommendation.value.lower()] += 1
                    visa_counts[outcome.visa_status or "UNKNOWN"] += 1
                consecutive_failures = consecutive_failures + 1 if outcome.kind == "failed" else 0
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    recorder.event(
                        "analysis.provider",
                        f"Stopped after {MAX_CONSECUTIVE_FAILURES} consecutive failures; the "
                        "remaining jobs stay queued for the next run",
                        level=EventLevel.WARNING,
                    )
                    break

            summary.update(visa=dict(visa_counts), usage=usage.as_dict())
            recorder.event(
                "analysis.summary",
                f"{totals['analysed']} job(s) analysed: {totals['apply']} apply, "
                f"{totals['review']} review, {totals['skip']} skip",
                data=totals,
            )
            recorder.increment(
                jobs_processed=totals["analysed"],
                jobs_qualified=totals["apply"] + totals["review"],
            )
            if stopped_by_config:
                status = RunStatus.PARTIAL_SUCCESS if totals["analysed"] else RunStatus.FAILED
            elif totals["failed"]:
                # FAILED when every attempted job failed; a refusal is an answer, not a failure.
                answered = totals["analysed"] + totals["refused"]
                status = RunStatus.PARTIAL_SUCCESS if answered else RunStatus.FAILED
            recorder.finish(status, summary=summary)
        return self._finished(run_id, status, totals)

    # --- preparation -------------------------------------------------------------------------
    def _prepare(
        self, session: Session, recorder: RunRecorder
    ) -> tuple[uuid.UUID, CandidateFacts] | None:
        candidates = CandidateService(session, candidate_dir=self._settings.candidate_dir)
        try:
            candidate, created = candidates.get_or_import_default()
        except AppError as exc:
            recorder.event(
                "analysis.candidate",
                f"No candidate profile ({exc.message}): nothing was analysed.",
                level=EventLevel.WARNING,
            )
            return None
        if created:
            AuditService(session).record(
                action=AuditAction.CANDIDATE_IMPORTED,
                actor=Actor.WORKER,
                entity_type="candidate",
                entity_id=str(candidate.id),
                details={"source": "yaml", "reason": "analysis", "profile_version": 1},
            )
        master = find_active_master(session, candidate)
        if master is None:
            recorder.event(
                "analysis.candidate",
                "No confirmed master CV: upload and confirm it on the CV page, then run the "
                "analysis again. Nothing was analysed.",
                level=EventLevel.WARNING,
            )
            return None

        def facts_of(model: Any) -> list[Any]:
            return list(
                session.scalars(
                    select(model).where(model.cv_version_id == master.id).order_by(model.position)
                )
            )

        facts = build_candidate_facts(
            profile=CandidateService.profile_of(candidate),
            cv=ParsedCV.model_validate(master.structure),
            cv_version_id=master.id,
            experiences=facts_of(Experience),
            projects=facts_of(Project),
            education=facts_of(Education),
            skills=SkillService(session).list(candidate),
            today=self._clock().date(),
        )
        return candidate.id, facts

    def _select(
        self,
        session: Session,
        candidate_id: uuid.UUID,
        job_ids: Sequence[uuid.UUID] | None,
        recorder: RunRecorder,
    ) -> tuple[list[uuid.UUID], int]:
        limit = self._settings.analysis_max_jobs_per_run
        hidden = () if self._settings.mock_mode else tuple(JobSourceService(session).mock_keys())
        if job_ids is None:
            query = (
                select(Application.id)
                .join(Job, Job.id == Application.job_id)
                .where(
                    Application.candidate_id == candidate_id,
                    Application.status == ApplicationStatus.DISCOVERED,
                    Job.duplicate_of_id.is_(None),
                )
                .order_by(Job.posted_at.desc().nulls_last(), Job.discovered_at.desc(), Job.id)
            )
            if hidden:
                query = query.where(Job.source.not_in(hidden))
            ids = list(session.scalars(query))
            return ids[:limit], max(0, len(ids) - limit)

        candidate = CandidateService(session, candidate_dir=self._settings.candidate_dir)
        owner = candidate.get_or_import_default()[0]
        applications = ApplicationService(session)
        selected: list[uuid.UUID] = []
        for job_id in job_ids:
            job = session.get(Job, job_id)
            if job is not None and job.duplicate_of_id is not None:
                job = session.get(Job, job.duplicate_of_id)  # analyse the primary record
            if job is None or job.source in hidden:
                recorder.event(
                    "analysis.selection", f"Job {job_id} was not found", level=EventLevel.WARNING
                )
                continue
            application, _ = applications.create_discovered(owner, job)
            if application.status not in ANALYSABLE:
                recorder.event(
                    "analysis.selection",
                    f"{job.title} is already at {application.status.value}: not re-analysed",
                    level=EventLevel.WARNING,
                )
                continue
            if application.id not in selected:
                selected.append(application.id)
        return selected[:limit], max(0, len(selected) - limit)

    # --- one application ---------------------------------------------------------------------
    def _input_hash(
        self, job: Job, facts: CandidateFacts, prompt: Prompt, provider: LLMProvider
    ) -> str:
        material = "|".join(
            (
                job.content_hash,
                facts.sha256,
                prompt.sha256,
                provider.name,
                provider.model,
                self._settings.llm_effort,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _analyse_one(
        self,
        application_id: uuid.UUID,
        facts: CandidateFacts,
        provider: LLMProvider,
        prompt: Prompt,
        run_id: uuid.UUID,
        force: bool,
        recorder: RunRecorder,
    ) -> _Outcome:
        with session_scope(self._session_factory) as session:
            application = session.get(Application, application_id)
            job = session.get(Job, application.job_id) if application is not None else None
            if application is None or job is None:
                return _Outcome("failed")
            input_hash = self._input_hash(job, facts, prompt, provider)
            if not force:
                latest = session.scalar(
                    select(JobAnalysis)
                    .where(
                        JobAnalysis.application_id == application.id,
                        JobAnalysis.status == AnalysisStatus.SUCCEEDED,
                    )
                    .order_by(JobAnalysis.created_at.desc())
                    .limit(1)
                )
                if latest is not None and latest.input_hash == input_hash:
                    return _Outcome("unchanged")

            request = LLMRequest(
                task=TASK,
                system=(SystemBlock(prompt.text), SystemBlock(facts.text, cache=True)),
                user=render_job_posting(job),
                prompt=prompt.reference(),
                context={"job": job_context(job), "candidate": _candidate_context(facts)},
            )
            label = f"{job.title or 'Untitled job'} — {job.company or 'unknown company'}"
            row = JobAnalysis(
                application_id=application.id,
                candidate_id=application.candidate_id,
                job_id=job.id,
                cv_version_id=facts.cv_version_id,
                run_id=run_id,
                provider=provider.name,
                requested_model=provider.model,
                prompt_name=prompt.name,
                prompt_version=prompt.version,
                prompt_sha256=prompt.sha256,
                input_hash=input_hash,
                rule_reasons=[],
                visa={},
                relevance={},
            )
            audit = AuditService(session)
            try:
                result = provider.generate_structured(request, JobAnalysisOutput)
            except LLMConfigError:
                raise
            except LLMRefusalError as exc:
                row.status = AnalysisStatus.REFUSED
                row.error_code = (exc.category or "refusal")[:50]
                row.error_message = exc.message
                session.add(row)
                session.flush()
                self._record(audit, AuditAction.ANALYSIS_REFUSED, job, row, category=exc.category)
                recorder.event(
                    "analysis.job",
                    f"{label}: the model declined to analyse this posting "
                    f"(category {exc.category or 'unknown'}); it stays queued",
                    level=EventLevel.WARNING,
                )
                return _Outcome("refused")
            except LLMError as exc:
                row.status = AnalysisStatus.FAILED
                row.error_code = exc.code[:50]
                row.error_message = exc.message
                session.add(row)
                session.flush()
                self._record(audit, AuditAction.ANALYSIS_FAILED, job, row, error_code=exc.code)
                recorder.error("analysis.job", exc, data={"job": label})
                return _Outcome("failed")

            assembled = assemble_analysis(result.output, job=job, facts=facts)
            row.status = AnalysisStatus.SUCCEEDED
            row.provider = result.provider
            row.requested_model = result.requested_model
            row.served_model = result.served_model
            row.fallback_used = result.fallback_used
            row.request_id = result.request_id
            row.input_tokens = result.usage.input_tokens
            row.output_tokens = result.usage.output_tokens
            row.cache_read_input_tokens = result.usage.cache_read_input_tokens
            row.cache_creation_input_tokens = result.usage.cache_creation_input_tokens
            row.duration_ms = result.duration_ms
            row.recommendation = assembled.recommendation
            row.llm_recommendation = assembled.llm_recommendation
            row.rule_reasons = list(assembled.reasons)
            row.visa_status = assembled.visa.status
            row.visa = assembled.visa.model_dump(mode="json")
            row.relevance = assembled.relevance.model_dump(mode="json")
            session.add(row)
            session.flush()

            application.visa_status = assembled.visa.status.value
            application.recommendation = assembled.recommendation
            lifecycle = ApplicationService(session)
            reason = f"Analysis {row.id}: {assembled.recommendation.value}"
            if application.status is ApplicationStatus.DISCOVERED:
                lifecycle.transition(
                    application, ApplicationStatus.ANALYZED, reason=reason, actor=Actor.WORKER
                )
            if application.status is ApplicationStatus.ANALYZED and assembled.recommendation in (
                Recommendation.APPLY,
                Recommendation.REVIEW,
            ):
                lifecycle.transition(
                    application, ApplicationStatus.QUALIFIED, reason=reason, actor=Actor.WORKER
                )
            self._record(
                audit,
                AuditAction.ANALYSIS_COMPLETED,
                job,
                row,
                recommendation=assembled.recommendation.value,
                visa_status=assembled.visa.status.value,
                served_model=result.served_model,
            )
            recorder.event(
                "analysis.job",
                f"{label}: {assembled.recommendation.value} "
                f"(visa {assembled.visa.status.value.removeprefix('SPONSORSHIP_').lower()})",
                data={
                    "analysis_id": str(row.id),
                    "recommendation": assembled.recommendation.value,
                    "visa_status": assembled.visa.status.value,
                },
            )
            return _Outcome(
                "analysed",
                recommendation=assembled.recommendation,
                visa_status=assembled.visa.status.value,
                usage=result.usage,
            )

    # --- helpers -----------------------------------------------------------------------------
    @staticmethod
    def _record(
        audit: AuditService, action: AuditAction, job: Job, row: JobAnalysis, **details: Any
    ) -> None:
        audit.record(
            action=action,
            actor=Actor.WORKER,
            entity_type="job",
            entity_id=str(job.id),
            details={
                "analysis_id": str(row.id),
                "application_id": str(row.application_id),
                "provider": row.provider,
                "model": row.requested_model,
                "prompt": f"{row.prompt_name}.v{row.prompt_version}",
                **details,
            },
        )

    def _finished(
        self, run_id: uuid.UUID, status: RunStatus, totals: Mapping[str, int]
    ) -> dict[str, Any]:
        self._audit(
            AuditAction.RUN_FINISHED, run_id, {"status": status.value, "totals": dict(totals)}
        )
        logger.info("analysis.completed", run_id=str(run_id), status=status.value, **totals)
        return {
            "run_id": str(run_id),
            "status": status.value,
            "jobs_processed": totals["analysed"],
            "jobs_qualified": totals["apply"] + totals["review"],
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


def _candidate_context(facts: CandidateFacts) -> dict[str, Any]:
    return {
        "target_roles": list(facts.target_roles),
        "skills": [{"name": item.name, "strength": item.strength} for item in facts.skills],
        "languages": (
            [{"language": item.language, "level": item.level} for item in facts.languages]
            if facts.languages
            else None
        ),
        "experience_years": facts.experience_years,
    }
