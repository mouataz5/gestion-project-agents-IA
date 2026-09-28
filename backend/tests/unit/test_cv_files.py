import io
import zipfile
from collections.abc import Callable

import pytest

from app.cv.errors import (
    EmptyFileError,
    FileTooLargeError,
    FileTypeMismatchError,
    UnsafeFileError,
    UnsupportedFileTypeError,
)
from app.cv.files import CvFileKind, detect_cv_file, sanitize_filename

pytestmark = pytest.mark.feature("cv-upload")


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_valid_docx_and_pdf_are_accepted(
    cv_docx: Callable[..., bytes], cv_pdf: Callable[..., bytes], sample_cv_en: list[tuple[str, str]]
) -> None:
    assert detect_cv_file("My CV.docx", cv_docx(sample_cv_en)) is CvFileKind.DOCX
    assert detect_cv_file("cv.PDF", cv_pdf(sample_cv_en)) is CvFileKind.PDF


@pytest.mark.parametrize("filename", ["cv.doc", "cv.txt", "cv", "cv.docx.exe", "cv.odt"])
def test_unsupported_extensions_are_rejected(filename: str) -> None:
    with pytest.raises(UnsupportedFileTypeError) as excinfo:
        detect_cv_file(filename, b"%PDF-1.7 whatever")
    assert excinfo.value.status_code == 415


def test_pdf_bytes_named_docx_are_rejected() -> None:
    with pytest.raises(FileTypeMismatchError):
        detect_cv_file("cv.docx", b"%PDF-1.7\n...")


def test_zip_bytes_named_pdf_are_rejected() -> None:
    with pytest.raises(FileTypeMismatchError):
        detect_cv_file("cv.pdf", _zip({"word/document.xml": b"<w:document/>"}))


def test_zip_without_a_word_document_is_rejected() -> None:
    with pytest.raises(FileTypeMismatchError):
        detect_cv_file("cv.docx", _zip({"hello.txt": b"not a word document"}))


def test_empty_and_oversized_files_are_rejected() -> None:
    with pytest.raises(EmptyFileError) as empty:
        detect_cv_file("cv.pdf", b"")
    assert empty.value.status_code == 400

    with pytest.raises(FileTooLargeError) as large:
        detect_cv_file("cv.pdf", b"%PDF-" + b"0" * 2000, max_bytes=1000)
    assert large.value.status_code == 413


def test_zip_bombs_are_rejected() -> None:
    bomb = _zip({"word/document.xml": b"<w:document/>", "word/media/big.bin": b"\0" * 3_000_000})

    with pytest.raises(UnsafeFileError) as excinfo:
        detect_cv_file("cv.docx", bomb, max_uncompressed_bytes=1_000_000)
    assert excinfo.value.status_code == 422


def test_archives_with_too_many_entries_are_rejected() -> None:
    entries = {f"word/f{i}.xml": b"x" for i in range(50)} | {"word/document.xml": b"<x/>"}

    with pytest.raises(UnsafeFileError):
        detect_cv_file("cv.docx", _zip(entries), max_entries=20)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("My CV 2024.docx", "My CV 2024.docx"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\me\\cv.pdf", "cv.pdf"),
        ("cv\x00<script>.pdf", "cvscript.pdf"),
        ("", "cv"),
    ],
)
def test_filenames_are_sanitized(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected
