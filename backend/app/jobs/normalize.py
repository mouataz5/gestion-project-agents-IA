"""Normalization helpers shared by every job source (English and French vocabulary)."""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

from app.jobs.types import EmploymentType, RemoteStatus, Seniority


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _pattern(*alternatives: str) -> re.Pattern[str]:
    return re.compile("|".join(alternatives), re.IGNORECASE)


# --- workplace ----------------------------------------------------------------------------------

_HYBRID = _pattern(r"\bhybrid\b", r"\bhybride\b", r"\bteletravail partiel\b")
_REMOTE = _pattern(
    r"\bremote\b",
    r"\bwork from home\b",
    r"\bwfh\b",
    r"\bteletravail\b",
    r"\bdistanciel\b",
    r"\bfully distributed\b",
)
_ONSITE = _pattern(
    r"\bon[- ]?site\b",
    r"\bin[- ]office\b",
    r"\bsur site\b",
    r"\bpresentiel\b",
    r"\boffice[- ]based\b",
)


def detect_remote_status(*texts: str | None) -> RemoteStatus:
    """Hybrid wins over remote ("remote-friendly (hybrid)"), remote over on-site."""
    text = _fold(" ".join(t for t in texts if t))
    if _HYBRID.search(text):
        return RemoteStatus.HYBRID
    if _REMOTE.search(text):
        return RemoteStatus.REMOTE
    if _ONSITE.search(text):
        return RemoteStatus.ONSITE
    return RemoteStatus.UNKNOWN


# --- contract type ------------------------------------------------------------------------------

_EMPLOYMENT: tuple[tuple[re.Pattern[str], EmploymentType], ...] = (
    (
        _pattern(
            r"\bintern(ship)?\b",
            r"\bstage\b",
            r"\balternance\b",
            r"\bapprentice(ship)?\b",
            r"\bwork[- ]study\b",
            r"\bworking student\b",
            r"\bwerkstudent\b",
        ),
        EmploymentType.INTERNSHIP,
    ),
    (
        _pattern(
            r"\bfixed[- ]term\b", r"\btemporary\b", r"\bcdd\b", r"\binterim\b", r"\bseasonal\b"
        ),
        EmploymentType.TEMPORARY,
    ),
    (_pattern(r"\bpart[- ]?time\b", r"\btemps partiel\b"), EmploymentType.PART_TIME),
    (
        _pattern(r"\bcontract(or)?\b", r"\bfreelance\b", r"\bindependent\b", r"\bindependant\b"),
        EmploymentType.CONTRACT,
    ),
    (
        _pattern(r"\bfull[- ]?time\b", r"\bpermanent\b", r"\bcdi\b", r"\btemps plein\b"),
        EmploymentType.FULL_TIME,
    ),
)


def parse_employment_type(value: str | None) -> EmploymentType:
    if not value:
        return EmploymentType.UNKNOWN
    text = _fold(value)
    for pattern, employment_type in _EMPLOYMENT:
        if pattern.search(text):
            return employment_type
    return EmploymentType.UNKNOWN


# --- seniority ----------------------------------------------------------------------------------

_SENIORITY: tuple[tuple[re.Pattern[str], Seniority], ...] = (
    (
        _pattern(r"\bintern\b", r"\binternship\b", r"\bstagiaire\b", r"\bstage\b", r"\balternant"),
        Seniority.INTERN,
    ),
    (
        _pattern(
            r"\bprincipal\b",
            r"\bdistinguished\b",
            r"\bhead of\b",
            r"\bdirector\b",
            r"\bdirecteur\b",
            r"\bvp\b",
            r"\bchief\b",
        ),
        Seniority.PRINCIPAL,
    ),
    (_pattern(r"\blead\b", r"\bstaff\b"), Seniority.LEAD),
    (_pattern(r"\bsenior\b", r"\bsr\b", r"\bconfirme\b", r"\bexperienced\b"), Seniority.SENIOR),
    (
        _pattern(r"\bjunior\b", r"\bjr\b", r"\bgraduate\b", r"\bentry[- ]level\b", r"\bdebutant\b"),
        Seniority.JUNIOR,
    ),
    (_pattern(r"\bmid[- ]?level\b", r"\bintermediate\b", r"\bmid\b"), Seniority.MID),
)


def infer_seniority(title: str) -> Seniority:
    text = _fold(title)
    for pattern, seniority in _SENIORITY:
        if pattern.search(text):
            return seniority
    return Seniority.UNKNOWN


# --- HTML -----------------------------------------------------------------------------------------

_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "tr",
        "table",
        "section",
        "article",
        "header",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "pre",
        "hr",
    }
)
_SKIPPED_TAGS = frozenset({"script", "style", "noscript", "template", "head", "iframe", "svg"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skipping += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
            if tag == "li":
                self.parts.append("• ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skipping = max(0, self._skipping - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Plain text from untrusted HTML: tags, scripts and styles removed, bullets kept.

    Descriptions are stored and displayed as text only, so source HTML can never execute in
    the dashboard.
    """
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def clean_text(text: str | None) -> str:
    """Trim a plain-text field and normalize its line breaks."""
    if not text:
        return ""
    lines = (
        re.sub(r"[ \t\r\f\v]+", " ", line).strip()
        for line in text.replace("\r\n", "\n").split("\n")
    )
    return "\n".join(line for line in lines if line)
