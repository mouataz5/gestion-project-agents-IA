# Implementation Plan

The system is built in 11 incremental phases. Each phase ends with working, tested software. Real
integrations arrive only in Phase 10, after the mock pipeline has been proven end to end. Design
references point to `docs/architecture.md`.

**Delivery order.** Phases 1–4 were delivered in order. On 2026-10-02 the user chose the fastest
route to real applications for the rest:

**5 → 6 → 10 → 7 → 8 → 9 → 11**

So the ATS engine and CV documents come first, then real job sources, then answers, browser
automation and approval. Phase numbers stay as they are, since they are referenced everywhere.

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

## Phase 3 — Jobs, discovery abstraction, mock source, deduplication, 24-hour window ✅

**Goal**: find recent AI/ML jobs from declared sources, once each, with honest posting dates.

Deliverables
- Migration `0003`: `companies` (watchlist), `job_sources` (runtime mirror of the policy file + last
  run status), `jobs` (all spec §7 fields + `posting_date_status`/`posting_date_basis`,
  `canonical_url`, `duplicate_of_id`, `last_seen_at`, `discovery_run_id`; unique
  `(source, source_job_id)`), `job_skills` (required/preferred), `applications` (spec §18, unique per
  candidate and job, 14 statuses).
- `app/crawlers/`: `JobSource` / `CompanyBoardSource` protocols, `RawJob`, `JobQuery`,
  `NormalizedJob` and the shared `build_job()`; validated `crawler/sources.yaml` (policies
  `api_only`/`allowed`/`manual_only`/`disabled`, priority, rate limit, notes) and registry with skip
  reasons; `MockAtsSource` (per watchlist board) and `MockFeedSource` reading
  `crawler/fixtures/mock_jobs/` (run only with `MOCK_MODE=true`).
- `app/jobs/` (pure): canonical URLs (tracking parameters, LinkedIn/Indeed ids, ATS apply pages),
  `validate_public_url` (SSRF), `content_hash`, EN/FR relative dates with conservative bounds, posting
  window, remote/employment/seniority/country detection, HTML → text, AI/ML title pre-filter, job
  links in alert emails.
- Deduplication with source priority (ATS > career page > feed > manual import); a later ATS record
  takes over as primary and re-points duplicates and applications.
- Compliance building blocks: `RobotsPolicy` (RFC 9309), Redis per-domain token-bucket `RateLimiter`.
- Discovery run (`DISCOVERY`, task `jobs.run_discovery`, `POST /runs/discovery`): per-source events,
  counters, summary totals, per-source and per-company status, failures isolated
  (`PARTIAL_SUCCESS`), `DISCOVERED` applications for primary in-window jobs in target countries.
- Imports: `POST /jobs/import` (pasted URL + optional details, never fetched) and
  `POST /jobs/import/email` (job-alert emails); `POST /jobs/{id}/track` for unknown-date jobs.
- API: `GET /jobs` (window, date status, source, country, search, duplicates, pagination),
  `GET /jobs/stats`, `GET /jobs/{id}`, `GET /job-sources`, `GET|POST /companies`,
  `GET|PATCH|DELETE /companies/{id}`, `POST /companies/import`; every change audited.
- UI: `/jobs` (tabs, filters, date badges, sources table, import dialog, run button), `/jobs/[id]`,
  `/companies` (CRUD, enable switch, YAML import), dashboard discovery card.
- n8n: `n8n/workflows/job-alert-email-import.json` (IMAP → `POST /jobs/import/email`).

Tests first: canonical URL rules and URL safety, hash stability, relative dates EN/FR and bounds,
window boundaries and unknown dates, normalization helpers, title filter, email link extraction,
sources/companies YAML validation and fixture validity, robots (allow/disallow/4xx/5xx/cache),
transition table, rate limiter, dedup matrix (priority swap, re-pointed applications, URL-only
imports), discovery (exact counters, events, queueing rules, watchlist checks, failing source,
idempotent second run, empty watchlist, live mode), jobs/import/email/companies/sources/runs APIs
(validation, auth, audit), worker task end to end, n8n workflow export, frontend helpers, E2E.

Acceptance: in mock mode a discovery run loads fake jobs, removes duplicates, applies the window and
shows the jobs with date-status badges. ✔ Verified natively and on the Docker stack (E2E with
`E2E_ALLOW_MUTATIONS=1`).

---

## Phase 4 — LLM provider, job analysis, visa classification, matching ✅

**Goal**: for each queued job, decide whether visa sponsorship is available, how well the job matches
the confirmed master CV, and whether to APPLY, REVIEW or SKIP. Every claim carries evidence.

Deliverables
- **`app/llm/`**:
  - the `LLMProvider` protocol;
  - `ClaudeProvider`, built on the official `anthropic` SDK. It sends structured output through
    `output_config.format` and validates it with Pydantic after checking `stop_reason`. It sets
    `output_config.effort` and no `thinking` or sampling parameters. The server-side refusal fallback
    is on by default. The candidate facts are prompt-cached. SDK errors are mapped to clear, redacted
    failures. Usage, served model and request id are recorded; prompts and answers are never logged.
  - `MockLLMProvider` (deterministic, offline);
  - a versioned prompt registry;
  - a provider factory. It fails fast without a key in live mode and falls back to the mock without a
    key in mock mode.
- **`prompts/job_analysis.v1.md`**: truthfulness rules; the posting is untrusted data, quotes must be
  verbatim, and the model answers "unknown" instead of guessing.
- **`app/analysis/`** (pure, unit-tested):
  - deterministic candidate facts (data minimisation: no contact data, employer or school names);
  - EN/FR/DE visa phrase rules merged with the model's claim. Only verbatim quotes count, negatives
    win, and relocation is never sponsorship.
  - sponsorship need from the profile (EU/EEA/CH free movement);
  - CV-backed skill verification and coverage;
  - language checks;
  - the qualification rules table;
  - assembly of the stored result.
- **Migration `0004`**: `job_analyses` (status, provenance, usage, visa and relevance JSON, decision
  and reasons, redacted errors) and `applications.recommendation`.
- **Analysis run** (`ANALYSIS`, task `jobs.run_analysis`, `POST /runs/analysis` with optional
  `job_ids` and `force`):
  - requires a confirmed master CV and is capped by `ANALYSIS_MAX_JOBS_PER_RUN`;
  - idempotent by input hash;
  - REFUSED and FAILED analyses are isolated per job;
  - stops after 3 consecutive failures or a configuration error;
  - status transitions DISCOVERED → ANALYZED → QUALIFIED for APPLY or REVIEW, all audited.
- **API**:
  - `JobRead.recommendation` and `visa_status`;
  - `JobDetail.analysis`;
  - `GET /jobs?recommendation=&visa_status=`;
  - analysis stats (`analysed`, `qualified`, `by_recommendation`, `awaiting_analysis`, `last_analysis`);
  - the effective LLM provider in system info;
  - settings `LLM_EFFORT`, `LLM_MAX_TOKENS`, `LLM_REFUSAL_FALLBACK` and `ANALYSIS_MAX_JOBS_PER_RUN`, and
    the default `CLAUDE_MODEL=claude-opus-5-5`.
- **UI**:
  - an analysis panel on `/jobs/[id]`: decision and reasons, the model's suggestion, skills backed and
    missing, removed claims, languages, concerns, visa quotes highlighted in the posting, provenance,
    and an "Analyse this job" / "Re-analyse" button that waits for its run;
  - an Analysis column and filters on `/jobs`;
  - a dashboard Job analysis card with "Analyse new jobs";
  - a Language model card in Settings.

Tests first:
- **Prompt registry**: version, hash, unknown or unsafe names.
- **Mock provider**: determinism and validation.
- **Provider factory**: selection and fail-fast.
- **Claude provider against a fake Messages API** (the SDK's HTTP transport):
  - request shape: schema, effort, `cache_control`, fallback beta and body, none of
    `thinking`/`temperature`/`top_p`/`top_k`/`tool_choice`;
  - outcomes: structured output and usage, fallback served model, schema mismatch, refusal with
    category, `max_tokens` truncation;
  - failures: 429 retried then reported, 5xx retried, timeout, network error, 400/401/403/404 mapping;
  - nothing private in the logs at DEBUG;
  - health check without and with an API call.
- **Visa corpus**: confirmed, likely, unknown, not available, relocation-only, contradictory, FR/DE
  phrases, grounding of the model's quotes.
- **Rules**: sponsorship need matrix, skill verification and coverage, languages, the qualification
  table (16 cases), and facts determinism and data minimisation.
- **Integration**:
  - a mock analysis run over the discovered fixtures: expected recommendations, transitions, counters,
    events and summary;
  - re-runs: idempotent skip and `force`;
  - edge cases: no confirmed CV gives a WARNING; refusal isolated; failures isolated with the stop
    after 3; configuration error stops the run;
  - claims without evidence removed and invented quotes discarded.
- **API**: run start, detail, filters, stats, auth, audit.
- **Worker task** end to end.
- **Frontend helpers**: labels, provenance, quote highlighting, filters.
- **E2E**: read-only checks, plus the analysis workflow behind `E2E_ALLOW_MUTATIONS`.

Acceptance:
- Mock jobs are analysed offline with the mock provider. ✔ Verified natively and on the Docker stack.
- With an API key, Claude produces valid structured analyses with evidence. This uses the same code
  path as the tests (request shape and parsing verified against a fake API). **The live run awaits an
  `ANTHROPIC_API_KEY`.**

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
