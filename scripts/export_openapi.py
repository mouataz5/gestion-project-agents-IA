"""Export the backend OpenAPI schema; the frontend generates its API types from it.

Usage (from the repository root):
    uv run python scripts/export_openapi.py [OUTPUT_PATH]
    npm --prefix frontend run gen:api          # regenerates src/lib/api/schema.d.ts

`make openapi` runs both steps.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.core.config import Settings
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "frontend" / "src" / "lib" / "api" / "openapi.json"


def main() -> None:
    output = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_OUTPUT
    # No .env: the schema must not depend on local configuration.
    settings = Settings(_env_file=None, log_level="WARNING")
    schema = create_app(settings).openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"OpenAPI schema written to {output.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
