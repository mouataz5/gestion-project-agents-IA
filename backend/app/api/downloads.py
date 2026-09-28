"""Helpers for file download responses."""

from __future__ import annotations

import unicodedata
from urllib.parse import quote


def content_disposition(filename: str) -> str:
    """``attachment`` header value; non-ASCII names use RFC 6266 ``filename*`` encoding."""
    ascii_name = (
        unicodedata.normalize("NFKD", filename)
        .encode("ascii", "ignore")
        .decode("ascii")
        .replace('"', "")
        .replace("\\", "")
        .strip()
    )
    if ascii_name == filename:
        return f'attachment; filename="{filename}"'
    fallback = ascii_name or "download"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"
