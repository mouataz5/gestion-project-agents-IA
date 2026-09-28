# AI Job Application Agent

A self-hosted platform that discovers newly posted AI/ML/GenAI jobs, analyses them (visa
sponsorship, relevance), builds a **truthful**, ATS-optimised CV for each qualifying job, prepares
the application in the company's own ATS — and **stops before submitting** until you approve.

> **Status: Phase 2 of 11 — Candidate profile & master CV** (Phase 1, the foundation, is complete).
> See [`progress.md`](progress.md) and the [implementation plan](docs/implementation-plan.md).

**Safe by default:** `MOCK_MODE=true` (fake jobs and mock ATS pages only) and `AUTO_SUBMIT=false`
(every application needs your explicit approval). The system never bypasses CAPTCHA, MFA or
anti-bot protections — it reports **"Manual action required."** instead.

| Document | Content |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Components, pipeline, data model, interfaces, decisions (ADRs) |
| [docs/implementation-plan.md](docs/implementation-plan.md) | The 11 phases, tests-first lists, acceptance criteria |
| [docs/security.md](docs/security.md) | Threat model, secrets, logging policy, automation ethics |
| [tests.json](tests.json) | Every test with its feature and status, plus planned tests |
| [progress.md](progress.md) | What is done, decisions, next steps |

---

## Prerequisites

- **Docker** with Docker Compose v2 (recommended path), and/or
- **Python 3.11+** with [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Node.js 20.9+** (22 recommended) with npm
- GNU Make (Linux/macOS; on Windows use **WSL2**)

## 1. Install

```bash
git clone https://github.com/mouataz5/gestion-project-agents-IA.git
cd gestion-project-agents-IA
make setup          # checks prerequisites, creates .env, installs Python + frontend + E2E deps
```

`make setup` runs the individual steps, which you can also call yourself:
`make env`, `make install-python` (`uv sync --all-packages`), `make install-frontend`, `make install-e2e`.

## 2. Configure

```bash
make env            # creates .env from .env.example with generated secrets (never overwrites)
```

`.env` is git-ignored. It contains a random `API_AUTH_TOKEN`, a Fernet `ENCRYPTION_KEY` and a
database password. Every variable is documented in [`.env.example`](.env.example). Optional now:
`ANTHROPIC_API_KEY` (used from Phase 4).

## 3. Start (Docker — recommended)

```bash
make up             # = docker compose up -d --build
make ps             # service status and health
make logs           # follow logs
```

| URL | What |
|---|---|
| http://localhost:3000 | Dashboard |
| http://localhost:8000/docs | API documentation (OpenAPI) |
| http://localhost:8000/api/v1/health/ready | Readiness (database, migrations, Redis, storage) |

All ports are bound to `127.0.0.1`. Stop with `make down` (data is kept; `docker compose down -v`
deletes it).

## 4. Run migrations

With Docker, the `migrate` service applies migrations automatically before the API and worker
start. Natively (or to re-run them):

```bash
make migrate                                   # = uv run alembic -c backend/alembic.ini upgrade head
make migration m="add candidate tables" rev=0002   # create a new migration (autogenerate)
```

## 5. Run tests

```bash
make infra-up       # PostgreSQL + Redis in Docker (skip if you run them natively)
make test           # backend + worker tests (pytest) and frontend unit tests (Vitest)
make lint           # Ruff, Black, ESLint, Prettier
make typecheck      # mypy --strict, TypeScript
make test-e2e       # browser E2E tests (Playwright) against a running stack
make tests-json     # run every suite and regenerate tests.json
```

E2E tests that change data (upload and confirm a CV, edit the profile) run only with
`E2E_ALLOW_MUTATIONS=1` — use it against a throwaway stack, never against your own data.

Integration tests create and drop their own temporary PostgreSQL database; they use
`TEST_DATABASE_URL` if set, otherwise the `DATABASE_URL` from `.env`. For the E2E tests, install the
browser once with `make e2e-browsers`.

## 6. Run in mock mode

Mock mode is the default. To force it regardless of `.env`:

```bash
make mock           # = MOCK_MODE=true AUTO_SUBMIT=false docker compose up -d --build
```

In Phase 1, mock mode is the enforced safety posture (visible as a **MOCK MODE** badge on every
page). The mock job source (Phase 3) and mock ATS sites (Phase 8) plug into this switch.

## 7. Start the frontend (native)

```bash
make frontend       # Next.js dev server on http://localhost:3000 (reads .env)
```

## 8. Start the backend (native)

```bash
make infra-up       # or your own PostgreSQL 16 + Redis 7 matching DATABASE_URL / REDIS_URL
make migrate
make backend        # API with auto-reload on http://localhost:8000
make worker         # Celery worker (second terminal)
```

## 9. Run the scheduler

The daily 08:00 (Africa/Tunis) pipeline scheduler — Celery beat — is delivered in **Phase 11**.
`make scheduler` is reserved for it and currently explains that. Until then, runs are started on
demand from the dashboard ("Run system diagnostic") or the API (`POST /api/v1/runs/diagnostic`).

## Optional: n8n (free, self-hosted)

```bash
make n8n            # n8n Community Edition on http://localhost:5678
```

n8n is an optional integration layer (notifications to any channel, job-alert email ingestion,
Google Sheets…). The core never depends on it. See [`n8n/README.md`](n8n/README.md).

---

## Your profile and master CV (Phase 2)

1. **Profile** — open http://localhost:3000/candidate. On first use the profile is imported from
   [`candidate/profile.yaml`](candidate/profile.yaml) (plus `candidate/profile.local.yaml` if you
   create one; it is git-ignored). Fields that need your input (email, phone, notice period, salary
   expectations, languages…) are highlighted; they are never guessed. Contact details are stored in
   the local database only and left out of YAML exports unless you ask for them.
2. **Master CV** — open http://localhost:3000/cv and drop your CV (`.docx` or text-based `.pdf`,
   up to `MAX_UPLOAD_MB`, 10 pages). It is parsed without AI into a draft: check the experience,
   education, projects and skills, fix anything the parser missed, then **Confirm as master CV**.
3. The confirmed version becomes the only source of facts for every later step. The Candidate page
   then shows, for each skill, whether the CV **demonstrates** it (experience/projects), only
   **lists** it, or has **no evidence** (such skills are never used for tailoring). To change a
   confirmed CV, click **Revise** (it creates a new draft) or upload a new version.

The original file is stored under `storage/candidates/…` (Docker: the `appstorage` volume), never in
Git. API: `/api/v1/candidate`, `/api/v1/candidate/skills`, `/api/v1/candidate/master-cv` (see
http://localhost:8000/docs).

## What Phase 2 delivers

- **Profile**: strict schema (unknown keys and wrong types rejected with field paths), YAML
  import/export with a private local override, versioned edits (conflicts detected), audit trail.
- **Master CV**: validated uploads (type, magic bytes, size, ZIP bombs, macros), deterministic
  DOCX/PDF parser for English and French CVs (sections, entries, dates with month/year precision,
  current roles, skills, languages, certifications), review editor, immutable confirmed versions and
  revisions, content-addressed storage.
- **Skill evidence**: declared and CV skills classified as demonstrated / listed / no evidence, with
  the CV excerpts that support them.

## What Phase 1 delivers

- **Backend** (FastAPI, SQLAlchemy 2, Alembic, PostgreSQL): validated configuration with safe
  defaults and production rules; structured JSON logging with secret redaction and request IDs;
  consistent error envelope; error-tracking abstraction; bearer-token API auth; encrypted-secret
  helper; storage abstraction; health (`/health/live`, `/health/ready`), system info/status,
  automation runs with event timelines, append-only audit log (enforced by a DB trigger).
- **Workers** (Celery + Redis): JSON-only, late-ack task queue; `system.run_diagnostic` records an
  end-to-end self-test run.
- **Frontend** (Next.js 16, TypeScript, Tailwind): dashboard with safety badges and component
  health, runs list and live run timelines, settings (secrets shown only as configured/not set);
  the API token stays on the server.
- **Infrastructure**: Docker images (non-root), Docker Compose (with optional n8n), Makefile,
  setup scripts, GitHub Actions CI (lint, types, tests, Docker stack + browser E2E).

## Project layout

```
backend/     FastAPI app + domain code (package `app`), Alembic migrations, tests
workers/     Celery worker package (`job_agent_workers`)
frontend/    Next.js dashboard
playwright/  browser E2E tests (mock ATS sites from Phase 8)
crawler/     job source configuration and fixtures (Phase 3+)
prompts/     versioned LLM prompts (Phase 4+)
candidate/   profile.yaml and the (git-ignored) master CV
storage/     runtime files for native runs (git-ignored; Docker uses the `appstorage` volume)
n8n/         optional n8n integration layer
scripts/     setup, .env generation, OpenAPI export, tests.json update, E2E sample CV
docker/      Dockerfiles
docs/        architecture, implementation plan, security
```

## Troubleshooting

- **Port already in use** — override in `.env` or the shell: `POSTGRES_PORT`, `REDIS_PORT`,
  `BACKEND_PORT`, `FRONTEND_PORT`, `N8N_PORT` (e.g. `BACKEND_PORT=18000 make up`).
- **Readiness returns 503** — `/api/v1/system/status` (authenticated) and the dashboard show which
  component is down and why; a system diagnostic run records the details.
- **Integration tests are skipped** — PostgreSQL/Redis are not reachable; run `make infra-up`
  (set `REQUIRE_INTEGRATION=1` to make them fail instead of skip).
- **Generated files in Docker** live in the `appstorage` volume:
  `docker compose cp backend:/app/storage ./storage-export`.
