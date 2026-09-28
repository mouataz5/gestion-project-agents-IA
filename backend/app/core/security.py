"""Cryptographic helpers: encryption of secrets at rest and constant-time token comparison."""

from __future__ import annotations

import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings


class EncryptionError(Exception):
    """Raised when a key is invalid/missing or a ciphertext cannot be decrypted."""


class SecretBox:
    """Authenticated symmetric encryption (Fernet: AES-128-CBC + HMAC-SHA256).

    Used for data that must be stored but never read by humans, e.g. browser session state.
    """

    def __init__(self, key: str | bytes) -> None:
        raw = key.encode() if isinstance(key, str) else key
        try:
            self._fernet = Fernet(raw)
        except (ValueError, TypeError) as exc:
            raise EncryptionError("Invalid encryption key") from exc

    @classmethod
    def from_settings(cls, settings: Settings) -> SecretBox:
        if settings.encryption_key is None:
            raise EncryptionError("ENCRYPTION_KEY is not configured")
        return cls(settings.encryption_key.get_secret_value())

    def encrypt(self, plaintext: str | bytes) -> str:
        data = plaintext.encode() if isinstance(plaintext, str) else plaintext
        return self._fernet.encrypt(data).decode()

    def decrypt(self, token: str) -> bytes:
        try:
            return self._fernet.decrypt(token.encode())
        except InvalidToken as exc:
            raise EncryptionError(
                "Ciphertext is invalid or was encrypted with another key"
            ) from exc

    def decrypt_text(self, token: str) -> str:
        return self.decrypt(token).decode()


def generate_encryption_key() -> str:
    return Fernet.generate_key().decode()


def generate_api_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def tokens_match(provided: str | None, expected: str) -> bool:
    """Constant-time comparison of a provided token with the expected one."""
    if not provided:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())
