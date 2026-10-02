"""LLM failures. Messages are redacted and never contain prompts, answers or credentials."""

from __future__ import annotations

from typing import Any

from app.core.errors import AppError
from app.core.redaction import redact_text


class LLMError(AppError):
    status_code = 502
    code = "llm_error"

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(redact_text(message), details=details)


class LLMConfigError(LLMError):
    """Missing key, rejected key, unknown model, invalid request: retrying will not help."""

    status_code = 503
    code = "llm_not_configured"


class LLMRefusalError(LLMError):
    code = "llm_refusal"

    def __init__(self, message: str, *, category: str | None = None) -> None:
        super().__init__(message, details={"category": category})
        self.category = category


class LLMTruncatedError(LLMError):
    code = "llm_truncated"


class LLMSchemaError(LLMError):
    code = "llm_invalid_output"


class LLMRateLimitError(LLMError):
    status_code = 503
    code = "llm_rate_limited"


class LLMTimeoutError(LLMError):
    status_code = 504
    code = "llm_timeout"


class LLMUnavailableError(LLMError):
    status_code = 503
    code = "llm_unavailable"
