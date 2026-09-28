"""File storage abstraction.

Keys are POSIX-style relative paths (``applications/<id>/cv/tailored_cv.pdf``). The local
provider refuses any key that could escape its root directory (absolute paths, ``..``
segments, NUL bytes, drive letters, symlinks pointing outside).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from app.core.config import Settings


class StorageError(Exception):
    """Base class for storage failures."""


class InvalidStorageKeyError(StorageError, ValueError):
    """The key is empty, absolute, or would escape the storage root."""


class StorageObjectNotFoundError(StorageError, KeyError):
    """No object is stored under the key."""


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    sha256: str


class StorageProvider(Protocol):
    def put_bytes(self, key: str, data: bytes) -> StoredObject: ...

    def get_bytes(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def list(self, prefix: str = "") -> list[str]: ...

    def health_check(self) -> str: ...


class LocalStorageProvider:
    """Stores objects as files under a root directory."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self._root = root.resolve()

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, key: str) -> Path:
        if not key or "\x00" in key or "\\" in key:
            raise InvalidStorageKeyError(f"Invalid storage key: {key!r}")
        pure = PurePosixPath(key)
        parts = key.split("/")
        if (
            pure.is_absolute()
            or not pure.parts
            or any(part in ("", ".", "..") for part in parts)
            or ":" in parts[0]
        ):
            raise InvalidStorageKeyError(f"Invalid storage key: {key!r}")
        path = (self._root / pure).resolve()
        if path == self._root or not path.is_relative_to(self._root):
            raise InvalidStorageKeyError(f"Storage key escapes the storage root: {key!r}")
        return path

    def put_bytes(self, key: str, data: bytes) -> StoredObject:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary file in the same directory, then atomically replace.
        fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return StoredObject(key=key, size=len(data), sha256=hashlib.sha256(data).hexdigest())

    def get_bytes(self, key: str) -> bytes:
        path = self._resolve(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise StorageObjectNotFoundError(key) from exc

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def delete(self, key: str) -> None:
        self._resolve(key).unlink(missing_ok=True)

    def list(self, prefix: str = "") -> list[str]:
        base = self._resolve(prefix) if prefix else self._root
        if not base.exists():
            return []
        candidates = [base] if base.is_file() else base.rglob("*")
        return sorted(
            path.relative_to(self._root).as_posix()
            for path in candidates
            if path.is_file() and not path.name.startswith(".tmp-")
        )

    def health_check(self) -> str:
        """Write, read back and delete a probe object; raise if storage is not usable."""
        key = f"diagnostics/.probe-{uuid.uuid4().hex}"
        payload = b"ok"
        self.put_bytes(key, payload)
        try:
            if self.get_bytes(key) != payload:
                raise StorageError("Storage probe read back different content")
        finally:
            self.delete(key)
        return "writable"


def create_storage(settings: Settings) -> StorageProvider:
    return LocalStorageProvider(settings.storage_dir)
