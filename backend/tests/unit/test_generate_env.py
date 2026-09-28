"""Tests for scripts/generate_env.py (the `.env` bootstrap used by `make env` / setup.sh)."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from app.core.config import REPO_ROOT, Settings

pytestmark = pytest.mark.feature("setup-scripts")


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_env", REPO_ROOT / "scripts" / "generate_env.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip('"')
    return values


def test_generated_env_contains_strong_unique_secrets(tmp_path: Path) -> None:
    script = _load_script()
    first, second = tmp_path / "a.env", tmp_path / "b.env"

    script.generate(REPO_ROOT / ".env.example", first)
    script.generate(REPO_ROOT / ".env.example", second)

    a, b = _parse(first), _parse(second)
    for key in ("API_AUTH_TOKEN", "ENCRYPTION_KEY", "POSTGRES_PASSWORD", "N8N_ENCRYPTION_KEY"):
        assert a[key], key
        assert "change-me" not in a[key]
        assert a[key] != b[key], f"{key} must be random"
    assert len(a["API_AUTH_TOKEN"]) >= 40
    assert f":{a['POSTGRES_PASSWORD']}@" in a["DATABASE_URL"]


def test_generated_env_is_accepted_by_the_application_settings(tmp_path: Path) -> None:
    script = _load_script()
    env_file = tmp_path / ".env"
    script.generate(REPO_ROOT / ".env.example", env_file)

    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]

    assert settings.mock_mode is True
    assert settings.auto_submit is False
    assert settings.encryption_key is not None
    assert not any("weak password" in warning for warning in settings.security_warnings())
    # The generated secrets are strong enough for production mode as well.
    Settings(_env_file=env_file, app_env="production", log_format="json")  # type: ignore[call-arg]


def test_existing_env_is_never_overwritten_without_force(tmp_path: Path) -> None:
    script = _load_script()
    env_file = tmp_path / ".env"
    env_file.write_text("API_AUTH_TOKEN=keep-me\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        script.generate(REPO_ROOT / ".env.example", env_file)
    assert env_file.read_text(encoding="utf-8") == "API_AUTH_TOKEN=keep-me\n"

    script.generate(REPO_ROOT / ".env.example", env_file, force=True)
    assert "keep-me" not in env_file.read_text(encoding="utf-8")
