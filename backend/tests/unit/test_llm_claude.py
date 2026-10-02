"""ClaudeProvider against a fake Messages API (no network): structured output, usage, refusals,
truncation, rate limits, server errors, timeouts, authentication, request shape and logging."""

import json
from collections.abc import Callable
from typing import Any, Literal

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.core.logging import configure_logging
from app.llm.claude import FALLBACK_BETA, ClaudeProvider
from app.llm.errors import (
    LLMConfigError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMSchemaError,
    LLMTimeoutError,
    LLMTruncatedError,
    LLMUnavailableError,
)
from app.llm.types import LLMRequest, PromptRef, SystemBlock

pytestmark = pytest.mark.feature("llm-provider")

API_KEY = "sk-ant-api03-test-0123456789abcdefghijklmnopqrstuvwxyz"
SECRET_JOB_TEXT = "Confidential posting text 7f3a"
SECRET_FACTS = "Candidate facts 91bd"


class Answer(BaseModel):
    verdict: Literal["yes", "no"]
    quote: str | None


REQUEST = LLMRequest(
    task="job_analysis",
    system=(SystemBlock("Rules for the task."), SystemBlock(SECRET_FACTS, cache=True)),
    user=SECRET_JOB_TEXT,
    prompt=PromptRef(name="job_analysis", version=1, sha256="0" * 64),
)


def message(
    text: str | None,
    *,
    stop_reason: str = "end_turn",
    model: str = "claude-opus-5-5",
    stop_details: dict[str, Any] | None = None,
    iterations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    usage: dict[str, Any] = {
        "input_tokens": 1200,
        "output_tokens": 300,
        "cache_read_input_tokens": 900,
        "cache_creation_input_tokens": 50,
    }
    if iterations is not None:
        usage["iterations"] = iterations
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [] if text is None else [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "stop_details": stop_details,
        "usage": usage,
    }


def error(kind: str, text: str) -> dict[str, Any]:
    return {"type": "error", "error": {"type": kind, "message": text}}


class FakeMessagesApi:
    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.responses: list[tuple[int, Any]] = []

    def reply(self, status: int, body: Any) -> None:
        self.responses.append((status, body))

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        status, body = self.responses.pop(0)
        if isinstance(body, Exception):
            raise body
        return httpx2.Response(
            status, json=body, headers={"request-id": "req_test_123", "retry-after-ms": "1"}
        )

    def body(self, index: int = -1) -> dict[str, Any]:
        payload = json.loads(self.requests[index].content)
        assert isinstance(payload, dict)
        return payload


@pytest.fixture
def api() -> FakeMessagesApi:
    return FakeMessagesApi()


@pytest.fixture
def make_provider(api: FakeMessagesApi) -> Callable[..., ClaudeProvider]:
    def _make(*, refusal_fallback: bool = True, max_retries: int = 0) -> ClaudeProvider:
        client = anthropic.Anthropic(
            api_key=API_KEY,
            base_url="https://api.anthropic.test",
            max_retries=max_retries,
            http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(api.handler)),
        )
        return ClaudeProvider(
            client=client,
            model="claude-opus-5-5",
            effort="medium",
            max_tokens=16000,
            refusal_fallback=refusal_fallback,
        )

    return _make


def test_structured_output_is_parsed_and_usage_recorded(
    api: FakeMessagesApi, make_provider: Callable[..., ClaudeProvider]
) -> None:
    api.reply(200, message('{"verdict": "yes", "quote": "We sponsor work visas."}'))

    result = make_provider().generate_structured(REQUEST, Answer)

    assert result.output == Answer(verdict="yes", quote="We sponsor work visas.")
    assert (result.provider, result.requested_model, result.served_model) == (
        "claude",
        "claude-opus-5-5",
        "claude-opus-5-5",
    )
    assert (result.usage.input_tokens, result.usage.output_tokens) == (1200, 300)
    assert (result.usage.cache_read_input_tokens, result.usage.cache_creation_input_tokens) == (
        900,
        50,
    )
    assert result.request_id == "req_test_123"
    assert result.fallback_used is False
    assert result.duration_ms >= 0


def test_the_request_uses_structured_outputs_effort_caching_and_the_fallback(
    api: FakeMessagesApi, make_provider: Callable[..., ClaudeProvider]
) -> None:
    api.reply(200, message('{"verdict": "no", "quote": null}'))

    make_provider().generate_structured(REQUEST, Answer)

    body = api.body()
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] == 16000
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["properties"]["verdict"]["enum"] == [
        "yes",
        "no",
    ]
    assert body["system"][0] == {"type": "text", "text": "Rules for the task."}
    assert body["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"] == [{"role": "user", "content": SECRET_JOB_TEXT}]
    assert body["fallbacks"] == "default"
    assert FALLBACK_BETA in api.requests[-1].headers["anthropic-beta"]
    # Thinking is always on for this model and sampling parameters are rejected: never sent.
    for forbidden in ("thinking", "temperature", "top_p", "top_k", "tool_choice"):
        assert forbidden not in body


def test_the_fallback_can_be_disabled(
    api: FakeMessagesApi, make_provider: Callable[..., ClaudeProvider]
) -> None:
    api.reply(200, message('{"verdict": "no", "quote": null}'))

    make_provider(refusal_fallback=False).generate_structured(REQUEST, Answer)

    assert "fallbacks" not in api.body()
    assert FALLBACK_BETA not in api.requests[-1].headers.get("anthropic-beta", "")


def test_a_fallback_answer_records_the_model_that_served_it(
    api: FakeMessagesApi, make_provider: Callable[..., ClaudeProvider]
) -> None:
    iterations = [
        {"type": "message", "model": "claude-opus-5-5", "input_tokens": 10, "output_tokens": 0},
        {
            "type": "fallback_message",
            "model": "claude-opus-5",
            "input_tokens": 1190,
            "output_tokens": 300,
        },
    ]
    api.reply(
        200,
        message('{"verdict": "yes", "quote": null}', model="claude-opus-5", iterations=iterations),
    )

    result = make_provider().generate_structured(REQUEST, Answer)

    assert result.fallback_used is True
    assert result.served_model == "claude-opus-5"
    assert result.requested_model == "claude-opus-5-5"


@pytest.mark.parametrize("text", ['{"verdict": "maybe", "quote": null}', "not json at all"])
def test_answers_that_do_not_match_the_schema_are_rejected(
    api: FakeMessagesApi, make_provider: Callable[..., ClaudeProvider], text: str
) -> None:
    api.reply(200, message(text))

    with pytest.raises(LLMSchemaError) as caught:
        make_provider().generate_structured(REQUEST, Answer)

    assert text not in str(caught.value.details)  # the model's text is never echoed back


def test_a_refusal_is_reported_with_its_category(
    api: FakeMessagesApi, make_provider: Callable[..., ClaudeProvider]
) -> None:
    details = {"type": "refusal", "category": "cyber", "explanation": "Declined."}
    api.reply(200, message(None, stop_reason="refusal", stop_details=details))

    with pytest.raises(LLMRefusalError) as caught:
        make_provider().generate_structured(REQUEST, Answer)

    assert caught.value.category == "cyber"


def test_a_truncated_answer_is_reported(
    api: FakeMessagesApi, make_provider: Callable[..., ClaudeProvider]
) -> None:
    api.reply(200, message('{"verdict": "ye', stop_reason="max_tokens"))

    with pytest.raises(LLMTruncatedError):
        make_provider().generate_structured(REQUEST, Answer)


def test_rate_limits_are_retried_then_reported(
    api: FakeMessagesApi, make_provider: Callable[..., ClaudeProvider]
) -> None:
    api.reply(429, error("rate_limit_error", "Too many requests"))
    api.reply(429, error("rate_limit_error", "Too many requests"))

    with pytest.raises(LLMRateLimitError):
        make_provider(max_retries=1).generate_structured(REQUEST, Answer)

    assert len(api.requests) == 2


def test_a_transient_server_error_is_retried(
    api: FakeMessagesApi, make_provider: Callable[..., ClaudeProvider]
) -> None:
    api.reply(529, error("overloaded_error", "Overloaded"))
    api.reply(200, message('{"verdict": "yes", "quote": null}'))

    result = make_provider(max_retries=1).generate_structured(REQUEST, Answer)

    assert result.output.verdict == "yes"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (500, error("api_error", "Internal error"), LLMUnavailableError),
        (529, error("overloaded_error", "Overloaded"), LLMUnavailableError),
        (401, error("authentication_error", "invalid x-api-key"), LLMConfigError),
        (403, error("permission_error", "Not allowed"), LLMConfigError),
        (404, error("not_found_error", "model: claude-opus-5-5"), LLMConfigError),
        (400, error("invalid_request_error", "bad schema"), LLMConfigError),
    ],
)
def test_api_errors_map_to_clear_failures(
    api: FakeMessagesApi,
    make_provider: Callable[..., ClaudeProvider],
    status: int,
    body: dict[str, Any],
    expected: type[Exception],
) -> None:
    api.reply(status, body)

    with pytest.raises(expected) as caught:
        make_provider().generate_structured(REQUEST, Answer)

    assert API_KEY not in str(caught.value)


def test_timeouts_are_reported(
    api: FakeMessagesApi, make_provider: Callable[..., ClaudeProvider]
) -> None:
    api.reply(0, httpx2.ReadTimeout("timed out"))

    with pytest.raises(LLMTimeoutError):
        make_provider().generate_structured(REQUEST, Answer)


def test_network_failures_are_reported(
    api: FakeMessagesApi, make_provider: Callable[..., ClaudeProvider]
) -> None:
    api.reply(0, httpx2.ConnectError("connection refused"))

    with pytest.raises(LLMUnavailableError):
        make_provider().generate_structured(REQUEST, Answer)


def test_prompts_answers_and_the_key_never_reach_the_logs(
    api: FakeMessagesApi,
    make_provider: Callable[..., ClaudeProvider],
    make_settings: Callable[..., Settings],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    configure_logging(make_settings(log_format="json", log_level="DEBUG"))
    caplog.set_level("DEBUG")
    api.reply(200, message('{"verdict": "yes", "quote": "Answer text 55c2"}'))

    make_provider().generate_structured(REQUEST, Answer)

    output = capsys.readouterr().out + caplog.text
    assert "llm.completed" in output  # metadata is logged
    for private in (SECRET_JOB_TEXT, SECRET_FACTS, "Answer text 55c2", API_KEY):
        assert private not in output


def test_health_check_does_not_call_the_api_unless_asked(
    api: FakeMessagesApi, make_provider: Callable[..., ClaudeProvider]
) -> None:
    provider = make_provider()

    assert provider.health_check().ok is True
    assert api.requests == []

    api.reply(
        200,
        {
            "type": "model",
            "id": "claude-opus-5-5",
            "display_name": "Claude",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )
    assert provider.health_check(live=True).ok is True
    api.reply(404, error("not_found_error", "model not found"))
    assert provider.health_check(live=True).ok is False
