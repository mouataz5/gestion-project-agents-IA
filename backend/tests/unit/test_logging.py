import json
import logging
from collections.abc import Callable
from typing import Any

import pytest
import structlog

from app.core.config import Settings
from app.core.logging import configure_logging, get_logger

pytestmark = pytest.mark.feature("structured-logging")


def _records(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


def test_json_logs_contain_standard_fields(
    make_settings: Callable[..., Settings], capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(make_settings(log_format="json"), component="api")
    structlog.contextvars.bind_contextvars(request_id="req-123")

    get_logger("tests.logging").info("job.discovered", count=3)

    record = _records(capsys.readouterr().out)[-1]
    assert record["event"] == "job.discovered"
    assert record["count"] == 3
    assert record["level"] == "info"
    assert record["logger"] == "tests.logging"
    assert record["request_id"] == "req-123"
    assert record["component"] == "api"
    assert record["timestamp"].endswith("Z")


def test_secrets_never_reach_log_output(
    make_settings: Callable[..., Settings], capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(make_settings(log_format="json"))
    secrets = ("hunter2", "abcdef1234567890", "sk-ant-api03-verysecretvalue123456")

    get_logger("tests").info(
        "login attempt with password=hunter2",
        password="hunter2",
        headers={"Authorization": "Bearer abcdef1234567890"},
        api_key="sk-ant-api03-verysecretvalue123456",
    )

    output = capsys.readouterr().out
    for secret in secrets:
        assert secret not in output
    assert "[REDACTED]" in output


def test_exception_messages_are_redacted(
    make_settings: Callable[..., Settings], capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(make_settings(log_format="json"))

    try:
        raise RuntimeError("could not connect to postgresql://app:topsecret@db/app")
    except RuntimeError:
        get_logger("tests").exception("db.error")

    output = capsys.readouterr().out
    assert "topsecret" not in output
    assert "RuntimeError" in output


def test_stdlib_loggers_are_rendered_and_redacted(
    make_settings: Callable[..., Settings], capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(make_settings(log_format="json"))

    logging.getLogger("uvicorn.error").warning("server started with token=abc123")

    record = _records(capsys.readouterr().out)[-1]
    assert record["logger"] == "uvicorn.error"
    assert record["level"] == "warning"
    assert "abc123" not in json.dumps(record)


def test_log_level_filters_lower_levels(
    make_settings: Callable[..., Settings], capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(make_settings(log_format="json", log_level="WARNING"))

    get_logger("tests").info("hidden")
    get_logger("tests").warning("shown")

    events = [record["event"] for record in _records(capsys.readouterr().out)]
    assert "shown" in events
    assert "hidden" not in events


def test_configure_logging_is_idempotent(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    configure_logging(settings)
    configure_logging(settings)

    ours = [h for h in logging.getLogger().handlers if getattr(h, "job_agent_handler", False)]
    assert len(ours) == 1


def test_console_format_is_human_readable(
    make_settings: Callable[..., Settings], capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(make_settings(log_format="console"))

    get_logger("tests").info("job.discovered", password="hunter2")

    output = capsys.readouterr().out
    assert "job.discovered" in output
    assert not output.lstrip().startswith("{")
    assert "hunter2" not in output
