import pytest
from fastapi.testclient import TestClient

from app import __version__

pytestmark = pytest.mark.feature("system-info")


def test_system_info_reports_the_safe_configuration(unit_client: TestClient) -> None:
    response = unit_client.get("/api/v1/system/info")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == __version__
    assert body["environment"] == "test"
    assert body["mock_mode"] is True
    assert body["auto_submit"] is False
    assert body["auth_enabled"] is True
    assert body["config"]["job_lookback_hours"] == 24
    assert body["config"]["ats_target_score"] == 95
    assert body["config"]["ats_max_iterations"] == 3
    assert body["config"]["daily_run_time"] == "08:00"
    assert body["config"]["timezone"] == "Africa/Tunis"
    assert body["config"]["llm_provider"] == "claude"
    assert body["config"]["llm_model"] == "claude-opus-5-5"
    assert body["config"]["llm_effort"] == "medium"
    assert body["config"]["llm_refusal_fallback"] is True
    assert body["config"]["analysis_max_jobs_per_run"] == 25
    # Mock mode without an API key: analysis runs offline, and the page says why.
    assert body["config"]["llm_effective_provider"] == "mock"
    assert "ANTHROPIC_API_KEY" in body["config"]["llm_effective_reason"]


def test_system_info_reports_secrets_only_as_booleans(
    unit_client: TestClient, api_token: str
) -> None:
    response = unit_client.get("/api/v1/system/info")

    secrets = response.json()["secrets"]
    assert secrets["api_auth_token"] is True
    assert secrets["anthropic_api_key"] is False
    assert all(isinstance(value, bool) for value in secrets.values())
    assert api_token not in response.text


def test_system_info_lists_the_roadmap(unit_client: TestClient) -> None:
    phases = unit_client.get("/api/v1/system/info").json()["phases"]

    assert [phase["number"] for phase in phases] == list(range(1, 12))
    assert phases[0]["name"] == "Foundation"
    assert phases[0]["status"] == "done"
    assert all(phase["status"] in {"done", "in_progress", "planned"} for phase in phases)


def test_system_info_surfaces_security_warnings(unit_client: TestClient) -> None:
    warnings = unit_client.get("/api/v1/system/info").json()["warnings"]
    assert any("ENCRYPTION_KEY" in warning for warning in warnings)
