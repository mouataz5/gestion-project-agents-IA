"""Versioned prompt files: latest version, explicit versions, hashes, shipped prompt rules."""

import hashlib
import re
from pathlib import Path

import pytest

from app.core.config import REPO_ROOT
from app.llm.prompts import PromptNotFoundError, PromptRegistry

pytestmark = pytest.mark.feature("llm-provider")


def test_the_latest_version_is_loaded_with_its_hash(tmp_path: Path) -> None:
    (tmp_path / "job_analysis.v1.md").write_text("first", encoding="utf-8")
    (tmp_path / "job_analysis.v2.md").write_text("second", encoding="utf-8")
    (tmp_path / "job_analysis.v10.md").write_text("tenth", encoding="utf-8")
    (tmp_path / "README.md").write_text("not a prompt", encoding="utf-8")
    registry = PromptRegistry(tmp_path)

    latest = registry.get("job_analysis")

    assert (latest.name, latest.version, latest.text, latest.ref) == (
        "job_analysis",
        10,
        "tenth",
        "job_analysis.v10",
    )
    assert latest.sha256 == hashlib.sha256(b"tenth").hexdigest()
    assert registry.get("job_analysis", version=1).text == "first"


@pytest.mark.parametrize("name", ["job_analysis", "../secrets", "Job-Analysis"])
def test_unknown_or_unsafe_prompt_names_are_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(PromptNotFoundError):
        PromptRegistry(tmp_path).get(name)


def test_an_unknown_version_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "job_analysis.v1.md").write_text("first", encoding="utf-8")

    with pytest.raises(PromptNotFoundError):
        PromptRegistry(tmp_path).get("job_analysis", version=2)


def test_the_shipped_job_analysis_prompt_states_the_rules() -> None:
    prompt = PromptRegistry(REPO_ROOT / "prompts").get("job_analysis")

    text = prompt.text.lower()
    for rule in ("untrusted", "verbatim", "relocation", "never invent", "candidate_skill"):
        assert rule in text, rule
    assert not re.search(r"sk-ant-|api[_ -]?key|password", text)
