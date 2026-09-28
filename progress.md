# Progress

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: Docker, PostgreSQL, FastAPI, Next.js, configuration, logging, health checks, migrations | 🚧 in progress |
| 2 | Candidate profile, master CV upload & parsing, candidate database | ⏳ planned |
| 3 | Job model, discovery abstraction, mock source, deduplication, 24-hour filter | ⏳ planned |
| 4 | LLM provider (Claude), job analysis, visa classification, matching | ⏳ planned |
| 5 | ATS engine, tailoring, iterative optimization | ⏳ planned |
| 6 | DOCX/PDF generation | ⏳ planned |
| 7 | Application question engine | ⏳ planned |
| 8 | Playwright, mock ATS, browser adapters | ⏳ planned |
| 9 | Human approval workflow | ⏳ planned |
| 10 | Real public career/ATS integrations | ⏳ planned |
| 11 | Scheduling, notifications, dashboard, hardening | ⏳ planned |

## Log

### 2026-09-28 — Phase 1 started
- Inspected the repository: empty apart from `.gitattributes` (initial commit).
- Created the monorepo skeleton, `docs/architecture.md`, `docs/implementation-plan.md`,
  `docs/security.md`, `tests.json` (80 planned tests for Phases 2–11) and this file.
- Created `candidate/profile.yaml` with the provided candidate data (no invented values; unknowns are `null`).
- User request: consider n8n if it works well and is free → adopted n8n Community Edition (self-hosted,
  free) as an **optional integration layer** (notifications, job-alert email ingestion, extras); the core
  stays in tested Python code (ADR 16, architecture §19).
