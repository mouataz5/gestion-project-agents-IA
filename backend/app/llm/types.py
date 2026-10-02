"""Requests to and results from an LLM provider."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class SystemBlock:
    """One block of the system prompt. ``cache`` marks the end of the cacheable prefix: keep
    cached blocks byte-identical between requests (no timestamps, sorted JSON)."""

    text: str
    cache: bool = False


@dataclass(frozen=True)
class PromptRef:
    name: str
    version: int
    sha256: str

    @property
    def ref(self) -> str:
        return f"{self.name}.v{self.version}"


@dataclass(frozen=True)
class LLMRequest:
    task: str
    system: tuple[SystemBlock, ...]
    user: str
    prompt: PromptRef
    max_tokens: int | None = None
    effort: str | None = None
    # Structured inputs the prompt was rendered from. Never sent to the API: the mock provider
    # answers from them, and tests use them to identify the request.
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def __add__(self, other: LLMUsage) -> LLMUsage:
        return LLMUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
            cache_creation_input_tokens=(
                self.cache_creation_input_tokens + other.cache_creation_input_tokens
            ),
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
        }


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    output: T
    provider: str
    requested_model: str
    served_model: str
    usage: LLMUsage
    duration_ms: int
    request_id: str | None = None
    fallback_used: bool = False  # a refusal fallback model produced the answer


@dataclass(frozen=True)
class ProviderHealth:
    ok: bool
    provider: str
    model: str
    detail: str
