#!/usr/bin/env bash
# First-time setup for the AI Job Application Agent.
#   ./scripts/setup.sh        (or: make setup)
# Checks prerequisites, creates .env with generated secrets, installs all dependencies.
set -euo pipefail
cd "$(dirname "$0")/.."

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

info "Checking prerequisites"
command -v python3 >/dev/null || fail "python3 (3.11+) is required"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || fail "Python 3.11 or newer is required (found $(python3 --version))"
command -v uv >/dev/null \
  || fail "uv is required: curl -LsSf https://astral.sh/uv/install.sh | sh  (https://docs.astral.sh/uv/)"
command -v node >/dev/null || fail "Node.js 20.9+ is required (https://nodejs.org)"
node -e 'const [a, b] = process.versions.node.split(".").map(Number); process.exit(a > 20 || (a === 20 && b >= 9) ? 0 : 1)' \
  || fail "Node.js 20.9 or newer is required (found $(node --version))"
command -v npm >/dev/null || fail "npm is required"
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  info "Docker Compose found: $(docker compose version --short 2>/dev/null || echo available)"
else
  warn "Docker Compose not found — use the native setup (PostgreSQL 16 + Redis 7 installed locally)."
fi

info "Creating .env (an existing .env is never overwritten)"
python3 scripts/generate_env.py

info "Installing the Python workspace (backend + workers + dev tools)"
uv sync --all-packages

info "Installing frontend dependencies"
npm --prefix frontend ci

info "Installing the E2E test runner"
npm --prefix playwright ci

cat <<'EOF'

Setup complete.

  Docker (recommended):   make up            → http://localhost:3000
  Native:                 make infra-up      (or your own PostgreSQL + Redis, see README)
                          make migrate && make backend / make worker / make frontend
  Tests:                  make test          (needs PostgreSQL + Redis)

Optional: add ANTHROPIC_API_KEY to .env (used from Phase 4); `make n8n` for the n8n layer.
EOF
