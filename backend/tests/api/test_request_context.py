import json
import re

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.feature("request-context")

HEX_ID = re.compile(r"[0-9a-f]{32}")


def test_request_id_is_generated(unit_client: TestClient) -> None:
    response = unit_client.get("/api/v1/health/live")
    assert HEX_ID.fullmatch(response.headers["x-request-id"])


def test_valid_incoming_request_id_is_propagated(unit_client: TestClient) -> None:
    response = unit_client.get("/api/v1/health/live", headers={"X-Request-ID": "trace-abc.123"})
    assert response.headers["x-request-id"] == "trace-abc.123"


@pytest.mark.parametrize("bad_id", ["has spaces", "<script>", "x" * 200, "semi;colon"])
def test_invalid_incoming_request_id_is_replaced(unit_client: TestClient, bad_id: str) -> None:
    response = unit_client.get("/api/v1/health/live", headers={"X-Request-ID": bad_id})
    assert HEX_ID.fullmatch(response.headers["x-request-id"])


def test_error_bodies_carry_the_request_id(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/api/v1/system/info")

    assert response.status_code == 401
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_access_log_records_requests_without_credentials(
    unit_client: TestClient, capsys: pytest.CaptureFixture[str], api_token: str
) -> None:
    capsys.readouterr()  # drop startup logs
    unit_client.get("/api/v1/system/info?token=leaky-query-token")

    records = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    access = [r for r in records if r["event"] == "http.request"]
    assert access, "an access log record is written for each request"
    entry = access[-1]
    assert entry["method"] == "GET"
    assert entry["path"] == "/api/v1/system/info"
    assert entry["status_code"] == 200
    assert entry["duration_ms"] >= 0
    assert HEX_ID.fullmatch(entry["request_id"])
    dumped = json.dumps(records)
    assert api_token not in dumped
    assert "leaky-query-token" not in dumped
