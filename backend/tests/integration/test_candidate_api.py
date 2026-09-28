from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.feature("candidate-profile"), pytest.mark.integration]


def _candidate(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/v1/candidate")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def test_first_access_imports_the_profile_from_yaml(candidate_client: TestClient) -> None:
    body = _candidate(candidate_client)

    assert body["slug"] == "default"
    assert body["profile_version"] == 1
    assert body["profile"]["identity"]["full_name"] == "Mouataz Bouazizi"
    assert "application_defaults.notice_period" in body["needs_user_input"]
    assert body["active_master_cv"] is None
    # A second read returns the same candidate, it does not import again.
    assert _candidate(candidate_client)["id"] == body["id"]


def test_profile_updates_increment_the_version_and_are_audited(
    candidate_client: TestClient,
) -> None:
    current = _candidate(candidate_client)
    profile = current["profile"]
    profile["application_defaults"]["notice_period"] = "1 month"
    profile["contact"]["email"] = "alex@example.com"

    response = candidate_client.put(
        "/api/v1/candidate",
        json={"profile_version": current["profile_version"], "profile": profile},
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["profile_version"] == current["profile_version"] + 1
    assert updated["profile"]["application_defaults"]["notice_period"] == "1 month"
    assert "application_defaults.notice_period" not in updated["needs_user_input"]
    assert "contact.email" not in updated["needs_user_input"]
    actions = [e["action"] for e in candidate_client.get("/api/v1/audit-logs").json()["items"]]
    assert "candidate.profile_updated" in actions
    # Audit details never contain the private contact values.
    assert "alex@example.com" not in candidate_client.get("/api/v1/audit-logs").text


def test_stale_profile_versions_are_rejected(candidate_client: TestClient) -> None:
    current = _candidate(candidate_client)
    payload = {"profile_version": current["profile_version"], "profile": current["profile"]}
    assert candidate_client.put("/api/v1/candidate", json=payload).status_code == 200

    stale = candidate_client.put("/api/v1/candidate", json=payload)

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "conflict"


def test_invalid_profiles_are_rejected_with_field_paths(candidate_client: TestClient) -> None:
    current = _candidate(candidate_client)
    profile = current["profile"]
    profile["identity"]["fullname"] = "typo"

    response = candidate_client.put(
        "/api/v1/candidate",
        json={"profile_version": current["profile_version"], "profile": profile},
    )

    assert response.status_code == 422
    assert any(item["loc"][-1] == "fullname" for item in response.json()["error"]["details"])


def test_import_reloads_the_yaml_files(candidate_client: TestClient, candidate_dir: Path) -> None:
    before = _candidate(candidate_client)
    (candidate_dir / "profile.local.yaml").write_text(
        "application_defaults:\n  notice_period: 2 months\n", encoding="utf-8"
    )

    response = candidate_client.post("/api/v1/candidate/import")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["profile_version"] == before["profile_version"] + 1
    assert body["profile"]["application_defaults"]["notice_period"] == "2 months"


def test_invalid_yaml_import_is_reported(candidate_client: TestClient, candidate_dir: Path) -> None:
    _candidate(candidate_client)
    (candidate_dir / "profile.yaml").write_text("identity: {}\n", encoding="utf-8")

    response = candidate_client.post("/api/v1/candidate/import")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_profile"


def test_export_hides_private_fields_unless_requested(candidate_client: TestClient) -> None:
    current = _candidate(candidate_client)
    current["profile"]["contact"]["phone"] = "+216 00 000 000"
    candidate_client.put(
        "/api/v1/candidate",
        json={"profile_version": current["profile_version"], "profile": current["profile"]},
    )

    public = candidate_client.get("/api/v1/candidate/export")
    private = candidate_client.get("/api/v1/candidate/export", params={"include_private": True})

    assert public.status_code == 200
    assert public.headers["content-type"].startswith("application/yaml")
    assert "+216 00 000 000" not in public.text
    assert yaml.safe_load(private.text)["contact"]["phone"] == "+216 00 000 000"
    assert yaml.safe_load(public.text)["identity"]["full_name"] == "Mouataz Bouazizi"


@pytest.mark.feature("candidate-skills")
def test_declared_skills_are_listed_as_not_evidenced_before_any_cv(
    candidate_client: TestClient,
) -> None:
    skills = candidate_client.get("/api/v1/candidate/skills").json()

    by_name = {skill["name"]: skill for skill in skills}
    assert "LangGraph" in by_name
    assert by_name["LangGraph"]["strength"] == "NONE"
    assert by_name["LangGraph"]["sources"] == ["PROFILE_DECLARED"]


@pytest.mark.feature("candidate-skills")
def test_changing_core_skills_refreshes_the_skill_list(candidate_client: TestClient) -> None:
    current = _candidate(candidate_client)
    profile = current["profile"]
    profile["core_skills"] = [*profile["core_skills"], "Rust"]

    candidate_client.put(
        "/api/v1/candidate",
        json={"profile_version": current["profile_version"], "profile": profile},
    )

    skills = {s["name"]: s for s in candidate_client.get("/api/v1/candidate/skills").json()}
    assert skills["Rust"]["strength"] == "NONE"


def test_first_use_import_is_audited(candidate_client: TestClient) -> None:
    candidate = _candidate(candidate_client)

    entries = candidate_client.get(
        "/api/v1/audit-logs", params={"entity_type": "candidate", "entity_id": candidate["id"]}
    ).json()["items"]

    assert [entry["action"] for entry in entries] == ["candidate.imported"]


def test_export_is_a_download(candidate_client: TestClient) -> None:
    response = candidate_client.get("/api/v1/candidate/export")

    assert response.headers["content-disposition"].startswith(
        'attachment; filename="profile-default-'
    )
    assert response.headers["cache-control"] == "no-store"


def test_a_missing_profile_file_is_reported(
    candidate_client: TestClient, candidate_dir: Path
) -> None:
    (candidate_dir / "profile.yaml").unlink()

    response = candidate_client.get("/api/v1/candidate")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "profile_not_found"


def test_candidate_endpoints_require_the_api_token(candidate_settings: Any) -> None:
    from app.main import create_app

    with TestClient(create_app(candidate_settings)) as anonymous:
        assert anonymous.get("/api/v1/candidate").status_code == 401
        assert anonymous.get("/api/v1/candidate/export").status_code == 401
