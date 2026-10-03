"""Analysis API: starting runs, analysis in job detail, list filters, stats, system info."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.tasks import TaskName
from app.main import create_app

pytestmark = [pytest.mark.feature("job-analysis"), pytest.mark.integration]


@pytest.fixture
def analysed(
    discover: Callable[..., Any],
    import_companies: Callable[[], None],
    confirm_master_cv: Callable[[], Any],
    analyse: Callable[..., Any],
) -> dict[str, Any]:
    import_companies()
    discover()
    confirm_master_cv()
    run = analyse()
    return {"run_id": str(run.id)}


def _jobs(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get("/api/v1/jobs", params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _job_id(client: TestClient, title: str) -> str:
    items = _jobs(client, window="all", q=title, limit=100)["items"]
    return str(next(item["id"] for item in items if item["title"] == title))


def test_starting_an_analysis_enqueues_the_worker_task(
    jobs_client: TestClient, recording_queue: Any
) -> None:
    job_id = str(uuid.uuid4())

    started = jobs_client.post("/api/v1/runs/analysis")
    targeted = jobs_client.post("/api/v1/runs/analysis", json={"job_ids": [job_id], "force": True})

    assert started.status_code == 202, started.text
    assert targeted.status_code == 202, targeted.text
    first, _second = recording_queue.calls
    assert first.name == TaskName.RUN_ANALYSIS.value
    assert first.args == (started.json()["run_id"],)
    run = jobs_client.get(f"/api/v1/runs/{targeted.json()['run_id']}").json()
    assert run["run_type"] == "ANALYSIS"
    assert run["parameters"] == {"job_ids": [job_id], "force": True}


def test_invalid_analysis_requests_are_rejected(jobs_client: TestClient) -> None:
    response = jobs_client.post("/api/v1/runs/analysis", json={"job_ids": ["not-a-uuid"]})

    assert response.status_code == 422


def test_the_job_detail_shows_the_analysis(
    jobs_client: TestClient, analysed: dict[str, Any]
) -> None:
    detail = jobs_client.get(f"/api/v1/jobs/{_job_id(jobs_client, 'Senior AI Engineer')}").json()

    analysis = detail["analysis"]
    assert detail["recommendation"] == "APPLY"
    assert detail["visa_status"] == "SPONSORSHIP_CONFIRMED"
    assert analysis["status"] == "SUCCEEDED"
    assert analysis["recommendation"] == "APPLY"
    assert analysis["provider"] == "mock"
    assert analysis["is_mock"] is True
    assert analysis["prompt"] == {"name": "job_analysis", "version": 1}
    assert analysis["run_id"] == analysed["run_id"]
    assert analysis["visa"]["status"] == "SPONSORSHIP_CONFIRMED"
    assert analysis["visa"]["evidence"][0]["quote"] == (
        "Visa sponsorship is available for non-EU candidates."
    )
    assert [m["job_skill"] for m in analysis["relevance"]["required_skill_matches"]] == [
        "Python",
        "LLMs",
        "RAG",
        "LangGraph",
    ]
    assert analysis["rule_reasons"]


def test_jobs_can_be_filtered_by_recommendation_and_visa(
    jobs_client: TestClient, analysed: dict[str, Any]
) -> None:
    apply = _jobs(jobs_client, window="all", recommendation="APPLY")
    no_visa = _jobs(jobs_client, window="all", visa_status="SPONSORSHIP_NOT_AVAILABLE")

    assert {item["title"] for item in apply["items"]} == {
        "Senior AI Engineer",
        "AI Research Engineer",
    }
    assert all(item["recommendation"] == "APPLY" for item in apply["items"])
    assert [item["title"] for item in no_visa["items"]] == ["Data Scientist, Time Series"]
    assert jobs_client.get("/api/v1/jobs", params={"recommendation": "MAYBE"}).status_code == 422


def test_stats_include_the_analysis(jobs_client: TestClient, analysed: dict[str, Any]) -> None:
    stats = jobs_client.get("/api/v1/jobs/stats").json()

    assert stats["analysed"] == 8
    assert stats["qualified"] == 7
    assert stats["by_recommendation"] == {"APPLY": 2, "REVIEW": 5, "SKIP": 1}
    assert stats["last_analysis"]["id"] == analysed["run_id"]
    assert stats["awaiting_analysis"] == 0


def test_system_info_reports_the_llm_without_secrets(
    make_settings: Callable[..., Settings], api_token: str
) -> None:
    settings = make_settings(anthropic_api_key="sk-ant-api03-secret-value-0123456789abcdef")
    with TestClient(
        create_app(settings), headers={"Authorization": f"Bearer {api_token}"}
    ) as client:
        response = client.get("/api/v1/system/info")

    assert response.status_code == 200
    config = response.json()["config"]
    assert config["llm_model"] == "claude-opus-5-5"
    assert config["llm_effort"] == "medium"
    assert config["llm_refusal_fallback"] is True
    assert config["llm_effective_provider"] == "claude"
    assert "sk-ant-api03-secret-value" not in response.text


def test_analysis_endpoints_require_the_api_token(jobs_settings: Settings) -> None:
    with TestClient(create_app(jobs_settings)) as anonymous:
        assert anonymous.post("/api/v1/runs/analysis").status_code == 401
