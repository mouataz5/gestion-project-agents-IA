from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.health import ComponentHealth, ComponentStatus


class PhaseInfo(BaseModel):
    number: int
    name: str
    status: str
    summary: str


class SystemConfig(BaseModel):
    job_lookback_hours: int
    ats_target_score: int
    ats_max_iterations: int
    scheduler_enabled: bool
    daily_run_time: str
    timezone: str
    llm_provider: str
    llm_model: str
    notification_channels: list[str]
    storage_backend: str
    log_level: str
    log_format: str


class SecretsStatus(BaseModel):
    """Whether each secret is configured — values are never exposed."""

    api_auth_token: bool
    encryption_key: bool
    anthropic_api_key: bool
    smtp_password: bool
    telegram_bot_token: bool
    n8n_webhook_secret: bool


class SystemInfo(BaseModel):
    name: str
    version: str
    environment: str
    api_prefix: str
    mock_mode: bool
    auto_submit: bool
    auth_enabled: bool
    config: SystemConfig
    secrets: SecretsStatus
    phases: list[PhaseInfo]
    warnings: list[str]


class SystemStatus(BaseModel):
    status: ComponentStatus
    components: list[ComponentHealth]
    checked_at: datetime
