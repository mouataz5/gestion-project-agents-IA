"""Job links from job-alert emails (LinkedIn, Indeed, ATS boards).

n8n forwards the raw email; extraction happens here so it is tested and identical for every
mailbox. Links are canonicalized (tracking removed) and only job-posting URLs are kept, so
"unsubscribe" and settings links are ignored. Nothing is fetched.
"""

from __future__ import annotations

import html
import re

from app.jobs.urls import canonical_url

DEFAULT_LIMIT = 50

_URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]+", re.IGNORECASE)
_JOB_URL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^https://linkedin\.com/jobs/view/\d+$"),
    re.compile(r"^https://([a-z]+\.)?indeed\.[a-z.]+/viewjob\?jk=\w+$"),
    re.compile(r"^https://(boards|job-boards)\.greenhouse\.io/[^/]+/jobs/\d+"),
    re.compile(r"^https://jobs\.(eu\.)?lever\.co/[^/]+/[\w-]+$"),
    re.compile(r"^https://jobs\.ashbyhq\.com/[^/]+/[\w-]+$"),
    re.compile(r"^https://(jobs|careers)\.smartrecruiters\.com/[^/]+/[\w-]+"),
    re.compile(r"^https://[\w.-]+\.myworkdayjobs\.com/.+/job/"),
    re.compile(r"^https://welcometothejungle\.com/[a-z]{2}/companies/[^/]+/jobs/[^/?]+"),
    re.compile(r"[?&]gh_jid=\d+"),
)


def extract_job_links(text: str, *, limit: int = DEFAULT_LIMIT) -> list[str]:
    """Canonical job-posting URLs found in an email body (HTML or plain text), in order."""
    found: list[str] = []
    for match in _URL_RE.finditer(html.unescape(text)):
        url = canonical_url(match.group(0).rstrip(".,;:!?"))
        if url in found or not any(pattern.search(url) for pattern in _JOB_URL_PATTERNS):
            continue
        found.append(url)
        if len(found) >= limit:
            break
    return found
