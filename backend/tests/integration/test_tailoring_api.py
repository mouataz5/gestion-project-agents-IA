"""CV generation API: starting runs, tailored CVs with their evidence, the tailoring on the job page,
the ATS score in the jobs list, statistics and settings."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.tasks import TaskName
from app.main import create_app

pytestmark = [pytest.mark.feature("cv-tailoring"), pytest.mark.integration]


@pytest.fixture
def tailored(
    discover: Callable[..., Any],
    import_companies: Callable[[], None],
    confirm_master_cv: Callable[[], uuid.UUID],
    analyse: Callable[..., Any],
    tailor: Callable[..., Any],
) -> dict[str, Any]:
    import_companies()
    discover()
    master_id = confirm_master_cv()
    analyse()
    run = tailor()
    return {"run_id": str(run.id), "master_id": str(master_id)}


def _job(client: TestClient, title: str) -> dict[str, Any]:
    response = client.get("/api/v1/jobs", params={"window": "all", "q": title, "limit": 100})
    assert response.status_code == 200, response.text
    job = next(item for item in response.json()["items"] if item["title"] == title)
    assert isinstance(job, dict)
    return job


def test_starting_a_cv_generation_enqueues_the_worker_task(
    jobs_client: TestClient, recording_queue: Any
) -> None:
    job_id = str(uuid.uuid4())

    started = jobs_client.post("/api/v1/runs/cv-generation")
    targeted = jobs_client.post(
        "/api/v1/runs/cv-generation", json={"job_ids": [job_id], "force": True}
    )

    assert started.status_code == 202, started.text
    assert targeted.status_code == 202, targeted.text
    first, _second = recording_queue.calls
    assert first.name == TaskName.RUN_CV_GENERATION.value
    assert first.args == (started.json()["run_id"],)
    run = jobs_client.get(f"/api/v1/runs/{targeted.json()['run_id']}").json()
    assert run["run_type"] == "CV_GENERATION"
    assert run["parameters"] == {"job_ids": [job_id], "force": True}


def test_invalid_cv_generation_requests_are_rejected(jobs_client: TestClient) -> None:
    for payload in ({"job_ids": ["not-a-uuid"]}, {"force": True, "target": 100}):
        response = jobs_client.post("/api/v1/runs/cv-generation", json=payload)
        assert response.status_code == 422, payload


def test_an_unavailable_queue_fails_the_run(
    jobs_settings: Settings, unavailable_queue: Any, api_token: str
) -> None:
    app = create_app(jobs_settings, task_queue=unavailable_queue)
    with TestClient(app, headers={"Authorization": f"Bearer {api_token}"}) as client:
        response = client.post("/api/v1/runs/cv-generation")
        run_id = response.json()["error"]["details"]["run_id"]
        run = client.get(f"/api/v1/runs/{run_id}").json()

    assert response.status_code == 503
    assert (run["run_type"], run["status"]) == ("CV_GENERATION", "FAILED")


def test_the_job_page_shows_the_tailoring(
    jobs_client: TestClient, tailored: dict[str, Any]
) -> None:
    job = _job(jobs_client, "Senior AI Engineer")
    detail = jobs_client.get(f"/api/v1/jobs/{job['id']}").json()

    assert (job["ats_score"], job["application_status"]) == (88.3, "CV_GENERATED")
    assert detail["tailored_cv_id"] == job["tailored_cv_id"]
    tailoring = detail["tailoring"]
    assert (tailoring["baseline_score"], tailoring["final_score"], tailoring["ceiling_score"]) == (
        82.3,
        88.3,
        88.3,
    )
    assert tailoring["target_score"] == 95
    assert tailoring["stop_reason"] == "ONLY_UNSUPPORTED_GAINS"
    assert (tailoring["status"], tailoring["is_mock"], tailoring["stale"]) == (
        "SUCCEEDED",
        True,
        False,
    )
    assert tailoring["prompt"] == {"name": "cv_tailoring", "version": 1}
    assert tailoring["run_id"] == tailored["run_id"]
    assert tailoring["cv_version_id"] == job["tailored_cv_id"]
    assert tailoring["assessed_weight"] == 100
    assert tailoring["requirements"]["keywords"][0]["term"] == "Python"
    assert {gap["subject"] for gap in tailoring["gaps"]} >= {"Python", "Mentor engineers"}
    master, best = tailoring["iterations"]
    assert (master["document_kind"], master["score"], master["selected"]) == ("MASTER", 82.3, False)
    assert (best["document_kind"], best["score"], best["selected"]) == ("TAILORED", 88.3, True)
    components = {component["name"]: component["score"] for component in best["components"]}
    assert (components["keywords"], components["skills"]) == (1.0, 0.9167)
    assert all(keyword["status"] != "UNSUPPORTED" for keyword in best["keywords"])


def test_a_job_without_a_tailoring_says_so(
    jobs_client: TestClient, tailored: dict[str, Any]
) -> None:
    job = _job(jobs_client, "Data Scientist, Time Series")  # SKIP: never tailored
    detail = jobs_client.get(f"/api/v1/jobs/{job['id']}").json()

    assert (job["ats_score"], job["tailored_cv_id"], detail["tailoring"]) == (None, None, None)


def test_tailored_cvs_with_their_evidence(
    jobs_client: TestClient, tailored: dict[str, Any]
) -> None:
    job = _job(jobs_client, "Senior AI Engineer")

    listed = jobs_client.get("/api/v1/candidate/tailored-cvs").json()
    for_job = jobs_client.get("/api/v1/candidate/tailored-cvs", params={"job_id": job["id"]})
    detail = jobs_client.get(f"/api/v1/candidate/tailored-cvs/{job['tailored_cv_id']}").json()

    assert {item["job_title"] for item in listed} == {"Senior AI Engineer", "AI Research Engineer"}
    assert [item["id"] for item in for_job.json()] == [job["tailored_cv_id"]]
    assert (detail["status"], detail["ats_score"], detail["stale"]) == ("GENERATED", 88.3, False)
    assert detail["company"] == job["company"]
    assert detail["base_version_id"] == tailored["master_id"]
    assert detail["structure"]["experiences"][0]["employer"] == "Acme Analytics"
    assert detail["extracted_text"].startswith("Alex Example\n")
    entries = {entry["path"]: entry for entry in detail["ledger"]}
    first = entries["experiences.0.bullets.0"]
    assert first["origin"] == "VERBATIM"
    assert first["sources"] == [
        {
            "id": "E1.B1",
            "label": "Experience 1 · bullet 1",
            "text": "Designed a RAG platform with LangGraph and a vector database serving "
            "2,000 users.",
            "path": "experiences.0.bullets.0",
        }
    ]
    assert first["keywords"] == ["RAG", "LangGraph"]
    langgraph = next(
        entry
        for entry in detail["ledger"]
        if entry["path"].startswith("skills.")
        and entry["sources"]
        and entry["sources"][0]["id"] == "E1.B1"
    )
    assert langgraph["origin"] == "SELECTED"
    assert (detail["unused_sources"], detail["repairs"]) == ([], [])
    assert detail["tailoring"]["final_score"] == 88.3


def test_unknown_tailored_cvs_are_not_found(
    jobs_client: TestClient, tailored: dict[str, Any]
) -> None:
    for version_id in (str(uuid.uuid4()), tailored["master_id"]):  # a master CV is not tailored
        response = jobs_client.get(f"/api/v1/candidate/tailored-cvs/{version_id}")
        assert response.status_code == 404, version_id


def test_a_new_master_cv_makes_tailored_cvs_stale(
    jobs_client: TestClient,
    tailored: dict[str, Any],
    confirm_master_cv: Callable[[], uuid.UUID],
) -> None:
    confirm_master_cv()  # a new confirmed version of the master CV

    listed = jobs_client.get("/api/v1/candidate/tailored-cvs").json()
    job = _job(jobs_client, "Senior AI Engineer")
    detail = jobs_client.get(f"/api/v1/jobs/{job['id']}").json()

    assert {item["stale"] for item in listed} == {True}
    assert detail["tailoring"]["stale"] is True


def test_stats_include_cv_generation(jobs_client: TestClient, tailored: dict[str, Any]) -> None:
    stats = jobs_client.get("/api/v1/jobs/stats").json()

    assert stats["cv_generated"] == 2
    assert (stats["awaiting_cv"], stats["awaiting_cv_review"]) == (0, 5)
    assert stats["last_cv_generation"]["id"] == tailored["run_id"]
    assert stats["last_cv_generation"]["cv_generated"] == 2


def test_system_info_reports_the_ats_settings(
    make_settings: Callable[..., Settings], api_token: str
) -> None:
    settings = make_settings(cv_generation_include_review=True)
    with TestClient(
        create_app(settings), headers={"Authorization": f"Bearer {api_token}"}
    ) as client:
        info = client.get("/api/v1/system/info").json()

    config = info["config"]
    assert config["ats_score_weights"]["keywords"] == 30
    assert sum(config["ats_score_weights"].values()) == 100
    assert config["ats_scoring_version"] == "ats-score.v1"
    assert (config["cv_generation_include_review"], config["cv_generation_max_jobs_per_run"]) == (
        True,
        10,
    )
    phase = next(item for item in info["phases"] if item["number"] == 5)
    assert phase["status"] == "in_progress"


def test_tailoring_endpoints_require_the_api_token(jobs_settings: Settings) -> None:
    with TestClient(create_app(jobs_settings)) as anonymous:
        assert anonymous.post("/api/v1/runs/cv-generation").status_code == 401
        assert anonymous.get("/api/v1/candidate/tailored-cvs").status_code == 401
        assert anonymous.get(f"/api/v1/candidate/tailored-cvs/{uuid.uuid4()}").status_code == 401
