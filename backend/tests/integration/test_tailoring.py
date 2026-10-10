"""Tailored CV versions in PostgreSQL: the constraints of migration 0005 (one current tailored
version per application, no file for tailored versions, statuses that follow the kind) and the
cascades from an application to its tailoring history."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.ats.mock_responder import mock_cv_tailoring, mock_job_requirements
from app.ats.types import CallStatus, DocumentKind, IterationStatus, StopReason
from app.core.logging import configure_logging
from app.llm.errors import LLMConfigError, LLMRefusalError, LLMUnavailableError
from app.llm.types import LLMRequest, LLMResult, LLMUsage, ProviderHealth
from app.models import (
    Application,
    AtsAnalysis,
    AuditLog,
    CvKind,
    CvStatus,
    CvTailoring,
    CvVersion,
    Job,
    RequirementsExtraction,
)

pytestmark = [pytest.mark.feature("cv-tailoring"), pytest.mark.integration]


@dataclass(frozen=True)
class World:
    candidate_id: uuid.UUID
    master_id: uuid.UUID
    application_ids: tuple[uuid.UUID, ...]
    job_ids: tuple[uuid.UUID, ...]


@pytest.fixture
def world(
    jobs_db: sessionmaker[Session],
    discover: Callable[..., Any],
    import_companies: Callable[[], None],
    confirm_master_cv: Callable[[], uuid.UUID],
) -> World:
    import_companies()
    discover()
    master_id = confirm_master_cv()
    with jobs_db() as session:
        applications = list(session.scalars(select(Application).order_by(Application.created_at)))
        return World(
            candidate_id=applications[0].candidate_id,
            master_id=master_id,
            application_ids=tuple(application.id for application in applications[:2]),
            job_ids=tuple(application.job_id for application in applications[:2]),
        )


def _tailored(
    world: World,
    *,
    version: int,
    status: CvStatus = CvStatus.GENERATED,
    application: int = 0,
    **overrides: Any,
) -> CvVersion:
    values: dict[str, Any] = {
        "candidate_id": world.candidate_id,
        "kind": CvKind.TAILORED,
        "version": version,
        "status": status,
        "extracted_text": "Alex Example\n",
        "structure": {"parser_version": "tailored-cv.v1"},
        "parser_version": "tailored-cv.v1",
        "application_id": world.application_ids[application],
        "job_id": world.job_ids[application],
        "base_version_id": world.master_id,
        "evidence": {"format": 1},
        "ats_score": 88.3,
    }
    values.update(overrides)
    return CvVersion(**values)


def _rejected(jobs_db: sessionmaker[Session], *rows: Any) -> None:
    with jobs_db() as session:
        session.add_all(rows)
        with pytest.raises(IntegrityError):
            session.flush()


def test_a_tailored_version_needs_its_application_and_base(
    world: World, jobs_db: sessionmaker[Session]
) -> None:
    _rejected(jobs_db, _tailored(world, version=1, application_id=None))
    _rejected(jobs_db, _tailored(world, version=1, base_version_id=None))
    with jobs_db() as session:
        session.add(_tailored(world, version=1))
        session.commit()


def test_a_master_version_needs_its_file(world: World, jobs_db: sessionmaker[Session]) -> None:
    master = CvVersion(
        candidate_id=world.candidate_id,
        kind=CvKind.MASTER,
        version=99,
        status=CvStatus.PARSED,
        extracted_text="",
        structure={},
        parser_version="1.0",
    )

    _rejected(jobs_db, master)


def test_statuses_follow_the_kind(world: World, jobs_db: sessionmaker[Session]) -> None:
    _rejected(jobs_db, _tailored(world, version=1, status=CvStatus.CONFIRMED))
    with jobs_db() as session:
        master = session.get(CvVersion, world.master_id)
        assert master is not None
        master.status = CvStatus.GENERATED
        with pytest.raises(IntegrityError):
            session.flush()


def test_an_application_has_one_current_tailored_version(
    world: World, jobs_db: sessionmaker[Session]
) -> None:
    _rejected(jobs_db, _tailored(world, version=1), _tailored(world, version=2))
    with jobs_db() as session:
        session.add_all(
            [
                _tailored(world, version=1, status=CvStatus.SUPERSEDED),
                _tailored(world, version=2),
                _tailored(world, version=3, application=1),  # another application
            ]
        )
        session.commit()


def test_one_successful_extraction_per_posting_version(
    world: World, jobs_db: sessionmaker[Session]
) -> None:
    def extraction(status: CallStatus) -> RequirementsExtraction:
        return RequirementsExtraction(
            job_id=world.job_ids[0],
            status=status,
            input_hash="a" * 64,
            provider="mock",
            requested_model="mock-deterministic-1",
            prompt_name="job_requirements",
            prompt_version=1,
            prompt_sha256="b" * 64,
        )

    _rejected(jobs_db, extraction(CallStatus.SUCCEEDED), extraction(CallStatus.SUCCEEDED))
    with jobs_db() as session:
        session.add_all([extraction(CallStatus.FAILED), extraction(CallStatus.FAILED)])
        session.add(extraction(CallStatus.SUCCEEDED))
        session.commit()


def test_deleting_an_application_deletes_its_tailoring_history(
    world: World, jobs_db: sessionmaker[Session]
) -> None:
    with jobs_db() as session:
        version = _tailored(world, version=1)
        session.add(version)
        session.flush()
        tailoring = CvTailoring(
            application_id=world.application_ids[0],
            candidate_id=world.candidate_id,
            job_id=world.job_ids[0],
            master_version_id=world.master_id,
            cv_version_id=version.id,
            status=CallStatus.SUCCEEDED,
            input_hash="c" * 64,
            scoring_version="ats-score.v1",
            target_score=95,
            max_iterations=3,
            provider="mock",
            requested_model="mock-deterministic-1",
            prompt_name="cv_tailoring",
            prompt_version=1,
            prompt_sha256="d" * 64,
        )
        session.add(tailoring)
        session.flush()
        session.add(
            AtsAnalysis(
                tailoring_id=tailoring.id,
                iteration=0,
                document_kind=DocumentKind.MASTER,
                status=IterationStatus.SCORED,
                scoring_version="ats-score.v1",
                score=82.3,
            )
        )
        application = session.get(Application, world.application_ids[0])
        assert application is not None
        application.cv_version_id = version.id
        session.commit()

    with jobs_db() as session:
        application = session.get(Application, world.application_ids[0])
        session.delete(application)
        session.commit()

    with jobs_db() as session:
        for model in (CvTailoring, AtsAnalysis):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        tailored = select(func.count()).where(CvVersion.kind == CvKind.TAILORED)
        assert session.scalar(tailored) == 0
        assert session.get(CvVersion, world.master_id) is not None  # the master stays


# --- CV generation runs --------------------------------------------------------------------------


@dataclass(frozen=True)
class JobState:
    application: Application
    versions: list[CvVersion]  # tailored versions, oldest first
    tailorings: list[CvTailoring]  # oldest first
    analyses: list[AtsAnalysis]  # of the latest tailoring
    extractions: list[RequirementsExtraction]

    @property
    def current(self) -> CvVersion | None:
        return next((v for v in self.versions if v.status is CvStatus.GENERATED), None)

    @property
    def latest(self) -> CvTailoring:
        return self.tailorings[-1]


def _states(jobs_db: sessionmaker[Session]) -> dict[str, JobState]:
    with jobs_db() as session:
        states: dict[str, JobState] = {}
        for job in session.scalars(select(Job)):
            application = session.scalar(select(Application).where(Application.job_id == job.id))
            if application is None:
                continue
            tailorings = list(
                session.scalars(
                    select(CvTailoring)
                    .where(CvTailoring.application_id == application.id)
                    .order_by(CvTailoring.created_at)
                )
            )
            analyses = (
                list(
                    session.scalars(
                        select(AtsAnalysis)
                        .where(AtsAnalysis.tailoring_id == tailorings[-1].id)
                        .order_by(AtsAnalysis.iteration)
                    )
                )
                if tailorings
                else []
            )
            states[job.source_job_id or str(job.id)] = JobState(
                application=application,
                versions=list(
                    session.scalars(
                        select(CvVersion)
                        .where(CvVersion.application_id == application.id)
                        .order_by(CvVersion.version)
                    )
                ),
                tailorings=tailorings,
                analyses=analyses,
                extractions=list(
                    session.scalars(
                        select(RequirementsExtraction).where(
                            RequirementsExtraction.job_id == job.id
                        )
                    )
                ),
            )
        return states


@pytest.fixture
def analysed(
    discover: Callable[..., Any],
    import_companies: Callable[[], None],
    confirm_master_cv: Callable[[], uuid.UUID],
    analyse: Callable[..., Any],
) -> uuid.UUID:
    """Discovered, analysed (mock) and a confirmed master CV: nova-1001 and sa-4001 are APPLY."""
    import_companies()
    discover()
    master_id = confirm_master_cv()
    analyse()
    return master_id


Answer = Callable[[dict[str, Any]], Any]


class ScriptedProvider:
    """A provider double: mock answers unless a script decides otherwise, recording every call."""

    name = "claude"
    model = "claude-opus-5-5"

    def __init__(self, *, requirements: Answer | None = None, tailoring: Answer | None = None):
        self._requirements = requirements or mock_job_requirements
        self._tailoring = tailoring or mock_cv_tailoring
        self.calls: list[tuple[str, str]] = []  # (task, job title)

    def generate_structured(self, request: LLMRequest, output_type: type[Any]) -> LLMResult[Any]:
        if request.task == "job_requirements":
            title, answer = request.context["posting"]["title"], self._requirements
        else:
            title, answer = request.context["requirements"]["title"], self._tailoring
        self.calls.append((request.task, title))
        return LLMResult(
            output=output_type.model_validate(answer(dict(request.context))),
            provider="claude",
            requested_model=self.model,
            served_model=self.model,
            usage=LLMUsage(input_tokens=1000, output_tokens=300, cache_read_input_tokens=800),
            duration_ms=7,
            request_id="req_scripted",
        )

    def generate_text(self, request: LLMRequest) -> LLMResult[str]:
        raise NotImplementedError

    def health_check(self, *, live: bool = False) -> ProviderHealth:
        return ProviderHealth(ok=True, provider=self.name, model=self.model, detail="scripted")


NOVA, SANDSTONE = "Senior AI Engineer", "AI Research Engineer"


def _when(title: str, error: Exception, otherwise: Answer) -> Answer:
    def answer(context: dict[str, Any]) -> Any:
        posting = context.get("posting") or context["requirements"]
        if posting["title"] == title:
            raise error
        return otherwise(context)

    return answer


def test_the_mock_run_tailors_every_apply_job(
    analysed: uuid.UUID, tailor: Callable[..., Any], jobs_db: sessionmaker[Session]
) -> None:
    run = tailor()

    assert run.status == "SUCCEEDED"
    assert (run.cv_generated, run.jobs_processed) == (2, 2)
    assert run.summary["totals"] == {
        "selected": 2,
        "generated": 2,
        "unchanged": 0,
        "skipped": 0,
        "refused": 0,
        "failed": 0,
    }
    assert run.summary["prompts"] == ["job_requirements.v1", "cv_tailoring.v1"]
    assert (run.summary["scoring_version"], run.summary["target_score"]) == ("ats-score.v1", 95)
    states = _states(jobs_db)

    nova = states["nova-1001"]
    assert nova.application.status.value == "CV_GENERATED"
    assert nova.current is not None
    assert (nova.application.cv_version_id, nova.application.ats_score) == (nova.current.id, 88.3)
    tailoring = nova.latest
    assert (tailoring.baseline_score, tailoring.final_score, tailoring.ceiling_score) == (
        82.3,
        88.3,
        88.3,
    )
    assert tailoring.stop_reason is StopReason.ONLY_UNSUPPORTED_GAINS
    assert (tailoring.iterations_used, tailoring.best_iteration) == (1, 1)
    assert tailoring.status is CallStatus.SUCCEEDED
    assert tailoring.cv_version_id == nova.current.id
    assert [
        (a.iteration, a.document_kind, a.status, a.score, a.selected) for a in nova.analyses
    ] == [
        (0, DocumentKind.MASTER, IterationStatus.SCORED, 82.3, False),
        (1, DocumentKind.TAILORED, IterationStatus.SCORED, 88.3, True),
    ]
    assert nova.analyses[1].feedback["not_listed"] == ["LangGraph", "Kubernetes", "MCP", "FastAPI"]
    for analysis in nova.analyses:
        assert all(keyword["status"] != "UNSUPPORTED" for keyword in analysis.keywords)
    version = nova.current
    assert (version.kind, version.version, version.base_version_id) == (
        CvKind.TAILORED,
        version.version,
        analysed,
    )
    assert version.parser_version == "tailored-cv.v1"
    assert version.evidence["format"] == 1
    assert version.evidence["repairs"] == []
    assert version.structure["experiences"][0]["employer"] == "Acme Analytics"
    assert version.extracted_text.startswith("Alex Example\n")
    assert version.original_filename is None
    gaps = {(gap["kind"], gap["subject"]) for gap in tailoring.gaps}
    assert ("RESPONSIBILITY", "Mentor engineers") in gaps
    assert ("NOT_DEMONSTRATED", "Python") in gaps
    assert [extraction.status for extraction in nova.extractions] == [CallStatus.SUCCEEDED]

    sandstone = states["sa-4001"]
    assert sandstone.application.status.value == "CV_GENERATED"
    assert (sandstone.latest.final_score, sandstone.latest.iterations_used) == (65.7, 0)
    assert [(a.document_kind, a.selected) for a in sandstone.analyses] == [
        (DocumentKind.MASTER, True)  # the master CV is already the best truthful version
    ]
    assert ("MISSING_KEYWORD", "Deep Learning") in {
        (gap["kind"], gap["subject"]) for gap in sandstone.latest.gaps
    }

    assert any(
        "82.3 → 88.3 (target 95, reachable 88.3), only unsupported gains left, "
        "0 unsupported keywords, 1 call(s)" in message
        for _, _, message in run.events
    )
    with jobs_db() as session:
        actions = list(session.scalars(select(AuditLog.action)))
    assert actions.count("cv.tailored") == 2
    assert actions.count("job.requirements_extracted") == 2


def test_review_jobs_are_tailored_when_asked(
    analysed: uuid.UUID, tailor: Callable[..., Any]
) -> None:
    run = tailor(cv_generation_include_review=True)

    assert run.status == "SUCCEEDED"
    assert (run.summary["totals"]["selected"], run.cv_generated) == (7, 7)


def test_an_unchanged_job_is_not_tailored_again_unless_forced(
    analysed: uuid.UUID, tailor: Callable[..., Any], jobs_db: sessionmaker[Session]
) -> None:
    tailor()
    nova_job = _states(jobs_db)["nova-1001"].application.job_id

    again = tailor()  # nothing is QUALIFIED any more
    unchanged = tailor(job_ids=[nova_job])
    forced = tailor(job_ids=[nova_job], force=True)

    assert again.summary["totals"]["selected"] == 0
    assert unchanged.summary["totals"]["unchanged"] == 1
    assert forced.summary["totals"]["generated"] == 1
    nova = _states(jobs_db)["nova-1001"]
    assert [version.status for version in nova.versions] == [
        CvStatus.SUPERSEDED,
        CvStatus.GENERATED,
    ]
    assert nova.application.cv_version_id == nova.versions[-1].id
    assert len(nova.tailorings) == 2
    assert len(nova.extractions) == 1  # the extraction cache was hit


def test_without_a_confirmed_master_cv_nothing_is_tailored(
    discover: Callable[..., Any], import_companies: Callable[[], None], tailor: Callable[..., Any]
) -> None:
    import_companies()
    discover()

    run = tailor()

    assert (run.status, run.cv_generated) == ("SUCCEEDED", 0)
    assert any(
        level == "WARNING" and "No confirmed master CV" in message
        for _, level, message in run.events
    )


def test_jobs_that_are_not_qualified_are_reported(
    analysed: uuid.UUID, tailor: Callable[..., Any], jobs_db: sessionmaker[Session]
) -> None:
    states = _states(jobs_db)
    skip_job = states["dw-2001"].application.job_id  # SKIP: stays ANALYZED

    run = tailor(job_ids=[skip_job, uuid.uuid4()])

    assert run.summary["totals"]["selected"] == 0
    warnings = [message for _, level, message in run.events if level == "WARNING"]
    assert any("ANALYZED; only qualified jobs are tailored" in message for message in warnings)
    assert any("was not found" in message for message in warnings)


def test_a_refused_tailoring_leaves_the_job_qualified(
    analysed: uuid.UUID, tailor: Callable[..., Any], jobs_db: sessionmaker[Session]
) -> None:
    provider = ScriptedProvider(
        tailoring=_when(NOVA, LLMRefusalError("declined", category="cyber"), mock_cv_tailoring)
    )

    run = tailor(provider=provider)

    assert run.status == "SUCCEEDED"  # a refusal is an answer, not a failure
    totals = run.summary["totals"]
    assert (totals["generated"], totals["refused"]) == (1, 1)
    nova = _states(jobs_db)["nova-1001"]
    assert nova.application.status.value == "QUALIFIED"
    assert nova.current is None
    assert (nova.latest.status, nova.latest.error_code) == (CallStatus.REFUSED, "cyber")
    assert nova.latest.stop_reason is StopReason.PROVIDER_ERROR
    assert [analysis.status for analysis in nova.analyses] == [
        IterationStatus.SCORED,
        IterationStatus.REFUSED,
    ]
    with jobs_db() as session:
        assert (
            session.scalar(select(func.count()).where(AuditLog.action == "cv.tailoring_refused"))
            == 1
        )


def test_an_unavailable_extraction_fails_only_that_job(
    analysed: uuid.UUID, tailor: Callable[..., Any], jobs_db: sessionmaker[Session]
) -> None:
    provider = ScriptedProvider(
        requirements=_when(NOVA, LLMUnavailableError("HTTP 529"), mock_job_requirements)
    )

    run = tailor(provider=provider)

    assert run.status == "PARTIAL_SUCCESS"
    totals = run.summary["totals"]
    assert (totals["generated"], totals["failed"]) == (1, 1)
    nova = _states(jobs_db)["nova-1001"]
    assert [e.status for e in nova.extractions] == [CallStatus.FAILED]
    assert nova.tailorings == []
    assert nova.application.status.value == "QUALIFIED"


def test_a_refused_extraction_falls_back_to_deterministic_requirements(
    analysed: uuid.UUID, tailor: Callable[..., Any], jobs_db: sessionmaker[Session]
) -> None:
    provider = ScriptedProvider(
        requirements=_when(NOVA, LLMRefusalError("declined"), mock_job_requirements)
    )

    run = tailor(provider=provider)

    assert run.cv_generated == 2
    nova = _states(jobs_db)["nova-1001"]
    assert [e.status for e in nova.extractions] == [CallStatus.REFUSED]
    assert nova.extractions[0].extraction["degraded"] is True
    assert nova.latest.final_score == 88.3  # the listed skills carry the same keywords
    assert any(
        level == "WARNING" and "deterministic patterns" in message
        for _, level, message in run.events
    )


def test_three_consecutive_failures_stop_the_run(
    analysed: uuid.UUID, tailor: Callable[..., Any]
) -> None:
    def unavailable(context: dict[str, Any]) -> Any:
        raise LLMUnavailableError("HTTP 529")

    provider = ScriptedProvider(requirements=unavailable)

    run = tailor(provider=provider, cv_generation_include_review=True)

    assert run.status == "FAILED"
    assert len(provider.calls) == 3
    assert any("3 consecutive failures" in message for _, _, message in run.events)


def test_a_configuration_error_stops_the_run(
    analysed: uuid.UUID, tailor: Callable[..., Any]
) -> None:
    def rejected(context: dict[str, Any]) -> Any:
        raise LLMConfigError("The Anthropic API rejected the API key (HTTP 401)")

    provider = ScriptedProvider(tailoring=rejected)

    run = tailor(provider=provider)

    assert run.status == "FAILED"
    assert provider.calls[-1] == ("cv_tailoring", NOVA)  # the first tailoring call stops it all
    assert run.cv_generated == 0


def test_an_invented_metric_is_repaired_and_recorded(
    analysed: uuid.UUID, tailor: Callable[..., Any], jobs_db: sessionmaker[Session]
) -> None:
    def embellish(context: dict[str, Any]) -> Any:
        answer = mock_cv_tailoring(context)
        first = answer["experiences"][0]["bullets"][0]
        first["text"] = first["text"].rstrip(".") + ", cutting costs by 40%."
        return answer

    run = tailor(provider=ScriptedProvider(tailoring=embellish))

    assert run.cv_generated == 2
    nova = _states(jobs_db)["nova-1001"]
    assert nova.analyses[1].status is IterationStatus.REPAIRED
    assert nova.analyses[1].repairs_count == 1
    assert nova.current is not None
    repairs = nova.current.evidence["repairs"]
    assert [v["code"] for v in repairs[0]["violations"]] == ["UNSUPPORTED_NUMBER"]
    assert "40%" not in nova.current.extracted_text
    assert nova.application.ats_score == 88.3


def test_logs_never_carry_cv_text_or_prompts(
    analysed: uuid.UUID,
    tailor: Callable[..., Any],
    make_settings: Callable[..., Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(make_settings(log_format="json", log_level="DEBUG"))

    tailor()

    output = capsys.readouterr().out + capsys.readouterr().err
    assert "tailoring.completed" in output
    for secret in ("Designed a RAG platform", "Acme Analytics", "alex.example", "CV tailoring"):
        assert secret not in output
