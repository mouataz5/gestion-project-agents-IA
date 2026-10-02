# Python image for the backend API, database migrations and Celery workers.
# Build context: repository root.

FROM python:3.11-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
# uv from PyPI (pinned): works wherever PyPI is reachable, no extra registry needed.
RUN pip install --no-cache-dir "uv==0.8.17"
WORKDIR /app

# --- Dependencies (cached until pyproject/uv.lock change) --------------------------------
FROM base AS deps
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/README.md backend/
COPY workers/pyproject.toml workers/README.md workers/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages --no-install-workspace

# --- Runtime -------------------------------------------------------------------------------
FROM base AS runtime
RUN groupadd --system app && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app
COPY --from=deps /app/.venv /app/.venv
COPY pyproject.toml uv.lock ./
COPY backend backend
COPY workers workers
COPY prompts prompts
COPY crawler crawler
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages \
 && mkdir -p /app/storage /app/candidate \
 && chown -R app:app /app/storage

ENV PATH="/app/.venv/bin:$PATH" \
    STORAGE_DIR=/app/storage \
    CANDIDATE_DIR=/app/candidate \
    PROMPTS_DIR=/app/prompts \
    CRAWLER_DIR=/app/crawler

USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4).status == 200 else 1)"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers"]
