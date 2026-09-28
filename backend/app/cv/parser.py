"""Deterministic CV parser: document lines -> structured draft (``ParsedCV``) with warnings.

Pipeline: read lines with layout hints -> split into sections by heading -> segment
experience/education/project sections into entries -> assign header parts to fields
(title, employer, location, dates) -> parse skills, languages, certifications -> extract
contact details from the header -> compute warnings for the user to review.

Every value is a substring of the extracted text: the parser trims, splits and classifies,
but never rewrites or generates text. When unsure it keeps text in ``details`` or
``other_sections`` rather than dropping it.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.cv.dates import DateMatch, find_date_range
from app.cv.errors import NoTextFoundError, TooManyPagesError
from app.cv.files import CvFileKind
from app.cv.models import (
    ContactInfo,
    DateRange,
    EducationEntry,
    ExperienceEntry,
    OtherSection,
    ParsedCV,
    ProjectEntry,
    SkillItem,
)
from app.cv.readers import Line, read_docx, read_pdf
from app.cv.sections import SectionKind, match_section

PARSER_VERSION = "1.0"
MAX_PAGES = 10
MAX_LINES = 3000
_MAX_FIELD_CHARS = 300
_MAX_SKILL_CHARS = 100

# ---------------------------------------------------------------------------------------------
# Vocabularies (English and French)
# ---------------------------------------------------------------------------------------------

_ROLE_RE = re.compile(
    r"(?<![^\W\d_])(?:engineer|developer|scientist|analyst|manager|intern|internship|lead|"
    r"consultant|researcher|architect|specialist|officer|director|head|designer|administrator|"
    r"technician|assistant|associate|professor|lecturer|teacher|tutor|founder|co-founder|cto|"
    r"ceo|cio|vp|president|freelance|freelancer|contractor|trainee|apprentice|programmer|"
    r"coordinator|advisor|expert|owner|devops|sre|mlops|ing[ée]nieure?|d[ée]veloppeuse?|"
    r"stagiaire|stage|alternante?|alternance|chef|responsable|directeur|directrice|chercheur|"
    r"chercheuse|doctorant|doctorante|analyste|technicien|technicienne|enseignant|enseignante|"
    r"fondateur|fondatrice|g[ée]rant|g[ée]rante|charg[ée]e?)(?![^\W\d_])",
    re.IGNORECASE,
)
_DEGREE_RE = re.compile(
    r"(?<![^\W\d_])(?:m\.?sc|b\.?sc|b\.?a|m\.?a|mba|ph\.?d|doctorate|doctorat|masters?|"
    r"master['’]s|mast[èe]re|bachelor|bachelor['’]s|licence|diploma|dipl[ôo]me|degree|"
    r"ing[ée]nieur|engineering|baccalaur[ée]at|bac|bts|dut|cycle|pr[ée]pa|preparatory|"
    r"certificate|high\s+school)(?![^\W\d_])",
    re.IGNORECASE,
)
_INSTITUTION_RE = re.compile(
    r"(?<![^\W\d_])(?:university|universit[ée]|school|[ée]cole|institute|institut|college|"
    r"coll[èe]ge|faculty|facult[ée]|academy|acad[ée]mie|polytechnique|polytechnic|"
    r"lyc[ée]e|campus)(?![^\W\d_])",
    re.IGNORECASE,
)
_COMPANY_SUFFIX_RE = re.compile(
    r"(?:inc|ltd|llc|llp|plc|gmbh|ag|sa|sas|sarl|suarl|bv|nv|srl|spa|co|corp|limited)\.?",
    re.IGNORECASE,
)
_REMOTE_WORDS = frozenset(
    {"remote", "hybrid", "on-site", "onsite", "full remote", "teletravail", "a distance"}
)
_COUNTRIES = frozenset(
    {
        "algeria",
        "algerie",
        "australia",
        "australie",
        "austria",
        "autriche",
        "bahrain",
        "belgium",
        "belgique",
        "canada",
        "china",
        "chine",
        "czech republic",
        "denmark",
        "danemark",
        "egypt",
        "egypte",
        "estonia",
        "finland",
        "finlande",
        "france",
        "germany",
        "allemagne",
        "greece",
        "grece",
        "india",
        "inde",
        "ireland",
        "irlande",
        "italy",
        "italie",
        "japan",
        "japon",
        "jordan",
        "jordanie",
        "kuwait",
        "koweit",
        "lebanon",
        "liban",
        "libya",
        "libye",
        "luxembourg",
        "malta",
        "malte",
        "morocco",
        "maroc",
        "netherlands",
        "pays-bas",
        "pays bas",
        "the netherlands",
        "new zealand",
        "norway",
        "norvege",
        "oman",
        "poland",
        "pologne",
        "portugal",
        "qatar",
        "romania",
        "roumanie",
        "saudi arabia",
        "ksa",
        "arabie saoudite",
        "singapore",
        "singapour",
        "spain",
        "espagne",
        "sweden",
        "suede",
        "switzerland",
        "suisse",
        "tunisia",
        "tunisie",
        "turkey",
        "turquie",
        "uae",
        "united arab emirates",
        "emirats arabes unis",
        "uk",
        "united kingdom",
        "royaume-uni",
        "england",
        "usa",
        "us",
        "united states",
        "etats-unis",
    }
)
_EN_WORDS = frozenset(
    [
        "and",
        "the",
        "of",
        "with",
        "for",
        "in",
        "on",
        "to",
        "an",
        "by",
        "at",
        "from",
        "as",
        "using",
        "built",
        "developed",
        "designed",
    ]
)
_FR_WORDS = frozenset(
    [
        "et",
        "le",
        "la",
        "les",
        "de",
        "des",
        "du",
        "en",
        "avec",
        "pour",
        "par",
        "sur",
        "dans",
        "une",
        "un",
        "au",
        "aux",
        "d",
        "l",
    ]
)

_PART_SEPARATOR_RE = re.compile(
    r"\s+[—–|·•@]\s+|\s+-\s+|\s*\|\s*|\t+|\s+(?:at|chez)\s+", re.IGNORECASE
)
_LEADING_JUNK = " \t|,;:·•—–-)]"
_TRAILING_JUNK = " \t|,;:·•—–-(["
_ITEM_SEPARATORS = ",;|•·"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s|,;()<>\"']+"
    r"|(?<![\w.@/])(?:[a-z0-9-]+\.)?(?:linkedin\.com|github\.com|gitlab\.com|medium\.com|"
    r"kaggle\.com|huggingface\.co|stackoverflow\.com|behance\.net|dribbble\.com|twitter\.com|"
    r"x\.com|scholar\.google\.com)/[^\s|,;()<>\"']+",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"(?<![\w+/.])(?:\(\+?\d{1,4}\)\s*|\+?\d)[\d\s().\-]{6,20}\d(?![\w@])")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# ---------------------------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------------------------


def parse_cv(data: bytes, kind: CvFileKind, *, max_pages: int = MAX_PAGES) -> tuple[ParsedCV, str]:
    """Parse a validated CV file into a draft structure and its extracted text."""
    lines = read_docx(data) if kind is CvFileKind.DOCX else read_pdf(data, max_pages=max_pages)
    lines = [line for line in lines if line.text]
    if not lines:
        raise NoTextFoundError(
            "No selectable text was found in the document. Scanned CVs are not supported: "
            "upload a DOCX file or a text-based PDF."
        )
    if len(lines) > MAX_LINES:
        raise TooManyPagesError(
            f"The document has more than {MAX_LINES} lines; a CV should be much shorter",
            details={"lines": len(lines), "max_lines": MAX_LINES},
        )
    return _CvParser(lines).parse(), extracted_text(lines)


def extracted_text(lines: list[Line]) -> str:
    return "\n".join(_display(line) for line in lines)


def structure_warnings(cv: ParsedCV) -> list[str]:
    """Problems the user should look at before confirming the CV (recomputed on every edit)."""
    warnings: list[str] = []
    if not cv.experiences:
        warnings.append("No work experience was found. Add your experience before confirming.")
    for experience in cv.experiences:
        label = experience.title or experience.employer or "untitled"
        if not experience.title:
            warnings.append(f'The experience "{label}" has no job title.')
        if experience.dates is None or experience.dates.start is None:
            warnings.append(f'No dates were found for the experience "{label}".')
    for education in cv.education:
        label = education.degree or education.institution or "untitled"
        if not education.degree:
            warnings.append(f'The education entry "{label}" has no degree.')
        if education.dates is None or education.dates.start is None:
            warnings.append(f'No dates were found for the education entry "{label}".')
    warnings.extend("A project has no name." for project in cv.projects if not project.name)
    return warnings


def confirmation_errors(cv: ParsedCV) -> list[dict[str, str]]:
    """Blocking problems: a confirmed CV becomes the fact base, so entries must be complete."""
    errors: list[dict[str, str]] = []

    def check_dates(loc: str, dates: DateRange | None) -> None:
        if dates is None or dates.start is None or dates.end is None:
            return
        start = (dates.start.year, dates.start.month or 1)
        end = (dates.end.year, dates.end.month or 12)
        if end < start:
            errors.append({"loc": f"{loc}.dates", "msg": "The end date is before the start date"})

    for index, experience in enumerate(cv.experiences):
        if not experience.title:
            errors.append({"loc": f"experiences.{index}.title", "msg": "A job title is required"})
        check_dates(f"experiences.{index}", experience.dates)
    for index, education in enumerate(cv.education):
        if not education.degree:
            errors.append({"loc": f"education.{index}.degree", "msg": "A degree is required"})
        check_dates(f"education.{index}", education.dates)
    for index, project in enumerate(cv.projects):
        if not project.name:
            errors.append({"loc": f"projects.{index}.name", "msg": "A project name is required"})
    for index, skill in enumerate(cv.skills):
        if not skill.name:
            errors.append({"loc": f"skills.{index}.name", "msg": "A skill name is required"})
    return errors


def detect_language(lines: list[Line]) -> str:
    counts: Counter[str] = Counter()
    for line in lines:
        for word in re.findall(r"[^\W\d_]+", line.text.casefold()):
            if word in _EN_WORDS:
                counts["en"] += 1
            if word in _FR_WORDS:
                counts["fr"] += 1
    if not counts:
        return "unknown"
    return "fr" if counts["fr"] > counts["en"] else "en"


def extract_contact(lines: list[str]) -> ContactInfo:
    emails: list[str] = []
    links: list[str] = []
    phones: list[str] = []
    for line in lines:
        masked = line
        for match in _EMAIL_RE.finditer(line):
            _append_unique(emails, match.group(0))
            masked = _mask(masked, match)
        for match in _URL_RE.finditer(masked):
            _append_unique(links, match.group(0).rstrip("."))
            masked = _mask(masked, match)
        for match in _PHONE_RE.finditer(masked):
            candidate = match.group(0).strip()
            digits = sum(ch.isdigit() for ch in candidate)
            if 8 <= digits <= 15 and find_date_range(candidate) is None:
                _append_unique(phones, candidate)
    return ContactInfo(emails=emails, phones=phones, links=links)


# ---------------------------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------------------------


def _display(line: Line) -> str:
    return f"• {line.text}" if line.is_bullet else line.text


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _mask(text: str, match: re.Match[str]) -> str:
    return text[: match.start()] + " " * (match.end() - match.start()) + text[match.end() :]


def _clean(segment: str) -> str:
    cleaned = segment.strip().lstrip(_LEADING_JUNK).rstrip(_TRAILING_JUNK).strip()
    return re.sub(r"^\(\s*\)$|^\[\s*\]$", "", cleaned)


def _is_location(text: str) -> bool:
    components = [_fold(part.strip()) for part in text.split(",")]
    if not components or any(not part or len(part.split()) > 4 for part in components):
        return False
    if any(_ROLE_RE.search(part) or _DEGREE_RE.search(part) for part in components):
        return False
    last = components[-1]
    if last in _REMOTE_WORDS or last in _COUNTRIES:
        return True
    raw_last = text.split(",")[-1].strip()
    return len(components) >= 2 and bool(re.fullmatch(r"[A-Z]{2,3}", raw_last))


def _looks_like_place(text: str) -> bool:
    words = text.split()
    return (
        0 < len(words) <= 4
        and not any(ch.isdigit() for ch in text)
        and all(word[:1].isupper() for word in words if word[:1].isalpha())
        and not _ROLE_RE.search(text)
    )


@dataclass
class _Part:
    text: str
    is_location: bool = False


def _split_parts(segment: str) -> list[_Part]:
    parts: list[_Part] = []
    for raw in _PART_SEPARATOR_RE.split(segment):
        part = _clean(raw)
        if not part:
            continue
        if _is_location(part):
            parts.append(_Part(part, is_location=True))
            continue
        if "," in part:
            parts.extend(_split_on_comma(part))
            continue
        parts.append(_Part(part))
    return parts


def _split_on_comma(part: str) -> list[_Part]:
    # "Acme Analytics, Paris, France" -> employer + location; "Acme, Inc." stays whole.
    commas = [index for index, ch in enumerate(part) if ch == ","]
    for index in commas:
        head, tail = _clean(part[:index]), _clean(part[index + 1 :])
        if head and tail and _is_location(tail):
            return [_Part(head), _Part(tail, is_location=True)]
    head, tail = _clean(part[: commas[0]]), _clean(part[commas[0] + 1 :])
    if head and tail and not _COMPANY_SUFFIX_RE.fullmatch(tail):
        return [_Part(head), _Part(tail)]
    return [_Part(part)]


def _split_items(text: str) -> list[str]:
    """Split a list line on , ; | • · (and " / ") outside parentheses."""
    items: list[str] = []
    depth = 0
    start = 0
    for index, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0 and ch in _ITEM_SEPARATORS:
            items.append(text[start:index])
            start = index + 1
    items.append(text[start:])
    result: list[str] = []
    for item in items:
        for piece in re.split(r"\s+/\s+", item):
            cleaned = piece.strip().rstrip(".").strip()
            if cleaned:
                result.append(cleaned)
    return result


@dataclass
class _Section:
    kind: SectionKind
    heading: str
    signal: int
    lines: list[Line] = field(default_factory=list)


@dataclass
class _RawEntry:
    header_lines: list[str] = field(default_factory=list)
    parts: list[_Part] = field(default_factory=list)
    first_bold: bool | None = None
    dates: DateRange | None = None
    header_complete: bool = False
    bullets: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    @property
    def has_body(self) -> bool:
        return bool(self.bullets or self.details)

    def add_header(self, line: Line, date_match: DateMatch | None, *, is_date_line: bool) -> None:
        text = line.text
        if date_match is not None:
            if self.dates is None:
                self.dates = date_match.range
            segments = [text[: date_match.start], text[date_match.end :]]
        else:
            segments = [text]
        for segment in segments:
            self.parts.extend(_split_parts(segment))
        if self.first_bold is None:
            self.first_bold = line.is_bold
        self.header_lines.append(text)
        if is_date_line and len(self.header_lines) > 1:
            self.header_complete = True


class _CvParser:
    def __init__(self, lines: list[Line]) -> None:
        self.lines = lines
        self.warnings: list[str] = []
        sizes = [line.font_size for line in lines if line.font_size]
        self.body_size = Counter(sizes).most_common(1)[0][0] if sizes else None

    # -- sections -------------------------------------------------------------------------

    def _signal(self, line: Line) -> int:
        """How strongly a line is styled as a heading: 3 style, 2 caps/larger, 1 bold, 0 none."""
        if line.heading_level is not None:
            return 3
        letters = [ch for ch in line.text if ch.isalpha()]
        if len(letters) >= 3 and all(ch.isupper() for ch in letters):
            return 2
        if line.font_size and self.body_size and line.font_size >= self.body_size + 1:
            return 2
        return 1 if line.is_bold else 0

    def _split_sections(self) -> tuple[list[Line], list[_Section]]:
        hits = [
            (line, kind)
            for line in self.lines
            if not line.is_bullet and (kind := match_section(line.text)) is not None
        ]
        styled = sum(1 for line, _ in hits if self._signal(line) >= 1) > len(hits) / 2
        word_levels = [line.heading_level for line, _ in hits if line.heading_level]
        section_level = min(word_levels) if word_levels else 1

        header: list[Line] = []
        sections: list[_Section] = []
        current: _Section | None = None
        for line in self.lines:
            signal = self._signal(line)
            kind = None if line.is_bullet else match_section(line.text)
            if kind is not None and self._accept_heading(kind, signal, current, styled=styled):
                current = _Section(kind, line.text, signal)
                sections.append(current)
                continue
            if kind is None and self._is_unknown_heading(line, section_level):
                current = _Section(SectionKind.OTHER, line.text, signal)
                sections.append(current)
                continue
            (current.lines if current is not None else header).append(line)
        return header, sections

    @staticmethod
    def _accept_heading(
        kind: SectionKind, signal: int, current: _Section | None, *, styled: bool
    ) -> bool:
        if styled and signal == 0:
            return False
        if current is not None and signal < current.signal:
            # A less prominent "Languages" inside Skills, or "Technologies" inside an
            # experience entry, is a label, not a new section.
            if current.kind is SectionKind.SKILLS and kind in (
                SectionKind.SKILLS,
                SectionKind.LANGUAGES,
            ):
                return False
            if (
                current.kind
                in (SectionKind.EXPERIENCE, SectionKind.PROJECTS, SectionKind.EDUCATION)
                and kind is SectionKind.SKILLS
            ):
                return False
        return True

    @staticmethod
    def _is_unknown_heading(line: Line, section_level: int) -> bool:
        return (
            line.heading_level is not None
            and 1 <= line.heading_level <= section_level
            and not line.is_bullet
            and len(line.text) <= 60
            and find_date_range(line.text) is None
        )

    # -- document ---------------------------------------------------------------------------

    def parse(self) -> ParsedCV:
        header, sections = self._split_sections()
        header_lines = [line.text for line in header]
        known = [s for s in sections if s.kind is not SectionKind.OTHER or s.lines]
        if not any(s.kind is not SectionKind.OTHER for s in sections):
            self.warnings.append(
                "No known CV sections (experience, education, skills...) were found; the text "
                "was kept in the header. Review the draft and add the entries manually."
            )

        summary_parts: list[str] = []
        experiences: list[ExperienceEntry] = []
        education: list[EducationEntry] = []
        projects: list[ProjectEntry] = []
        skills: list[SkillItem] = []
        certifications: list[str] = []
        languages: list[str] = []
        other_sections: list[OtherSection] = []

        for section in known:
            if section.kind is SectionKind.SUMMARY:
                summary_parts.append("\n".join(_display(line) for line in section.lines))
            elif section.kind is SectionKind.EXPERIENCE:
                experiences.extend(self._experiences(section.lines))
            elif section.kind is SectionKind.EDUCATION:
                education.extend(self._education(section.lines))
            elif section.kind is SectionKind.PROJECTS:
                projects.extend(self._projects(section.lines))
            elif section.kind is SectionKind.SKILLS:
                items, overflow = _parse_skills(section.lines)
                skills.extend(items)
                if overflow:
                    other_sections.append(OtherSection(heading=section.heading, lines=overflow))
            elif section.kind is SectionKind.CERTIFICATIONS:
                certifications.extend(line.text for line in section.lines)
            elif section.kind is SectionKind.LANGUAGES:
                for line in section.lines:
                    languages.extend(_split_items(line.text))
            elif section.kind is SectionKind.CONTACT:
                header_lines.extend(line.text for line in section.lines)
            else:
                if section.heading and not match_section(section.heading):
                    self.warnings.append(
                        f'The section "{section.heading}" was not recognised and was kept as-is.'
                    )
                other_sections.append(
                    OtherSection(
                        heading=section.heading, lines=[line.text for line in section.lines]
                    )
                )

        cv = ParsedCV(
            parser_version=PARSER_VERSION,
            language=detect_language(self.lines),
            header_lines=header_lines,
            contact=extract_contact(header_lines),
            summary="\n".join(part for part in summary_parts if part) or None,
            experiences=experiences,
            education=education,
            projects=projects,
            skills=skills,
            certifications=certifications,
            languages=languages,
            other_sections=other_sections,
        )
        cv.warnings = [*self.warnings, *structure_warnings(cv)]
        return cv

    # -- entries -----------------------------------------------------------------------------

    def _segment(self, lines: list[Line]) -> list[_RawEntry]:
        entries: list[_RawEntry] = []
        entry: _RawEntry | None = None
        for line in lines:
            if line.is_bullet:
                if entry is None:
                    entry = _RawEntry()
                    entries.append(entry)
                entry.bullets.append(line.text)
                continue
            date_match = find_date_range(line.text)
            if date_match is None and entry is not None and _is_description(line, entry):
                entry.details.append(line.text)
                continue
            is_date_line = date_match is not None and _is_date_line(line.text, date_match)
            if entry is None or _starts_new_entry(entry, line, date_match):
                entry = _RawEntry()
                entries.append(entry)
            entry.add_header(line, date_match, is_date_line=is_date_line)
        return entries

    def _experiences(self, lines: list[Line]) -> list[ExperienceEntry]:
        result = []
        for raw in self._segment(lines):
            title, employer, location, leftovers = _assign(raw.parts, _ROLE_RE, None)
            result.append(
                ExperienceEntry(
                    title=title,
                    employer=employer,
                    location=location,
                    dates=raw.dates,
                    bullets=raw.bullets,
                    details=[*leftovers, *raw.details],
                )
            )
        return result

    def _education(self, lines: list[Line]) -> list[EducationEntry]:
        result = []
        for raw in self._expand_headerless(self._segment(lines)):
            degree, institution, location, leftovers = _assign(
                raw.parts, _DEGREE_RE, _INSTITUTION_RE
            )
            result.append(
                EducationEntry(
                    degree=degree,
                    institution=institution,
                    location=location,
                    dates=raw.dates,
                    bullets=raw.bullets,
                    details=[*leftovers, *raw.details],
                )
            )
        return result

    def _projects(self, lines: list[Line]) -> list[ProjectEntry]:
        result = []
        for raw in self._expand_headerless(self._segment(lines)):
            names = [part.text for part in raw.parts]
            name = names[0] if names and len(names[0]) <= _MAX_FIELD_CHARS else ""
            leftovers = names[1:] if name else names
            result.append(
                ProjectEntry(
                    name=name,
                    dates=raw.dates,
                    bullets=raw.bullets,
                    details=[*leftovers, *raw.details],
                )
            )
        return result

    @staticmethod
    def _expand_headerless(entries: list[_RawEntry]) -> list[_RawEntry]:
        """A bullet list without entry headers ("• MSc ..., 2019") is one entry per bullet."""
        expanded: list[_RawEntry] = []
        for entry in entries:
            if entry.header_lines or not entry.bullets:
                expanded.append(entry)
                continue
            for bullet in entry.bullets:
                single = _RawEntry()
                name, _, rest = bullet.partition(": ")
                if rest and len(name.split()) <= 8:
                    single.add_header(Line(text=name), find_date_range(name), is_date_line=False)
                    single.bullets.append(rest)
                else:
                    single.add_header(
                        Line(text=bullet), find_date_range(bullet), is_date_line=False
                    )
                expanded.append(single)
        return expanded


def _is_description(line: Line, entry: _RawEntry) -> bool:
    text = line.text
    if line.is_bold:
        return False
    words = len(text.split())
    return (
        text.endswith(":")
        or len(text) >= 100
        or (text.endswith(".") and words >= 8)
        or (entry.dates is not None and text.endswith(".") and words >= 3)
    )


def _is_date_line(text: str, match: DateMatch) -> bool:
    remainder = _clean(text[: match.start]) + " " + _clean(text[match.end :])
    return len(remainder.split()) <= 4


def _starts_new_entry(entry: _RawEntry, line: Line, date_match: DateMatch | None) -> bool:
    if entry.has_body or entry.header_complete or len(entry.header_lines) >= 4:
        return True
    if entry.dates is not None and date_match is not None:
        return True
    if date_match is None and entry.header_lines and line.is_bold == entry.first_bold:
        # Two "Degree, School" lines in a row without dates are two entries.
        new_parts = [p for p in _split_parts(line.text) if not p.is_location]
        old_parts = [p for p in entry.parts if not p.is_location]
        return len(new_parts) >= 2 and len(old_parts) >= 2
    return False


def _assign(
    parts: list[_Part], primary: re.Pattern[str], secondary: re.Pattern[str] | None
) -> tuple[str, str | None, str | None, list[str]]:
    """Assign header parts to (main, organisation, location, leftovers).

    Experience: main = job title (role keywords), organisation = employer.
    Education: main = degree (degree keywords), organisation = institution.
    """
    location = next((part.text for part in parts if part.is_location), None)
    rest = [part.text for part in parts if not part.is_location]
    if location is not None:
        extra_locations = [p.text for p in parts if p.is_location][1:]
        rest.extend(extra_locations)
    oversized = [text for text in rest if len(text) > _MAX_FIELD_CHARS]
    rest = [text for text in rest if len(text) <= _MAX_FIELD_CHARS]

    main_index = next((i for i, text in enumerate(rest) if primary.search(text)), 0)
    main = rest.pop(main_index) if rest else ""
    organisation: str | None = None
    if not rest and location is not None and location.count(",") >= 2:
        # "Gamma Corp, Berlin, Germany": the first component is the organisation.
        head, _, tail = location.partition(",")
        organisation, location = head.strip(), tail.strip()
    elif rest:
        org_index = 0
        if secondary is not None:
            org_index = next((i for i, text in enumerate(rest) if secondary.search(text)), 0)
        organisation = rest.pop(org_index)
    if location is None and rest and _looks_like_place(rest[0]):
        location = rest.pop(0)
    if location is not None and len(location) > 200:
        rest.append(location)
        location = None
    return main, organisation, location, [*rest, *oversized]


def _parse_skills(lines: list[Line]) -> tuple[list[SkillItem], list[str]]:
    items: list[SkillItem] = []
    overflow: list[str] = []
    label: str | None = None
    for line in lines:
        text = line.text
        category: str | None = None
        match = re.match(r"^(?P<category>[^:：]{1,40}?)\s*[:：]\s*(?P<rest>.*)$", text)
        if match and len(match["category"].split()) <= 4 and "," not in match["category"]:
            category, text = match["category"].strip(), match["rest"].strip()
            if not text:
                label = category
                continue
        elif (
            line.is_bold
            and not line.is_bullet
            and "," not in text
            and len(text.split()) <= 4
            and len(text) <= 100
        ):
            label = text
            continue
        for name in _split_items(text):
            if len(name) > _MAX_SKILL_CHARS:
                overflow.append(name)
            else:
                items.append(SkillItem(name=name, category=category or label))
    return items, overflow


def summarize(cv: ParsedCV) -> dict[str, Any]:
    """Counts used in logs and audit entries (never the CV content itself)."""
    return {
        "experiences": len(cv.experiences),
        "education": len(cv.education),
        "projects": len(cv.projects),
        "skills": len(cv.skills),
        "warnings": len(cv.warnings),
        "language": cv.language,
    }
