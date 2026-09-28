import pytest

from app.core.redaction import REDACTED, is_sensitive_key, redact, redact_text

pytestmark = pytest.mark.feature("log-redaction")


def test_sensitive_keys_are_redacted_recursively_without_mutating_input() -> None:
    data = {
        "user": "alice",
        "password": "hunter2",
        "nested": {
            "api_key": "abc",
            "items": [{"Authorization": "Bearer xyz"}, {"Set-Cookie": "sid=1"}],
        },
        "access_token": "t0k3n",
        "max_tokens": 1000,
        "session_id": "s-1",
    }

    result = redact(data)

    assert result["user"] == "alice"
    assert result["password"] == REDACTED
    assert result["nested"]["api_key"] == REDACTED
    assert result["nested"]["items"][0]["Authorization"] == REDACTED
    assert result["nested"]["items"][1]["Set-Cookie"] == REDACTED
    assert result["access_token"] == REDACTED
    assert result["session_id"] == REDACTED
    assert result["max_tokens"] == 1000  # token *counts* are not secrets
    assert data["password"] == "hunter2"  # the input is not mutated


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "DB_PASSWORD",
        "passwd",
        "client_secret",
        "api_key",
        "x-api-key",
        "apikey",
        "Authorization",
        "cookie",
        "refresh_token",
        "private_key",
        "database_dsn",
        "credentials",
    ],
)
def test_sensitive_key_detection(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize(
    "key", ["author", "keyword", "storage_key", "input_tokens", "status", "job_id", "tokenizer"]
)
def test_non_sensitive_keys_are_kept(key: str) -> None:
    assert not is_sensitive_key(key)


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("Authorization: Bearer abcdef1234567890", "abcdef1234567890"),
        ("key sk-ant-api03-AbCdEf0123456789xyz used", "sk-ant-api03-AbCdEf0123456789xyz"),
        ("postgresql+psycopg://jobagent:s3cr3tpass@db:5432/app", "s3cr3tpass"),
        (
            "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0",
        ),
        (
            "bot 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ",
            "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ",
        ),
        ("GET /callback?token=abc123&page=2", "abc123"),
        ("password=hunter2 user=bob", "hunter2"),
        (
            "github ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        ),
    ],
)
def test_secret_values_are_redacted_in_free_text(text: str, secret: str) -> None:
    result = redact_text(text)
    assert secret not in result
    assert REDACTED in result


def test_url_redaction_keeps_user_and_host() -> None:
    assert redact_text("redis://user:pw123@cache:6379/0") == "redis://user:[REDACTED]@cache:6379/0"


def test_non_sensitive_text_is_unchanged() -> None:
    text = "Discovered 12 jobs from greenhouse in 3.2s (page=2)"
    assert redact_text(text) == text


def test_strings_inside_structures_are_scanned() -> None:
    result = redact(
        {"message": "retrying with password=hunter2", "values": ("Bearer abcdefgh12345",)}
    )
    assert "hunter2" not in str(result)
    assert "abcdefgh12345" not in str(result)


def test_deeply_nested_structures_are_truncated_safely() -> None:
    data: dict[str, object] = {}
    cursor = data
    for _ in range(50):
        child: dict[str, object] = {}
        cursor["child"] = child
        cursor = child

    result = redact(data)

    assert "[TRUNCATED]" in str(result)


def test_non_string_keys_and_scalars_are_preserved() -> None:
    assert redact({1: "one", "count": 3, "ok": True, "none": None}) == {
        1: "one",
        "count": 3,
        "ok": True,
        "none": None,
    }
