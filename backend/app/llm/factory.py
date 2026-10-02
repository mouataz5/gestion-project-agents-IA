"""Provider selection from the settings.

* ``LLM_PROVIDER=mock`` → the deterministic mock provider.
* ``LLM_PROVIDER=claude`` with ``ANTHROPIC_API_KEY`` → Claude.
* ``LLM_PROVIDER=claude`` without a key: in ``MOCK_MODE`` the mock provider runs (offline demo;
  every result is labelled mock); in live mode this is a configuration error, reported clearly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.core.config import Settings
from app.llm.base import LLMProvider
from app.llm.claude import ClaudeProvider
from app.llm.errors import LLMConfigError
from app.llm.mock import MOCK_MODEL, MockLLMProvider, Responder

NO_KEY_IN_MOCK_MODE = "no ANTHROPIC_API_KEY in mock mode"
NO_KEY_IN_LIVE_MODE = (
    "LLM_PROVIDER=claude needs ANTHROPIC_API_KEY in live mode (or set LLM_PROVIDER=mock)"
)


@dataclass(frozen=True)
class EffectiveProvider:
    name: str  # "claude" | "mock" | "unavailable"
    model: str
    reason: str | None = None


def effective_llm_provider(settings: Settings) -> EffectiveProvider:
    """Which provider analyses jobs with these settings, and why (no client is created)."""
    if settings.llm_provider == "mock":
        return EffectiveProvider("mock", MOCK_MODEL, "LLM_PROVIDER=mock")
    if settings.anthropic_api_key is not None:
        return EffectiveProvider("claude", settings.claude_model)
    if settings.mock_mode:
        return EffectiveProvider("mock", MOCK_MODEL, NO_KEY_IN_MOCK_MODE)
    return EffectiveProvider("unavailable", settings.claude_model, NO_KEY_IN_LIVE_MODE)


def create_llm_provider(
    settings: Settings, *, mock_responders: Mapping[str, Responder]
) -> LLMProvider:
    effective = effective_llm_provider(settings)
    if effective.name == "mock":
        return MockLLMProvider(responders=mock_responders, reason=effective.reason)
    if effective.name == "unavailable":
        raise LLMConfigError(effective.reason or NO_KEY_IN_LIVE_MODE)
    return ClaudeProvider.from_settings(settings)
