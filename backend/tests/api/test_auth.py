from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.feature("api-auth")

PROTECTED = "/api/v1/system/info"


def test_protected_endpoint_requires_a_token(anonymous_client: TestClient) -> None:
    response = anonymous_client.get(PROTECTED)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(
    "authorization",
    ["Bearer wrong-token", "Basic dXNlcjpwYXNz", "Bearer", "Bearer ", "test-api-token"],
)
def test_invalid_credentials_are_rejected(anonymous_client: TestClient, authorization: str) -> None:
    response = anonymous_client.get(PROTECTED, headers={"Authorization": authorization})
    assert response.status_code == 401


def test_valid_token_is_accepted(unit_client: TestClient) -> None:
    assert unit_client.get(PROTECTED).status_code == 200


def test_bearer_scheme_is_case_insensitive(anonymous_client: TestClient, api_token: str) -> None:
    response = anonymous_client.get(PROTECTED, headers={"Authorization": f"bearer {api_token}"})
    assert response.status_code == 200


def test_health_endpoints_are_public(anonymous_client: TestClient) -> None:
    assert anonymous_client.get("/api/v1/health/live").status_code == 200
    # readiness is public too (it answers 503 here because no database is reachable)
    assert anonymous_client.get("/api/v1/health/ready").status_code in (200, 503)


def test_auth_is_disabled_when_no_token_is_configured(
    make_settings: Callable[..., Settings],
) -> None:
    app = create_app(make_settings(api_auth_token=None))

    with TestClient(app) as client:
        response = client.get(PROTECTED)

    assert response.status_code == 200
    assert response.json()["auth_enabled"] is False
