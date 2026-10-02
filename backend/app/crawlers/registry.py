"""Source policy registry (``crawler/sources.yaml``) and watchlist seed (``crawler/companies.yaml``).

The YAML files are reviewed, versioned configuration. The registry decides which sources may
run: enabled, policy ``api_only``/``allowed``, implemented, and real or mock according to
MOCK_MODE. Every skipped source gets a human-readable reason (shown in runs and the dashboard).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from app.core.errors import AppError
from app.crawlers.base import JobSource, SourceKind, SourcePolicy
from app.crawlers.mock import MockAtsSource, MockFeedSource
from app.schemas.companies import CompanyCreate

SOURCES_FILE = "sources.yaml"
COMPANIES_FILE = "companies.yaml"


class SourcesConfigError(AppError):
    status_code = 500
    code = "invalid_crawler_config"

    def __init__(self, message: str, details: list[dict[str, Any]]) -> None:
        super().__init__(message, details=details)
        self.details: list[dict[str, Any]] = details


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceConfig(_Strict):
    key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,49}$")]
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    kind: SourceKind
    policy: SourcePolicy
    enabled: bool = False
    mock: bool = False
    priority: int = Field(default=10, ge=0, le=1000)
    rate_limit_per_minute: int = Field(default=30, ge=1, le=6000)
    available_from_phase: int | None = Field(default=None, ge=1, le=11)
    description: str | None = None
    notes: str | None = None


class SourcesFile(_Strict):
    version: Literal[1]
    user_agent: Annotated[str, StringConstraints(min_length=3, max_length=200)]
    sources: list[SourceConfig]

    @model_validator(mode="after")
    def _unique_keys(self) -> SourcesFile:
        keys = [source.key for source in self.sources]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ValueError(f"duplicate source keys: {', '.join(duplicates)}")
        return self


class CompanyEntry(CompanyCreate):
    """One watchlist company in ``companies.yaml`` (same fields and rules as the API)."""


class CompaniesFile(_Strict):
    version: Literal[1]
    companies: list[CompanyEntry]


def _validation_details(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "loc": ".".join(str(part) for part in error["loc"]),
            "msg": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]


def _read_yaml(path: Path) -> Any:
    if not path.is_file():
        raise SourcesConfigError(f"{path.name} not found in the crawler folder", [])
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SourcesConfigError(
            f"{path.name} is not valid YAML", [{"loc": path.name, "msg": "invalid YAML"}]
        ) from exc


def load_sources_config(crawler_dir: Path) -> SourcesFile:
    try:
        return SourcesFile.model_validate(_read_yaml(crawler_dir / SOURCES_FILE))
    except ValidationError as exc:
        raise SourcesConfigError(f"{SOURCES_FILE} is invalid", _validation_details(exc)) from exc


def load_companies_file(crawler_dir: Path) -> CompaniesFile:
    try:
        return CompaniesFile.model_validate(_read_yaml(crawler_dir / COMPANIES_FILE))
    except ValidationError as exc:
        raise SourcesConfigError(f"{COMPANIES_FILE} is invalid", _validation_details(exc)) from exc


# Implemented sources; real ones are added in Phase 10.
IMPLEMENTED: dict[str, Callable[[Path], JobSource]] = {
    "mock_ats": MockAtsSource,
    "mock_feed": MockFeedSource,
}


def skip_reason(source: SourceConfig, *, mock_mode: bool) -> str | None:
    """Why ``source`` does not run in a discovery (None when it runs)."""
    if source.policy is SourcePolicy.MANUAL_ONLY:
        return "manual only: jobs arrive through /jobs/import (pasted URLs, job-alert emails)"
    if source.policy is SourcePolicy.DISABLED:
        return "policy: disabled"
    if not source.enabled:
        phase = f" (implemented in Phase {source.available_from_phase})"
        return "disabled in crawler/sources.yaml" + (phase if source.available_from_phase else "")
    if source.mock and not mock_mode:
        return "mock source: runs only with MOCK_MODE=true"
    if not source.mock and mock_mode:
        return "real source: not contacted while MOCK_MODE=true"
    if source.key not in IMPLEMENTED:
        return f"not implemented yet (Phase {source.available_from_phase or 10})"
    return None


class SourceRegistry:
    def __init__(self, config: SourcesFile, *, mock_mode: bool, fixtures_dir: Path) -> None:
        self.config = config
        self._runnable: list[JobSource] = []
        self._skipped: list[tuple[str, str]] = []
        for source in sorted(config.sources, key=lambda item: -item.priority):
            reason = skip_reason(source, mock_mode=mock_mode)
            if reason is None:
                self._runnable.append(IMPLEMENTED[source.key](fixtures_dir))
            else:
                self._skipped.append((source.key, reason))

    def runnable(self) -> list[JobSource]:
        return list(self._runnable)

    def skipped(self) -> list[tuple[str, str]]:
        return list(self._skipped)

    def source_config(self, key: str) -> SourceConfig:
        return next(source for source in self.config.sources if source.key == key)
