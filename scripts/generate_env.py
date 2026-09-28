#!/usr/bin/env python3
"""Create `.env` from `.env.example` with strong, random secrets.

Generates API_AUTH_TOKEN, ENCRYPTION_KEY (Fernet), POSTGRES_PASSWORD (and the matching
DATABASE_URL) and N8N_ENCRYPTION_KEY. Uses only the standard library so it can run before any
dependency is installed. Never overwrites an existing file unless --force is given.

Usage:
    python3 scripts/generate_env.py [--output .env] [--force]
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_ASSIGNMENT = re.compile(r"^(?P<key>[A-Z][A-Z0-9_]*)=(?P<value>.*)$")


def _fernet_key() -> str:
    # A Fernet key is 32 random bytes, url-safe base64 encoded.
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def generate(template: Path, output: Path, *, force: bool = False) -> Path:
    if output.exists() and not force:
        raise FileExistsError(f"{output} already exists (use --force to replace it)")

    values = {
        "API_AUTH_TOKEN": secrets.token_urlsafe(32),
        "ENCRYPTION_KEY": _fernet_key(),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "N8N_ENCRYPTION_KEY": secrets.token_hex(32),
    }
    lines = template.read_text(encoding="utf-8").splitlines()
    current = {
        match["key"]: match["value"].strip('"')
        for line in lines
        if (match := _ASSIGNMENT.match(line))
    }
    user = current.get("POSTGRES_USER", "jobagent")
    database = current.get("POSTGRES_DB", "jobagent")
    port = current.get("POSTGRES_PORT", "5432")
    values["DATABASE_URL"] = (
        f"postgresql+psycopg://{user}:{values['POSTGRES_PASSWORD']}@localhost:{port}/{database}"
    )

    rendered = []
    for line in lines:
        match = _ASSIGNMENT.match(line)
        if match and match["key"] in values:
            rendered.append(f"{match['key']}={values[match['key']]}")
        else:
            rendered.append(line)

    output.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    output.chmod(0o600)  # secrets: readable by the owner only
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--template", type=Path, default=REPO_ROOT / ".env.example")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--force", action="store_true", help="replace an existing file")
    args = parser.parse_args(argv)
    try:
        path = generate(args.template, args.output, force=args.force)
    except FileExistsError as exc:
        print(f"Skipped: {exc}", file=sys.stderr)
        return 0
    print(f"Created {path} with freshly generated secrets (permissions 600).")
    print("Review it, then add optional values such as ANTHROPIC_API_KEY when needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
