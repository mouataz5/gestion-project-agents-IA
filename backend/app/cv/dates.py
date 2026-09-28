"""Recognise date ranges in CV lines (English and French).

Supported forms: month names and abbreviations ("Jan 2022", "Sept. 2019", "janv. 2021",
"déc. 2020"), numeric months ("01/2020", "2020-03"), plain years ("2017"), current markers
("Present", "now", "aujourd'hui", "Présent", "en cours"), "Since/Depuis <date>", and
"From/De <date> to/à <date>". Years are limited to 1950-2099 so counts ("2,000 users")
and room numbers are not mistaken for dates.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.cv.models import DateRange, YearMonth

_MONTH_SPELLINGS: dict[int, tuple[str, ...]] = {
    1: ("january", "jan", "janvier", "janv"),
    2: ("february", "feb", "février", "fevrier", "févr", "fevr", "fév", "fev"),
    3: ("march", "mar", "mars"),
    4: ("april", "apr", "avril", "avr"),
    5: ("may", "mai"),
    6: ("june", "jun", "juin"),
    7: ("july", "jul", "juillet", "juil"),
    8: ("august", "aug", "août", "aout", "aoû"),
    9: ("september", "sept", "sep", "septembre"),
    10: ("october", "oct", "octobre"),
    11: ("november", "nov", "novembre"),
    12: ("december", "dec", "décembre", "decembre", "déc"),
}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


_MONTHS: dict[str, int] = {
    _fold(spelling): month
    for month, spellings in _MONTH_SPELLINGS.items()
    for spelling in spellings
}
_MONTH_ALTERNATION = "|".join(
    sorted(
        {re.escape(s) for spellings in _MONTH_SPELLINGS.values() for s in spellings},
        key=len,
        reverse=True,
    )
)

_YEAR = r"(?:19[5-9]\d|20\d\d)"
_NOT_AFTER_LETTER = r"(?<![^\W\d_])"
_NOT_BEFORE_LETTER = r"(?![^\W\d_])"


def _point(prefix: str) -> str:
    """A single date: month name + year, MM/YYYY, YYYY-MM or a plain year."""
    return (
        "(?:"
        rf"{_NOT_AFTER_LETTER}(?P<{prefix}mn>{_MONTH_ALTERNATION})\.?,?\s*[-/]?\s*"
        rf"(?P<{prefix}my>{_YEAR})(?!\d)"
        rf"|(?<![\d/.])(?P<{prefix}nm>0?[1-9]|1[0-2])\s*[/.]\s*(?P<{prefix}ny>{_YEAR})(?!\d)"
        rf"|(?<![\d/.])(?P<{prefix}iy>{_YEAR})-(?P<{prefix}im>0[1-9]|1[0-2])(?!\d|-\d)"
        rf"|(?<![\d/.])(?P<{prefix}y>{_YEAR})(?!\d|[/.]\d)"
        ")"
    )


_CURRENT = (
    rf"{_NOT_AFTER_LETTER}(?P<current>present|current(?:ly)?|now|today|ongoing|to\s+date|date"
    r"|aujourd['’]\s?hui|pr[ée]sent|actuel(?:lement)?|maintenant|en\s+cours|ce\s+jour)"
    rf"{_NOT_BEFORE_LETTER}"
)
_SEPARATOR = (
    r"(?:\s*(?:--?|[–—‒―~→]|->)\s*"
    r"|\s+(?:to|until|till|through|thru|and|au|à|a|et|jusqu['’]\s?(?:à|a|au|en))\s+)"
)
_RANGE_RE = re.compile(
    rf"(?:{_NOT_AFTER_LETTER}(?:from|de|du|between|entre)\s+)?"
    rf"{_point('s_')}{_SEPARATOR}(?:{_point('e_')}|{_CURRENT})",
    re.IGNORECASE,
)
_YEAR_PAIR_RE = re.compile(
    rf"(?<![\d/.])(?P<s_y>{_YEAR})\s*/\s*(?P<e_y>{_YEAR})(?![\d/.])", re.IGNORECASE
)
_SINCE_RE = re.compile(
    rf"{_NOT_AFTER_LETTER}(?:since|depuis|starting|as\s+of)\s+{_point('s_')}", re.IGNORECASE
)
_POINT_RE = re.compile(_point("s_"), re.IGNORECASE)


@dataclass(frozen=True)
class DateMatch:
    """A recognised date range and its position (``start``/``end``) in the searched text."""

    range: DateRange
    start: int
    end: int


def _year_month(match: re.Match[str], prefix: str) -> YearMonth | None:
    groups = match.groupdict()
    if groups.get(f"{prefix}mn"):
        month_name = _fold(groups[f"{prefix}mn"])
        return YearMonth(year=int(groups[f"{prefix}my"]), month=_MONTHS[month_name])
    if groups.get(f"{prefix}nm"):
        return YearMonth(year=int(groups[f"{prefix}ny"]), month=int(groups[f"{prefix}nm"]))
    if groups.get(f"{prefix}iy"):
        return YearMonth(year=int(groups[f"{prefix}iy"]), month=int(groups[f"{prefix}im"]))
    if groups.get(f"{prefix}y"):
        return YearMonth(year=int(groups[f"{prefix}y"]))
    return None


def _to_match(
    match: re.Match[str], *, start: YearMonth | None, end: YearMonth | None, is_current: bool
) -> DateMatch:
    return DateMatch(
        range=DateRange(text=match.group(0), start=start, end=end, is_current=is_current),
        start=match.start(),
        end=match.end(),
    )


def find_date_range(text: str) -> DateMatch | None:
    """Return the most specific date range in ``text`` (ranges first, then single dates)."""
    ranges = [m for m in (_RANGE_RE.search(text), _YEAR_PAIR_RE.search(text)) if m is not None]
    if ranges:
        match = min(ranges, key=lambda m: m.start())
        is_current = bool(match.groupdict().get("current"))
        return _to_match(
            match,
            start=_year_month(match, "s_"),
            end=None if is_current else _year_month(match, "e_"),
            is_current=is_current,
        )
    since = _SINCE_RE.search(text)
    if since is not None:
        return _to_match(since, start=_year_month(since, "s_"), end=None, is_current=True)
    point = _POINT_RE.search(text)
    if point is not None:
        when = _year_month(point, "s_")
        return _to_match(point, start=when, end=when, is_current=False)
    return None
