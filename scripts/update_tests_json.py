"""Regenerate tests.json from real test runs.

* Backend + workers: pytest with the `--tests-json-report` option (feature = `feature` marker).
* Frontend: Vitest JSON reporter (feature = `frontend-<test file name>`).
* E2E: the Playwright JSON report of the last `make test-e2e` run, if present.

The hand-maintained "planned" section of tests.json is preserved. Exits non-zero when any test
failed, after writing the file, so failures are never hidden.

Usage (from the repository root):  uv run python scripts/update_tests_json.py [--skip-frontend]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO_ROOT / ".artifacts"
TESTS_JSON = REPO_ROOT / "tests.json"
PYTEST_REPORT = ARTIFACTS / "pytest-results.json"
VITEST_REPORT = ARTIFACTS / "vitest-results.json"
PLAYWRIGHT_REPORT = ARTIFACTS / "playwright-results.json"

Entry = dict[str, Any]


def run_pytest() -> list[Entry]:
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", f"--tests-json-report={PYTEST_REPORT}"],
        cwd=REPO_ROOT,
        check=False,
    )
    entries: list[Entry] = json.loads(PYTEST_REPORT.read_text(encoding="utf-8"))
    return entries


def run_vitest() -> list[Entry]:
    subprocess.run(
        [
            "npm",
            "--prefix",
            "frontend",
            "run",
            "test",
            "--",
            "--reporter=default",
            "--reporter=json",
            f"--outputFile.json={VITEST_REPORT}",
        ],
        cwd=REPO_ROOT,
        check=False,
    )
    report = json.loads(VITEST_REPORT.read_text(encoding="utf-8"))
    entries: list[Entry] = []
    for test_file in report.get("testResults", []):
        path = Path(test_file["name"]).relative_to(REPO_ROOT).as_posix()
        feature = "frontend-" + Path(path).name.removesuffix(".test.ts")
        for assertion in test_file.get("assertionResults", []):
            status = {"passed": "passed", "failed": "failed"}.get(assertion["status"], "skipped")
            entries.append(
                {
                    "test": f"{path}::{assertion['fullName']}",
                    "feature": feature,
                    "suite": "frontend",
                    "status": status,
                }
            )
    return entries


def read_playwright() -> list[Entry]:
    if not PLAYWRIGHT_REPORT.exists():
        return []
    report = json.loads(PLAYWRIGHT_REPORT.read_text(encoding="utf-8"))
    recorded_at = datetime.fromtimestamp(PLAYWRIGHT_REPORT.stat().st_mtime, UTC).isoformat()
    entries: list[Entry] = []

    def feature_of(titles: list[str]) -> str:
        # The top-level suite is the spec file: "candidate.spec.ts" -> "e2e-candidate".
        spec_file = titles[0] if titles else ""
        return f"e2e-{spec_file.split('.')[0]}" if spec_file else "e2e"

    def walk(suite: dict[str, Any], titles: list[str]) -> None:
        for spec in suite.get("specs", []):
            outcomes = {test.get("status") for test in spec.get("tests", [])}
            if spec.get("ok") and outcomes <= {"expected", "flaky"}:
                status = "passed"
            elif outcomes == {"skipped"}:
                status = "skipped"
            else:
                status = "failed"
            entries.append(
                {
                    "test": " > ".join([*titles, spec["title"]]),
                    "feature": feature_of(titles),
                    "suite": "e2e",
                    "status": status,
                    "recorded_at": recorded_at,
                }
            )
        for child in suite.get("suites", []):
            walk(child, [*titles, child["title"]] if child.get("title") else titles)

    for suite in report.get("suites", []):
        walk(suite, [suite["title"]] if suite.get("title") else [])
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate tests.json from real test runs")
    parser.add_argument("--skip-frontend", action="store_true")
    args = parser.parse_args()
    ARTIFACTS.mkdir(exist_ok=True)

    tests = run_pytest()
    if not args.skip_frontend:
        tests += run_vitest()
    tests += read_playwright()

    previous = json.loads(TESTS_JSON.read_text(encoding="utf-8")) if TESTS_JSON.exists() else {}
    planned = previous.get("planned", [])
    counts = Counter(entry["status"] for entry in tests)
    document = {
        "description": previous.get("description", "Test tracking"),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "summary": {
            "total": len(tests),
            "passed": counts.get("passed", 0),
            "failed": counts.get("failed", 0) + counts.get("error", 0),
            "skipped": counts.get("skipped", 0),
            "planned": len(planned),
            "by_suite": dict(sorted(Counter(entry["suite"] for entry in tests).items())),
        },
        "tests": sorted(tests, key=lambda entry: (entry["suite"], entry["feature"], entry["test"])),
        "planned": planned,
    }
    TESTS_JSON.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    summary = document["summary"]
    print(
        f"tests.json: {summary['passed']} passed, {summary['failed']} failed, "
        f"{summary['skipped']} skipped, {summary['planned']} planned"
    )
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
