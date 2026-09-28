# Architecture — AI Job Application Agent

> Status: **Phase 1 (Foundation) implemented.** Sections describing later phases are the agreed
> design; each phase may refine details and must record deviations in the ADR log at the end.

## 1. Purpose

A self-hosted platform that, for one candidate (multi-candidate ready), continuously:

1. **Discovers** newly posted AI/ML/GenAI jobs from permitted sources (public ATS APIs, career pages,
   feeds), deduplicates them and applies a 24-hour posting window.
2. **Analyses** each job: visa/sponsorship evidence, relevance to the candidate, requirements.
3. **Generates** a truthful, job-specific CV optimised for ATS readability (target score 95, never by
   fabrication), plus a cover letter and application answers when useful.
4. **Prepares** the application in the company's real ATS with a browser, stopping before submission.
5. **Submits** only after explicit human approval, where automation is permitted and no security
   challenge is present, and records everything.

## 2. Guiding principles

| Principle | Consequence in the design |
|---|---|
| **Human in control** | `AUTO_SUBMIT=false` by default; submission requires an approval recorded in the audit log. |
| **Truthfulness** | The master CV is the source of truth. A *truthfulness guard* rejects any generated content that adds employers, titles, dates, technologies, certifications, education or metrics absent from it. Unknown answers become `NEEDS_USER_INPUT`. |
| **Compliance** | Public APIs/feeds preferred; `robots.txt`, site terms and per-domain rate limits respected; CAPTCHA/MFA/anti-bot never bypassed → "Manual action required." |
| **Safety by default** | `MOCK_MODE=true` by default; mock mode can only touch mock ATS pages. |
| **Provider independence** | Every external dependency sits behind an interface (LLM, job sources, notifications, storage, browser, error tracking). Claude is the first LLM provider, not a hard dependency. |
| **Self-hosted & open source** | PostgreSQL, Redis, FastAPI, Celery, Next.js, Playwright, LibreOffice. No paid SaaS except the LLM API, isolated behind `LLMProvider`. |
| **Explainability** | Decisions are structured (JSON with evidence quotes), not a single opaque score. ATS scores are computed deterministically from recorded evidence. |
| **Observability** | Every automation run, every run step and every application action is persisted and visible in the UI. |

## 3. System context

```mermaid
flowchart LR
    user([Candidate]) -->|reviews, edits, approves| ui[Dashboard<br/>Next.js]
    ui --> api[Backend API<br/>FastAPI]
    subgraph platform[Self-hosted platform]
        api
        worker[Workers<br/>Celery]
        scheduler[Scheduler<br/>Celery beat]
        db[(PostgreSQL)]
        redis[(Redis)]
        files[(Storage<br/>CVs, screenshots)]
    end
    api <--> db
    api -->|enqueue| redis
    scheduler -->|daily 08:00| redis
    redis --> worker
    worker <--> db
    worker <--> files
    worker -->|public APIs / feeds / pages<br/>robots.txt + rate limits| sources[(Job sources:<br/>Greenhouse, Lever, Ashby,<br/>SmartRecruiters, Workday,<br/>career pages, RSS)]
    worker -->|LLMProvider| llm[Claude API<br/>or other provider]
    worker -->|Playwright, stops before submit| ats[Company ATS<br/>application sites]
    worker -->|NotificationProvider| notify[Email / Telegram]
```

## 4. Containers (Docker Compose)

| Service | Image / tech | Responsibility | Phase |
|---|---|---|---|
| `postgres` | postgres:16-alpine | System of record | 1 |
| `redis` | redis:7-alpine | Celery broker/result backend; later rate-limit buckets | 1 |
| `migrate` | backend image | `alembic upgrade head`, runs once before API/worker start | 1 |
| `backend` | backend image, uvicorn | REST API (`/api/v1`), OpenAPI docs, health checks | 1 |
| `worker` | backend image, Celery | Executes runs and pipeline stages; later a `browser` queue (concurrency 1) with Playwright + LibreOffice | 1 |
| `frontend` | Next.js standalone | Dashboard; server-side proxy to the API | 1 |
| `scheduler` | backend image, Celery beat | Daily pipeline trigger (`DAILY_RUN_TIME` in `TIMEZONE`) | 11 |
| `mock-ats` | static server | Mock Greenhouse/Lever/generic ATS pages for safe automation tests | 8 |
| `n8n` (profile `n8n`) | n8n Community Edition (free, self-hosted) | Optional integration layer: notifications, job-alert email ingestion, extras (§19); the core never depends on it | 1 (service), 3/10/11 (workflows) |

All published ports are bound to `127.0.0.1`. The browser only talks to the frontend; the frontend's
server talks to the API with a bearer token that never reaches the browser.

## 5. Repository layout

The repository root is the `job-agent/` monorepo root.

```
backend/                 FastAPI app + all domain code (Python package `app`)
  app/api/               HTTP layer: routers, dependencies, error handlers
  app/core/              config, logging, redaction, errors, security, storage, queue, clock
  app/db/                SQLAlchemy base/session, Alembic migrations
  app/models/            ORM models
  app/schemas/           Pydantic API schemas
  app/services/          use-case services (health, runs, audit, diagnostics, …)
  app/agents/            LLM-driven analysers (job analysis, visa, relevance, tailoring) — Phase 4+
  app/crawlers/          JobSource implementations — Phase 3/10
  app/ats/               ATS engine (Phase 5) and ATS form adapters (Phase 8)
  app/browser/           ApplicationBrowser / BrowserProvider (Playwright) — Phase 8
  app/llm/               LLMProvider interface + Claude/mock providers — Phase 4
  app/applications/      application preparation, approval, submission guard — Phase 7/9
  app/notifications/     NotificationProvider + email/telegram — Phase 11
  tests/                 unit/ and integration/
workers/                 Celery app + thin task wrappers (package `job_agent_workers`)
frontend/                Next.js 16 (App Router, TypeScript, Tailwind CSS)
playwright/              Dashboard E2E tests; mock ATS sites (Phase 8)
crawler/                 Source configuration, company watchlist seed, mock job fixtures
prompts/                 Versioned LLM prompt templates
candidate/               profile.yaml; master_cv/ (git-ignored)
storage/                 Runtime files (git-ignored)
scripts/                 setup, env generation, OpenAPI export, tests.json update
docker/                  Dockerfiles
n8n/                     optional n8n integration: README + exported workflows (no credentials)
docs/                    architecture, implementation plan, security
```

Python is a **uv workspace** (root `pyproject.toml` is virtual): `backend` (distribution
`job-agent-backend`) and `workers` (`job-agent-workers`, depends on the backend). The backend never
imports the workers package; it enqueues tasks **by name** using constants in `app/core/tasks.py`.

## 6. Processing pipeline

The system separates five stages with different automation levels:

| Stage | Automation | Human involvement |
|---|---|---|
| A. Discovery | full | none |
| B. Analysis (visa, relevance, requirements) | full | reviews results |
| C. CV generation (tailoring + ATS loop) | full | may edit |
| D. Application preparation (answers, form filling, preview) | full, stops before submit | reviews exactly what will be submitted |
| E. Submission | only after approval | **explicit approval required** |

Daily workflow (Phase 11 wires it to the scheduler; each step is also runnable on demand):

```mermaid
flowchart TD
    s[Scheduler 08:00 Africa/Tunis] --> d[Discover jobs from enabled sources]
    d --> n[Normalize to Job]
    n --> dd[Deduplicate]
    dd --> f[24-hour filter<br/>posted_after = now - JOB_LOOKBACK_HOURS]
    f --> v[Visa / sponsorship classification]
    v --> m[Candidate matching - relevance JSON]
    m --> q{Qualified?}
    q -- no --> keep[Keep as ANALYZED<br/>recommendation SKIP]
    q -- yes --> a1[ATS analysis of master CV]
    a1 --> t[Tailor CV - truthful]
    t --> a2[ATS re-evaluation<br/>loop up to ATS_MAX_ITERATIONS]
    a2 --> g[Generate DOCX/PDF, answers, cover letter]
    g --> st[Store versions + reports]
    st --> nt[Notify user: summary + dashboard links]
```

Every execution is an **AutomationRun** with counters (`jobs_discovered`, `jobs_processed`,
`jobs_qualified`, `cv_generated`, `applications_prepared`, `applications_submitted`), an error list and
a timeline of **RunEvents**. A failure of one job never aborts the run: it is recorded and the run ends
`PARTIAL_SUCCESS`.

## 7. Core abstractions

All interfaces are `typing.Protocol`s; implementations are selected by configuration.

```python
class LLMProvider(Protocol):                       # app/llm — Phase 4
    name: str
    def generate_structured(self, request: LLMRequest, schema: type[T]) -> LLMResult[T]: ...
    def generate_text(self, request: LLMRequest) -> LLMResult[str]: ...
    def health_check(self) -> ProviderHealth: ...
# Implementations: ClaudeProvider (official `anthropic` SDK, structured outputs validated with
# Pydantic, refusal/stop-reason handling, usage recorded), MockLLMProvider (deterministic fixtures,
# used in tests and offline mock mode). Later: OpenAIProvider, OllamaProvider, LocalModelProvider.

class JobSource(Protocol):                          # app/crawlers — Phase 3/10
    key: str
    def search(self, query: JobQuery) -> Iterable[RawJob]: ...   # query carries posted_after/posted_before
    def get_job(self, source_job_id: str) -> RawJob | None: ...
    def normalize(self, raw: RawJob) -> NormalizedJob: ...
    def health_check(self) -> SourceHealth: ...

class NotificationProvider(Protocol):               # app/notifications — Phase 11
    channel: str
    def send(self, message: Notification) -> DeliveryResult: ...

class StorageProvider(Protocol):                    # app/core/storage.py — Phase 1 (implemented)
    def put_bytes(self, key: str, data: bytes) -> StoredObject: ...
    def get_bytes(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def list(self, prefix: str = "") -> list[str]: ...

class BrowserProvider(Protocol):                    # app/browser — Phase 8
    def new_session(self, options: BrowserOptions) -> BrowserSessionHandle: ...

class ApplicationAdapter(Protocol):                 # app/ats/adapters — Phase 8
    ats_type: str
    def matches(self, url: str, page: Page) -> bool: ...
    def discover_fields(self, page: Page) -> list[FormField]: ...
    def fill(self, page: Page, plan: FillPlan) -> FillReport: ...
    def detect_challenge(self, page: Page) -> Challenge | None: ...
    def submit(self, page: Page) -> SubmissionResult: ...          # only via SubmissionGuard

class ErrorTracker(Protocol):                       # app/core/error_tracking.py — Phase 1 (implemented)
    def capture_exception(self, exc: BaseException, *, context: Mapping[str, object] | None = None) -> str: ...
    def capture_message(self, message: str, *, level: str = "error", context: ... = None) -> str: ...
```

Adapters: `GreenhouseAdapter`, `LeverAdapter`, `WorkdayAdapter`, `AshbyAdapter`,
`SmartRecruitersAdapter`, `GenericAdapter`. Selectors are never global: each adapter resolves fields
through resilient strategies (accessible label → role/name → `name`/`id` attributes → label-text
similarity) with per-ATS overrides kept as data.

## 8. Data model

UUID primary keys, `timestamptz` (UTC) timestamps, JSONB for structured payloads, enum-like columns as
`VARCHAR` + named `CHECK` constraints, constraint naming convention for stable Alembic migrations.
Candidate-scoped tables carry `candidate_id` (multi-candidate readiness).

```mermaid
erDiagram
    CANDIDATE ||--o{ CANDIDATE_SKILL : has
    CANDIDATE ||--o{ EXPERIENCE : has
    CANDIDATE ||--o{ EDUCATION : has
    CANDIDATE ||--o{ PROJECT : has
    CANDIDATE ||--o{ CV_VERSION : owns
    CANDIDATE ||--o{ APPLICATION : makes
    COMPANY ||--o{ JOB : posts
    JOB_SOURCE ||--o{ JOB : discovered_by
    JOB ||--o{ JOB_SKILL : requires
    JOB ||--o{ JOB_ANALYSIS : analysed_in
    JOB ||--o{ APPLICATION : targeted_by
    APPLICATION ||--o{ CV_VERSION : uses
    APPLICATION ||--o{ APPLICATION_ANSWER : contains
    APPLICATION ||--o{ BROWSER_SESSION : automated_by
    CV_VERSION ||--o{ ATS_ANALYSIS : scored_by
    AUTOMATION_RUN ||--o{ AUTOMATION_RUN_EVENT : logs
    AUTOMATION_RUN ||--o{ NOTIFICATION : sends
```

| Entity | Key fields | Phase |
|---|---|---|
| `automation_runs` | run_type, trigger, status, started_at, finished_at, the six counters, error_count, errors, parameters, summary, task_id | **1** |
| `automation_run_events` | run_id, level, stage, message, data | **1** |
| `audit_logs` (append-only) | actor, action, entity_type, entity_id, request_id, details | **1** |
| `candidates` | identity, work authorization, relocation, targets, application defaults, profile version | 2 |
| `candidate_skills` | name, normalized_name, category, source (`MASTER_CV`/`PROFILE_DECLARED`), evidence refs, proficiency only if evidenced | 2 |
| `experiences`, `educations`, `projects` | parsed from the master CV, with original text and ordering | 2 |
| `companies` (watchlist) | name, career_url, country, ats_type, board token, target_roles, enabled, last_checked_at | 3 |
| `job_sources` | key, kind (ATS_API/FEED/CAREER_PAGE/BOARD), enabled, config, rate limit, compliance notes, last status | 3 |
| `jobs` | spec fields (source, source_job_id, company, title, description, location, country, remote_status, employment_type, seniority, salary_*, posted_at, discovered_at, application_url, company_url, ats_type, visa_information, relocation_information, required/preferred skills, languages, education/experience requirements, responsibilities, raw_content, content_hash) + `posting_date_status`, `canonical_url`, `duplicate_of_id`, visa fields | 3 |
| `job_skills` | name, normalized_name, category, importance (REQUIRED/PREFERRED), evidence_quote | 3–5 |
| `job_analyses` *(addition)* | relevance JSON, recommendation, model, prompt version | 4 |
| `applications` | spec §18 fields + candidate_id, approval metadata, blocked/manual reason | 3+ |
| `cv_versions` | kind (MASTER/TAILORED), version, parent, structured content, file keys (docx/pdf), content_hash, template | 2, 5, 6 |
| `ats_analyses` | overall + component scores, matched/missing/unsupported keywords, recommendations, iteration, scoring_version | 5 |
| `application_answers` | question, normalized key, answer, status (`DRAFT`/`NEEDS_USER_INPUT`/`APPROVED`), sources | 7 |
| `browser_sessions` | adapter, status, step, screenshots, error, manual_action_required, encrypted storage state | 8 |
| `notifications` | channel, status, subject, body, error, sent_at, run_id | 11 |

### 8.1 Application lifecycle

An `Application` row is created per (candidate, job) once a job passes deduplication and the posting
window; it then tracks the job through the whole pipeline.

```mermaid
stateDiagram-v2
    [*] --> DISCOVERED
    DISCOVERED --> ANALYZED
    ANALYZED --> QUALIFIED : recommendation APPLY/REVIEW
    QUALIFIED --> CV_GENERATED
    CV_GENERATED --> READY_FOR_REVIEW : answers + preview ready
    READY_FOR_REVIEW --> READY_FOR_REVIEW : user edits
    READY_FOR_REVIEW --> APPROVED : user approves
    READY_FOR_REVIEW --> WITHDRAWN : user skips
    APPROVED --> SUBMITTED : guard passes
    APPROVED --> MANUAL_ACTION_REQUIRED : CAPTCHA / MFA / login wall
    APPROVED --> BLOCKED : automation not permitted / error
    MANUAL_ACTION_REQUIRED --> SUBMITTED : user submitted manually
    BLOCKED --> READY_FOR_REVIEW : retry after fix
    SUBMITTED --> HR_SCREEN
    HR_SCREEN --> INTERVIEW
    INTERVIEW --> OFFER
    SUBMITTED --> REJECTED
    HR_SCREEN --> REJECTED
    INTERVIEW --> REJECTED
    OFFER --> WITHDRAWN
```

Jobs that are analysed but not qualified stay `ANALYZED` with `recommendation=SKIP` and are hidden from
the review queue. Every transition is validated by a transition table and written to `audit_logs`.

## 9. Discovery, normalization, deduplication, posting window

- **Sources** (Phase 3 mock, Phase 10 real): Greenhouse Job Board API, Lever Postings API, Ashby Job
  Board API, SmartRecruiters Posting API, Workday public career-site endpoints where permitted, generic
  career pages (JSON-LD `JobPosting` first, HTML fallback), RSS/Atom feeds. **LinkedIn** is supported only
  through permitted mechanisms (user-pasted job URLs, job-alert emails the user forwards); it is never
  scraped and never an architectural dependency.
- **Watchlist**: `companies` rows (name, career URL, country, ATS type, target roles, enabled,
  last_checked) are checked every run.
- **Normalization** produces a `NormalizedJob` with every field of spec §7.
- **Deduplication**: a posting is the same job if any of these match:
  `(source, source_job_id)`; the canonical application URL (lower-cased host, tracking parameters such as
  `utm_*`, `gh_src`, `lever-source` removed, fragment dropped); or `content_hash` =
  SHA-256 of normalized company + title + location + description. Cross-source duplicates link through
  `duplicate_of_id`, preferring direct ATS records over aggregators.
- **Posting window**: queries carry `posted_after`/`posted_before` (default `now - JOB_LOOKBACK_HOURS`).
  `posting_date_status` is `KNOWN` (source timestamp), `ESTIMATED` (relative text such as "2 days ago",
  with the basis recorded) or `UNKNOWN`. Unknown dates are **never** reported as "posted within 24 h";
  they are shown separately.

## 10. Analysis engines (Phase 4)

- **Visa/sponsorship engine**: deterministic phrase rules + LLM extraction, both producing evidence.
  Output: `visa_status` ∈ `SPONSORSHIP_CONFIRMED | SPONSORSHIP_LIKELY | SPONSORSHIP_UNKNOWN |
  SPONSORSHIP_NOT_AVAILABLE`, `visa_evidence`, verbatim `visa_evidence_quote`, `visa_country`,
  `relocation_available`. Relocation support alone never implies sponsorship. Explicit negative statements
  ("must already have work authorization", "no visa sponsorship") win over positive heuristics.
- **Relevance engine**: structured JSON (`role_relevance`, `seniority_fit`, `skill_matches`,
  `skill_gaps`, `required_skill_matches`, `preferred_skill_matches`, `visa_status`, `relocation_status`,
  `language_requirements`, `concerns`, `recommendation: APPLY|REVIEW|SKIP`, `reasoning`), validated by
  Pydantic. Qualification rules combine these fields explicitly (no single opaque score).
- Default model `CLAUDE_MODEL=claude-opus-5`, configurable; prompts are versioned files in `prompts/`;
  every stored analysis records provider, model and prompt version.

## 11. ATS engine, tailoring and truthfulness (Phase 5)

- **Extraction**: the LLM extracts hard/soft skills, tools, frameworks, languages, cloud platforms,
  methodologies, title, responsibilities, qualifications and domain terms as structured JSON; a skills
  taxonomy normalizes synonyms (e.g. `k8s` → Kubernetes).
- **Scoring is deterministic** and versioned: component scores (keyword, skills, experience,
  responsibility, education, title alignment, formatting) combined with configurable weights. Formatting is
  checked on the generated DOCX (single column, no tables/images/text boxes, standard headings, length).
- **Evidence ledger**: every CV claim links to master-CV evidence. Keywords are classified as
  `matched` (present with evidence), `missing` (genuine gap — reported, never added) or `unsupported`
  (present in the tailored CV without master-CV evidence — must be zero; any occurrence fails validation).
- **Truthfulness guard**: employers, titles (unless `allow_title_changes`), dates, education and
  certifications must equal the master CV; every technology and every number/metric in the tailored CV
  must exist in the master CV.
- **Iterative loop** (`ATS_MAX_ITERATIONS=3`, `ATS_TARGET_SCORE=95`): analyse → score → identify
  *supported* weaknesses → rewrite/reorder → validate → rescore. Stops at the target, at the iteration cap,
  or when further gains would need unsupported claims; remaining gaps are reported. 95 is an optimisation
  target, not a promise about any employer's ATS.

## 12. Documents, answers, browser automation, approval

- **Documents (Phase 6)**: deterministic `python-docx` template (ATS-friendly, no decorative graphics),
  PDF via headless LibreOffice in the worker image. Stored under
  `storage/applications/{application_id}/cv/` with `ats_report.json`.
- **Answers (Phase 7)**: questions are extracted from the form; answers use only profile, master CV, job
  description and company information; uncertain answers are `NEEDS_USER_INPUT` and block approval
  until resolved.
- **Browser (Phase 8)**: Python Playwright in a dedicated `browser` queue (concurrency 1). The
  `ApplicationBrowser` opens the real application URL, detects the ATS, fills fields, uploads the
  job-specific CV/cover letter, takes screenshots, saves state and **stops before the final submit**.
  CAPTCHA, MFA, login walls or bot blocks → status `MANUAL_ACTION_REQUIRED` with the message
  "Manual action required." and a screenshot. Browser auth state is encrypted at rest and never logged.
- **Approval (Phase 9)**: the review screen shows company, job, location, visa status, application URL,
  tailored CV, ATS score, answers, cover letter and concerns with `[EDIT] [SKIP] [APPROVE & SUBMIT]`.
- **SubmissionGuard**: submits only if (a) the application is `APPROVED` by the user — or `AUTO_SUBMIT=true`
  (opt-in, off by default) and it passes every strict criterion (APPLY recommendation, ATS ≥ target, no
  `NEEDS_USER_INPUT`, no concerns); (b) the site's policy permits automated submission; (c) no challenge is
  present; (d) in `MOCK_MODE`, the target is a mock ATS. Every decision is audit-logged.

## 13. Compliance layer (Phase 3/10)

`RobotsPolicy` (cached `robots.txt` per host, identifying user agent), per-domain token-bucket
`RateLimiter` in Redis, and a source policy registry (`crawler/sources.yaml`: `api_only`, `allowed`,
`manual_only`, `disabled`, ToS review notes). A source that fails compliance is skipped and the reason
is recorded in the run.

## 14. Observability (Phase 1 — implemented)

- **Structured logs**: `structlog`, JSON in production, console in development; the standard library,
  uvicorn and Celery logs flow through the same processors. Context variables add `request_id`,
  `run_id`, `task_id`.
- **Redaction**: one processor scrubs sensitive keys (password, secret, token, api key, authorization,
  cookie, session, credential, DSN…) and sensitive values (Bearer tokens, `sk-…` keys, credentials in URLs,
  JWTs, Telegram bot tokens) from every log line, run event, audit entry and error context.
- **Request IDs**: `X-Request-ID` accepted (validated) or generated, returned on every response and in
  error bodies.
- **Run logs**: `automation_runs` + `automation_run_events` (UI: `/runs`).
- **Audit log**: append-only `audit_logs`.
- **Error tracking**: `ErrorTracker` abstraction; the default implementation writes structured error
  events with an event id; a Sentry-compatible adapter (e.g. self-hosted GlitchTip) can be added.
- **Health**: `/api/v1/health/live` (process), `/api/v1/health/ready` (database, migrations at head,
  Redis, storage), `/api/v1/system/status` (+ worker ping).

## 15. Frontend

Next.js 16 App Router + TypeScript + Tailwind CSS. Pages are server components that read the API
through `BACKEND_INTERNAL_URL` at request time; interactive actions call the route handler
`/api/backend/[...path]`, which validates the path, forwards the request and injects the API bearer
token server-side. API types are generated from the backend OpenAPI schema (`openapi-typescript`).
Navigation shows later-phase pages as disabled with their phase number — no placeholder pages. A
header badge always shows `MOCK MODE` and the `AUTO-SUBMIT` state.

## 16. Configuration

All configuration comes from environment variables / the repo-root `.env` (see `.env.example`) through
one validated `Settings` object. Important switches:

| Setting | Default | Meaning |
|---|---|---|
| `MOCK_MODE` | `true` | Fake jobs, mock ATS pages only, never real submissions |
| `AUTO_SUBMIT` | `false` | Per-application approval required |
| `JOB_LOOKBACK_HOURS` | `24` | Posting window |
| `ATS_TARGET_SCORE` / `ATS_MAX_ITERATIONS` | `95` / `3` | ATS optimisation loop |
| `DAILY_RUN_TIME` / `TIMEZONE` | `08:00` / `Africa/Tunis` | Scheduler |
| `LLM_PROVIDER` / `CLAUDE_MODEL` | `claude` / `claude-opus-5` | LLM selection |
| `API_AUTH_TOKEN` | generated | Bearer token for the API (required in production) |
| `ENCRYPTION_KEY` | generated | Fernet key for secrets at rest (required in production) |

Production mode (`APP_ENV=production`) refuses to start without an API token, a valid encryption key and
JSON logs.

## 17. Testing strategy

- **Unit**: pure logic (config validation, redaction, dedup, scoring, truthfulness validators).
- **Integration**: real PostgreSQL (temporary database migrated with Alembic per test session) and Redis;
  API through FastAPI's test client; worker tasks executed directly or through an eager queue.
- **Browser**: Python Playwright against the mock ATS sites (Phase 8); Node Playwright E2E for the
  dashboard (Phase 1+).
- **LLM**: `MockLLMProvider` fixtures in CI; live-model evaluation suites are opt-in.
- **Tracking**: each test declares a `feature`; `scripts/update_tests_json.py` regenerates
  `tests.json` from real results and keeps the hand-maintained list of planned tests.
- Integration tests skip with an explicit reason when PostgreSQL/Redis are unreachable locally, and
  **fail** instead when `CI` or `REQUIRE_INTEGRATION` is set.

## 18. Multi-candidate readiness

`candidate_id` on candidate-scoped tables; services take a candidate context; one default candidate
initially. Authentication is a single bearer token today; per-user auth can replace it later without
changing the domain model.

## 19. n8n integration layer (optional, free)

n8n **Community Edition, self-hosted** is free for this use (Sustainable Use License: free for personal
and internal use; only reselling n8n as a hosted service is restricted). n8n Cloud and n8n Enterprise
features are not used. It runs as the optional Compose profile `n8n` (`make n8n`, UI on
`http://localhost:5678`), with its own volume and encryption key, telemetry disabled.

**Boundary — what goes where**

| n8n (low-code, user-editable) | Core (Python, tested, versioned) |
|---|---|
| Notification fan-out to any channel (Telegram, email, WhatsApp, Slack…) from core events | Discovery, normalization, dedup, 24-hour filter |
| Inbound job alerts: IMAP/Gmail trigger reads job-alert emails the user subscribed to (e.g. LinkedIn, Indeed) and posts the job URLs to the import API — the compliant way to cover LinkedIn | Visa classification, relevance, ATS scoring, truthfulness guard |
| Personal extras: Google Sheets export of applications, calendar follow-up reminders | CV tailoring, DOCX/PDF generation, answers |
| Optional alternative scheduler (Schedule Trigger → `POST` daily-run endpoint) | Browser automation, approval, SubmissionGuard, audit log |

**Contract**

- *Outbound*: the core's `WebhookNotificationProvider` (Phase 11) posts JSON events
  (`run.completed`, `application.ready_for_review`, `application.submitted`,
  `application.manual_action_required`) to `N8N_WEBHOOK_URL`, signed with HMAC-SHA256
  (`N8N_WEBHOOK_SECRET`) so n8n can verify them.
- *Inbound*: n8n calls the public REST API (e.g. job import, run trigger) with the API bearer token stored
  as an n8n "Header Auth" credential — n8n gets no database access and no extra privileges.
- Exported workflows live in `n8n/workflows/*.json` (no credentials inside) and are imported through the
  n8n UI or CLI.

The core never depends on n8n: Celery beat remains the built-in scheduler and Email/Telegram are
implemented natively, so stopping n8n loses only the optional extras.

## 20. Architecture decision records

| # | Decision | Rationale |
|---|---|---|
| 1 | Repository root is the `job-agent` monorepo root | The repository exists solely for this project; avoids an extra directory level for CI, Docker and README. |
| 2 | uv workspace: `backend` (package `app`) + `workers` (package `job_agent_workers`) | Matches the requested layout with real, separately deployable packages; one lockfile; the API never imports worker-only dependencies. |
| 3 | Celery + Redis (beat for scheduling in Phase 11) | Robust retries, time limits, separate queues (browser work isolated), cron schedules with time zones — one system instead of APScheduler + a queue. |
| 4 | Synchronous SQLAlchemy 2.0 + psycopg 3 | Same code in FastAPI (threadpool) and Celery (sync); simpler than mixing async and sync sessions. |
| 5 | UUID keys, UTC `timestamptz`, JSONB, VARCHAR + CHECK enums | Stable ids across systems; evolvable enums (a migration swaps the constraint) with DB-level integrity. |
| 6 | Next.js server-side proxy for mutations, server components for reads | API token never in the browser; backend URL configurable at runtime; no CORS dependency. |
| 7 | Bearer-token API auth + ports bound to localhost | Minimal, effective protection for a single-user self-hosted app. |
| 8 | structlog with a central redaction processor | One place guarantees secrets never reach logs, run events, audit entries or error reports. |
| 9 | Deterministic ATS scoring; LLM only extracts | Explainable, reproducible scores; prevents an LLM from "grading itself". |
| 10 | Python Playwright for automation, Node Playwright for dashboard E2E | Automation shares domain code in Python; UI tests use the standard Next.js tooling. |
| 11 | LibreOffice headless for DOCX → PDF (Phase 6) | Open source, reliable, server-side. |
| 12 | `MOCK_MODE=true`, `AUTO_SUBMIT=false` defaults | Safe by default; real submissions require deliberate configuration and approval. |
| 13 | Default LLM `claude-opus-5`, configurable | Most capable default for analysis/tailoring; cost trade-offs are the user's decision via config. |
| 14 | Application row created at discovery; user "skip" maps to `WITHDRAWN` with a reason | Uses exactly the requested status list while keeping one lifecycle per job. |
| 15 | Python 3.11 in containers and CI | Matches the verified development environment; upgrade is a one-line change. |
| 16 | n8n Community Edition (self-hosted, free) as an optional integration layer, pinned `n8nio/n8n:2.40.7` | Easy, user-editable notifications/email ingestion/extras at no cost; core logic stays in tested code, so the core never depends on n8n (requested by the user and by the spec). |
