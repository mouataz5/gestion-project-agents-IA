# Implementation Plan

The system is built in 11 incremental phases. Each phase ends with working, tested software; no phase
jumps ahead (real integrations only arrive in Phase 10, after the mock pipeline is proven end to end).
Design references point to `docs/architecture.md`.

## Process for every phase

1. Write or extend tests **before** implementing the functionality (`tests.json` → `planned` entries
   become real tests).
2. Implement until the tests pass; keep lint (Ruff, ESLint), formatting (Black, Prettier) and type
   checks (mypy, `tsc`) clean.
3. Database changes only through reviewed Alembic migrations that upgrade **and** downgrade.
4. Run the full test suite; regenerate `tests.json` (`make tests-json`); update `progress.md`.
5. Record any design deviation as an ADR in `docs/architecture.md`.
6. Commit working increments with descriptive messages; push to the working branch.

**Definition of done**: acceptance criteria met, all tests green (no test removed or weakened to pass),
docs and tracking files updated, and run instructions verified.

---

## Phase 1 — Foundation ✅

**Goal**: a production-grade skeleton every later phase plugs into.

Deliverables
- Monorepo layout; uv workspace (`backend` → package `app`, `workers` → `job_agent_workers`).
- Validated configuration (`Settings`, repo-root `.env`, `.env.example`), production safety rules,
  safe configuration summary.
- Structured logging (structlog JSON/console) with central secret redaction; request IDs; access log.
- Error envelope + handlers, `ErrorTracker` abstraction (logging implementation).
- API bearer-token auth (constant-time comparison); health endpoints are public.
- `StorageProvider` + local implementation (path-traversal safe); Fernet helper for secrets at rest.
- SQLAlchemy base (naming convention, UUID/timestamp mixins), Alembic, migration `0001_foundation`:
  `automation_runs`, `automation_run_events`, `audit_logs`.
- Services: health (database, migrations at head, Redis, storage, worker), runs (lifecycle recorder),
  audit, diagnostics (system self-test).
- API: `GET /api/v1/health/live|ready`, `GET /api/v1/system/info|status`, `GET /api/v1/runs`,
  `GET /api/v1/runs/{id}`, `POST /api/v1/runs/diagnostic`, `GET /api/v1/audit-logs`; OpenAPI docs.
- Celery app (JSON-only serialization, late acks) with `system.ping` and `system.run_diagnostic`.
- Next.js dashboard: safety badges (mock mode, auto-submit), health grid, configuration summary, recent
  runs, "Run system diagnostic", phase roadmap; `/runs`, `/runs/[id]`, `/settings`; server-side API proxy;
  OpenAPI-generated types.
- Docker Compose (postgres, redis, migrate, backend, worker, frontend, optional `n8n` profile),
  Dockerfiles, Makefile, setup scripts, CI workflow, Playwright E2E smoke test.

Tests first: configuration, redaction, logging, crypto, error tracking, storage, health aggregation,
migrations (round trip + models in sync), health/auth/request-ID/error-envelope APIs, runs API,
run lifecycle, audit log, system info/status, Celery configuration, worker tasks, API → queue → worker
path, frontend utilities and proxy, dashboard E2E.

Acceptance: `make test` green; the stack starts healthy (`/api/v1/health/ready` = 200); the dashboard
shows component health; a diagnostic run started from the UI completes `SUCCEEDED` with a visible
event timeline.

---

## Phase 2 — Candidate profile & master CV ✅

**Goal**: the candidate's facts are structured, validated, editable and stored.

Deliverables
- Strict Pydantic schema for the profile (`app/schemas/candidate.py`): unknown keys rejected, errors
  reported with dotted field paths and never echoing input; `null` = unknown. `candidate/profile.yaml`
  deep-merged with the optional git-ignored `profile.local.yaml` (lists replace, mappings merge).
- The database is the live profile (`candidates.profile` JSONB + denormalised identity columns); YAML
  is the seed (auto-import of the `default` candidate on first use) and the explicit import/export
  format. Private contact details are hidden from exports unless requested.
- `NEEDS_USER_INPUT` reporting: required-but-empty fields (contact, notice period, salary, start date,
  languages, work modes…) are listed for the user and never guessed.
- Migration `0002`: `candidates`, `cv_versions` (one active master per candidate through a partial
  unique index), `experiences`, `educations`, `projects`, `candidate_skills`;
  `automation_runs.candidate_id`.
- Master CV upload: `.docx`/`.pdf` allow-list, magic bytes, `MAX_UPLOAD_MB` (default 5), ZIP bomb /
  encryption / macro checks, 10-page limit; stored through `StorageProvider` under a generated
  content-addressed key (identical files share storage); original filename kept only as sanitised
  metadata.
- Deterministic parser (`app/cv/`, no LLM): DOCX (styles, bold, lists, tables, text boxes) and PDF
  (pdfplumber lines, font weight/size, wrapped bullets) → EN/FR sections → entries (title, employer,
  location, dates with month/year precision and "present") → skills, languages, certifications,
  contact, unknown sections kept. Property-tested: every parsed value is a substring of the document.
- Lifecycle: `PARSED` draft (editable) → `CONFIRMED` (read-only, rebuilds the fact tables and skill
  evidence in one transaction; the previous master becomes `SUPERSEDED`) → `revise` creates a new
  editable draft. Every action is audited without CV content.
- Skill evidence (`app/cv/evidence.py`): `DEMONSTRATED` (experience/project text), `LISTED` (skills,
  summary, education, certifications), `NONE` (declared only, never used for tailoring); word-boundary
  and synonym-aware matching; excerpts stored as evidence.
- API: `GET/PUT /candidate` (optimistic concurrency on `profile_version` → 409), `POST
  /candidate/import`, `GET /candidate/export`, `GET /candidate/skills`, `POST|GET
  /candidate/master-cv`, `GET /candidate/master-cv/{id}`, `GET …/{id}/file`, `PUT …/{id}/structure`,
  `POST …/{id}/confirm`, `POST …/{id}/revise`.
- UI: `/candidate` (profile editor with needs-input highlighting, YAML import/export, skill evidence)
  and `/cv` (drag-and-drop upload, versions, draft review editor, confirm/revise, download).

Tests first: profile schema (valid, unknown fields, wrong types, `null` = unknown, local override,
export privacy), upload validation (wrong/spoofed type, empty, oversize, ZIP bomb, too many entries,
filename sanitising), date ranges (EN/FR, precision, current, false positives), section headings,
DOCX/PDF parsing (layouts, wrapped bullets, warnings, no-invention property), skill evidence and
synonyms, candidate/master CV APIs (concurrency, audit, immutability, supersede, revise, dedup, auth),
multi-candidate isolation, frontend helpers and proxy, E2E upload → review → confirm → evidence.

Acceptance: profile editable in the UI and persisted; master CV uploaded, parsed, corrected and saved as
a versioned fact base. ✔ Verified natively and on the Docker stack (E2E with `E2E_ALLOW_MUTATIONS=1`).

---

## Phase 3 — Jobs, discovery abstraction, mock source, deduplication, 24-hour window

Deliverables
- Migration `0003`: `companies` (watchlist), `job_sources`, `jobs` (all spec §7 fields +
  `posting_date_status`, `canonical_url`, `duplicate_of_id`), `job_skills`, `applications`.
- `JobSource` protocol and registry; `MockJobSource` reading `crawler/fixtures/mock_jobs/`.
- Normalization, canonical URLs (tracking parameters removed), `content_hash`, deduplication
  (source id / URL / hash, cross-source linking), posting window (`posted_after`, `posted_before`,
  `JOB_LOOKBACK_HOURS`) with `KNOWN`/`ESTIMATED`/`UNKNOWN` dates — unknown dates never counted as
  "last 24 h".
- Compliance building blocks: `RobotsPolicy`, Redis per-domain rate limiter, source policy registry
  (`crawler/sources.yaml`).
- Discovery run (`AutomationRun` type `DISCOVERY`) creating `DISCOVERED` applications.
- Job import endpoint (`POST /jobs/import` — a URL pasted by the user or posted by n8n from job-alert
  emails: the permitted LinkedIn path).
- API + UI: `/jobs` (filters: last 24 h, date status, source, country), `/jobs/[id]`, `/companies` (CRUD).
- n8n: exported "job-alert email ingestion" workflow.

Tests first: normalization, canonical URL rules, hash stability, dedup matrix, window boundaries and
unknown-date handling, relative-date parsing, robots disallow respected, rate limiter, discovery
counters, watchlist CRUD, import endpoint validation.

Acceptance: in mock mode a discovery run loads fake jobs, removes duplicates, applies the window and
shows the jobs with date-status badges.

---

## Phase 4 — LLM provider, job analysis, visa classification, matching

Deliverables
- `LLMProvider` protocol; `ClaudeProvider` (official `anthropic` SDK, structured outputs validated
  against Pydantic models, adaptive thinking, refusal/stop-reason handling, timeouts/retries, token usage
  recorded, no prompt/secret logging); `MockLLMProvider` for tests/offline mock mode.
- Versioned prompts in `prompts/`; migration `0004`: `job_analyses`.
- Visa engine: phrase rules + LLM with verbatim evidence quotes; the four `SPONSORSHIP_*` statuses;
  relocation never implies sponsorship; explicit negatives win.
- Relevance engine returning the spec JSON; explicit qualification rules (`APPLY`/`REVIEW`/`SKIP`).
- Analysis stage in runs; job detail page shows "why it matches", skills, gaps, concerns, visa evidence.

Tests first: provider contract, Claude provider with mocked HTTP (success, schema mismatch, refusal,
rate limit, timeout), visa corpus (confirmed / likely / unknown / not available, relocation-only,
contradictory statements), relevance schema validation, qualification rules, prompt version recorded,
redaction of provider errors.

Acceptance: mock jobs analysed offline with the mock provider; with an API key, Claude produces valid
structured analyses with evidence.

---

## Phase 5 — ATS engine, tailoring, iterative optimisation

Deliverables
- Requirement extraction (LLM → structured) + skills taxonomy normalization (synonyms, categories).
- Deterministic, versioned scoring (keyword, skills, experience, responsibility, education, title
  alignment, formatting) → `ats_analyses` (migration `0005`) with matched / missing / unsupported
  keywords and recommendations.
- Tailoring agent producing a structured CV where every bullet references master-CV evidence.
- Truthfulness guard (employers, titles, dates, education, certifications unchanged; technologies and
  metrics must exist in the master CV).
- Iterative loop: `ATS_TARGET_SCORE=95`, `ATS_MAX_ITERATIONS=3`, stop on target, cap, or when only
  unsupported gains remain; genuine gaps reported.

Tests first: taxonomy, scoring determinism and weights, keyword classification, guard rejections (new
employer, changed dates, new technology, invented metric, new certification, title change unless
allowed), loop stop conditions, gap report, keyword-stuffing detection.

Acceptance: for each qualifying mock job, a tailored CV + ATS report with iteration history and zero
unsupported keywords.

---

## Phase 6 — DOCX / PDF generation

Deliverables
- Deterministic, ATS-friendly `python-docx` template (single column, standard headings, no tables,
  images or text boxes), template registry for future templates.
- PDF conversion with headless LibreOffice in the worker image; files stored at
  `storage/applications/{application_id}/cv/` (`master_cv`, `tailored_cv.docx`, `tailored_cv.pdf`,
  `ats_report.json`).
- Formatting checks feed the ATS formatting score; download/preview API; UI "compare with master" diff.

Tests first: DOCX structure checks, deterministic content, length limit, PDF conversion (skips locally
only if LibreOffice is missing; required in CI/Docker), storage layout, download authorization.

---

## Phase 7 — Application question engine

Deliverables
- Question extraction (form fields from the ATS page, job text), normalized question keys.
- Answers from profile + master CV + job + company information only, with cited sources; standard
  answers (visa sponsorship, work authorization, relocation, notice period, salary expectations, years of
  experience, why this role/company, relevant experience, technical questions).
- `NEEDS_USER_INPUT` for anything uncertain; approval blocked until resolved.
- Cover letter only when required or useful, under the same truthfulness guard.
- Migration `0007`: `application_answers`; answers editor UI.

Tests first: standard question mapping, unknown → `NEEDS_USER_INPUT`, years of experience computed from
CV dates, sponsorship answer consistent with profile, no uncited claims, cover letter guard.

---

## Phase 8 — Playwright, mock ATS, browser adapters

Deliverables
- `playwright/mock-ats/`: Greenhouse-like, Lever-like and generic multi-step forms, including simulated
  CAPTCHA, login wall and MFA pages; `mock-ats` Compose service.
- `BrowserProvider` (Playwright Chromium), `ApplicationBrowser` (open URL, detect ATS, navigate, fill
  text/select/checkbox/radio, upload CV/cover letter, answer standard questions, screenshots, error
  recording, state saving), adapters (`Greenhouse`, `Lever`, `Generic` first; `Ashby`,
  `SmartRecruiters`, `Workday`), resilient locator strategies, dedicated `browser` Celery queue.
- Migration `0008`: `browser_sessions` (encrypted storage state).
- Challenge detection → `MANUAL_ACTION_REQUIRED` with "Manual action required." and a screenshot.

Tests first (Python Playwright against mock ATS): ATS detection, complete filling, correct CV uploaded,
**stops before submit**, screenshots saved, CAPTCHA/login/MFA → manual action, missing required field
reported, locator resilience to attribute changes.

---

## Phase 9 — Human approval workflow

Deliverables
- Review page with company, job, location, visa status, application URL, tailored CV, ATS score,
  answers, cover letter, concerns; `[EDIT]`, `[SKIP]` (→ `WITHDRAWN`, reason recorded),
  `[APPROVE & SUBMIT]`.
- Status transition table; `SubmissionGuard` (approval / `AUTO_SUBMIT` strict criteria, site policy,
  no challenge, mock-mode restriction); submission task (idempotent); full audit trail.

Tests first: transition table, guard decision matrix, approval blocked by `NEEDS_USER_INPUT`, mock-mode
submission only to mock ATS, double-approval idempotency, audit entries.

Acceptance: end-to-end in mock mode: discovered → analysed → CV generated → ready for review →
approved → submitted to the mock ATS, all visible and audited.

---

## Phase 10 — Real public career / ATS integrations

Deliverables
- Sources: Greenhouse Job Board API, Lever Postings API, Ashby Job Board API, SmartRecruiters Posting
  API, Workday public career-site endpoints where permitted, generic career pages (JSON-LD
  `JobPosting` first), RSS/Atom feeds; LinkedIn only through permitted mechanisms (URL import, job-alert
  emails via n8n).
- Compliance enforced for every request (robots.txt, rate limits, source policy, identifying user
  agent); source health checks; company watchlist seed (`crawler/companies.yaml`).

Tests first: recorded HTTP fixtures per source (normalization, pagination, errors), robots disallow,
rate limiting, policy `disabled`/`manual_only`; opt-in live smoke tests.

---

## Phase 11 — Scheduling, notifications, dashboard, hardening

Deliverables
- Celery beat daily pipeline at `DAILY_RUN_TIME` in `TIMEZONE` (default 08:00 Africa/Tunis) with
  catch-up after downtime; `scheduler` Compose service; on-demand pipeline trigger.
- `NotificationProvider`: Email (SMTP), Telegram (Bot API), Webhook (HMAC-signed, for n8n);
  `notifications` table; daily summary ("47 jobs found / 18 relevant / 11 sponsorship-friendly /
  7 applications ready for review") with dashboard links.
- Dashboard KPIs: jobs found today, jobs in last 24 h, qualified, visa-friendly, CVs generated, awaiting
  approval, submitted, interview pipeline, failed runs.
- n8n workflows: notification fan-out, alternative scheduler, Google Sheets export.
- Hardening: database backups, container resource limits, CSP/security headers, API rate limiting,
  dependency audit in CI, data-retention job, optional Sentry-compatible error tracker.

Tests first: schedule computation (time zone, DST), pipeline orchestration counters, notification
formatting and delivery (mock SMTP, mocked Telegram HTTP), HMAC signatures, KPI queries, full mock-mode
E2E happy path.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Sites change markup or block automation | Public APIs first; adapters with resilient locators; generic fallback; manual-action path; health checks per source |
| Terms of service / legal constraints | Source policy registry, robots.txt, rate limits, no LinkedIn scraping, no CAPTCHA/MFA bypass, human approval |
| LLM hallucination | Structured outputs, evidence quotes, deterministic truthfulness guard, `NEEDS_USER_INPUT`, human review |
| LLM cost | Model/effort configurable, caching of analyses by content hash, mock provider for development |
| Personal data exposure | Git-ignored CVs/storage, redaction, localhost-only ports, bearer auth, encryption at rest (see `docs/security.md`) |
| Flaky browser tests | Deterministic mock ATS sites; real sites only in opt-in smoke tests |
| Docker unavailable on a dev machine | Documented native path (local PostgreSQL + Redis) |
