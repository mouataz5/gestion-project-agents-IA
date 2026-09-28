# n8n/ — optional integration layer

[n8n](https://n8n.io) Community Edition, **self-hosted and free** (Sustainable Use License: free for
personal and internal use; only reselling n8n as a hosted service is restricted). We do not use n8n
Cloud or paid Enterprise features.

n8n is **optional**. The core application (discovery, analysis, ATS scoring, truthful CV tailoring,
browser automation, approval) is tested Python code and runs without n8n. n8n adds easy,
user-editable integrations on top. See `docs/architecture.md` §19 for the full boundary.

## Start it

```bash
make n8n                      # = docker compose --profile n8n up -d n8n
open http://localhost:5678    # create the local owner account on first visit
```

- Data (workflows, encrypted credentials) lives in the `n8ndata` Docker volume.
- `N8N_ENCRYPTION_KEY` in `.env` encrypts n8n credentials; `scripts/generate_env.py` generates it.
  Keep it stable, otherwise stored credentials become unreadable.
- Telemetry and personalization are disabled; the port is bound to `127.0.0.1` only.

## Connect n8n to the job agent API

Inside Docker Compose, n8n reaches the API at `http://backend:8000/api/v1`.
Create an n8n credential of type **Header Auth**:

| Field | Value |
|---|---|
| Name | `Authorization` |
| Value | `Bearer <API_AUTH_TOKEN from .env>` |

Example (works today): an *HTTP Request* node `POST http://backend:8000/api/v1/runs/diagnostic` with that
credential starts a system self-test run, visible on the dashboard under **Runs**.

## Planned workflows (exported to `workflows/`, never containing credentials)

| Workflow | Trigger | Action | Phase |
|---|---|---|---|
| Job-alert email ingestion | IMAP / Gmail trigger on job-alert emails (LinkedIn, Indeed, …) | Extract job URLs → `POST /api/v1/jobs/import` | 3 / 10 |
| Notification fan-out | Webhook from the core (`run.completed`, `application.ready_for_review`, …) verified with HMAC | Telegram / email / WhatsApp / Slack message with dashboard links | 11 |
| Alternative scheduler | Schedule trigger (08:00 Africa/Tunis) | `POST` the daily-run endpoint (set `SCHEDULER_ENABLED=false` in the core) | 11 |
| Application tracker export | Webhook / schedule | Append/refresh rows in Google Sheets | 11 |
