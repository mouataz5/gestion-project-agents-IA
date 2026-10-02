"""Exported n8n workflows are valid, wired correctly and never contain credentials."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.core.config import REPO_ROOT

pytestmark = pytest.mark.feature("job-import")

WORKFLOWS = sorted((REPO_ROOT / "n8n" / "workflows").glob("*.json"))


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_the_job_alert_workflow_is_exported() -> None:
    assert "job-alert-email-import.json" in [path.name for path in WORKFLOWS]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_workflows_are_wired_and_credential_free(path: Path) -> None:
    workflow = _load(path)
    names = [node["name"] for node in workflow["nodes"]]
    assert len(names) == len(set(names))
    for source, outputs in workflow["connections"].items():
        assert source in names
        for branch in outputs["main"]:
            for link in branch:
                assert link["node"] in names
    for node in workflow["nodes"]:
        for credential in node.get("credentials", {}).values():
            assert set(credential) <= {"id", "name"}  # a reference by name, never a secret
            assert credential["id"] == ""
    text = path.read_text(encoding="utf-8")
    assert "Bearer " not in text
    assert "password" not in text.lower()


def test_the_job_alert_workflow_posts_emails_to_the_import_api() -> None:
    workflow = _load(REPO_ROOT / "n8n" / "workflows" / "job-alert-email-import.json")
    http = next(node for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.httpRequest")

    assert http["parameters"]["method"] == "POST"
    assert http["parameters"]["url"].endswith("/api/v1/jobs/import/email")
    assert http["parameters"]["genericAuthType"] == "httpHeaderAuth"
