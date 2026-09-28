# Progress

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: Docker, PostgreSQL, FastAPI, Next.js, configuration, logging, health checks, migrations | ✅ done |
| 2 | Candidate profile, master CV upload & parsing, candidate database | ⏳ next |
| 3 | Job model, discovery abstraction, mock source, deduplication, 24-hour filter | ⏳ planned |
| 4 | LLM provider (Claude), job analysis, visa classification, matching | ⏳ planned |
| 5 | ATS engine, tailoring, iterative optimization | ⏳ planned |
| 6 | DOCX/PDF generation | ⏳ planned |
| 7 | Application question engine | ⏳ planned |
| 8 | Playwright, mock ATS, browser adapters | ⏳ planned |
| 9 | Human approval workflow | ⏳ planned |
| 10 | Real public career/ATS integrations | ⏳ planned |
| 11 | Scheduling, notifications, dashboard, hardening | ⏳ planned |

## Test status (from `tests.json`)

231 tests, **all passing, none skipped**: 165 backend (unit, API, PostgreSQL/Redis integration),
8 workers, 53 frontend (Vitest), 5 browser E2E (Playwright). 80 tests are planned for Phases 2–11.

## Phase 1 — what was delivered

- **Docs**: architecture (context, containers, pipeline A–E, interfaces, data model for all
  entities, application state machine, ATS/truthfulness design, compliance, observability,
  21 ADRs), implementation plan (11 phases, tests-first lists, acceptance criteria), security.
- **Backend** (`backend/`, package `app`): validated `Settings` with safe defaults and production
  rules; structlog JSON/console logging with central secret redaction; request IDs + access log;
  error envelope; `ErrorTracker`; bearer-token auth; Fernet `SecretBox`; traversal-safe
  `LocalStorageProvider`; Celery `TaskQueue` abstraction; SQLAlchemy 2.1 models and Alembic
  migration `0001` (`automation_runs`, `automation_run_events`, append-only `audit_logs` enforced
  by a trigger); services for health, run lifecycle, audit and diagnostics; API
  `/health/live|ready`, `/system/info|status`, `/runs`, `/runs/{id}`, `POST /runs/diagnostic`,
  `/audit-logs`; OpenAPI docs at `/docs`.
- **Workers** (`workers/`, package `job_agent_workers`): Celery app (JSON only, late acks),
  logging/error-tracking signals, fork-safe runtime, `system.ping`, `system.run_diagnostic`.
- **Frontend** (`frontend/`): Next.js 16 dashboard (safety badges, component health, pipeline
  configuration, recent runs, run diagnostic, roadmap), runs list/filters/pagination, live run
  timeline, settings (secrets only as configured/not set), server-side API proxy, generated API types.
- **Infrastructure**: backend/frontend Dockerfiles (non-root), Docker Compose (postgres, redis,
  migrate, backend, worker, frontend, optional n8n), Makefile, `scripts/setup.sh`,
  `scripts/generate_env.py`, `scripts/export_openapi.py`, `scripts/update_tests_json.py`,
  GitHub Actions CI (lint, types, tests, Docker stack + E2E).

## Verification performed (2026-09-28)

- `make lint`, `make typecheck` (mypy strict, 61 files; tsc), `make test` — all green.
- **Docker**: both images built from the repository Dockerfiles; `docker compose up` brought
  postgres, redis, migrate, backend, worker and frontend up healthy; readiness 200; a diagnostic
  started through the dashboard proxy completed `SUCCEEDED`; Playwright E2E 5/5 against the stack.
  (Sandbox note: the images were built on local base images carrying this sandbox's HTTPS-proxy
  CA; the Dockerfiles themselves are unmodified and CI builds them on standard infrastructure.)
- **Native**: `make migrate`, `make backend`, `make worker`, `make frontend`; Playwright E2E 5/5.
- A real Celery worker processed a diagnostic through the Redis broker (not only eager mode).

## Log

### 2026-09-28 — Phase 1 completed
- Inspected the repository: empty apart from `.gitattributes` (initial commit).
- Wrote the architecture, implementation plan, security documents, `tests.json` (80 planned tests
  for Phases 2–11) and this file; created `candidate/profile.yaml` from the provided data
  (unknowns left `null`, never invented).
- User request: "use n8n if it works well and is free" → adopted n8n Community Edition
  (self-hosted, free) as an **optional integration layer** (notifications, job-alert email
  ingestion, extras); the core stays in tested Python code (ADR 16, architecture §19). The n8n
  service is ready (`make n8n`); workflows arrive with Phases 3/10/11.
- Bugs found and fixed during verification (each covered by a test or recorded as an ADR):
  unstable ordering from transaction timestamps (ADR 20); task publishing blocking ~20 s when
  Redis is down (ADR 17); non-writable bind-mounted storage for the non-root containers (ADR 18);
  empty `.env` values breaking validation (ADR 21); squashed status badges and acronym labels in
  the UI.

## Decisions to confirm with the user

1. The repository root is the `job-agent/` monorepo root (no extra `job-agent/` folder) — ADR 1.
2. Default LLM model `claude-opus-5` (most capable); switchable with `CLAUDE_MODEL` — ADR 13.
3. A user "Skip" maps to status `WITHDRAWN` with a reason (the requested status list has no
   `SKIPPED`) — ADR 14.
4. `AUTO_SUBMIT=true` is interpreted as "submit without per-application approval only when every
   strict criterion passes" (still never with CAPTCHA/MFA or on sites that disallow automation).

## Known limitations

- No scheduler yet (Phase 11): runs are started on demand (dashboard/API).
- Dashboard pipeline KPIs (jobs, applications, interviews) arrive with the phases producing them.
- The CI workflow runs on GitHub after push; its first result should be checked on the branch.

## Next step

Phase 2 — candidate profile schema and UI, master CV upload and parsing, candidate tables.
Waiting for the go-ahead.
