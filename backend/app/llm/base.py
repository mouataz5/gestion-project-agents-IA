"""The provider protocol (architecture §7). Implementations are selected by configuration."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.llm.types import LLMRequest, LLMResult, ProviderHealth

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_structured(
        self, request: LLMRequest, output_type: type[ModelT]
    ) -> LLMResult[ModelT]:
        """Answer validated against ``output_type``; raises ``LLMError`` subclasses."""
        ...

    def generate_text(self, request: LLMRequest) -> LLMResult[str]: ...

    def health_check(self, *, live: bool = False) -> ProviderHealth:
        """Configuration check; ``live`` also contacts the provider (no tokens billed)."""
        ...
