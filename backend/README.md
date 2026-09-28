# backend/

FastAPI application and all domain code (Python package `app`).

```
app/
├── main.py          # create_app() factory — run with: uvicorn app.main:create_app --factory
├── api/             # routers, dependencies (auth, DB session), error handlers
├── core/            # config, logging, redaction, errors, error tracking, security, storage, queue
├── db/              # SQLAlchemy base/session + Alembic migrations (db/migrations)
├── models/          # ORM models
├── schemas/         # Pydantic API schemas
├── services/        # use cases: health, runs, audit, diagnostics
├── agents/ crawlers/ ats/ browser/ llm/ applications/ notifications/   # later phases
tests/
├── unit/            # no external services
└── integration/     # PostgreSQL + Redis (temporary database, migrated per session)
```

Common commands (run from the repository root):

```bash
uv sync --all-packages                                  # install
uv run alembic -c backend/alembic.ini upgrade head      # migrate  (make migrate)
uv run uvicorn app.main:create_app --factory --reload   # dev server (make backend)
uv run pytest                                           # tests (make test-backend)
```

API documentation: http://localhost:8000/docs (OpenAPI JSON at `/openapi.json`).
