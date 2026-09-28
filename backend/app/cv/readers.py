"""Extract text lines with layout hints (heading style, bold, bullet, font size) from CVs.

DOCX: paragraphs in document order, including tables and text boxes, via the XML tree
(python-docx's ``Paragraph.text`` skips runs inside tracked insertions and content controls).
PDF: pdfplumber text lines; bold and font size come from the character font metadata.
"""

from __future__ import annotations

import io
import re
import statistics
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any

import docx
import pdfplumber
from docx.enum.style import WD_STYLE_TYPE
from docx.styles.style import StyleFactory

from app.cv.errors import CvFileError, TooManyPagesError, UnreadableFileError

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
# Containers whose paragraphs are visited on their own (nested paragraphs) or never (deleted
# text, compatibility fallbacks that duplicate a text box).
_SKIP_IN_PARAGRAPH = {f"{_W}p", f"{_W}txbxContent", f"{_W}del", _MC_FALLBACK}

_BULLET_RE = re.compile(r"^\s*(?:\(cid:\d+\)|[•◦▪▫■□●○►▶▸‣⁃➢➤✓✔◆◇❖·∙]" r"|[-–—*](?=\s))\s*")
_PAGE_NUMBER_RE = re.compile(r"^(?:page\s*)?\d{1,3}(?:\s*(?:/|of|sur)\s*\d{1,3})?$", re.IGNORECASE)
_BOLD_FONT_RE = re.compile(r"bold|black|heavy|semibold|demibold", re.IGNORECASE)
_HEADING_STYLE_RE = re.compile(r"^heading\s*(\d)$", re.IGNORECASE)


@dataclass(frozen=True)
class Line:
    """One logical line of the document with the layout hints the parser relies on."""

    text: str
    is_bullet: bool = False
    is_bold: bool = False
    heading_level: int | None = None  # 0 = Word "Title" style, 1-9 = "Heading N"
    font_size: float | None = None
    x0: float | None = None  # PDF only: left position, used to join wrapped bullet lines


def strip_bullet(raw: str) -> tuple[bool, str]:
    """Split a leading bullet marker from ``raw``: ``(is_bullet, text)``."""
    match = _BULLET_RE.match(raw)
    if match is None or match.end() == len(raw):
        return False, raw.strip()
    return True, raw[match.end() :].strip()


# ---------------------------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------------------------


def read_docx(data: bytes) -> list[Line]:
    try:
        document = docx.Document(io.BytesIO(data))
        lines: list[Line] = []
        section = document.sections[0] if len(document.sections) else None
        if section is not None and not section.header.is_linked_to_previous:
            lines.extend(_docx_lines(section.header._element, document))
        lines.extend(_docx_lines(document.element.body, document))
    except CvFileError:
        raise
    except Exception as exc:  # malformed documents raise a wide range of exceptions
        raise UnreadableFileError("The Word document is corrupt or unreadable") from exc
    return lines


def _docx_lines(container: Any, document: Any) -> Iterator[Line]:
    for paragraph in container.iter(f"{_W}p"):
        if _has_ancestor(paragraph, _MC_FALLBACK, stop=container):
            continue
        text = _paragraph_text(paragraph)
        if not text.strip():
            continue
        style = _paragraph_style(paragraph, document)
        heading_level = _heading_level(style)
        list_style = style is not None and "list" in (style.name or "").lower()
        numbered = paragraph.find(f"{_W}pPr/{_W}numPr") is not None or _style_has_numbering(style)
        bold = _paragraph_is_bold(paragraph, style)
        size = _paragraph_font_size(paragraph)
        for raw in text.split("\n"):
            if not raw.strip():
                continue
            marker, clean = strip_bullet(raw)
            yield Line(
                text=clean,
                is_bullet=marker or list_style or numbered,
                is_bold=bold,
                heading_level=heading_level,
                font_size=size,
            )


def _has_ancestor(element: Any, tag: str, *, stop: Any) -> bool:
    parent = element.getparent()
    while parent is not None and parent is not stop:
        if parent.tag == tag:
            return True
        parent = parent.getparent()
    return False


def _paragraph_text(paragraph: Any) -> str:
    parts: list[str] = []

    def walk(element: Any) -> None:
        for child in element:
            tag = child.tag
            if not isinstance(tag, str) or tag in _SKIP_IN_PARAGRAPH:
                continue
            if tag == f"{_W}t":
                parts.append(child.text or "")
            elif tag == f"{_W}tab":
                parts.append("\t")
            elif tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
            elif tag == f"{_W}noBreakHyphen":
                parts.append("-")
            else:
                walk(child)

    walk(paragraph)
    return re.sub(r"[ \t ]+", " ", "".join(parts)).strip()


def _paragraph_style(paragraph: Any, document: Any) -> Any:
    styles = document.styles.element
    reference = paragraph.find(f"{_W}pPr/{_W}pStyle")
    style_id = reference.get(f"{_W}val") if reference is not None else None
    element = styles.get_by_id(style_id) if style_id else None
    if element is None:
        element = styles.default_for(WD_STYLE_TYPE.PARAGRAPH)
    return StyleFactory(element) if element is not None else None


def _heading_level(style: Any) -> int | None:
    if style is None:
        return None
    for current in _style_chain(style):
        name = (current.name or "").strip()
        if name.lower() == "title":
            return 0
        match = _HEADING_STYLE_RE.match(name)
        if match:
            return int(match.group(1))
    return None


def _style_chain(style: Any, depth: int = 5) -> Iterator[Any]:
    current = style
    while current is not None and depth > 0:
        yield current
        current = getattr(current, "base_style", None)
        depth -= 1


def _style_has_numbering(style: Any) -> bool:
    return any(
        current.element.find(f"{_W}pPr/{_W}numPr") is not None for current in _style_chain(style)
    )


def _style_is_bold(style: Any) -> bool:
    for current in _style_chain(style):
        bold = current.font.bold
        if bold is not None:
            return bool(bold)
    return False


def _run_is_bold(run: Any) -> bool | None:
    flag = run.find(f"{_W}rPr/{_W}b")
    if flag is None:
        return None
    return flag.get(f"{_W}val", "true").lower() not in ("0", "false", "off")


def _paragraph_is_bold(paragraph: Any, style: Any) -> bool:
    style_bold = style is not None and _style_is_bold(style)
    runs = [
        run
        for run in paragraph.iter(f"{_W}r")
        if "".join(t.text or "" for t in run.iter(f"{_W}t")).strip()
    ]
    if not runs:
        return False
    for run in runs:
        bold = _run_is_bold(run)
        if not (bold if bold is not None else style_bold):
            return False
    return True


def _paragraph_font_size(paragraph: Any) -> float | None:
    sizes = [
        int(size.get(f"{_W}val")) / 2
        for size in paragraph.iter(f"{_W}sz")
        if (size.get(f"{_W}val") or "").isdigit()
    ]
    return max(sizes) if sizes else None


# ---------------------------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------------------------


def read_pdf(data: bytes, *, max_pages: int) -> list[Line]:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) > max_pages:
                raise TooManyPagesError(
                    f"The PDF has {len(pdf.pages)} pages; a CV may have at most {max_pages}",
                    details={"pages": len(pdf.pages), "max_pages": max_pages},
                )
            lines: list[Line] = []
            for page in pdf.pages:
                for item in page.extract_text_lines(return_chars=True, strip=True):
                    line = _pdf_line(item)
                    if line is not None:
                        lines.append(line)
    except CvFileError:
        raise
    except Exception as exc:  # malformed PDFs raise a wide range of exceptions
        raise UnreadableFileError("The PDF is corrupt, encrypted or unreadable") from exc
    return _join_wrapped_bullets(lines)


def _pdf_line(item: dict[str, Any]) -> Line | None:
    raw = str(item.get("text") or "").strip()
    if not raw or _PAGE_NUMBER_RE.match(raw):
        return None
    chars = [c for c in item.get("chars", []) if str(c.get("text", "")).strip()]
    bold = bool(chars) and (
        sum(1 for c in chars if _BOLD_FONT_RE.search(str(c.get("fontname", ""))))
        >= 0.8 * len(chars)
    )
    size = statistics.median(float(c.get("size", 0)) for c in chars) if chars else None
    marker, text = strip_bullet(raw)
    return Line(
        text=text,
        is_bullet=marker,
        is_bold=bold,
        font_size=round(size, 1) if size else None,
        x0=float(item.get("x0", 0.0)),
    )


def _join_wrapped_bullets(lines: list[Line]) -> list[Line]:
    """Join the continuation lines of a wrapped bullet point back onto the bullet."""
    joined: list[Line] = []
    for line in lines:
        previous = joined[-1] if joined else None
        if (
            previous is not None
            and previous.is_bullet
            and not line.is_bullet
            and not line.is_bold
            and _is_continuation(previous, line)
        ):
            separator = "" if previous.text.endswith("-") else " "
            joined[-1] = replace(previous, text=f"{previous.text}{separator}{line.text}")
            continue
        joined.append(line)
    return joined


def _is_continuation(previous: Line, line: Line) -> bool:
    if previous.font_size and line.font_size and abs(previous.font_size - line.font_size) > 0.6:
        return False
    indented = previous.x0 is not None and line.x0 is not None and line.x0 > previous.x0 + 2
    unfinished = not previous.text.rstrip().endswith((".", "!", "?", ";", ":"))
    return indented or (unfinished and line.text[:1].islower())
