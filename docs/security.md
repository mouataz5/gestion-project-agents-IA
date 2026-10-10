# Security & Compliance

This platform handles personal data (CVs, contact details, work-authorization status), third-party
credentials (LLM API key, SMTP, Telegram, ATS accounts) and can act on external websites on the
candidate's behalf. Security and compliance are therefore design constraints, not add-ons.

## 1. Assets

| Asset | Where it lives | Protection |
|---|---|---|
| Master CV, tailored CVs, cover letters | `candidate/master_cv/`, `storage/` (native) or the `appstorage` Docker volume | Git-ignored; served only through the authenticated API; `candidate/` is mounted read-only into containers; host disk encryption recommended |
| Candidate profile | `candidate/profile.yaml`, database | Contains no contact details; private overrides in git-ignored `profile.local.yaml` |
| API keys & passwords | `.env` (git-ignored) | `SecretStr` in config, redacted everywhere, never sent to the browser |
| API bearer token | `.env` → backend + Next.js server | Constant-time comparison; injected server-side by the Next.js proxy |
| Browser session state (cookies) | `browser_sessions` table (Phase 8) | Fernet-encrypted at rest, never logged, never committed (`playwright/.auth/` ignored) |
| Application history & audit trail | PostgreSQL | Append-only audit log; database port bound to localhost |

## 2. Threat model (summary)

| Threat | Mitigation |
|---|---|
| Secrets committed to Git | `.gitignore` covers `.env*`, auth state, storage, CVs; `.env.example` holds placeholders only; `scripts/generate_env.py` creates real values locally |
| Secrets leaked through logs, run events, audit entries or error reports | Central redaction (`app/core/redaction.py`) applied by the logging pipeline, the run recorder, the audit service and the error tracker; access logs never include headers or bodies; sensitive query parameters redacted |
| Secrets leaked to the browser | The API token and backend URL are server-only (`server-only` modules); the browser talks only to the Next.js origin |
| Unauthorized API access | Bearer token on every non-health endpoint (required when `APP_ENV=production`); all Compose ports bound to `127.0.0.1` |
| Unintended job applications | `AUTO_SUBMIT=false`, explicit approval, `SubmissionGuard`, `MOCK_MODE=true` default, idempotent submission, audit log (Phases 8–9) |
| Prompt injection inside job postings | Phase 4: the posting is sent inside `<job_posting>` tags (embedded tags neutralised) and the prompt declares it untrusted data; no tools are offered; answers must match a JSON schema; deterministic guards keep only visa quotes found verbatim in the posting and skill matches backed by the confirmed CV; explicit rules — not the model — decide APPLY/REVIEW/SKIP. Later phases add the truthfulness guard for generated documents; LLM output never triggers actions without the guards |
| Personal data sent to the LLM provider | Phase 4 sends only the facts that change the analysis (targets, work authorization, languages, CV-backed skills, experience/project bullets and technologies, degrees); never the name, contact details, employer or school names. Mock mode sends nothing |
| Prompts or answers leaking into logs | Only metadata is logged (provider, model, tokens, duration, request id); the Anthropic SDK and HTTP-client loggers are pinned at WARNING because they log whole request bodies at DEBUG; schema errors never echo the model's text (tested at `LOG_LEVEL=DEBUG`) |
| Fabricated CV content | Truthfulness guard + evidence ledger; unsupported keywords must be zero; unknown answers become `NEEDS_USER_INPUT` |
| SSRF through job-import URLs | Phase 3 never fetches imported URLs. `validate_public_url` accepts only http/https on ports 80/443 without credentials and rejects local/internal/single-label host names and non-global IP addresses in every notation (tested). Phase 10 fetchers add resolved-address checks at connection time, redirect re-validation, size and time limits |
| Malicious uploads (CV files) | Size limit, extension + magic-byte check, parsing in the worker with limits (zip-bomb safe DOCX reading), files stored with generated names (Phase 2) |
| XSS from scraped job content | Job descriptions are converted to plain text at ingestion and rendered as text (React escaping), never as HTML; external links open with `rel="noopener noreferrer"` |
| Path traversal in storage keys | `LocalStorageProvider` rejects absolute paths, `..` segments and keys resolving outside the storage root |
| Insecure deserialization in the task queue | Celery accepts JSON only (no pickle) |
| Supply-chain risk | Lockfiles (`uv.lock`, `package-lock.json`), pinned container images, CI lint/type/test gates; dependency audit added in Phase 11 |
| Container compromise impact | Non-root users in the backend/worker/frontend images; no Docker socket mounted; minimal base images |

## 3. Secrets management

- All secrets come from environment variables / the repo-root `.env`. Nothing secret is hard-coded.
- `make env` (or `scripts/setup.sh`) generates a strong `API_AUTH_TOKEN`, a Fernet `ENCRYPTION_KEY`,
  a database password and `N8N_ENCRYPTION_KEY`; it never overwrites an existing `.env` without `--force`.
- Production mode refuses to start without an API token (≥ 32 chars), a valid encryption key and JSON
  logs, and warns when the default database password is used.
- Settings expose secrets only as booleans ("configured / not configured") through
  `/api/v1/system/info`.
- **Rotation**: change the value in `.env`, restart the stack. Rotating `ENCRYPTION_KEY` requires
  re-encrypting stored secrets (a rotation command will ship with Phase 8, when the first encrypted
  column appears). Rotating `N8N_ENCRYPTION_KEY` makes stored n8n credentials unreadable — re-enter them.

## 4. Logging policy

Never logged: passwords, cookies, session tokens, API keys, authentication headers, request/response
bodies, CV contents, browser storage state. The redaction processor matches sensitive **keys**
(password, passwd, secret, token, api key, authorization, cookie, session, credential, private key,
DSN, signature…) and sensitive **values** (Bearer tokens, `sk-…` keys, credentials embedded in URLs,
JWTs, Telegram bot tokens) in every structured log event, including nested data and exception messages.
Tests assert that these values never appear in log output.

## 5. Network exposure

- Compose publishes PostgreSQL, Redis, API, frontend and n8n on `127.0.0.1` only.
- For remote access, put the frontend behind a TLS reverse proxy with authentication (e.g. Caddy with
  basic auth) or a private VPN (WireGuard/Tailscale). Do not expose the API or database directly.
- The frontend sets `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin` and a restrictive `Permissions-Policy`; a full CSP
  is added in Phase 11.

## 6. Automation ethics and website compliance

- Prefer official public APIs and feeds (Greenhouse, Lever, Ashby, SmartRecruiters job-board APIs,
  RSS) over HTML crawling.
- Respect `robots.txt`, site terms and API terms; enforce per-domain rate limits; identify the crawler
  with a descriptive user agent.
- LinkedIn is never scraped; only user-provided job URLs and job-alert emails are imported
  (`linkedin` and `manual_import` are `manual_only` sources).
- **Implemented in Phase 3** (`backend/app/crawlers/compliance.py`, `crawler/sources.yaml`): the source
  policy registry decides which sources may run and records why others are skipped; `RobotsPolicy`
  (RFC 9309: 4xx = no rules, 429/5xx/network error = disallow all, per-origin cache) and the Redis
  per-domain `RateLimiter` are tested now and wired into the real fetchers of Phase 10; mock sources
  run only with `MOCK_MODE=true` and never touch the network.
- **Never** bypass CAPTCHA, MFA, anti-bot systems, rate limits, paywalls or access controls. When one is
  met, the automation stops, takes a screenshot and reports **"Manual action required."**
  (`MANUAL_ACTION_REQUIRED`).
- Final submission requires explicit user approval by default (`AUTO_SUBMIT=false`) and is only
  performed where the site's policy allows automated submission.
- In `MOCK_MODE` the browser layer may only open mock ATS pages.

## 7. Data protection

- Data minimisation: only data needed for applications is stored; raw job content can be purged after a
  retention period (retention job in Phase 11).
- The candidate can export or delete their data (Phase 11 endpoint); backups should be encrypted.
- Third-party processing: job descriptions and CV content are sent to the configured LLM provider only
  for analysis/tailoring. Choose a provider/plan whose data-retention terms you accept; a local model
  provider (Ollama) can be added behind `LLMProvider`.

### 7.3 CV tailoring and ATS scoring (Phase 5)

- **What is sent to Anthropic** when `ANTHROPIC_API_KEY` is set, in two kinds of calls:
  - *Requirement extraction*: the job posting only, inside `<job_posting>` tags, as in §7.2. No
    candidate data is sent with it, and the result is cached per posting version.
  - *Tailoring*: the master CV facts with source ids — summary, experience titles and periods,
    bullets, project names and bullets, degree names, certifications, spoken languages and skills
    backed by the CV — plus the grounded requirement strings and deterministic feedback. Never sent:
    the name, email, phone, address, links, employer names, school names, locations, detail lines or
    other sections, and never the raw posting. The facts are built deterministically
    (`app/ats/tailoring.py`) and a unit test checks that contact data, employers and schools are
    absent.
- **Integrity**: the model never writes employers, titles, dates, education, certifications or
  languages; they are copied from the confirmed master CV by code. Every generated sentence cites
  master-CV source ids, and the deterministic guard reverts or rejects any technology, number, claim,
  job term or skill the cited sources do not contain. Unsupported keywords must be zero. Repairs are
  stored and shown, never silently dropped.
- **What is stored**: the tailored CV structure and plain text (personal data: same protection as the
  master CV in §7.1), the evidence ledger, each iteration's scores, keywords, violations and the
  validated document, the grounded requirements, token counts, request ids and models. Raw model
  answers are not stored. Error messages are redacted.
- **Logs** carry ids, scores and counts only: a test runs a tailoring at `LOG_LEVEL=DEBUG` and checks
  that no CV text and no prompt reaches the output.
- **Mock mode** without a key sends nothing anywhere; tailored CVs are labelled "Mock tailoring".

### 7.2 Job analysis (Phase 4)

- **What is sent to Anthropic** when `ANTHROPIC_API_KEY` is set: the job posting and the *candidate
  facts* document.
  - The facts are the target roles and countries, work authorization and relocation, languages, skills
    backed by the confirmed CV, experience and project titles with periods, bullets and technologies,
    degree names, certifications and years of experience.
  - Never sent: the candidate's name, email, phone, address, links, employer names or school names.
  - The document is built deterministically (`app/analysis/facts.py`) and covered by a test that checks
    contact data and employer names are absent.
- **What is stored**: the validated analysis (verdicts, quotes from the posting, reasons), token counts,
  the request id and the models. The raw model answer is not stored. Error messages are redacted.
- **Mock mode** without a key sends nothing anywhere; analyses are labelled "Mock analysis".
- **Key handling**: `ANTHROPIC_API_KEY` lives only in `.env`. It is passed to the SDK client and
  appears nowhere else: not in logs, run events, audit entries, error messages or the API (system
  info reports it as a boolean). Tests check that the key and the prompt text never reach the logs.

### 7.1 Candidate profile and master CV (Phase 2)

- **Where personal data lives**: the profile (including private contact details) and the parsed CV
  live in PostgreSQL; the original CV file lives in `STORAGE_DIR` (the `appstorage` Docker volume).
  None of it is in Git: `candidate/master_cv/*` and `candidate/*.local.yaml` are git-ignored, and the
  committed `profile.yaml` holds no contact details.
- **Exports** omit the private `contact` section unless `include_private=true` is explicitly requested;
  every export is audited with that flag. Audit entries record *which* profile sections changed and
  counts for CVs — never field values or CV text. Tests assert that contact values never reach the
  audit log and that CV text never reaches the service logs.
- **Upload validation** (before any parser touches the file): `.docx`/`.pdf` extension allow-list,
  magic bytes must match the extension, `MAX_UPLOAD_MB` limit (also enforced by the dashboard proxy),
  DOCX archives are inspected without extraction (entry count, total uncompressed size against ZIP
  bombs, encryption, macros), PDFs are limited to 10 pages and parsing errors map to `unreadable_file`.
  Rejected files are never stored.
- **Storage keys** are generated from the candidate id and the SHA-256 of the content; the uploaded
  filename is sanitised (no directories, control or reserved characters) and used only as metadata and
  in an RFC 6266 `Content-Disposition` header; downloads are sent with `nosniff` and `no-store`.
- **Integrity**: the parser never generates text, confirmed versions are immutable, and later phases
  may only use the confirmed fact base; skills without evidence (`NONE`) are never used for tailoring.

## 8. n8n

n8n Community Edition runs self-hosted (optional profile), bound to localhost, telemetry disabled, with
its own encryption key. It receives only the API bearer token (as an n8n credential) and signed webhook
events; it never gets database access. Exported workflows in `n8n/workflows/` must not contain
credentials.

## 9. Incident response

1. Rotate the affected secret(s) in `.env` (and at the provider), restart the stack.
2. Review `audit_logs` and the run history for unexpected actions.
3. Revoke browser sessions (delete `browser_sessions` rows; Phase 8) and re-authenticate manually.
4. Record the incident and the fix in `progress.md`.

## 10. Reporting

This is a personal project; report vulnerabilities privately to the repository owner rather than in a
public issue.
