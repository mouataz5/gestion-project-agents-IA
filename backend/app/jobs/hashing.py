"""Content hash: the same posting published by several sources has the same hash."""

from __future__ import annotations

import hashlib
import re
import unicodedata


def normalize_text(text: str | None) -> str:
    """Unicode NFKC, case-folded, whitespace collapsed (formatting differences are ignored)."""
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", folded).strip()


def content_hash(*, company: str, title: str, location: str | None, description: str | None) -> str:
    """SHA-256 of the normalized company, title, location and description."""
    material = "\x1f".join(normalize_text(part) for part in (company, title, location, description))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
