"""Company watchlist: import, CRUD, validation, audit, link with discovered jobs."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.feature("company-watchlist"), pytest.mark.integration]

ORION = {
    "name": "Orion Labs",
    "career_url": "https://orion.example/careers",
    "country_code": "fr",
    "ats_type": "LEVER",
    "board_token": "orion",
    "target_roles": ["AI Engineer"],
    "enabled": True,
}


def _companies(client: TestClient) -> list[dict[str, Any]]:
    response = client.get("/api/v1/companies")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    return body


def test_the_seed_is_imported_once(jobs_client: TestClient) -> None:
    first = jobs_client.post("/api/v1/companies/import")
    second = jobs_client.post("/api/v1/companies/import")

    assert first.status_code == 200, first.text
    assert first.json() == {"created": 5, "updated": 0, "unchanged": 0}
    assert second.json() == {"created": 0, "updated": 0, "unchanged": 5}
    companies = _companies(jobs_client)
    assert [c["name"] for c in companies] == [
        "Datawise Labs",
        "Kappa Robotics",
        "Nova AI",
        "Quiet Corp",
        "Sandstone Analytics",
    ]
    assert all(c["job_count"] == 0 and c["last_checked_at"] is None for c in companies)


def test_companies_can_be_created_updated_and_deleted(jobs_client: TestClient) -> None:
    created = jobs_client.post("/api/v1/companies", json=ORION)
    assert created.status_code == 201, created.text
    company = created.json()
    assert company["country_code"] == "FR"

    updated = jobs_client.patch(
        f"/api/v1/companies/{company['id']}", json={"enabled": False, "notes": "Paused"}
    )
    assert updated.status_code == 200, updated.text
    assert (updated.json()["enabled"], updated.json()["notes"]) == (False, "Paused")
    assert updated.json()["name"] == "Orion Labs"

    deleted = jobs_client.delete(f"/api/v1/companies/{company['id']}")
    assert deleted.status_code == 204
    assert jobs_client.get(f"/api/v1/companies/{company['id']}").status_code == 404
    entries = jobs_client.get(
        "/api/v1/audit-logs", params={"entity_type": "company", "entity_id": company["id"]}
    ).json()["items"]
    assert {e["action"] for e in entries} == {
        "company.created",
        "company.updated",
        "company.deleted",
    }


def test_company_names_are_unique_case_insensitively(jobs_client: TestClient) -> None:
    jobs_client.post("/api/v1/companies", json=ORION)

    duplicate = jobs_client.post("/api/v1/companies", json={**ORION, "name": "orion labs"})

    assert duplicate.status_code == 409


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("career_url", "http://localhost/careers"),
        ("career_url", "not-a-url"),
        ("country_code", "France"),
        ("ats_type", "MYSPACE"),
        ("name", ""),
    ],
)
def test_invalid_companies_are_rejected(jobs_client: TestClient, field: str, value: str) -> None:
    response = jobs_client.post("/api/v1/companies", json={**ORION, field: value})

    assert response.status_code == 422
    assert any(item["loc"][-1] == field for item in response.json()["error"]["details"])


def test_unknown_companies_return_404(jobs_client: TestClient) -> None:
    assert (
        jobs_client.patch(f"/api/v1/companies/{uuid.uuid4()}", json={"enabled": True}).status_code
        == 404
    )


def test_discovery_links_jobs_and_records_checks(
    jobs_client: TestClient, discover: Callable[..., Any]
) -> None:
    jobs_client.post("/api/v1/companies/import")
    discover()

    companies = {c["name"]: c for c in _companies(jobs_client)}

    assert companies["Nova AI"]["job_count"] == 3  # primary records only
    assert companies["Nova AI"]["last_checked_at"] is not None
    assert companies["Quiet Corp"]["last_checked_at"] is None

    nova = companies["Nova AI"]["id"]
    jobs_client.delete(f"/api/v1/companies/{nova}")
    titles = [
        job["title"]
        for job in jobs_client.get("/api/v1/jobs", params={"window": "all", "q": "Nova AI"}).json()[
            "items"
        ]
    ]
    assert "Senior AI Engineer" in titles  # jobs are kept when a company is removed
