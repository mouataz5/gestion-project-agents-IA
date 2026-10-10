# Progress

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: Docker, PostgreSQL, FastAPI, Next.js, configuration, logging, health checks, migrations | ✅ done |
| 2 | Candidate profile, master CV upload & parsing, candidate database | ✅ done |
| 3 | Job model, discovery abstraction, mock source, deduplication, 24-hour filter | ✅ done |
| 4 | LLM provider (Claude), job analysis, visa classification, matching | ✅ done |
| 5 | ATS engine, tailoring, iterative optimization | ✅ done |
| 6 | DOCX/PDF generation | ⏳ next |
| 7 | Application question engine | ⏳ planned |
| 8 | Playwright, mock ATS, browser adapters | ⏳ planned |
| 9 | Human approval workflow | ⏳ planned |
| 10 | Real public career/ATS integrations | ⏳ planned |
| 11 | Scheduling, notifications, dashboard, hardening | ⏳ planned |

Delivery order of the remaining phases, chosen by the user on 2026-10-02 as the fastest route to real
applications: **5 → 6 → 10 → 7 → 8 → 9 → 11**.

## Test status (from `tests.json`)

1160 tests, **all passing, none skipped**:
- 970 backend (unit, API, PostgreSQL/Redis integration);
- 15 workers;
- 145 frontend (Vitest);
- 30 browser E2E (Playwright, including the data-changing CV, discovery, analysis and tailoring
  workflows).

36 tests are planned for Phases 6–11. The 10 Phase 5 placeholders were replaced by real tests
(features `ats-engine`, `cv-tailoring`, `ats-loop`, `frontend-ats`, `e2e-tailoring`).

## Phase 5 — what was delivered

- **ATS engine** (`app/ats/`, pure and unit-tested):
  - one skills taxonomy (terms, categories, aliases, scan flag) shared with the CV evidence and the
    analysis; text primitives for stems, numbers and proper nouns; master-CV source ids;
  - job requirements merged from the listed skills, languages, a taxonomy scan and an extraction
    grounded in the posting (`prompts/job_requirements.v1.md`), cached per posting version;
  - the deterministic `ats-score.v1` score: 7 weighted components (configurable with
    `ATS_SCORE_WEIGHTS`), renormalised when a component does not apply, the supported ceiling,
    keyword classes (matched / available / missing / unsupported), stuffing penalties, feedback for
    the next iteration and gaps for the candidate.
- **Truthful tailoring**:
  - the model returns only a summary, a skill choice, sourced bullet rewrites and a project order
    (`prompts/cv_tailoring.v1.md`); employers, titles, dates, education, certifications and
    languages are copied from the master by code;
  - every sentence cites master-CV source ids from its own entry; the guard reverts any unsupported
    technology, number, job term, claim or excess new content to its source, then the final gate
    rejects any version that still breaks a rule; unsupported keywords must be 0;
  - an evidence ledger records the origin and sources of every text, the unused facts and the
    repairs.
- **Optimisation loop**: up to `ATS_MAX_ITERATIONS` calls towards `ATS_TARGET_SCORE`, no call when
  none can help, six explicit stop reasons, the best valid version kept.
- **Data model** (migration `0005`): `job_requirements`, `cv_tailorings`, `ats_analyses`, and
  tailored versions in `cv_versions` (ledger, score, one current version per application).
- **CV generation run** (`jobs.run_cv_generation`, `POST /runs/cv-generation` with optional
  `job_ids` / `force`): APPLY jobs by default (REVIEW on request), capped at 10 per run, idempotent,
  failures isolated per job, QUALIFIED → CV_GENERATED, audited.
- **API**: tailored CV list and detail (with the resolved ledger), the tailoring on the job detail,
  the ATS score on jobs, CV generation stats and the ATS settings in system info.
- **Frontend**: the job page's "Tailored CV & ATS" card with "Tailor CV" / "Re-tailor"; the tailored
  CV page with origin and source badges, unused facts and repairs; tailored CVs on `/cv`; an ATS
  column on `/jobs`; a dashboard CV generation card with "Tailor CVs"; an ATS engine card in Settings.
- **Phase 4 fix**: the analysis input hash now covers the whole rendered posting.
- **Docs**: architecture §8, §11 (as implemented), §15 and §16, ADRs 49–57; security §7.3; README
  "Tailor your CV"; `prompts/README.md`; the implementation plan.

## Phase 4 — what was delivered

- **LLM layer** (`app/llm/`):
  - `LLMProvider` protocol.
  - `ClaudeProvider`, on the official `anthropic` SDK 1.11:
    - JSON-schema structured output, validated after checking `stop_reason`;
    - `output_config.effort`, with no `thinking` or sampling parameters;
    - server-side refusal fallback on by default;
    - prompt caching of the candidate facts;
    - SDK errors mapped to clear, redacted failures;
    - usage, served model and request id recorded.
  - `MockLLMProvider` (deterministic, offline).
  - A versioned prompt registry.
  - A provider factory: fail-fast without a key in live mode, mock without a key in mock mode.
- **Prompt** `prompts/job_analysis.v1.md`: truthfulness rules; the posting is untrusted data; quotes
  must be verbatim; "unknown" instead of guessing.
- **Analysis rules** (`app/analysis/`):
  - deterministic candidate facts, with no contact data, employer or school names;
  - EN/FR/DE visa phrase rules merged with the model's claim (verbatim quotes only, negatives win,
    relocation is never sponsorship);
  - sponsorship need from the profile (EU/EEA/CH free movement);
  - CV-backed skill matching and coverage;
  - language checks;
  - the APPLY / REVIEW / SKIP rules table, which decides, with the model's suggestion stored next to
    it.
- **Data model** (migration `0004`): `job_analyses` (status, provenance, usage, visa and relevance
  JSON, decision and reasons, redacted errors) and `applications.recommendation`.
- **Analysis run** (`jobs.run_analysis`, `POST /runs/analysis` with optional `job_ids` / `force`):
  - requires a confirmed CV and is capped at 25 jobs per run;
  - idempotent by input hash;
  - refusals and failures isolated per job, with a stop after 3 consecutive failures or a configuration
    error;
  - audited lifecycle transitions.
- **API**: recommendation and visa on jobs, the latest analysis on the detail, filters, analysis stats
  (including jobs waiting), and the effective LLM provider in system info.
- **Frontend**:
  - an analysis panel on `/jobs/[id]` (decision and reasons, skills backed and missing, removed claims,
    languages, concerns, visa quotes highlighted in the posting, provenance, "Analyse" / "Re-analyse"
    that waits for its run);
  - an Analysis column and filters on `/jobs`;
  - a dashboard Job analysis card;
  - a Settings Language model card;
  - analysis runs counted in the runs table.
- **Docs**:
  - architecture §5, §7, §8, §10, §16 and §17;
  - ADR 13 updated, and ADRs 38–48;
  - security (data sent to Anthropic, prompt injection, log quieting);
  - `prompts/README.md`;
  - README "Analyse jobs";
  - the implementation plan, with the new delivery order.

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

## Verification performed — Phase 5 (2026-10-10)

- **Static checks:** `ruff`, `black --check`, `mypy --strict` (154 files), ESLint, Prettier, `tsc` and
  `next build` (CI) are all green. `make tests-json`: 1160 passed, 0 failed, 0 skipped.
- **CI:** every part was pushed on its own and went green before the next one (parts 1–8; part 9
  with this commit).
- **Migration `0005`:** hand-cleaned; tests check that the models and migrations are in sync (the
  `alembic check` comparison), the downgrade / upgrade round trip and the new constraints. Applied on the native database (`0004 → 0005`) and on a
  fresh Docker stack (`0001 → 0005`).
- **Golden values** (the sample CV, asserted by tests and seen in the browser): Nova AI "Senior AI
  Engineer" 82.3 → 88.3 in one mock call, ceiling 88.3, stop reason "only unsupported gains left";
  Sandstone "AI Research Engineer" 65.7 = its ceiling, so no call and a copy of the master. Both
  with 0 unsupported keywords. Gaps reported for Nova AI: Python listed but not shown in a role;
  "Design RAG pipelines", "Evaluate LLM quality" and "Mentor engineers" not covered.
- **Browser, native stack:** Tailor CVs from the dashboard → run succeeded → the ATS column on
  `/jobs` → the job's "Tailored CV & ATS" card → the tailored CV with "Experience 1 · bullet 1"
  source badges → Re-tailor (a new version, the old one superseded) → `/cv` and Settings, in light
  and dark mode, with no console errors. Fixed: the provenance said "Mock analysis" on a tailoring;
  long setting names overflowed the Settings cards.
- **Browser, Docker stack** (fresh volumes, rebuilt images): 30/30 Playwright tests with
  `E2E_ALLOW_MUTATIONS=1`. The database ended with 1 confirmed master, 2 current tailored CVs and
  1 superseded one. Backend and worker logs contain no traceback, CV text, prompt, posting text,
  key or bearer token.
- **Not verified:** a live Claude extraction or tailoring. No `ANTHROPIC_API_KEY` is configured here;
  both calls use the provider code verified in Phase 4, and their schemas pass the SDK's
  structured-output transform in tests.

## Verification performed — Phase 4 (2026-10-03)

- **Static checks:** `ruff`, `black --check`, `mypy --strict` (135 files), ESLint, Prettier, `tsc` and
  `next build` are all green. `make tests-json`: 882 passed, 0 failed, 0 skipped.
- **Migration `0004`:** autogenerated against a scratch database and hand-cleaned. `alembic check`
  reports no drift, and the downgrade/upgrade round trip works. It applied on the native database
  (`0003 → 0004`) and on a fresh Docker stack (`0001 → 0004`).
- **Claude provider** (fake Messages API on the SDK transport):
  - Request shape: `output_config` schema and effort, `cache_control` on the facts, the fallback beta
    and `fallbacks="default"`; `thinking`, `temperature`, `top_p`, `top_k` and `tool_choice` are never
    sent.
  - Outcomes: refusal with category, `max_tokens`, 429 retried then reported, 5xx retried, timeout,
    network error, 400/401/403/404, and the served model after a fallback.
  - Logging: nothing private in the logs at `LOG_LEVEL=DEBUG`. This test found the SDK logging whole
    requests at DEBUG; that logger is now pinned at WARNING.
- **Mock analysis** of the discovered fixtures (exact expectations in tests): 8 queued jobs became
  2 APPLY, 5 REVIEW and 1 SKIP. A re-run skips unchanged jobs, and `force` re-analyses them. Refusals
  and failures are isolated. A run where every job fails is `FAILED` and stops after 3. Without a
  confirmed CV, the run ends with a WARNING and analyses nothing.
- **Browser, native stack:** analysis run, Apply/Skip/Review pages, list filters, dashboard and
  settings. All were reviewed in light and dark mode. Fixed: the label for a language missing from the
  CV, quote highlighting with different trailing punctuation, the job count for analysis runs, and the
  wording of the mock suggestion.
- **Browser, Docker stack** (fresh volumes, rebuilt images): 24/24 Playwright tests with
  `E2E_ALLOW_MUTATIONS=1`. The run analysed 10 jobs (2 apply, 7 review, 1 skip), and "Re-analyse" on a
  job page worked. Backend and worker logs contain no traceback, prompt, candidate facts, contact data,
  posting text or key.
- **Not verified:** a live Claude call. No `ANTHROPIC_API_KEY` is configured in this environment. The
  request and response handling were verified against a fake API that implements the documented
  shapes.

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

### 2026-10-10 — Phase 5 completed
- The user chose "Start Phase 5" and asked for every part to be committed and pushed as soon as it is
  developed and tested. Phase 5 shipped in nine parts, each green in CI: taxonomy and text; sources
  and requirements (with the Phase 4 hash fix); scoring; guard, ledger and mock tailoring; the loop;
  migration `0005`; the service, prompts and settings; the worker and API; the frontend; then E2E
  and docs.
- Design choices are recorded as ADRs 49–57. Deviations from the approved plan:
  - no `UNCHANGED` tailoring status: as in Phase 4, an unchanged input writes no row and is counted
    in the run summary;
  - taxonomy category labels never name a term ("Artificial intelligence", "Infrastructure &
    operations"), so a label cannot count as a keyword match;
  - stuffing is measured relative to the master CV, so the candidate's own dense summary is not
    penalised;
  - score reports carry `assessed_weight`, the share of the 100 points that could be assessed;
  - the candidate-facing advice is called "gaps", not "recommendations", to avoid confusion with
    APPLY / REVIEW / SKIP.
- Found and fixed while building and verifying:
  - a bullet could cite a title id, and the summary's citation rule was checked in the wrong order
    (`may_cite` precedence); both fixed with tests;
  - work evidence matched the education source `ED1`; unused sources counted skill evidence;
  - the scoring model `Recommendation` clashed with the analysis enum in the OpenAPI schema; renamed
    `Gap`;
  - the tailoring provenance said "Mock analysis"; long setting names overflowed the Settings cards.

### 2026-10-03 — Phase 4 completed
- The user asked whether the system can already apply to jobs. The answer was not yet. The user
  chose the fastest route for the remaining phases: 4 → 5 → 6 → 10 → 7 → 8 → 9 → 11.
- Plan approved. Tests were written first:
  - prompt registry, mock provider and factory;
  - the Claude provider against a fake Messages API;
  - visa corpus, sponsorship need, skills, languages, the qualification table, and candidate facts;
  - the analysis service, the API and the worker.
  The implementation followed.
- The default model moved to `claude-opus-5-5` (ADR 13). Design choices are recorded as ADRs 38–48:
  - the SDK and structured output;
  - effort instead of thinking or sampling parameters;
  - the refusal fallback on by default;
  - the cached candidate facts;
  - the posting treated as untrusted data;
  - deterministic grounding guards;
  - explicit qualification rules;
  - sponsorship need from the profile;
  - data minimisation;
  - provider selection;
  - the analysis as its own idempotent run.
- During the work the user typed "reset", then clarified "continue your job". Nothing was reset.
- Found and fixed while building and verifying:
  - The Anthropic SDK logs whole request bodies (prompts, CV facts) at DEBUG. Its logger is now
    pinned at WARNING, with a test.
  - Experience counted in days would have changed every day, defeating the cache and the
    idempotence. It is now counted in whole years.
  - A test assumed the sample CV lacked Spark, but the CV demonstrates it. The test premise was
    corrected.
  - A run where every job failed reported `PARTIAL_SUCCESS`. It now reports `FAILED`, with a test.
  - Four UI details found in the visual review (see the verification above).
  - The analysis E2E needs the CV and discovery specs. It now runs after them, as a dependent
    Playwright project.

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
2. Default LLM model `claude-opus-5-5` (newer and cheaper than `claude-opus-5`), switchable with
   `CLAUDE_MODEL` — ADR 13. The effort is `medium` (`LLM_EFFORT`); raise it if analyses feel
   shallow.
3. A user "Skip" maps to status `WITHDRAWN` with a reason (the requested status list has no
   `SKIPPED`) — ADR 14.
4. `AUTO_SUBMIT=true` is interpreted as "submit without per-application approval only when every
   strict criterion passes" (still never with CAPTCHA/MFA or on sites that disallow automation).
5. The database is the live profile; `candidate/profile.yaml` is only the seed and the
   import/export format (ADR 22). Edit at `/candidate`, or edit the YAML and click "Import".
6. Master CV parsing uses no AI (ADR 23); an optional AI-assisted re-parse could be added later,
   always as a suggestion you confirm.
7. The server-side **refusal fallback is enabled by default** (`LLM_REFUSAL_FALLBACK=true`). If
   Claude declines a posting, the API re-runs it on the fallback model Anthropic designates, and the
   analysis records which model answered. Set it to `false` if you prefer refusals to stay refusals.
8. These facts are sent to Claude for each analysis: targets, work authorization, relocation,
   languages, CV-backed skills, experience and project bullets and technologies, degrees and
   certifications. Your name, contact details and employer names are never sent (ADR 46).
9. For tailoring, Claude receives your master CV's summary, titles, periods, bullets, project names,
   degrees, certifications, languages and backed skills, with ids; never your name, contact
   details, employers, schools or locations, and never the raw posting (ADR 56).
10. By default only **Apply** jobs are tailored in a run; a **Review** job is tailored when you click
    "Tailor CV" on its page (`CV_GENERATION_INCLUDE_REVIEW=true` includes them all). Experience
    titles are never changed (`cv_policy.allow_title_changes: false` in your profile).

## Needed from you (not blocking Phase 6)

- Upload your real master CV at `/cv`, review the draft and confirm it (it stays out of Git).
- Fill in the highlighted fields at `/candidate`: email, phone, notice period, salary expectations,
  earliest start date, spoken languages, preferred work modes.
- Replace the fictional watchlist with the companies you follow at `/companies` (name, career URL,
  ATS and board token); their real boards are read from Phase 10.
- Review the **gaps** a tailored CV reports (on each job page). Add a skill, a bullet or a
  responsibility to your master CV only if it is true; the tailoring will then use it.
- Optional: import `n8n/workflows/job-alert-email-import.json` into n8n and connect the mailbox that
  receives your LinkedIn/Indeed job alerts.
- **`ANTHROPIC_API_KEY` in `.env`** for real analysis and tailoring by Claude. Without it, mock mode
  works offline with rules, and every result is labelled "Mock analysis" or "Mock tailoring". A `.env` created before Phase 4
  keeps `CLAUDE_MODEL=claude-opus-5`; change it to `claude-opus-5-5` to use the new default.

## Known limitations

- No scheduler yet (Phase 11): runs are started on demand (dashboard/API).
- Dashboard pipeline KPIs (applications, interviews, offers) arrive with the phases producing them.
- Only mock sources run in Phase 3; real ATS APIs, career pages and feeds arrive in Phase 10.
  Imported URLs are stored, not fetched, so their description stays empty unless provided.
- The discovery title pre-filter is keyword-based. Relevance and visa sponsorship are then judged by
  the analysis.
- **Analysis:**
  - The live Claude path has not been exercised against the real API here, since no key is configured.
  - "Analyse new jobs" covers newly queued jobs. After a CV change, re-analyse individual jobs from
    their page; bulk re-analysis comes with the Phase 11 daily pipeline.
  - The mock analysis is rule-based (title and listed skills), not a real judgement.
  - The Batch API (half the cost) is deferred to Phase 11, because it does not support the refusal
    fallback.
- **ATS engine:**
  - The score is our deterministic estimate of keyword and structure fit, not any employer's ATS.
    95 is a target, not a promise: with the sample CV the Nova AI job reaches 88.3, its ceiling.
  - Formatting is checked on the CV structure only; DOCX checks arrive with Phase 6
    (`ats-score.v2`). Tailored CVs are not yet downloadable as files (Phase 6).
  - The mock tailoring only selects, reorders and copies master sentences verbatim (into the skills
    and the summary); it never rewords. Real rewording needs Claude and passes the same guard. The
    live path awaits an API key.
  - A tailored CV stays in the master CV's language; postings in another language are scored as
    they are.
  - The guard is deliberately strict: a legitimate paraphrase with several new words is reverted to
    the master sentence, and the repair is shown.
- Scanned (image-only) PDFs are rejected: OCR is out of scope. Multi-column PDF layouts may
  interleave columns; DOCX gives the best results. The draft review step exists for these cases.
- The parser recognises English and French section headings; other languages need manual review.
- Deleting CV versions and exporting/deleting all personal data arrive in Phase 11.

## Next step

Phase 6 — DOCX / PDF generation: a deterministic, ATS-friendly DOCX template and PDF conversion for
each tailored CV, stored per application, with DOCX formatting checks feeding `ats-score.v2`, and
download and "compare with master" in the UI. Then Phase 10 (real sources), following the chosen
order 6 → 10 → 7 → 8 → 9 → 11.
