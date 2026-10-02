"""Mock provider (offline, deterministic) and provider selection from the settings."""

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.llm.claude import ClaudeProvider
from app.llm.errors import LLMConfigError, LLMSchemaError
from app.llm.factory import create_llm_provider, effective_llm_provider
from app.llm.mock import MOCK_MODEL, MockLLMProvider
from app.llm.types import LLMRequest, PromptRef, SystemBlock

pytestmark = pytest.mark.feature("llm-provider")


class Echo(BaseModel):
    title: str
    count: int


def _request(task: str = "echo", **context: Any) -> LLMRequest:
    return LLMRequest(
        task=task,
        system=(SystemBlock("rules"),),
        user="job",
        prompt=PromptRef(name="echo", version=1, sha256="0" * 64),
        context=context,
    )


def test_the_mock_provider_is_deterministic_and_validated() -> None:
    provider = MockLLMProvider(responders={"echo": lambda ctx: {"title": ctx["title"], "count": 2}})

    first = provider.generate_structured(_request(title="AI Engineer"), Echo)
    second = provider.generate_structured(_request(title="AI Engineer"), Echo)

    assert first.output == second.output == Echo(title="AI Engineer", count=2)
    assert (first.provider, first.served_model) == ("mock", MOCK_MODEL)
    assert first.usage.input_tokens == 0


def test_the_mock_provider_validates_its_responders() -> None:
    provider = MockLLMProvider(responders={"echo": lambda ctx: {"title": "x"}})

    with pytest.raises(LLMSchemaError):
        provider.generate_structured(_request(), Echo)


def test_the_mock_provider_rejects_unknown_tasks() -> None:
    with pytest.raises(LLMConfigError):
        MockLLMProvider(responders={}).generate_structured(_request("other"), Echo)


def test_the_provider_follows_the_settings(make_settings: Callable[..., Settings]) -> None:
    responders: dict[str, Any] = {}

    mock = create_llm_provider(make_settings(llm_provider="mock"), mock_responders=responders)
    claude = create_llm_provider(
        make_settings(llm_provider="claude", anthropic_api_key="sk-ant-test-key-0123456789"),
        mock_responders=responders,
    )
    offline = create_llm_provider(
        make_settings(llm_provider="claude", mock_mode=True), mock_responders=responders
    )

    assert isinstance(mock, MockLLMProvider)
    assert isinstance(claude, ClaudeProvider)
    assert claude.model == "claude-opus-5-5"  # the default model
    assert isinstance(offline, MockLLMProvider)  # mock mode without a key stays offline


def test_live_mode_without_an_api_key_fails_clearly(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(llm_provider="claude", mock_mode=False)

    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY"):
        create_llm_provider(settings, mock_responders={})


@pytest.mark.parametrize(
    ("overrides", "name", "reason"),
    [
        ({"llm_provider": "mock"}, "mock", "LLM_PROVIDER=mock"),
        ({"llm_provider": "claude", "mock_mode": True}, "mock", "ANTHROPIC_API_KEY"),
        (
            {"llm_provider": "claude", "anthropic_api_key": "sk-ant-test-key-0123456789"},
            "claude",
            None,
        ),
        ({"llm_provider": "claude", "mock_mode": False}, "unavailable", "ANTHROPIC_API_KEY"),
    ],
)
def test_the_effective_provider_is_explained(
    make_settings: Callable[..., Settings],
    overrides: dict[str, Any],
    name: str,
    reason: str | None,
) -> None:
    effective = effective_llm_provider(make_settings(**overrides))

    assert effective.name == name
    if reason is None:
        assert effective.reason is None
    else:
        assert reason in (effective.reason or "")
