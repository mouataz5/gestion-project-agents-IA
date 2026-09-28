"""Secret redaction for logs, run events, audit entries and error reports.

Two complementary mechanisms:

* **Key-based**: values stored under sensitive keys (``password``, ``access_token``,
  ``X-Api-Key``, ``cookie``, ...) are replaced entirely, at any nesting depth.
* **Value-based**: free text is scanned for secrets that can appear anywhere (Bearer tokens,
  API keys, credentials embedded in URLs, JWTs, bot tokens, ``password=...`` pairs).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from itertools import pairwise
from typing import Any

REDACTED = "[REDACTED]"
TRUNCATED = "[TRUNCATED]"
MAX_DEPTH = 12

# A key is split into lower-case word segments ("X-Api-Key" -> x, api, key; "accessToken" ->
# access, token). It is sensitive when one segment, or a pair of consecutive segments, is listed.
_SENSITIVE_SEGMENTS = frozenset(
    {
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "dsn",
        "passphrase",
        "passwd",
        "password",
        "pwd",
        "secret",
        "session",
        "signature",
        "token",
    }
)
_SENSITIVE_PAIRS = frozenset(
    {("api", "key"), ("access", "key"), ("private", "key"), ("signing", "key"), ("auth", "header")}
)
_KEY_SEGMENTS = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")

_CREDENTIAL_CHARS = r"[A-Za-z0-9._~+/=-]"
_VALUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # "Authorization: <scheme> <credentials>" anywhere in text
    (
        re.compile(
            r"(?P<key>\bauthorization[\"']?\s*[:=]\s*[\"']?)(?:(?:bearer|basic)\s+)?[^\s,;\"']+",
            re.IGNORECASE,
        ),
        r"\g<key>" + REDACTED,
    ),
    # Bare "Bearer <token>" / "Basic <credentials>" (token-looking: long, or containing a digit)
    (
        re.compile(
            rf"\b(?P<scheme>Bearer|Basic)\s+(?:{_CREDENTIAL_CHARS}{{20,}}|(?={_CREDENTIAL_CHARS}*\d){_CREDENTIAL_CHARS}{{8,}})",
            re.IGNORECASE,
        ),
        r"\g<scheme> " + REDACTED,
    ),
    # Credentials embedded in URLs: scheme://user:password@host
    (
        re.compile(r"(?P<prefix>\b[A-Za-z][A-Za-z0-9+.-]*://[^:/@\s]*:)[^@/\s]+@"),
        r"\g<prefix>" + REDACTED + "@",
    ),
    # Anthropic / OpenAI style API keys
    (re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{12,}"), REDACTED),
    # GitHub tokens
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), REDACTED),
    # AWS access key ids
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    # JSON Web Tokens
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"), REDACTED),
    # Telegram bot tokens
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}"), REDACTED),
    # key=value / key: value pairs whose key names a secret (query strings, DSN options, messages)
    (
        re.compile(
            r"(?P<key>\b[\w-]*(?:password|passwd|pwd|secret|token|api[_-]?key|apikey)\b[\"']?\s*[=:]\s*[\"']?)"
            r"[^\s&;,\"']+",
            re.IGNORECASE,
        ),
        r"\g<key>" + REDACTED,
    ),
)


def is_sensitive_key(key: str) -> bool:
    """True when a mapping key names a secret (e.g. ``password``, ``X-Api-Key``, ``Cookie``)."""
    segments = [segment.lower() for segment in _KEY_SEGMENTS.findall(key)]
    if any(segment in _SENSITIVE_SEGMENTS for segment in segments):
        return True
    return any(pair in _SENSITIVE_PAIRS for pair in pairwise(segments))


def redact_text(text: str) -> str:
    """Replace secrets that appear inside free text."""
    for pattern, replacement in _VALUE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Return a redacted deep copy of ``value`` (mappings, sequences, sets and strings)."""
    if _depth > MAX_DEPTH:
        return TRUNCATED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and is_sensitive_key(key):
                result[key] = REDACTED
            else:
                result[key] = redact(item, _depth=_depth + 1)
        return result
    if isinstance(value, list):
        return [redact(item, _depth=_depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item, _depth=_depth + 1) for item in value)
    if isinstance(value, set | frozenset):
        return {redact(item, _depth=_depth + 1) for item in value}
    return value
