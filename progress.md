# Progress

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: Docker, PostgreSQL, FastAPI, Next.js, configuration, logging, health checks, migrations | ✅ done |
| 2 | Candidate profile, master CV upload & parsing, candidate database | ✅ done |
| 3 | Job model, discovery abstraction, mock source, deduplication, 24-hour filter | ✅ done |
| 4 | LLM provider (Claude), job analysis, visa classification, matching | ⏳ next |
| 5 | ATS engine, tailoring, iterative optimization | ⏳ planned |
| 6 | DOCX/PDF generation | ⏳ planned |
| 7 | Application question engine | ⏳ planned |
| 8 | Playwright, mock ATS, browser adapters | ⏳ planned |
| 9 | Human approval workflow | ⏳ planned |
| 10 | Real public career/ATS integrations | ⏳ planned |
| 11 | Scheduling, notifications, dashboard, hardening | ⏳ planned |

## Test status (from `tests.json`)

732 tests, **all passing, none skipped**: 590 backend (unit, API, PostgreSQL/Redis integration),
11 workers, 113 frontend (Vitest), 18 browser E2E (Playwright, including the data-changing CV and
job discovery workflows). 55 tests are planned for Phases 4–11.

## Phase 3 — what was delivered

- **Data model** (migration `0003`): `companies` (watchlist), `job_sources`, `jobs` (every spec §7
  field + posting-date status/basis, canonical URL, duplicate link, last seen, discovery run),
  `job_skills`, `applications` (spec §18, 14 statuses, transition table with audit).
- **Sources**: `crawler/sources.yaml` (validated policy: `api_only` / `allowed` / `manual_only` /
  `disabled`, priority, rate limit, notes) mirrored into `job_sources`; registry with skip reasons;
  `JobSource` / `CompanyBoardSource` protocols and a shared `build_job()`; mock ATS boards (one per
  watchlist company) and a mock aggregator feed, run only with `MOCK_MODE=true`. Real sources are
  declared but disabled until Phase 10; LinkedIn is `manual_only`.
- **Normalization** (`app/jobs/`): canonical URLs (tracking parameters, LinkedIn/Indeed ids, ATS
  apply pages), SSRF-safe URL validation, content hash, EN/FR relative dates with conservative
  bounds, inclusive posting window, remote/employment/seniority/country detection, HTML → text,
  AI/ML title pre-filter, job links in alert emails.
- **Deduplication**: source id, canonical URL, content hash; primary record from the highest-priority
  source, with take-over (duplicates and applications re-pointed).
- **Discovery run**: worker task `jobs.run_discovery`, `POST /runs/discovery`; per-source events and
  status, watchlist checks, summary totals, failures isolated (`PARTIAL_SUCCESS`); `DISCOVERED`
  applications for primary, in-window jobs in target countries; unknown dates are never "recent" and
  can be tracked by hand.
- **Imports**: `POST /jobs/import` (pasted URL + details, never fetched) and
  `POST /jobs/import/email` (job-alert emails); n8n workflow `job-alert-email-import.json`.
- **Compliance building blocks**: `RobotsPolicy` (RFC 9309) and a Redis per-domain token-bucket
  `RateLimiter`, tested now, wired into the Phase 10 fetchers.
- **API**: `/jobs` (filters, pagination), `/jobs/stats`, `/jobs/{id}`, `/jobs/{id}/track`,
  `/job-sources`, `/companies` CRUD + `/companies/import`; every change audited.
- **Frontend**: `/jobs` (window tabs, filters, date-status badges, sources table, import dialog,
  run button), `/jobs/[id]` (posting-date basis, other listings, pipeline, raw data),
  `/companies` (CRUD dialog, enable switch, YAML import), dashboard discovery card.
- **Docs**: architecture §9 and §13, ADRs 30–37, security (SSRF, compliance), crawler and n8n
  READMEs, README usage section.

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

## Verification performed — Phase 3 (2026-10-02)

- `ruff`, `black --check`, `mypy --strict` (114 files), ESLint, Prettier, `tsc` — all green;
  `make tests-json`: 732 passed, 0 failed, 0 skipped.
- Migration `0003`: autogenerated against a scratch database, hand-cleaned, `alembic check` reports
  no drift, downgrade/upgrade round trip; applied on the Docker stack (`0002 → 0003`).
- **Discovery** (exact counts asserted by tests, fixed clock): 19 postings fetched, 3 non-AI titles
  filtered, 14 new jobs + 2 duplicate listings (tracking parameters, identical content), 9 in the
  window, 4 older, 1 unknown date, 1 outside the target countries, 8 queued; a second run updates
  16 and queues nothing; a failing source gives `PARTIAL_SUCCESS`; live mode never runs mock sources.
- **Browser** (native stack and Docker stack): import the watchlist → run discovery → jobs with date
  badges → unknown-date tab → filters → detail with other listings → track → LinkedIn URL import →
  company edit; 18/18 Playwright tests with `E2E_ALLOW_MUTATIONS=1`. Pages reviewed in light and dark
  mode (fixed: posting-date card spacing, source ordering, product-name labels, link wrapping).
- **Docker**: job-alert email import through the API (1 job link found, tracking removed), cloud
  metadata URL rejected (422), no traceback or token in the backend/worker logs.

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

### 2026-10-02 — Phase 3 completed
- "go ahead with Phase 3": plan approved; tests written first (URLs, dates, window, normalization,
  sources/companies YAML, robots, rate limiter, lifecycle, dedup matrix, discovery with exact
  counts, jobs/companies/import APIs, worker, n8n export), then the implementation.
- Design choices (ADRs 30–37): global jobs and per-candidate applications; source-priority primary
  records with take-over; conservative estimated dates; deterministic queueing rules (unknown
  dates tracked by hand, imports always queued); versioned source policy with mock isolation;
  imports never fetched and never guessed; email parsing in the core with n8n as transport;
  failures isolated per source, board and posting.
- Found and fixed while building: deprecated `Result.tuples()` in SQLAlchemy 2.1; generated
  TypeScript types marking defaulted job fields optional; an E2E test that could not be re-run on
  an existing database.

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

## Needed from you (not blocking Phase 4)

- Upload your real master CV at `/cv`, review the draft and confirm it (it stays out of Git).
- Fill in the highlighted fields at `/candidate`: email, phone, notice period, salary expectations,
  earliest start date, spoken languages, preferred work modes.
- Replace the fictional watchlist with the companies you follow at `/companies` (name, career URL,
  ATS and board token); their real boards are read from Phase 10.
- Optional: import `n8n/workflows/job-alert-email-import.json` into n8n and connect the mailbox that
  receives your LinkedIn/Indeed job alerts.
- Phase 4 calls the Claude API: an `ANTHROPIC_API_KEY` in `.env` will be needed for real analysis
  (mock mode works without it).

## Known limitations

- No scheduler yet (Phase 11): runs are started on demand (dashboard/API).
- Dashboard pipeline KPIs (applications, interviews, offers) arrive with the phases producing them.
- Only mock sources run in Phase 3; real ATS APIs, career pages and feeds arrive in Phase 10.
  Imported URLs are stored, not fetched, so their description stays empty unless provided.
- The title pre-filter is keyword-based; relevance and visa analysis arrive in Phase 4.
- Scanned (image-only) PDFs are rejected: OCR is out of scope. Multi-column PDF layouts may
  interleave columns; DOCX gives the best results. The draft review step exists for these cases.
- The parser recognises English and French section headings; other languages need manual review.
- Deleting CV versions and exporting/deleting all personal data arrive in Phase 11.

## Next step

Phase 4 — LLM provider (Claude), job analysis, visa classification and matching.
Waiting for the go-ahead.
