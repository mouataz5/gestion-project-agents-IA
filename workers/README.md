# workers/

Celery worker package (`job_agent_workers`). It depends on the backend package (`app`) and contains
**only thin task wrappers** — all business logic lives in `backend/app/services/` so it can be tested
without a broker.

```
workers/
├── job_agent_workers/
│   ├── celery_app.py      # Celery application (shared config from app.core.queue)
│   ├── signals.py         # logging context, error tracking, per-process DB engine reset
│   ├── runtime.py         # lazily-created per-process resources (settings, DB, storage)
│   └── tasks/system.py    # system.ping, system.run_diagnostic
└── tests/
```

Run locally (from the repository root):

```bash
make worker
# = uv run celery -A job_agent_workers.celery_app worker --loglevel=INFO
```

The backend never imports this package: it enqueues tasks by name (`app/core/tasks.py`), which keeps
the API process free of worker-only dependencies (Playwright, LibreOffice) added in later phases.
The daily scheduler (Celery beat) is added in Phase 11.
