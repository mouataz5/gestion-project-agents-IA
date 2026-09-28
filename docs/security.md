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
| Prompt injection inside job postings | Job text is treated as data inside structured prompts; outputs are schema-validated; the truthfulness guard checks every claim against the master CV; LLM output never triggers actions without the guards (Phases 4–7) |
| Fabricated CV content | Truthfulness guard + evidence ledger; unsupported keywords must be zero; unknown answers become `NEEDS_USER_INPUT` |
| SSRF through job-import URLs | Scheme allow-list (`https`, `http`), DNS resolution checked against private/loopback/link-local ranges, redirects re-validated, size and time limits (Phase 3) |
| Malicious uploads (CV files) | Size limit, extension + magic-byte check, parsing in the worker with limits (zip-bomb safe DOCX reading), files stored with generated names (Phase 2) |
| XSS from scraped job content | Job descriptions rendered as sanitized text/Markdown, never as raw HTML; React escaping by default |
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
- LinkedIn is never scraped; only user-provided job URLs and job-alert emails are imported.
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
