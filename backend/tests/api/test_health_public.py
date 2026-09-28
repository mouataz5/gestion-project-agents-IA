import pytest
from fastapi.testclient import TestClient

from app import __version__

pytestmark = pytest.mark.feature("health-checks")


def test_liveness(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "backend", "version": __version__}


def test_readiness_is_503_when_the_database_is_unreachable(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/api/v1/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "down"
    components = {c["name"]: c for c in body["components"]}
    assert set(components) == {"database", "migrations", "redis", "storage"}
    assert components["database"]["status"] == "down"
    assert components["storage"]["status"] == "ok"


def test_public_readiness_never_exposes_failure_details(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/api/v1/health/ready")

    assert all(component["detail"] is None for component in response.json()["components"])
    assert "jobagent" not in response.text
    assert "127.0.0.1" not in response.text


def test_root_describes_the_service(anonymous_client: TestClient) -> None:
    body = anonymous_client.get("/").json()
    assert body["docs"] == "/docs"
    assert body["health"] == "/api/v1/health/live"
