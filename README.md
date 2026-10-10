# AI Job Application Agent

A self-hosted platform that discovers newly posted AI/ML/GenAI jobs, analyses them (visa
sponsorship, relevance), builds a **truthful**, ATS-optimised CV for each qualifying job, prepares
the application in the company's own ATS — and **stops before submitting** until you approve.

> **Status: Phases 1–5 complete** — foundation, candidate profile & master CV, job discovery, job
> analysis (visa sponsorship, CV match, APPLY / REVIEW / SKIP) and the **ATS engine** (a truthful
> tailored CV per job, scored and improved towards a target). Next: Phase 6, the CV documents
> (DOCX/PDF). The remaining phases are delivered in the order 6 → 10 → 7 → 8 → 9 → 11, the fastest
> route to real applications. See [`progress.md`](progress.md) and the
> [implementation plan](docs/implementation-plan.md).

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
database password. Every variable is documented in [`.env.example`](.env.example).

To analyse jobs with Claude, add your key: `ANTHROPIC_API_KEY=sk-ant-…` (from
[console.anthropic.com](https://console.anthropic.com)). Without it, mock mode runs a deterministic
offline analysis instead, clearly labelled **Mock analysis**. `CLAUDE_MODEL` defaults to
`claude-opus-5-5` and `LLM_EFFORT` to `medium`. A `.env` created before Phase 4 keeps the
`CLAUDE_MODEL` it was created with: change it there if you want the new default.

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

Mock mode is the enforced safety posture (visible as a **MOCK MODE** badge on every page). In mock
mode, discovery reads fictional ATS boards and a fictional aggregator feed from
`crawler/fixtures/mock_jobs/` and never contacts a real site; the mock ATS sites (Phase 8) plug into
the same switch. With `MOCK_MODE=false`, mock sources never run and their jobs are hidden.

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
demand from the dashboard ("Run job discovery", "Analyse new jobs", "Run system diagnostic") or the
API (`POST /api/v1/runs/discovery`, `POST /api/v1/runs/analysis`, `POST /api/v1/runs/diagnostic`).

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

## Find jobs (Phase 3)

1. **Watchlist** — open http://localhost:3000/companies and click **Import companies.yaml** (the
   seed holds fictional companies served by the mock boards), or add the companies you follow.
2. **Discovery** — click **Run job discovery** (Jobs page or dashboard). The run timeline shows each
   source, the counts and anything that failed.
3. **Jobs** — http://localhost:3000/jobs lists jobs posted in the last `JOB_LOOKBACK_HOURS` by default.
   Each job shows how its date is known: *Posted 3 h ago* (source timestamp), *≈ 2 d ago (estimated)*
   (relative text, counted conservatively) or *Date unknown* (never counted as recent — see the
   **Date unknown** tab and use **Track this job** to queue one by hand). Duplicates found on several
   sources are merged under the most authoritative listing.
4. **LinkedIn and other sites** — use **Import a job URL** and paste the posting with the details you
   see. Nothing is fetched or scraped. Job-alert emails can be imported automatically with the n8n
   workflow in [`n8n/workflows/`](n8n/workflows/job-alert-email-import.json).

Matching jobs (AI/ML title, target country, posted in the window) are queued as `DISCOVERED`, ready
for the analysis below. Source policy and compliance rules: [`crawler/README.md`](crawler/README.md).

## Analyse jobs (Phase 4)

1. **Confirm your master CV first** (Phase 2 above). The analysis reads only the confirmed version.
2. Click **Analyse new jobs** on the dashboard or the Jobs page. Each queued job is analysed (up to
   `ANALYSIS_MAX_JOBS_PER_RUN` per run, 25 by default), and the run timeline shows each decision.
3. Open a job to see its analysis:
   - **Apply / Review / Skip** and the reasons. Explicit rules decide; Claude's own suggestion is
     shown when it differs.
   - **Visa sponsorship**: confirmed, likely, not mentioned, or ruled out, always with the sentences
     quoted from the posting (highlighted in the description). The page also says whether *you* need
     sponsorship there, based on your profile.
   - **Match**: the required and preferred skills your CV backs, the ones it does not, languages,
     seniority, and concerns.
   - **Provenance**: model, prompt version, tokens.

   **Re-analyse** runs it again, for example after you change your CV.
4. Filter the Jobs list by recommendation or visa status. The dashboard counts the jobs to apply to,
   review, skip, and those still waiting.

Nothing is invented. A visa statement counts only if it is quoted verbatim from the posting. A skill
match counts only if your confirmed CV demonstrates or lists the skill. Unknown stays unknown, and
uncertain cases go to **Review**, never to **Skip**. Only the facts needed for the match are sent to
Claude, never your name, contact details or employer names
([security](docs/security.md#72-job-analysis-phase-4)). The server-side **refusal fallback** is
enabled by default (`LLM_REFUSAL_FALLBACK=true`): if Claude declines a posting, the request is retried
on the fallback model Anthropic designates, and the analysis records which model answered.

## Tailor your CV (Phase 5)

1. **Analyse the jobs first** (Phase 4 above). Jobs recommended **Apply** are tailored by default;
   a **Review** job is tailored when you click **Tailor CV** on its page (or with
   `CV_GENERATION_INCLUDE_REVIEW=true`). **Skip** jobs never are.
2. Click **Tailor CVs** on the dashboard. Each waiting job (up to `CV_GENERATION_MAX_JOBS_PER_RUN`
   per run, 10 by default) gets its own CV version, and the run timeline shows each score.
3. Open a job to see its **Tailored CV & ATS** card:
   - the **ATS score** of your master CV and of the tailored version, the **target** (95 by default)
     and the score **reachable** with what your CV actually says;
   - **why it stopped**: target reached, only unsupported gains left, no further improvement, or the
     iteration limit;
   - the **score breakdown** (keywords, skills, experience, responsibilities, title, education,
     structure) and the job's keywords: in this CV, in your master CV but unused, and **missing**;
   - **gaps only you can close**: add them to your master CV *only if they are true*.

   **Re-tailor** runs it again, for example after you confirm a new master CV (older tailored CVs
   are then marked as built from an earlier master).
4. **Open the tailored CV** to check it line by line. Every summary and bullet shows where it comes
   from in your master CV ("Experience 1 · bullet 1"), with the original text one click away, and the
   page lists the facts not used and any rewrite the guard reverted.

Nothing is invented. Employers, titles, dates, education, certifications and languages are copied
from your confirmed master CV by code, never written by the model. Every rewritten sentence must
cite the master-CV lines it comes from, and a deterministic guard reverts any technology, number,
claim or job term those lines do not contain. A keyword your CV does not support is reported as a
gap, never added: **95 is a target, not a promise**. The scoring is deterministic and versioned
(`ats-score.v1`), with weights you can change (`ATS_SCORE_WEIGHTS`). Claude never sees your name,
contact details, employers or schools, and never the raw posting when it rewrites your CV
([security](docs/security.md#73-cv-tailoring-and-ats-scoring-phase-5)). Without an API key, mock mode
tailors offline and labels the result "Mock tailoring".

## What Phase 5 delivers

- **ATS engine**: a skills taxonomy shared with the analysis, job requirements grounded in the posting
  (cached per posting), the deterministic `ats-score.v1` score with a supported ceiling, keyword
  classes (matched / available / missing / unsupported, which must be 0), stuffing penalties, and
  feedback and gaps.
- **Truthful tailoring**: the model only selects, orders and rewords sourced bullets; immutable facts
  are copied by code; a guard checks every sentence against the master-CV lines it cites, reverts
  what it cannot back, and rejects any version that still breaks a rule. Every text carries an
  evidence ledger.
- **Optimisation loop**: up to `ATS_MAX_ITERATIONS` calls towards `ATS_TARGET_SCORE`, stopping as soon
  as further gains would need unsupported claims; no call at all when none can help.
- **Runs and storage**: a CV generation run per click (or per job), idempotent and capped, with each
  attempt, iteration and tailored CV version stored and audited.
- **UI**: the job page's ATS card, the tailored CV page with sources, the tailored CVs on `/cv`, an
  ATS column on `/jobs`, a dashboard card and an ATS engine card in Settings.

## What Phase 4 delivers

- **LLM layer**: provider interface with Claude (official SDK, structured JSON output, effort, refusal
  fallback, prompt caching of your facts, clear errors for keys, limits and outages) and an offline
  mock. Prompts are versioned files ([`prompts/`](prompts/README.md)).
- **Analysis**: visa classification (EN/FR/DE phrase rules plus Claude, verbatim quotes only),
  sponsorship need from your profile, CV-backed skill matching, language checks and an explicit
  APPLY / REVIEW / SKIP rules table. Stored with model, prompt and token usage.
- **Runs**: an analysis run per click (or per job), with a confirmed-CV check, a per-run cap and
  idempotence. Failures and refusals are isolated per job.
- **UI**: analysis panel on each job, recommendation and visa filters, a dashboard analysis card, and
  a Language model card in Settings.

## What Phase 3 delivers

- **Jobs** with every field of the specification, job skills, company watchlist and applications
  with the full status lifecycle (transition table, audited).
- **Sources**: versioned policy file (`crawler/sources.yaml`), mock ATS boards and aggregator feed,
  registry that explains why a source does not run; robots.txt policy and per-domain rate limiter
  ready for real sources (Phase 10).
- **Deduplication** by source id, canonical URL (tracking removed) and content hash, with the ATS
  record as primary; **posting window** with known / estimated / unknown dates.
- **Imports** of pasted URLs and job-alert emails (validated against SSRF, never fetched).
- **UI**: Jobs list and detail, Companies, discovery card on the dashboard.

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
crawler/     source policy, watchlist seed and mock job fixtures
prompts/     versioned LLM prompts
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
