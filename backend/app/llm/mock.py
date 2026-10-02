"""Deterministic offline provider (tests, and mock mode without an API key).

Each task has a *responder* computing the answer from the structured inputs the prompt was
rendered from (``LLMRequest.context``). Results are labelled ``mock`` wherever they are shown.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.errors import LLMConfigError, LLMSchemaError
from app.llm.types import LLMRequest, LLMResult, LLMUsage, ProviderHealth

MOCK_MODEL = "mock-deterministic-1"
Responder = Callable[[Mapping[str, Any]], Any]
ModelT = TypeVar("ModelT", bound=BaseModel)


class MockLLMProvider:
    name = "mock"

    def __init__(
        self,
        *,
        responders: Mapping[str, Responder],
        model: str = MOCK_MODEL,
        reason: str | None = None,
    ) -> None:
        self._responders = dict(responders)
        self.model = model
        self.reason = reason  # why the mock provider is used (shown in runs)

    def _answer(self, request: LLMRequest) -> Any:
        responder = self._responders.get(request.task)
        if responder is None:
            raise LLMConfigError(f"The mock provider cannot answer task {request.task!r}")
        return responder(request.context)

    def generate_structured(
        self, request: LLMRequest, output_type: type[ModelT]
    ) -> LLMResult[ModelT]:
        try:
            output = output_type.model_validate(self._answer(request))
        except ValidationError as exc:
            raise LLMSchemaError(
                f"The mock answer for {request.task!r} does not match the expected structure",
                details=[
                    {"loc": ".".join(map(str, e["loc"])), "type": e["type"]} for e in exc.errors()
                ],
            ) from None
        return self._result(output)

    def generate_text(self, request: LLMRequest) -> LLMResult[str]:
        return self._result(str(self._answer(request)))

    def health_check(self, *, live: bool = False) -> ProviderHealth:
        return ProviderHealth(
            ok=True, provider=self.name, model=self.model, detail=self.reason or "offline mock"
        )

    def _result(self, output: Any) -> LLMResult[Any]:
        return LLMResult(
            output=output,
            provider=self.name,
            requested_model=self.model,
            served_model=self.model,
            usage=LLMUsage(),
            duration_ms=0,
        )
