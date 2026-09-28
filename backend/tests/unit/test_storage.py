import hashlib
from pathlib import Path

import pytest

from app.core.storage import (
    InvalidStorageKeyError,
    LocalStorageProvider,
    StorageObjectNotFoundError,
)

pytestmark = pytest.mark.feature("storage")


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(tmp_path / "store")


def test_put_and_get_roundtrip(storage: LocalStorageProvider) -> None:
    stored = storage.put_bytes("applications/123/cv/tailored_cv.pdf", b"%PDF-data")

    assert stored.key == "applications/123/cv/tailored_cv.pdf"
    assert stored.size == 9
    assert stored.sha256 == hashlib.sha256(b"%PDF-data").hexdigest()
    assert storage.exists("applications/123/cv/tailored_cv.pdf")
    assert storage.get_bytes("applications/123/cv/tailored_cv.pdf") == b"%PDF-data"


def test_overwrite_replaces_content_and_leaves_no_temp_files(
    storage: LocalStorageProvider, tmp_path: Path
) -> None:
    storage.put_bytes("a/file.txt", b"one")
    storage.put_bytes("a/file.txt", b"two")

    assert storage.get_bytes("a/file.txt") == b"two"
    assert sorted(p.name for p in (tmp_path / "store" / "a").iterdir()) == ["file.txt"]


def test_list_and_delete(storage: LocalStorageProvider) -> None:
    storage.put_bytes("applications/1/cv/a.docx", b"a")
    storage.put_bytes("applications/1/cv/b.pdf", b"b")
    storage.put_bytes("uploads/master.docx", b"m")

    assert storage.list("applications/1") == [
        "applications/1/cv/a.docx",
        "applications/1/cv/b.pdf",
    ]
    assert len(storage.list()) == 3

    storage.delete("applications/1/cv/a.docx")
    storage.delete("applications/1/cv/a.docx")  # deleting a missing object is a no-op

    assert not storage.exists("applications/1/cv/a.docx")


def test_missing_object_raises(storage: LocalStorageProvider) -> None:
    with pytest.raises(StorageObjectNotFoundError):
        storage.get_bytes("missing.txt")


@pytest.mark.parametrize(
    "key",
    [
        "",
        "../escape.txt",
        "/etc/passwd",
        "a/../../b",
        "a/./../../c",
        "a\x00b",
        "C:\\windows\\x",
        ".",
    ],
)
def test_unsafe_keys_are_rejected(storage: LocalStorageProvider, key: str) -> None:
    with pytest.raises(InvalidStorageKeyError):
        storage.put_bytes(key, b"x")


def test_symlink_escape_is_rejected(storage: LocalStorageProvider, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "store" / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(InvalidStorageKeyError):
        storage.put_bytes("link/secret.txt", b"x")
    assert not (outside / "secret.txt").exists()


def test_health_check_leaves_no_files(storage: LocalStorageProvider, tmp_path: Path) -> None:
    storage.health_check()
    assert storage.list() == []
