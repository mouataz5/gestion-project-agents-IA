"""Jobs API: listing with posting-window filters, detail, stats, tracking, imports, discovery runs."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.tasks import TaskName
from app.main import create_app

pytestmark = [pytest.mark.feature("job-discovery"), pytest.mark.integration]

LINKEDIN = "https://www.linkedin.com/jobs/view/3912345678/?trk=abc&refId=1"
ALERT_EMAIL = """
<p>New jobs for "AI Engineer"</p>
<a href="https://www.linkedin.com/comm/jobs/view/3911111111/?trackingId=x">AI Engineer - Orion</a>
<a href="https://www.linkedin.com/comm/jobs/view/3922222222/?trackingId=y">LLM Engineer - Vega</a>
<a href="https://www.linkedin.com/comm/jobs/alerts?unsubscribe=1">Unsubscribe</a>
"""


@pytest.fixture
def discovered(
    discover: Callable[..., Any], import_companies: Callable[[], None]
) -> dict[str, Any]:
    import_companies()
    run = discover()  # real clock: the fixtures are relative to "now"
    return {"run_id": str(run.id)}


def _jobs(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get("/api/v1/jobs", params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _job_id(client: TestClient, title: str) -> str:
    items = _jobs(client, window="all", include_duplicates=True, q=title, limit=100)["items"]
    return str(next(item["id"] for item in items if item["title"] == title))


@pytest.mark.feature("posting-window")
def test_the_default_list_shows_jobs_posted_in_the_lookback_window(
    jobs_client: TestClient, discovered: dict[str, Any]
) -> None:
    body = _jobs(jobs_client)

    assert body["total"] == 9
    assert body["window"]["lookback_hours"] == 24
    statuses = {item["posting_date_status"] for item in body["items"]}
    assert statuses <= {"KNOWN", "ESTIMATED"}  # unknown dates are never "last 24 h"
    assert all(item["duplicate_of_id"] is None for item in body["items"])
    posted = [item["posted_at"] for item in body["items"]]
    assert posted == sorted(posted, reverse=True)
    assert all(item["window_status"] == "IN_WINDOW" for item in body["items"])


@pytest.mark.feature("posting-window")
def test_filters(jobs_client: TestClient, discovered: dict[str, Any]) -> None:
    assert _jobs(jobs_client, window="all")["total"] == 14
    assert _jobs(jobs_client, window="all", include_duplicates=True)["total"] == 16
    unknown = _jobs(jobs_client, window="all", date_status="UNKNOWN")
    assert [item["company"] for item in unknown["items"]] == ["Polaris Systems"]
    assert _jobs(jobs_client, window="all", source="mock_feed")["total"] == 6
    assert _jobs(jobs_client, window="all", country="FR")["total"] == 6
    assert [item["title"] for item in _jobs(jobs_client, q="computer vision")["items"]] == [
        "Computer Vision Engineer"
    ]
    page = _jobs(jobs_client, limit=2, offset=0)
    assert (len(page["items"]), page["total"]) == (2, 9)
    assert len(_jobs(jobs_client, limit=2, offset=8)["items"]) == 1


def test_job_detail_shows_other_listings_and_pipeline_entries(
    jobs_client: TestClient, discovered: dict[str, Any]
) -> None:
    job_id = _job_id(jobs_client, "Senior AI Engineer")

    detail = jobs_client.get(f"/api/v1/jobs/{job_id}").json()

    assert detail["company"] == "Nova AI"
    assert detail["source"] == "mock_ats"
    assert "<" not in detail["description"]
    assert detail["required_skills"] == ["Python", "LLMs", "RAG", "LangGraph"]
    assert [d["source"] for d in detail["duplicates"]] == ["mock_feed"]
    assert [a["status"] for a in detail["applications"]] == ["DISCOVERED"]
    assert detail["window_status"] == "IN_WINDOW"
    assert jobs_client.get(f"/api/v1/jobs/{uuid.uuid4()}").status_code == 404


def test_stats_summarise_the_discovery(jobs_client: TestClient, discovered: dict[str, Any]) -> None:
    stats = jobs_client.get("/api/v1/jobs/stats").json()

    assert stats["found_today"] == 14
    assert stats["in_window"] == 9
    assert stats["unknown_date"] == 1
    assert stats["duplicates"] == 2
    assert stats["total"] == 14
    assert stats["by_source"] == {"mock_ats": 8, "mock_feed": 6}
    assert stats["last_discovery"]["status"] == "SUCCEEDED"
    assert stats["last_discovery"]["id"] == discovered["run_id"]
    assert stats["awaiting_analysis"] == 8  # every queued job waits for the analysis
    assert (stats["analysed"], stats["last_analysis"]) == (0, None)


def test_unknown_date_jobs_can_be_tracked_manually(
    jobs_client: TestClient, discovered: dict[str, Any]
) -> None:
    job_id = _job_id(jobs_client, "AI Engineer")  # Polaris Systems, date unknown

    tracked = jobs_client.post(f"/api/v1/jobs/{job_id}/track")
    again = jobs_client.post(f"/api/v1/jobs/{job_id}/track")

    assert tracked.status_code == 201, tracked.text
    assert tracked.json()["status"] == "DISCOVERED"
    assert again.status_code == 409


def test_duplicate_listings_cannot_be_tracked(
    jobs_client: TestClient, discovered: dict[str, Any]
) -> None:
    items = _jobs(jobs_client, window="all", include_duplicates=True, source="mock_feed", limit=50)
    duplicate = next(item for item in items["items"] if item["duplicate_of_id"])

    response = jobs_client.post(f"/api/v1/jobs/{duplicate['id']}/track")

    assert response.status_code == 409


@pytest.mark.feature("compliance")
def test_sources_report_their_policy_and_status(
    jobs_client: TestClient, discovered: dict[str, Any]
) -> None:
    sources = {s["key"]: s for s in jobs_client.get("/api/v1/job-sources").json()}

    assert sources["mock_ats"]["runnable"] is True
    assert sources["mock_ats"]["last_status"] == "ok"
    assert sources["greenhouse"]["runnable"] is False
    assert sources["greenhouse"]["skip_reason"]
    assert sources["linkedin"]["policy"] == "manual_only"


def test_starting_a_discovery_enqueues_the_worker_task(
    jobs_client: TestClient, recording_queue: Any
) -> None:
    response = jobs_client.post("/api/v1/runs/discovery")

    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    call = recording_queue.calls[0]
    assert call.name == TaskName.RUN_DISCOVERY.value
    assert call.args == (run_id,)
    run = jobs_client.get(f"/api/v1/runs/{run_id}").json()
    assert run["run_type"] == "DISCOVERY"
    assert run["status"] == "PENDING"


def test_jobs_require_the_api_token(jobs_settings: Settings) -> None:
    with TestClient(create_app(jobs_settings)) as anonymous:
        assert anonymous.get("/api/v1/jobs").status_code == 401
        assert anonymous.post("/api/v1/jobs/import", json={"url": LINKEDIN}).status_code == 401


# --- imports ------------------------------------------------------------------------------------


@pytest.mark.feature("job-import")
def test_a_pasted_linkedin_url_is_imported_once(jobs_client: TestClient) -> None:
    payload = {
        "url": LINKEDIN,
        "title": "AI Engineer",
        "company": "Orion Labs",
        "location": "Paris, France",
        "posted_text": "2 hours ago",
    }

    created = jobs_client.post("/api/v1/jobs/import", json=payload)
    again = jobs_client.post(
        "/api/v1/jobs/import",
        json={**payload, "url": "https://fr.linkedin.com/jobs/view/ai-engineer-3912345678?trk=x"},
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created"] is True
    assert body["application_created"] is True
    job = body["job"]
    assert job["source"] == "manual_import"
    assert job["canonical_url"] == "https://linkedin.com/jobs/view/3912345678"
    assert job["ats_type"] == "LINKEDIN"
    assert job["posting_date_status"] == "ESTIMATED"
    assert again.status_code == 200
    assert again.json()["created"] is False
    assert again.json()["job"]["id"] == job["id"]
    assert again.json()["application_created"] is False
    actions = [e["action"] for e in jobs_client.get("/api/v1/audit-logs").json()["items"]]
    assert actions.count("job.imported") == 2


@pytest.mark.feature("job-import")
def test_importing_a_known_posting_links_to_the_existing_job(
    jobs_client: TestClient, discovered: dict[str, Any]
) -> None:
    primary = _job_id(jobs_client, "Senior AI Engineer")

    response = jobs_client.post(
        "/api/v1/jobs/import",
        json={"url": "https://nova-ai.example/careers/jobs/1001?utm_source=newsletter"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["job"]["id"] == primary
    assert response.json()["duplicate"] is True


@pytest.mark.feature("job-import")
@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"url": "http://127.0.0.1:8000/admin"}, "unsafe_url"),
        ({"url": "file:///etc/passwd"}, "unsafe_url"),
        ({"url": "https://user:secret@example.com/job"}, "unsafe_url"),
        ({"title": "No URL"}, "validation_error"),
    ],
)
def test_unsafe_or_invalid_imports_are_rejected(
    jobs_client: TestClient, payload: dict[str, Any], code: str
) -> None:
    response = jobs_client.post("/api/v1/jobs/import", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert _jobs(jobs_client, window="all")["total"] == 0


@pytest.mark.feature("job-import")
def test_job_alert_emails_import_every_job_link(jobs_client: TestClient) -> None:
    response = jobs_client.post(
        "/api/v1/jobs/import/email",
        json={"subject": "Your job alert", "text": ALERT_EMAIL, "sender": "alerts@linkedin.com"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["links_found"] == 2
    assert [r["job"]["canonical_url"] for r in body["results"]] == [
        "https://linkedin.com/jobs/view/3911111111",
        "https://linkedin.com/jobs/view/3922222222",
    ]
    assert all(r["created"] for r in body["results"])
    assert all(r["job"]["posting_date_status"] == "UNKNOWN" for r in body["results"])
    # Two distinct URL-only imports are not mistaken for duplicates of each other.
    assert _jobs(jobs_client, window="all")["total"] == 2

    empty = jobs_client.post("/api/v1/jobs/import/email", json={"text": "No links."}).json()
    assert empty == {"links_found": 0, "results": []}


@pytest.mark.feature("job-import")
def test_oversized_emails_are_rejected(jobs_client: TestClient) -> None:
    response = jobs_client.post("/api/v1/jobs/import/email", json={"text": "x" * 1_000_001})

    assert response.status_code == 422
