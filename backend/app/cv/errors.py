"""Errors raised while validating or parsing an uploaded CV. Each maps to an HTTP status."""

from __future__ import annotations

from app.core.errors import AppError


class CvFileError(AppError):
    status_code = 422
    code = "invalid_cv_file"


class EmptyFileError(CvFileError):
    status_code = 400
    code = "empty_file"


class FileTooLargeError(CvFileError):
    status_code = 413
    code = "file_too_large"


class UnsupportedFileTypeError(CvFileError):
    status_code = 415
    code = "unsupported_file_type"


class FileTypeMismatchError(CvFileError):
    """The content does not match the file extension (for example PDF bytes named .docx)."""

    status_code = 415
    code = "file_type_mismatch"


class UnsafeFileError(CvFileError):
    """The archive looks like a decompression bomb, is encrypted or contains macros."""

    code = "unsafe_file"


class UnreadableFileError(CvFileError):
    code = "unreadable_file"


class TooManyPagesError(CvFileError):
    code = "too_many_pages"


class NoTextFoundError(CvFileError):
    code = "no_text_found"
