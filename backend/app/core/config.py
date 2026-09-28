"""Application configuration.

All configuration comes from environment variables and the repository-root `.env` file (see
`.env.example`). Secrets are `SecretStr` so they are never printed by accident; use
`Settings.safe_summary()` whenever configuration has to be shown to a user.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_DATABASE_URL = "postgresql+psycopg://jobagent:jobagent@localhost:5432/jobagent"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
WEAK_DATABASE_PASSWORDS = frozenset({"jobagent", "postgres", "password", "changeme", "change-me"})
MIN_PRODUCTION_TOKEN_LENGTH = 32
SECRET_FIELDS = (
    "api_auth_token",
    "encryption_key",
    "anthropic_api_key",
    "smtp_password",
    "telegram_bot_token",
    "n8n_webhook_secret",
)

_TIME_OF_DAY = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

NotificationChannel = Literal["email", "telegram", "webhook"]


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Validated runtime configuration (one instance per process via `get_settings()`)."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # `KEY=` (empty) means "not set": use the default instead of an empty string.
        env_ignore_empty=True,
    )

    # --- Application ---------------------------------------------------------
    app_name: str = "AI Job Application Agent"
    app_env: Environment = Environment.DEVELOPMENT
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "console"
    api_prefix: str = "/api/v1"
    enable_api_docs: bool = True
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    api_auth_token: SecretStr | None = None
    public_dashboard_url: str = "http://localhost:3000"

    # --- Safety switches -----------------------------------------------------
    mock_mode: bool = True
    auto_submit: bool = False

    # --- Infrastructure --------------------------------------------------------
    database_url: SecretStr = SecretStr(DEFAULT_DATABASE_URL)
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_echo: bool = False
    redis_url: SecretStr = SecretStr(DEFAULT_REDIS_URL)
    celery_broker_url: SecretStr | None = None
    celery_result_backend: SecretStr | None = None

    # --- Paths -------------------------------------------------------------------
    storage_dir: Path = REPO_ROOT / "storage"
    candidate_dir: Path = REPO_ROOT / "candidate"
    prompts_dir: Path = REPO_ROOT / "prompts"

    # --- Security ------------------------------------------------------------------
    encryption_key: SecretStr | None = None

    # --- Pipeline ------------------------------------------------------------------
    job_lookback_hours: int = Field(default=24, ge=1, le=24 * 30)
    ats_target_score: int = Field(default=95, ge=0, le=100)
    ats_max_iterations: int = Field(default=3, ge=1, le=10)
    scheduler_enabled: bool = True
    daily_run_time: str = "08:00"
    timezone: str = "Africa/Tunis"

    # --- LLM -------------------------------------------------------------------------
    llm_provider: Literal["claude", "mock"] = "claude"
    claude_model: str = "claude-opus-5"
    anthropic_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=300.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=10)

    # --- Notifications ---------------------------------------------------------------
    notification_channels: Annotated[list[NotificationChannel], NoDecode] = Field(
        default_factory=list
    )
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = True
    email_from: str | None = None
    email_to: str | None = None
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    n8n_webhook_url: str | None = None
    n8n_webhook_secret: SecretStr | None = None

    # --- Observability ---------------------------------------------------------------
    error_tracker: Literal["logging"] = "logging"

    # ---------------------------------------------------------------------------------
    # Validation
    # ---------------------------------------------------------------------------------
    @field_validator("cors_origins", "notification_channels", mode="before")
    @classmethod
    def _split_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [item.strip() for item in text.split(",") if item.strip()]
        return value

    @field_validator("api_prefix")
    @classmethod
    def _validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("API_PREFIX must start with '/' and must not end with '/'")
        return value

    @field_validator("daily_run_time")
    @classmethod
    def _validate_time_of_day(cls, value: str) -> str:
        if not _TIME_OF_DAY.fullmatch(value):
            raise ValueError("DAILY_RUN_TIME must use the 24-hour HH:MM format, e.g. 08:00")
        return value

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"TIMEZONE {value!r} is not a valid IANA time zone") from exc
        return value

    @field_validator("encryption_key")
    @classmethod
    def _validate_encryption_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            try:
                Fernet(value.get_secret_value().encode())
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    "ENCRYPTION_KEY must be a Fernet key (32 url-safe base64-encoded bytes); "
                    "generate one with `make env`"
                ) from exc
        return value

    @field_validator("storage_dir", "candidate_dir", "prompts_dir")
    @classmethod
    def _resolve_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else (REPO_ROOT / value).resolve()

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.app_env is not Environment.PRODUCTION:
            return self
        problems: list[str] = []
        token = self.api_auth_token.get_secret_value() if self.api_auth_token else ""
        if len(token) < MIN_PRODUCTION_TOKEN_LENGTH:
            problems.append(
                f"API_AUTH_TOKEN must be set to at least {MIN_PRODUCTION_TOKEN_LENGTH} "
                "characters in production"
            )
        if self.encryption_key is None:
            problems.append("ENCRYPTION_KEY must be set in production")
        if self.log_format != "json":
            problems.append("LOG_FORMAT must be 'json' in production")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    # ---------------------------------------------------------------------------------
    # Derived values
    # ---------------------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.app_env is Environment.PRODUCTION

    @property
    def auth_enabled(self) -> bool:
        return self.api_auth_token is not None

    @property
    def database_dsn(self) -> str:
        return self.database_url.get_secret_value()

    @property
    def redis_dsn(self) -> str:
        return self.redis_url.get_secret_value()

    @property
    def broker_url(self) -> str:
        return (self.celery_broker_url or self.redis_url).get_secret_value()

    @property
    def result_backend_url(self) -> str | None:
        """Celery result backend. Disabled unless configured: run results live in PostgreSQL."""
        if self.celery_result_backend is None:
            return None
        return self.celery_result_backend.get_secret_value()

    @property
    def llm_model(self) -> str:
        return self.claude_model if self.llm_provider == "claude" else self.llm_provider

    def security_warnings(self) -> list[str]:
        """Human-readable warnings about risky (but allowed) configuration."""
        warnings: list[str] = []
        if not self.auth_enabled:
            warnings.append(
                "API_AUTH_TOKEN is not set: the API accepts unauthenticated requests "
                "(only allowed outside production)."
            )
        password = urlsplit(self.database_dsn).password
        if password is not None and password in WEAK_DATABASE_PASSWORDS:
            warnings.append("DATABASE_URL uses a default or weak password.")
        if self.encryption_key is None:
            warnings.append("ENCRYPTION_KEY is not set: secrets cannot be encrypted at rest.")
        if self.auto_submit:
            warnings.append(
                "AUTO_SUBMIT is enabled: applications meeting strict criteria may be submitted "
                "without per-application approval."
            )
        if not self.mock_mode:
            warnings.append("MOCK_MODE is disabled: the system may contact real job sites.")
        return warnings

    def safe_summary(self) -> dict[str, Any]:
        """Configuration that is safe to display: secrets are reported only as booleans."""
        return {
            "app_name": self.app_name,
            "app_env": self.app_env.value,
            "api_prefix": self.api_prefix,
            "mock_mode": self.mock_mode,
            "auto_submit": self.auto_submit,
            "auth_enabled": self.auth_enabled,
            "log_level": self.log_level,
            "log_format": self.log_format,
            "job_lookback_hours": self.job_lookback_hours,
            "ats_target_score": self.ats_target_score,
            "ats_max_iterations": self.ats_max_iterations,
            "scheduler_enabled": self.scheduler_enabled,
            "daily_run_time": self.daily_run_time,
            "timezone": self.timezone,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "notification_channels": list(self.notification_channels),
            "storage_backend": "local",
            "secrets_configured": {name: getattr(self, name) is not None for name in SECRET_FIELDS},
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings instance (cleared in tests via `get_settings.cache_clear()`)."""
    return Settings()
