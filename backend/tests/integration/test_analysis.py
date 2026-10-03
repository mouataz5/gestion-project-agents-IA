"""Job analysis runs: mock provider over the discovered fixtures, status transitions, grounding
guards, idempotency, isolated failures and configuration errors."""

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.analysis.schemas import JobAnalysisOutput, SkillAssessment, VisaClaim
from app.analysis.types import VisaStatus
from app.llm.errors import LLMConfigError, LLMRefusalError, LLMUnavailableError
from app.llm.types import LLMRequest, LLMResult, LLMUsage, ProviderHealth
from app.models import Application, AuditLog, Job, JobAnalysis

pytestmark = [pytest.mark.feature("job-analysis"), pytest.mark.integration]


def _by_source_id(
    jobs_db: sessionmaker[Session],
) -> dict[str, tuple[Job, Application | None, JobAnalysis | None]]:
    with jobs_db() as session:
        result: dict[str, tuple[Job, Application | None, JobAnalysis | None]] = {}
        for job in session.scalars(select(Job)):
            application = session.scalar(select(Application).where(Application.job_id == job.id))
            analysis = session.scalar(
                select(JobAnalysis)
                .where(JobAnalysis.job_id == job.id)
                .order_by(JobAnalysis.created_at.desc())
                .limit(1)
            )
            result[job.source_job_id or str(job.id)] = (job, application, analysis)
        return result


@pytest.fixture
def ready(
    discover: Callable[..., Any],
    import_companies: Callable[[], None],
    confirm_master_cv: Callable[[], Any],
) -> None:
    import_companies()
    discover()  # real clock: the fixtures are relative to "now"
    confirm_master_cv()


class ScriptedProvider:
    """A provider double: answers (or fails) per job, recording every call."""

    name = "claude"
    model = "claude-opus-5-5"

    def __init__(self, script: Callable[[dict[str, Any]], JobAnalysisOutput]) -> None:
        self._script = script
        self.calls: list[str] = []

    def generate_structured(self, request: LLMRequest, output_type: type[Any]) -> LLMResult[Any]:
        job = request.context["job"]
        self.calls.append(job["source_job_id"])
        return LLMResult(
            output=self._script(job),
            provider="claude",
            requested_model=self.model,
            served_model=self.model,
            usage=LLMUsage(input_tokens=1000, output_tokens=200, cache_read_input_tokens=800),
            duration_ms=5,
            request_id="req_scripted",
        )

    def generate_text(self, request: LLMRequest) -> LLMResult[str]:
        raise NotImplementedError

    def health_check(self, *, live: bool = False) -> ProviderHealth:
        return ProviderHealth(ok=True, provider=self.name, model=self.model, detail="scripted")


def _output(**overrides: Any) -> JobAnalysisOutput:
    values: dict[str, Any] = {
        "role_relevance": "HIGH",
        "role_relevance_reason": "Target role.",
        "seniority_fit": "MATCH",
        "seniority_reason": "Experience fits.",
        "skills": [],
        "language_requirements": [],
        "visa": VisaClaim(status=VisaStatus.SPONSORSHIP_UNKNOWN, quote=None, relocation_quote=None),
        "concerns": [],
        "recommendation": "REVIEW",
        "explanation": "Scripted explanation.",
    }
    values.update(overrides)
    return JobAnalysisOutput(**values)


def test_the_mock_analysis_classifies_every_queued_job(
    ready: None, analyse: Callable[..., Any], jobs_db: sessionmaker[Session]
) -> None:
    run = analyse()

    assert run.status == "SUCCEEDED"
    assert (run.jobs_processed, run.jobs_qualified) == (8, 7)
    assert run.summary["totals"] == {
        "selected": 8,
        "analysed": 8,
        "unchanged": 0,
        "refused": 0,
        "failed": 0,
        "apply": 2,
        "review": 5,
        "skip": 1,
    }
    assert run.summary["provider"] == {
        "name": "mock",
        "model": "mock-deterministic-1",
        "reason": "no ANTHROPIC_API_KEY in mock mode",
    }
    assert run.summary["prompt"] == "job_analysis.v1"

    jobs = _by_source_id(jobs_db)
    expected = {
        "nova-1001": ("APPLY", "QUALIFIED", "SPONSORSHIP_CONFIRMED"),
        "sa-4001": ("APPLY", "QUALIFIED", "SPONSORSHIP_CONFIRMED"),
        "dw-2001": ("SKIP", "ANALYZED", "SPONSORSHIP_NOT_AVAILABLE"),
        "nova-1002": ("REVIEW", "QUALIFIED", "SPONSORSHIP_UNKNOWN"),
        "kr-3001": ("REVIEW", "QUALIFIED", "SPONSORSHIP_UNKNOWN"),
        "kr-3002": ("REVIEW", "QUALIFIED", "SPONSORSHIP_UNKNOWN"),
        "feed-03": ("REVIEW", "QUALIFIED", "SPONSORSHIP_LIKELY"),
        "feed-07": ("REVIEW", "QUALIFIED", "SPONSORSHIP_UNKNOWN"),
    }
    for source_job_id, (recommendation, status, visa) in expected.items():
        _, application, analysis = jobs[source_job_id]
        assert application is not None, source_job_id
        assert analysis is not None, source_job_id
        assert analysis.recommendation is not None
        assert (
            analysis.recommendation.value,
            application.status.value,
            analysis.visa_status.value if analysis.visa_status else None,
        ) == (
            recommendation,
            status,
            visa,
        ), source_job_id
        assert application.recommendation is not None
        assert application.recommendation.value == recommendation
        assert application.visa_status == visa
        assert (analysis.provider, analysis.prompt_name, analysis.prompt_version) == (
            "mock",
            "job_analysis",
            1,
        )

    nova = jobs["nova-1001"][2]
    assert nova is not None
    assert (
        nova.visa["evidence"][0]["quote"] == "Visa sponsorship is available for non-EU candidates."
    )
    assert nova.visa["relocation_available"] is True
    assert nova.visa["sponsorship_needed"] is True
    assert [m["job_skill"] for m in nova.relevance["required_skill_matches"]] == [
        "Python",
        "LLMs",
        "RAG",
        "LangGraph",
    ]
    assert nova.relevance["required_coverage"] == 1.0
    assert any("confirmed" in reason for reason in nova.rule_reasons)

    kr = jobs["kr-3001"][2]
    assert kr is not None
    assert kr.visa["relocation_available"] is True
    assert "Computer Vision" in kr.relevance["skill_gaps"]  # declared, but not in the CV
    assert any("sponsorship is not mentioned" in reason.lower() for reason in kr.rule_reasons)

    with jobs_db() as session:
        actions = list(session.scalars(select(AuditLog.action)))
        assert actions.count("analysis.completed") == 8


def test_unchanged_jobs_are_not_analysed_twice(
    ready: None, analyse: Callable[..., Any], jobs_db: sessionmaker[Session]
) -> None:
    analyse()
    nova = _by_source_id(jobs_db)["nova-1001"][0]

    pending = analyse()
    unchanged = analyse(job_ids=[nova.id])
    forced = analyse(job_ids=[nova.id], force=True)

    assert pending.summary["totals"]["selected"] == 0  # nothing is DISCOVERED any more
    assert unchanged.summary["totals"]["unchanged"] == 1
    assert unchanged.jobs_processed == 0
    assert forced.summary["totals"]["analysed"] == 1
    with jobs_db() as session:
        count = session.scalar(
            select(func.count()).select_from(JobAnalysis).where(JobAnalysis.job_id == nova.id)
        )
        assert count == 2


def test_without_a_confirmed_cv_nothing_is_analysed(
    discover: Callable[..., Any],
    import_companies: Callable[[], None],
    analyse: Callable[..., Any],
    jobs_db: sessionmaker[Session],
) -> None:
    import_companies()
    discover()

    run = analyse()

    assert run.status == "SUCCEEDED"
    assert run.jobs_processed == 0
    assert any(
        level == "WARNING" and "confirmed master CV" in message for _, level, message in run.events
    )
    with jobs_db() as session:
        statuses = set(session.scalars(select(Application.status)))
        assert {status.value for status in statuses} == {"DISCOVERED"}


def test_claims_without_evidence_are_removed(
    ready: None, analyse: Callable[..., Any], jobs_db: sessionmaker[Session]
) -> None:
    def script(job: dict[str, Any]) -> JobAnalysisOutput:
        if job["source_job_id"] != "nova-1002":
            return _output()
        return _output(
            skills=[
                # "3+ years in NLP or search": the sample CV has no NLP evidence.
                SkillAssessment(
                    job_skill="NLP",
                    importance="PREFERRED",
                    candidate_skill="Natural Language Processing Expert",
                ),
            ],
            visa=VisaClaim(
                status=VisaStatus.SPONSORSHIP_CONFIRMED,
                quote="We sponsor visas for all hires.",  # not in the posting
                relocation_quote=None,
            ),
            recommendation="APPLY",
        )

    run = analyse(provider=ScriptedProvider(script))

    assert run.status == "SUCCEEDED"
    analysis = _by_source_id(jobs_db)["nova-1002"][2]
    assert analysis is not None
    assert analysis.relevance["unsupported_claims"] == ["NLP → Natural Language Processing Expert"]
    assert "NLP" in analysis.relevance["skill_gaps"]
    # Spark is listed by the posting and demonstrated in the CV: matched without the model.
    assert {
        (match["job_skill"], match["source"])
        for match in analysis.relevance["preferred_skill_matches"]
    } == {("Spark", "EXACT")}
    assert analysis.visa_status is VisaStatus.SPONSORSHIP_UNKNOWN
    assert analysis.visa["discarded_quotes"] == ["We sponsor visas for all hires."]
    assert analysis.llm_recommendation is not None
    assert analysis.llm_recommendation.value == "APPLY"
    assert analysis.recommendation is not None
    assert analysis.recommendation.value == "REVIEW"
    assert (analysis.provider, analysis.served_model, analysis.input_tokens) == (
        "claude",
        "claude-opus-5-5",
        1000,
    )
    assert run.summary["usage"]["cache_read_input_tokens"] == 8 * 800


def test_failures_and_refusals_are_isolated(
    ready: None, analyse: Callable[..., Any], jobs_db: sessionmaker[Session]
) -> None:
    def script(job: dict[str, Any]) -> JobAnalysisOutput:
        if job["source_job_id"] == "nova-1001":
            raise LLMRefusalError("The model declined to answer", category="cyber")
        if job["source_job_id"] == "dw-2001":
            raise LLMUnavailableError("Anthropic API unavailable (HTTP 529)")
        return _output()

    run = analyse(provider=ScriptedProvider(script))

    assert run.status == "PARTIAL_SUCCESS"
    assert run.error_count == 1
    totals = run.summary["totals"]
    assert (totals["analysed"], totals["refused"], totals["failed"]) == (6, 1, 1)
    jobs = _by_source_id(jobs_db)
    refused_app, refused = jobs["nova-1001"][1], jobs["nova-1001"][2]
    failed_app, failed = jobs["dw-2001"][1], jobs["dw-2001"][2]
    assert refused is not None
    assert failed is not None
    assert (refused.status.value, refused.error_code) == ("REFUSED", "cyber")
    assert (failed.status.value, failed.error_code) == ("FAILED", "llm_unavailable")
    assert refused_app is not None
    assert refused_app.status.value == "DISCOVERED"
    assert failed_app is not None
    assert failed_app.status.value == "DISCOVERED"
    assert any(level == "WARNING" and "declined" in message for _, level, message in run.events)


def test_the_run_stops_after_three_consecutive_failures(
    ready: None, analyse: Callable[..., Any], jobs_db: sessionmaker[Session]
) -> None:
    def script(job: dict[str, Any]) -> JobAnalysisOutput:
        raise LLMUnavailableError("Anthropic API unavailable (HTTP 529)")

    provider = ScriptedProvider(script)
    run = analyse(provider=provider)

    assert len(provider.calls) == 3  # the other queued jobs are not attempted
    assert run.status == "FAILED"  # every attempted job failed
    assert (run.jobs_processed, run.summary["totals"]["failed"]) == (0, 3)
    assert any(
        level == "WARNING" and "3 consecutive failures" in message
        for _, level, message in run.events
    )
    with jobs_db() as session:
        statuses = {status.value for status in session.scalars(select(Application.status))}
    assert statuses == {"DISCOVERED"}  # everything stays queued for the next run


def test_a_configuration_error_stops_the_run(ready: None, analyse: Callable[..., Any]) -> None:
    def script(job: dict[str, Any]) -> JobAnalysisOutput:
        raise LLMConfigError("The Anthropic API rejected the API key (HTTP 401)")

    provider = ScriptedProvider(script)
    run = analyse(provider=provider)

    assert run.status == "FAILED"
    assert len(provider.calls) == 1  # no point calling again with a broken configuration
    assert any("rejected the API key" in message for _, _, message in run.events)


def test_live_mode_without_an_api_key_fails_clearly(
    ready: None, analyse: Callable[..., Any]
) -> None:
    run = analyse(mock_mode=False, llm_provider="claude")

    assert run.status == "FAILED"
    assert any("ANTHROPIC_API_KEY" in message for _, _, message in run.events)


def test_the_number_of_jobs_per_run_is_capped(ready: None, analyse: Callable[..., Any]) -> None:
    run = analyse(analysis_max_jobs_per_run=3)

    assert run.summary["totals"]["analysed"] == 3
    assert run.summary["pending_remaining"] == 5
    assert any("wait for the next analysis run" in message for _, _, message in run.events)
