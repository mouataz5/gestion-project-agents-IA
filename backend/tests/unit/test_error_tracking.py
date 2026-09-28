import json
import re
from collections.abc import Callable
from typing import Any

import pytest

from app.core.config import Settings
from app.core.error_tracking import LoggingErrorTracker, create_error_tracker
from app.core.logging import configure_logging

pytestmark = pytest.mark.feature("error-tracking")


def _captured(output: str) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    return [record for record in records if record["event"].startswith("error.")]


def test_capture_exception_logs_a_redacted_event(
    make_settings: Callable[..., Settings], capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(make_settings())
    tracker = LoggingErrorTracker()

    try:
        raise ValueError("bad api_key=sk-ant-api03-abcdefghijklmnop1234")
    except ValueError as exc:
        event_id = tracker.capture_exception(exc, context={"password": "p4ss", "job_id": "42"})

    assert re.fullmatch(r"[0-9a-f]{32}", event_id)
    record = _captured(capsys.readouterr().out)[-1]
    assert record["event"] == "error.captured"
    assert record["event_id"] == event_id
    assert record["error_type"] == "ValueError"
    assert record["context"]["job_id"] == "42"
    assert record["context"]["password"] == "[REDACTED]"
    assert "sk-ant-api03-abcdefghijklmnop1234" not in json.dumps(record)


def test_capture_message(
    make_settings: Callable[..., Settings], capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(make_settings())

    event_id = LoggingErrorTracker().capture_message(
        "source returned HTTP 429", level="warning", context={"source": "greenhouse"}
    )

    record = _captured(capsys.readouterr().out)[-1]
    assert record["event"] == "error.message"
    assert record["event_id"] == event_id
    assert record["level"] == "warning"
    assert record["context"] == {"source": "greenhouse"}


def test_factory_returns_the_configured_tracker(make_settings: Callable[..., Settings]) -> None:
    assert isinstance(create_error_tracker(make_settings()), LoggingErrorTracker)
