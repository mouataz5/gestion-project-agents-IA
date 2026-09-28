# AI Job Application Agent — developer commands.  Run `make help` for the list.
# Requires: uv, Node.js >= 20.9 + npm, and Docker (for the containerised stack).

SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
NPM ?= npm
COMPOSE ?= docker compose
ALEMBIC := $(UV) run alembic -c backend/alembic.ini
# Export the variables of .env to the command (values in .env are shell-compatible).
WITH_ENV := set -a; if [ -f .env ]; then . ./.env; fi; set +a;

.PHONY: help install install-python install-frontend install-e2e e2e-browsers env setup \
	up down logs ps infra-up n8n compose-check mock \
	migrate migration backend worker frontend scheduler \
	test test-backend test-frontend test-e2e lint format typecheck check tests-json openapi clean

help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-17s\033[0m %s\n", $$1, $$2}'

# --- Setup ---------------------------------------------------------------------------------
install: install-python install-frontend install-e2e ## Install all dependencies
install-python: ## Install the Python workspace (backend + workers + dev tools)
	$(UV) sync --all-packages
install-frontend: ## Install frontend dependencies
	$(NPM) --prefix frontend ci
install-e2e: ## Install the Playwright test runner
	$(NPM) --prefix playwright ci
e2e-browsers: ## Download the Chromium build used by the E2E tests
	cd playwright && npx playwright install chromium
env: ## Create .env with freshly generated secrets (never overwrites an existing .env)
	python3 scripts/generate_env.py
setup: ## First-time setup: prerequisites check, .env, dependencies
	./scripts/setup.sh

# --- Docker Compose ------------------------------------------------------------------------
up: ## Build and start the full stack
	$(COMPOSE) up -d --build
mock: ## Start the full stack forcing MOCK_MODE=true and AUTO_SUBMIT=false
	MOCK_MODE=true AUTO_SUBMIT=false $(COMPOSE) up -d --build
down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down
logs: ## Follow the logs of all services
	$(COMPOSE) logs -f --tail=100
ps: ## Show service status and health
	$(COMPOSE) ps
infra-up: ## Start only PostgreSQL and Redis (for native development)
	$(COMPOSE) up -d postgres redis
n8n: ## Start the optional n8n integration layer on http://localhost:5678
	$(COMPOSE) --profile n8n up -d n8n
compose-check: ## Validate docker-compose.yml
	$(COMPOSE) config --quiet && echo "docker-compose.yml is valid"

# --- Native development --------------------------------------------------------------------
migrate: ## Apply database migrations
	$(WITH_ENV) $(ALEMBIC) upgrade head
migration: ## New migration: make migration m="add candidate tables" rev=0002
	@test -n "$(m)" -a -n "$(rev)" || (echo 'usage: make migration m="message" rev=0002'; exit 1)
	$(WITH_ENV) $(ALEMBIC) revision --autogenerate -m "$(m)" --rev-id $(rev)
backend: ## Run the API with auto-reload on http://localhost:8000
	$(WITH_ENV) $(UV) run uvicorn app.main:create_app --factory --reload \
		--port $${BACKEND_PORT:-8000} --no-access-log
worker: ## Run a Celery worker
	$(WITH_ENV) $(UV) run celery -A job_agent_workers.celery_app:celery_app worker \
		--loglevel=INFO --concurrency=2
frontend: ## Run the dashboard dev server on http://localhost:3000
	$(WITH_ENV) $(NPM) --prefix frontend run dev
scheduler: ## Daily scheduler (Celery beat) — delivered in Phase 11
	@echo "The daily scheduler is delivered in Phase 11 (see docs/implementation-plan.md)."
	@exit 1

# --- Quality -------------------------------------------------------------------------------
test: test-backend test-frontend ## Run all unit and integration tests
test-backend: ## Backend + worker tests (needs PostgreSQL and Redis: make infra-up)
	$(UV) run pytest
test-frontend: ## Frontend unit tests
	$(NPM) --prefix frontend run test
test-e2e: ## Browser E2E tests against a running stack (E2E_BASE_URL, default :3000)
	$(WITH_ENV) $(NPM) --prefix playwright test
lint: ## Ruff, Black (check), ESLint and Prettier (check)
	$(UV) run ruff check .
	$(UV) run black --check .
	$(NPM) --prefix frontend run lint
	$(NPM) --prefix frontend run format:check
format: ## Auto-format Python and TypeScript
	$(UV) run ruff check --fix .
	$(UV) run black .
	$(NPM) --prefix frontend run format
typecheck: ## mypy (strict) and TypeScript
	$(UV) run mypy
	$(NPM) --prefix frontend run typecheck
check: lint typecheck test ## Everything CI runs
tests-json: ## Run every suite and regenerate tests.json
	$(UV) run python scripts/update_tests_json.py
openapi: ## Export the OpenAPI schema and regenerate the frontend API types
	$(UV) run python scripts/export_openapi.py
	$(NPM) --prefix frontend run gen:api
clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .artifacts frontend/.next \
		playwright/test-results playwright/playwright-report
	find . -name __pycache__ -type d -prune -not -path "./.venv/*" -exec rm -rf {} +
