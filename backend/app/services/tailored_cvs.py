"""Tailored CV versions and tailoring attempts, as the API shows them (read-only)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ats.keywords import KeywordResult
from app.ats.ledger import Ledger, Violation
from app.ats.requirements import JobRequirements
from app.ats.scoring import ComponentScore, Gap, StuffingSignal
from app.ats.sources import Source, build_sources
from app.core.errors import NotFoundError
from app.cv.models import ParsedCV
from app.models import (
    Application,
    AtsAnalysis,
    Candidate,
    CvKind,
    CvStatus,
    CvTailoring,
    CvVersion,
    Job,
)
from app.schemas.ats import (
    AtsIterationRead,
    LedgerEntry,
    LedgerSource,
    TailoredCvDetail,
    TailoredCvSummary,
    TailoringRead,
)
from app.schemas.common import AnalysisUsage, PromptInfo


class TailoredCvService:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- tailored versions -------------------------------------------------------------------
    def versions(self, candidate: Candidate, *, job_id: uuid.UUID | None = None) -> list[CvVersion]:
        query = select(CvVersion).where(
            CvVersion.candidate_id == candidate.id, CvVersion.kind == CvKind.TAILORED
        )
        if job_id is not None:
            query = query.where(CvVersion.job_id == job_id)
        return list(self._session.scalars(query.order_by(CvVersion.version.desc())))

    def get(self, candidate: Candidate, version_id: uuid.UUID) -> CvVersion:
        version = self._session.scalar(
            select(CvVersion).where(
                CvVersion.id == version_id,
                CvVersion.candidate_id == candidate.id,
                CvVersion.kind == CvKind.TAILORED,
            )
        )
        if version is None:
            raise NotFoundError("Tailored CV not found")
        return version

    def summaries(
        self, candidate: Candidate, versions: Sequence[CvVersion]
    ) -> list[TailoredCvSummary]:
        active = self.active_master_id(candidate.id)
        jobs = self._jobs(version.job_id for version in versions)
        return [_summary(version, jobs.get(version.job_id), active) for version in versions]

    def detail(self, candidate: Candidate, version: CvVersion) -> TailoredCvDetail:
        active = self.active_master_id(candidate.id)
        job = self._jobs([version.job_id]).get(version.job_id)
        sources = self._base_sources(version)
        ledger = Ledger.model_validate(version.evidence or {})
        tailoring = self._session.scalar(
            select(CvTailoring).where(CvTailoring.cv_version_id == version.id)
        )
        return TailoredCvDetail(
            **_summary(version, job, active).model_dump(),
            structure=ParsedCV.model_validate(version.structure),
            extracted_text=version.extracted_text,
            ledger=[
                LedgerEntry(
                    path=item.path,
                    origin=item.origin,
                    sources=[_source(source_id, sources) for source_id in item.sources],
                    keywords=list(item.keywords),
                )
                for item in ledger.items
            ],
            unused_sources=[_source(source_id, sources) for source_id in ledger.unused_sources],
            repairs=list(ledger.repairs),
            tailoring=self.tailoring_read(tailoring, active) if tailoring is not None else None,
        )

    # --- tailoring attempts ------------------------------------------------------------------
    def latest_tailoring(self, application: Application) -> CvTailoring | None:
        return self._session.scalar(
            select(CvTailoring)
            .where(CvTailoring.application_id == application.id)
            .order_by(CvTailoring.created_at.desc())
            .limit(1)
        )

    def tailoring_read(
        self, tailoring: CvTailoring, active_master_id: uuid.UUID | None
    ) -> TailoringRead:
        analyses = list(
            self._session.scalars(
                select(AtsAnalysis)
                .where(AtsAnalysis.tailoring_id == tailoring.id)
                .order_by(AtsAnalysis.iteration)
            )
        )
        master = next((analysis for analysis in analyses if analysis.iteration == 0), None)
        return TailoringRead(
            id=tailoring.id,
            created_at=tailoring.created_at,
            status=tailoring.status,
            stop_reason=tailoring.stop_reason,
            run_id=tailoring.run_id,
            provider=tailoring.provider,
            is_mock=tailoring.provider == "mock",
            requested_model=tailoring.requested_model,
            served_model=tailoring.served_model,
            fallback_used=tailoring.fallback_used,
            prompt=PromptInfo(name=tailoring.prompt_name, version=tailoring.prompt_version),
            usage=AnalysisUsage(
                input_tokens=tailoring.input_tokens,
                output_tokens=tailoring.output_tokens,
                cache_read_input_tokens=tailoring.cache_read_input_tokens,
                cache_creation_input_tokens=tailoring.cache_creation_input_tokens,
            ),
            duration_ms=tailoring.duration_ms,
            scoring_version=tailoring.scoring_version,
            weights={key: int(value) for key, value in (tailoring.weights or {}).items()},
            target_score=tailoring.target_score,
            max_iterations=tailoring.max_iterations,
            baseline_score=tailoring.baseline_score,
            final_score=tailoring.final_score,
            ceiling_score=tailoring.ceiling_score,
            assessed_weight=master.assessed_weight if master is not None else None,
            iterations_used=tailoring.iterations_used,
            best_iteration=tailoring.best_iteration,
            requirements=JobRequirements.model_validate(tailoring.requirements),
            gaps=[Gap.model_validate(item) for item in tailoring.gaps],
            cv_version_id=tailoring.cv_version_id,
            stale=(
                tailoring.master_version_id is not None
                and tailoring.master_version_id != active_master_id
            ),
            error_code=tailoring.error_code,
            error_message=tailoring.error_message,
            iterations=[_iteration(analysis) for analysis in analyses],
        )

    # --- helpers -----------------------------------------------------------------------------
    def active_master_id(self, candidate_id: uuid.UUID) -> uuid.UUID | None:
        """The confirmed master CV: a tailored version built from another one is stale."""
        return self._session.scalar(
            select(CvVersion.id).where(
                CvVersion.candidate_id == candidate_id,
                CvVersion.kind == CvKind.MASTER,
                CvVersion.status == CvStatus.CONFIRMED,
            )
        )

    def _jobs(self, job_ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID | None, Job]:
        ids = {job_id for job_id in job_ids if job_id is not None}
        if not ids:
            return {}
        return {job.id: job for job in self._session.scalars(select(Job).where(Job.id.in_(ids)))}

    def _base_sources(self, version: CvVersion) -> dict[str, Source]:
        base = (
            self._session.get(CvVersion, version.base_version_id)
            if version.base_version_id is not None
            else None
        )
        if base is None:
            return {}
        return build_sources(ParsedCV.model_validate(base.structure))


def _summary(
    version: CvVersion, job: Job | None, active_master_id: uuid.UUID | None
) -> TailoredCvSummary:
    return TailoredCvSummary(
        id=version.id,
        version=version.version,
        status=version.status,
        application_id=version.application_id,
        job_id=version.job_id,
        job_title=job.title if job is not None else None,
        company=job.company if job is not None else None,
        base_version_id=version.base_version_id,
        ats_score=version.ats_score,
        stale=version.base_version_id is not None and version.base_version_id != active_master_id,
        created_at=version.created_at,
    )


def _source(source_id: str, sources: dict[str, Source]) -> LedgerSource:
    source = sources.get(source_id)
    if source is None:  # the base version is gone: show the id alone
        return LedgerSource(id=source_id, label=source_id, text="", path=None)
    return LedgerSource(id=source.id, label=source.label, text=source.text, path=source.path)


def _iteration(analysis: AtsAnalysis) -> AtsIterationRead:
    return AtsIterationRead(
        iteration=analysis.iteration,
        document_kind=analysis.document_kind,
        status=analysis.status,
        selected=analysis.selected,
        score=analysis.score,
        assessed_weight=analysis.assessed_weight,
        penalty=analysis.penalty,
        components=[ComponentScore.model_validate(item) for item in analysis.components],
        keywords=[KeywordResult.model_validate(item) for item in analysis.keywords],
        stuffing=[StuffingSignal.model_validate(item) for item in analysis.stuffing],
        violations=[Violation.model_validate(item) for item in analysis.violations],
        repairs_count=analysis.repairs_count,
        served_model=analysis.served_model,
        request_id=analysis.request_id,
        usage=AnalysisUsage(
            input_tokens=analysis.input_tokens,
            output_tokens=analysis.output_tokens,
            cache_read_input_tokens=analysis.cache_read_input_tokens,
            cache_creation_input_tokens=analysis.cache_creation_input_tokens,
        ),
        duration_ms=analysis.duration_ms,
        error_code=analysis.error_code,
        error_message=analysis.error_message,
    )
