import json
import re

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import REPO_ROOT, Environment, Settings

pytestmark = pytest.mark.feature("configuration")


def _settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_defaults_are_safe_and_match_the_specification() -> None:
    settings = _settings()

    assert settings.app_env is Environment.DEVELOPMENT
    assert settings.mock_mode is True
    assert settings.auto_submit is False
    assert settings.job_lookback_hours == 24
    assert settings.ats_target_score == 95
    assert settings.ats_max_iterations == 3
    assert settings.daily_run_time == "08:00"
    assert settings.timezone == "Africa/Tunis"
    assert settings.llm_provider == "claude"
    assert settings.claude_model == "claude-opus-5"
    assert settings.api_prefix == "/api/v1"


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("JOB_LOOKBACK_HOURS", "48")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    monkeypatch.setenv("NOTIFICATION_CHANNELS", "email,telegram")

    settings = _settings()

    assert settings.mock_mode is False
    assert settings.job_lookback_hours == 48
    assert settings.cors_origins == ["http://a.test", "http://b.test"]
    assert settings.notification_channels == ["email", "telegram"]


def test_list_settings_also_accept_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["http://a.test"]')
    assert _settings().cors_origins == ["http://a.test"]


def test_env_file_is_loaded(tmp_path) -> None:  # type: ignore[no-untyped-def]
    env_file = tmp_path / ".env"
    env_file.write_text("ATS_TARGET_SCORE=90\nMOCK_MODE=true\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]

    assert settings.ats_target_score == 90


def test_relative_paths_are_resolved_against_the_repository_root() -> None:
    settings = _settings(storage_dir="storage")
    assert settings.storage_dir == REPO_ROOT / "storage"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timezone", "Mars/Olympus_Mons"),
        ("daily_run_time", "25:00"),
        ("daily_run_time", "8am"),
        ("ats_target_score", 101),
        ("ats_max_iterations", 0),
        ("job_lookback_hours", 0),
        ("api_prefix", "api/v1"),
        ("api_prefix", "/api/v1/"),
        ("notification_channels", "email,pigeon"),
    ],
)
def test_invalid_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _settings(**{field: value})


def test_invalid_encryption_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="ENCRYPTION_KEY"):
        _settings(encryption_key="not-a-fernet-key")


def test_valid_encryption_key_is_accepted() -> None:
    key = Fernet.generate_key().decode()
    assert _settings(encryption_key=key).encryption_key is not None


def test_production_requires_security_settings() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _settings(app_env="production", log_format="console")

    message = str(excinfo.value)
    assert "API_AUTH_TOKEN" in message
    assert "ENCRYPTION_KEY" in message
    assert "LOG_FORMAT" in message


def test_production_rejects_short_api_token() -> None:
    with pytest.raises(ValidationError, match="API_AUTH_TOKEN"):
        _settings(
            app_env="production",
            log_format="json",
            api_auth_token="too-short",
            encryption_key=Fernet.generate_key().decode(),
        )


def test_production_accepts_a_complete_configuration() -> None:
    settings = _settings(
        app_env="production",
        log_format="json",
        api_auth_token="x" * 40,
        encryption_key=Fernet.generate_key().decode(),
        database_url="postgresql+psycopg://jobagent:a-strong-password@db:5432/jobagent",
    )
    assert settings.is_production is True
    assert settings.auth_enabled is True


def test_broker_defaults_to_redis_and_result_backend_is_opt_in() -> None:
    settings = _settings(redis_url="redis://cache:6379/0")
    assert settings.broker_url == "redis://cache:6379/0"
    assert settings.result_backend_url is None  # run results are stored in PostgreSQL

    explicit = _settings(
        redis_url="redis://cache:6379/0",
        celery_broker_url="redis://broker:6379/2",
        celery_result_backend="redis://results:6379/3",
    )
    assert explicit.broker_url == "redis://broker:6379/2"
    assert explicit.result_backend_url == "redis://results:6379/3"


def test_safe_summary_never_exposes_secret_values() -> None:
    secrets = {
        "api_auth_token": "tok-" + "a" * 40,
        "anthropic_api_key": "sk-ant-api03-supersecretvalue1234567890",
        "database_url": "postgresql+psycopg://jobagent:db-password-123@db:5432/jobagent",
        "encryption_key": Fernet.generate_key().decode(),
        "telegram_bot_token": "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ",
    }
    settings = _settings(**secrets)

    summary = settings.safe_summary()
    dumped = json.dumps(summary, default=str)

    assert "db-password-123" not in dumped
    for value in secrets.values():
        assert value not in dumped
    assert summary["secrets_configured"]["anthropic_api_key"] is True
    assert summary["secrets_configured"]["smtp_password"] is False
    assert summary["mock_mode"] is True
    assert summary["auto_submit"] is False


def test_security_warnings_flag_risky_configuration() -> None:
    settings = _settings(api_auth_token=None, auto_submit=True, mock_mode=False)

    warnings = " | ".join(settings.security_warnings())

    assert "API_AUTH_TOKEN" in warnings
    assert "AUTO_SUBMIT" in warnings
    assert "MOCK_MODE" in warnings
    assert "DATABASE_URL" in warnings  # default password


def test_empty_values_are_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENCRYPTION_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SMTP_HOST", "")

    settings = _settings()

    assert settings.encryption_key is None
    assert settings.anthropic_api_key is None
    assert settings.smtp_host is None
    assert settings.safe_summary()["secrets_configured"]["anthropic_api_key"] is False


def test_env_example_itself_is_a_valid_configuration() -> None:
    settings = Settings(_env_file=REPO_ROOT / ".env.example")  # type: ignore[call-arg]

    assert settings.mock_mode is True
    assert settings.auto_submit is False
    assert settings.encryption_key is None  # left empty in the template


def test_env_example_documents_every_setting() -> None:
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", env_example, flags=re.MULTILINE))

    missing = {name.upper() for name in Settings.model_fields} - documented

    assert not missing, f".env.example is missing: {sorted(missing)}"
