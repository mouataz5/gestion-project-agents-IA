from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

pytestmark = [pytest.mark.feature("health-checks"), pytest.mark.integration]


def _components(response_json: dict[str, object]) -> dict[str, dict[str, object]]:
    components = response_json["components"]
    assert isinstance(components, list)
    return {component["name"]: component for component in components}


def test_readiness_is_ok_when_all_dependencies_are_up(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    components = _components(body)
    assert set(components) == {"database", "migrations", "redis", "storage"}
    assert all(component["status"] == "ok" for component in components.values())


def test_readiness_is_503_when_redis_is_down(db_settings: Settings) -> None:
    # db_settings points to the real database but to an unreachable Redis
    with TestClient(create_app(db_settings)) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    components = _components(response.json())
    assert components["database"]["status"] == "ok"
    assert components["redis"]["status"] == "down"


def test_readiness_detects_a_database_without_migrations(
    make_settings: Callable[..., Settings], empty_database_url: str, redis_url: str
) -> None:
    settings = make_settings(database_url=empty_database_url, redis_url=redis_url)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    components = _components(response.json())
    assert components["database"]["status"] == "ok"
    assert components["migrations"]["status"] == "down"
