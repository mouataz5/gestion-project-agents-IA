"""Claude through the official ``anthropic`` SDK.

* Structured output: the Pydantic model becomes a JSON schema (``anthropic.transform_schema``) sent
  as ``output_config.format``; the answer is validated *after* checking ``stop_reason``, so a
  refusal or a truncated answer is reported as such, not as a schema error.
* No ``thinking`` field and no sampling parameters: current models think adaptively and reject
  them. Depth (and cost) is set with ``output_config.effort``.
* Refusal fallback: ``fallbacks="default"`` (beta) lets the API re-run a declined request on the
  model Anthropic recommends for that refusal category; the served model is recorded.
* Prompt caching: system blocks flagged ``cache`` carry ``cache_control`` (ephemeral).
* Retries and timeouts are the SDK's (``LLM_MAX_RETRIES``, ``LLM_TIMEOUT_SECONDS``).
* Only metadata is logged: never the prompt, the answer or the key.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal, TypeVar, cast

import anthropic
from anthropic.types.beta import (
    BetaMessage,
    BetaMessageParam,
    BetaOutputConfigParam,
    BetaTextBlockParam,
)
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.logging import get_logger
from app.llm.errors import (
    LLMConfigError,
    LLMError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMSchemaError,
    LLMTimeoutError,
    LLMTruncatedError,
    LLMUnavailableError,
)
from app.llm.types import LLMRequest, LLMResult, LLMUsage, ProviderHealth

logger = get_logger(__name__)
# The SDK logs whole requests (prompts: job postings, candidate facts) at DEBUG.
_sdk_logger = logging.getLogger("anthropic")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
Effort = Literal["low", "medium", "high", "xhigh", "max"]
ModelT = TypeVar("ModelT", bound=BaseModel)


class ClaudeProvider:
    name = "claude"

    def __init__(
        self,
        *,
        client: anthropic.Anthropic,
        model: str,
        effort: str,
        max_tokens: int,
        refusal_fallback: bool,
    ) -> None:
        self._client = client
        self.model = model
        self._effort = effort
        self._max_tokens = max_tokens
        self._refusal_fallback = refusal_fallback
        if _sdk_logger.getEffectiveLevel() < logging.WARNING:  # even before logging is configured
            _sdk_logger.setLevel(logging.WARNING)

    @classmethod
    def from_settings(cls, settings: Settings) -> ClaudeProvider:
        if settings.anthropic_api_key is None:
            raise LLMConfigError(
                "ANTHROPIC_API_KEY is not set: add it to .env, or set LLM_PROVIDER=mock for "
                "offline analysis"
            )
        client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        return cls(
            client=client,
            model=settings.claude_model,
            effort=settings.llm_effort,
            max_tokens=settings.llm_max_tokens,
            refusal_fallback=settings.llm_refusal_fallback,
        )

    # --- public API --------------------------------------------------------------------------
    def generate_structured(
        self, request: LLMRequest, output_type: type[ModelT]
    ) -> LLMResult[ModelT]:
        schema = anthropic.transform_schema(output_type)
        message, duration_ms = self._call(request, schema)
        text = self._text_of(message, request)
        try:
            output = output_type.model_validate_json(text)
        except ValidationError as exc:
            problems = [
                {"loc": ".".join(str(part) for part in error["loc"]), "type": error["type"]}
                for error in exc.errors()
            ]
            # ``from None``: the validation error quotes the answer, which must not leak.
            raise LLMSchemaError(
                "The model's answer does not match the expected structure", details=problems
            ) from None
        return self._result(request, message, output, duration_ms)

    def generate_text(self, request: LLMRequest) -> LLMResult[str]:
        message, duration_ms = self._call(request, None)
        return self._result(request, message, self._text_of(message, request), duration_ms)

    def health_check(self, *, live: bool = False) -> ProviderHealth:
        if not live:
            return ProviderHealth(
                ok=True, provider=self.name, model=self.model, detail="API key configured"
            )
        try:
            self._client.models.retrieve(self.model)
        except LLMError as exc:  # pragma: no cover - defensive
            return ProviderHealth(
                ok=False, provider=self.name, model=self.model, detail=exc.message
            )
        except anthropic.APIError as exc:
            return ProviderHealth(
                ok=False, provider=self.name, model=self.model, detail=self._failure(exc).message
            )
        return ProviderHealth(ok=True, provider=self.name, model=self.model, detail="reachable")

    # --- internals ---------------------------------------------------------------------------
    def _call(self, request: LLMRequest, schema: dict[str, Any] | None) -> tuple[BetaMessage, int]:
        system: list[BetaTextBlockParam] = []
        for block in request.system:
            item: BetaTextBlockParam = {"type": "text", "text": block.text}
            if block.cache:
                item["cache_control"] = {"type": "ephemeral"}
            system.append(item)
        output_config: BetaOutputConfigParam = {
            "effort": cast(Effort, request.effort or self._effort)
        }
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        messages: list[BetaMessageParam] = [{"role": "user", "content": request.user}]
        started = time.monotonic()
        try:
            message = self._client.beta.messages.create(
                model=self.model,
                max_tokens=request.max_tokens or self._max_tokens,
                system=system,
                messages=messages,
                output_config=output_config,
                betas=[FALLBACK_BETA] if self._refusal_fallback else anthropic.omit,
                fallbacks="default" if self._refusal_fallback else anthropic.omit,
            )
        except anthropic.APIError as exc:
            failure = self._failure(exc)
            logger.warning(
                "llm.failed",
                provider=self.name,
                task=request.task,
                prompt=request.prompt.ref,
                model=self.model,
                error_code=failure.code,
                status_code=getattr(exc, "status_code", None),
                request_id=getattr(exc, "request_id", None),
            )
            raise failure from None
        return message, int((time.monotonic() - started) * 1000)

    def _failure(self, exc: anthropic.APIError) -> LLMError:
        """Map SDK errors (most specific first) to clear, redacted failures."""
        if isinstance(exc, anthropic.AuthenticationError):
            return LLMConfigError(
                "The Anthropic API rejected the API key (HTTP 401): check ANTHROPIC_API_KEY"
            )
        if isinstance(exc, anthropic.PermissionDeniedError):
            return LLMConfigError(
                "The API key is not allowed to use this model or feature (HTTP 403)"
            )
        if isinstance(exc, anthropic.NotFoundError):
            return LLMConfigError(
                f"Model {self.model!r} was not found (HTTP 404): check CLAUDE_MODEL"
            )
        if isinstance(exc, anthropic.RateLimitError):
            return LLMRateLimitError("The Anthropic API rate limit was reached (HTTP 429)")
        if isinstance(exc, anthropic.BadRequestError):
            return LLMConfigError(
                f"The Anthropic API rejected the request (HTTP 400): {exc.message}"
            )
        if isinstance(exc, anthropic.APIStatusError):
            if exc.status_code in (413, 422):
                return LLMConfigError(
                    f"The Anthropic API rejected the request (HTTP {exc.status_code})"
                )
            return LLMUnavailableError(f"The Anthropic API is unavailable (HTTP {exc.status_code})")
        if isinstance(exc, anthropic.APITimeoutError):
            return LLMTimeoutError("The Anthropic API did not answer in time")
        if isinstance(exc, anthropic.APIConnectionError):
            return LLMUnavailableError("The Anthropic API could not be reached (network error)")
        return LLMUnavailableError(f"Anthropic API error ({type(exc).__name__})")

    def _text_of(self, message: BetaMessage, request: LLMRequest) -> str:
        if message.stop_reason == "refusal":
            category = getattr(message.stop_details, "category", None)
            logger.warning(
                "llm.refused",
                provider=self.name,
                task=request.task,
                prompt=request.prompt.ref,
                model=message.model,
                category=category,
            )
            raise LLMRefusalError("The model declined to answer this request", category=category)
        if message.stop_reason == "max_tokens":
            raise LLMTruncatedError(
                "The answer was cut off by the max_tokens limit (LLM_MAX_TOKENS)"
            )
        text = "".join(block.text for block in message.content if block.type == "text")
        if not text.strip():
            raise LLMSchemaError("The model returned no answer")
        return text

    def _result(
        self, request: LLMRequest, message: BetaMessage, output: Any, duration_ms: int
    ) -> LLMResult[Any]:
        raw = message.usage
        usage = LLMUsage(
            input_tokens=raw.input_tokens or 0,
            output_tokens=raw.output_tokens or 0,
            cache_read_input_tokens=raw.cache_read_input_tokens or 0,
            cache_creation_input_tokens=raw.cache_creation_input_tokens or 0,
        )
        fallback_used = any(
            getattr(item, "type", None) == "fallback_message" for item in raw.iterations or []
        )
        request_id: str | None = getattr(message, "_request_id", None)
        logger.info(
            "llm.completed",
            provider=self.name,
            task=request.task,
            prompt=request.prompt.ref,
            requested_model=self.model,
            served_model=message.model,
            fallback_used=fallback_used,
            duration_ms=duration_ms,
            request_id=request_id,
            **usage.as_dict(),
        )
        return LLMResult(
            output=output,
            provider=self.name,
            requested_model=self.model,
            served_model=message.model,
            usage=usage,
            duration_ms=duration_ms,
            request_id=request_id,
            fallback_used=fallback_used,
        )
