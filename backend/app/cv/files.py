"""Upload validation: extension allow-list, magic bytes, size limits and ZIP safety checks.

The file is never trusted: the extension must be .docx or .pdf, the content must match it,
and DOCX archives are inspected (without extracting anything) for decompression bombs,
encryption and macros before any parser touches them.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from enum import StrEnum
from pathlib import PurePosixPath

from app.cv.errors import (
    EmptyFileError,
    FileTooLargeError,
    FileTypeMismatchError,
    UnreadableFileError,
    UnsafeFileError,
    UnsupportedFileTypeError,
)

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 1000

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_CONTENT_TYPE = "application/pdf"


class CvFileKind(StrEnum):
    DOCX = "DOCX"
    PDF = "PDF"

    @property
    def content_type(self) -> str:
        return DOCX_CONTENT_TYPE if self is CvFileKind.DOCX else PDF_CONTENT_TYPE

    @property
    def extension(self) -> str:
        return ".docx" if self is CvFileKind.DOCX else ".pdf"


_EXTENSIONS = {".docx": CvFileKind.DOCX, ".pdf": CvFileKind.PDF}
_FORBIDDEN_CHARS = set('<>:"/\\|?*')


def sanitize_filename(name: str, *, default: str = "cv", max_length: int = 120) -> str:
    """Return a display-safe base name: no directories, control or reserved characters."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFC", base)
    base = "".join(ch for ch in base if ch.isprintable() and ch not in _FORBIDDEN_CHARS)
    base = re.sub(r"\s+", " ", base).strip(" .")
    if not base:
        return default
    if len(base) > max_length:
        suffix = PurePosixPath(base).suffix
        suffix = suffix if len(suffix) <= 10 else ""
        base = base[: max_length - len(suffix)].rstrip(" .") + suffix
    return base


def detect_cv_file(
    filename: str,
    data: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> CvFileKind:
    """Validate an uploaded CV and return its kind, or raise a ``CvFileError`` subclass."""
    suffix = PurePosixPath(sanitize_filename(filename)).suffix.lower()
    kind = _EXTENSIONS.get(suffix)
    if kind is None:
        raise UnsupportedFileTypeError(
            "Only .docx and .pdf files are accepted", details={"extension": suffix or None}
        )
    if not data:
        raise EmptyFileError("The file is empty")
    if len(data) > max_bytes:
        raise FileTooLargeError(
            f"The file is larger than {max_bytes // (1024 * 1024) or 1} MB",
            details={"size_bytes": len(data), "max_bytes": max_bytes},
        )
    if kind is CvFileKind.PDF:
        if b"%PDF-" not in data[:1024]:
            raise FileTypeMismatchError("The file is named .pdf but is not a PDF document")
        return kind
    if not data.startswith(b"PK\x03\x04"):
        raise FileTypeMismatchError("The file is named .docx but is not a Word document")
    _check_docx_archive(
        data, max_uncompressed_bytes=max_uncompressed_bytes, max_entries=max_entries
    )
    return kind


def _check_docx_archive(data: bytes, *, max_uncompressed_bytes: int, max_entries: int) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, OSError) as exc:
        raise UnreadableFileError("The Word document is corrupt or unreadable") from exc
    if len(entries) > max_entries:
        raise UnsafeFileError(
            "The Word document contains too many parts", details={"entries": len(entries)}
        )
    total = sum(entry.file_size for entry in entries)
    if total > max_uncompressed_bytes:
        raise UnsafeFileError(
            "The Word document expands to an unsafe size",
            details={"uncompressed_bytes": total, "max_uncompressed_bytes": max_uncompressed_bytes},
        )
    names = {entry.filename for entry in entries}
    if any(entry.flag_bits & 0x1 for entry in entries):
        raise UnsafeFileError("Encrypted Word documents are not supported")
    if "word/document.xml" not in names:
        raise FileTypeMismatchError("The file is named .docx but is not a Word document")
    if any(name.lower().endswith("vbaproject.bin") for name in names):
        raise UnsafeFileError("Macro-enabled documents are not accepted")
