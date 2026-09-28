# Progress

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: Docker, PostgreSQL, FastAPI, Next.js, configuration, logging, health checks, migrations | ✅ done |
| 2 | Candidate profile, master CV upload & parsing, candidate database | ✅ done |
| 3 | Job model, discovery abstraction, mock source, deduplication, 24-hour filter | ⏳ next |
| 4 | LLM provider (Claude), job analysis, visa classification, matching | ⏳ planned |
| 5 | ATS engine, tailoring, iterative optimization | ⏳ planned |
| 6 | DOCX/PDF generation | ⏳ planned |
| 7 | Application question engine | ⏳ planned |
| 8 | Playwright, mock ATS, browser adapters | ⏳ planned |
| 9 | Human approval workflow | ⏳ planned |
| 10 | Real public career/ATS integrations | ⏳ planned |
| 11 | Scheduling, notifications, dashboard, hardening | ⏳ planned |

## Test status (from `tests.json`)

435 tests, **all passing, none skipped**: 328 backend (unit, API, PostgreSQL/Redis integration),
8 workers, 89 frontend (Vitest), 10 browser E2E (Playwright, including the data-changing CV
workflow). 69 tests are planned for Phases 3–11.

## Phase 2 — what was delivered

- **Profile**: strict schema (`app/schemas/candidate.py`) with dotted error paths; YAML loader with
  git-ignored `profile.local.yaml` deep-merge; the database holds the live profile (auto-import of
  the `default` candidate, explicit import/export, private contact hidden from default exports);
  `needs_user_input`; optimistic concurrency (`profile_version`, 409); audited edits (section names
  only).
- **Master CV** (`app/cv/`): upload validation (allow-list, magic bytes, `MAX_UPLOAD_MB`, ZIP bomb /
  encryption / macro checks, 10 pages); deterministic DOCX/PDF parser for English and French CVs
  (sections, entries, dates with month/year precision and current roles, skills with categories,
  languages, certifications, contact, unknown sections kept, warnings); property-tested
  no-invention guarantee; content-addressed storage.
- **Lifecycle**: `PARSED` drafts edited by the user → `CONFIRMED` (rebuilds `experiences`,
  `educations`, `projects` and skill evidence in one transaction; the previous master becomes
  `SUPERSEDED`; one active master enforced by a partial unique index) → `revise` → new draft.
- **Skill evidence**: `DEMONSTRATED` / `LISTED` / `NONE` with synonyms, word boundaries and excerpts.
- **API**: `/candidate` (GET/PUT), `/candidate/import`, `/candidate/export`, `/candidate/skills`,
  `/candidate/master-cv` (upload, list, detail, file, structure, confirm, revise). Migration `0002`.
- **Frontend**: `/candidate` profile editor and skill evidence panel; `/cv` upload, versions, review
  editor, confirm/revise, read-only view; proxy body limit follows `MAX_UPLOAD_MB`, downloads keep
  their filename.
- **Docs**: ADRs 22–29, architecture §8.1 (candidate facts), security §7.1, README usage section.

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

## Verification performed — Phase 2 (2026-09-28)

- `ruff`, `black --check`, `mypy --strict` (83 files), ESLint, Prettier, `tsc` — all green;
  `make tests-json`: 435 passed, 0 failed, 0 skipped.
- Migration `0002`: upgrade, downgrade/upgrade round trip, models-in-sync test; applied on the
  Docker stack from an empty database (`0001 → 0002`).
- **Browser** (native stack and Docker stack): upload of a synthetic DOCX → draft review → edit →
  save → confirm → skill evidence on `/candidate`; profile edit persisted; 10/10 Playwright tests
  with `E2E_ALLOW_MUTATIONS=1`. Screens reviewed visually (layout issues found and fixed: inline
  row inputs, evidence panel labels).
- **Docker**: CV stored as `candidates/<id>/master_cv/<sha256>.docx` in the `appstorage` volume;
  `candidate/` mounted read-only; no CV content in any service log (also covered by a test).

## Verification performed — Phase 1 (2026-09-28)

- `make lint`, `make typecheck` (mypy strict, 61 files; tsc), `make test` — all green.
- **Docker**: both images built from the repository Dockerfiles; `docker compose up` brought
  postgres, redis, migrate, backend, worker and frontend up healthy; readiness 200; a diagnostic
  started through the dashboard proxy completed `SUCCEEDED`; Playwright E2E 5/5 against the stack.
  (Sandbox note: the images were built on local base images carrying this sandbox's HTTPS-proxy
  CA; the Dockerfiles themselves are unmodified and CI builds them on standard infrastructure.)
- **Native**: `make migrate`, `make backend`, `make worker`, `make frontend`; Playwright E2E 5/5.
- A real Celery worker processed a diagnostic through the Redis broker (not only eager mode).

## Log

### 2026-09-28 — Phase 2 completed
- Plan approved by the user; tests written first (profile schema, upload validation, dates,
  sections, DOCX/PDF parsing, skill evidence, APIs, multi-candidate isolation), then the
  implementation.
- Design choices (recorded as ADRs 22–29): database as the live profile with YAML import/export;
  deterministic parsing without an LLM; immutable confirmed versions and revisions (invalid uploads
  are rejected, not stored as `FAILED`); partial unique index for the active master CV instead of a
  foreign-key cycle; content-addressed storage keys; derived skill evidence; opt-in data-changing
  E2E tests; required fields in response schemas for accurate TypeScript types.
- Found and fixed while verifying: company/location splitting ("Gamma Corp, Berlin, Germany"),
  job titles mistaken for locations ("Freelance ML Engineer, Remote"), full-width inputs in list
  rows, overlapping labels in the evidence panel.

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
5. The database is the live profile; `candidate/profile.yaml` is only the seed and the
   import/export format (ADR 22). Edit at `/candidate`, or edit the YAML and click "Import".
6. Master CV parsing uses no AI (ADR 23); an optional AI-assisted re-parse could be added later,
   always as a suggestion you confirm.

## Needed from you (not blocking Phase 3)

- Upload your real master CV at `/cv`, review the draft and confirm it (it stays out of Git).
- Fill in the highlighted fields at `/candidate`: email, phone, notice period, salary expectations,
  earliest start date, spoken languages, preferred work modes.

## Known limitations

- No scheduler yet (Phase 11): runs are started on demand (dashboard/API).
- Dashboard pipeline KPIs (jobs, applications, interviews) arrive with the phases producing them.
- Scanned (image-only) PDFs are rejected: OCR is out of scope. Multi-column PDF layouts may
  interleave columns; DOCX gives the best results. The draft review step exists for these cases.
- The parser recognises English and French section headings; other languages need manual review.
- Deleting CV versions and exporting/deleting all personal data arrive in Phase 11.

## Next step

Phase 3 — job model, discovery abstraction, mock source, deduplication and the 24-hour window.
Waiting for the go-ahead.
