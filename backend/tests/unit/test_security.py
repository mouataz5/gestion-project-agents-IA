from collections.abc import Callable

import pytest

from app.core.config import Settings
from app.core.security import (
    EncryptionError,
    SecretBox,
    generate_api_token,
    generate_encryption_key,
    tokens_match,
)

pytestmark = pytest.mark.feature("encryption")


def test_encrypt_decrypt_roundtrip() -> None:
    box = SecretBox(generate_encryption_key())

    token = box.encrypt("cookie=session-value")

    assert "session-value" not in token
    assert box.decrypt_text(token) == "cookie=session-value"
    assert box.decrypt(box.encrypt(b"\x00\x01")) == b"\x00\x01"


def test_decrypting_with_another_key_fails() -> None:
    token = SecretBox(generate_encryption_key()).encrypt("secret")

    with pytest.raises(EncryptionError):
        SecretBox(generate_encryption_key()).decrypt(token)


def test_tampered_ciphertext_is_rejected() -> None:
    box = SecretBox(generate_encryption_key())
    token = box.encrypt("secret")
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")

    with pytest.raises(EncryptionError):
        box.decrypt(tampered)


def test_invalid_key_is_rejected() -> None:
    with pytest.raises(EncryptionError):
        SecretBox("not-a-valid-key")


def test_from_settings_requires_a_configured_key(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(EncryptionError, match="ENCRYPTION_KEY"):
        SecretBox.from_settings(make_settings(encryption_key=None))

    box = SecretBox.from_settings(make_settings(encryption_key=generate_encryption_key()))
    assert box.decrypt_text(box.encrypt("ok")) == "ok"


def test_tokens_match_uses_exact_comparison() -> None:
    assert tokens_match("abc", "abc")
    assert not tokens_match("abc", "abd")
    assert not tokens_match("abc", "abcd")
    assert not tokens_match(None, "abc")
    assert not tokens_match("", "abc")


def test_generated_api_tokens_are_long_and_unique() -> None:
    first, second = generate_api_token(), generate_api_token()
    assert len(first) >= 40
    assert first != second
