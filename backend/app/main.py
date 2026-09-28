"""FastAPI application factory.

Run with:  uvicorn app.main:create_app --factory
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.error_tracking import ErrorTracker, create_error_tracker
from app.core.logging import configure_logging, get_logger
from app.core.queue import CeleryTaskQueue, TaskQueue, create_celery
from app.core.storage import StorageProvider, create_storage
from app.db.session import create_db_engine, create_session_factory
from app.services.health import HealthService

logger = get_logger("app.main")

DESCRIPTION = """
Self-hosted AI job application agent.

* **Discovery → analysis → CV generation → application preparation** are automated.
* **Submission** always requires explicit approval by default (`AUTO_SUBMIT=false`).
* All endpoints except `/health/*` require `Authorization: Bearer <API_AUTH_TOKEN>`.
"""


def create_app(
    settings: Settings | None = None,
    *,
    task_queue: TaskQueue | None = None,
    storage: StorageProvider | None = None,
    error_tracker: ErrorTracker | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings, component="api")

    engine = create_db_engine(settings, application_name="job-agent-api")
    session_factory = create_session_factory(engine)
    storage = storage or create_storage(settings)
    error_tracker = error_tracker or create_error_tracker(settings)
    task_queue = task_queue or CeleryTaskQueue(create_celery(settings))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "app.startup",
            version=__version__,
            environment=settings.app_env.value,
            mock_mode=settings.mock_mode,
            auto_submit=settings.auto_submit,
            api_auth=settings.auth_enabled,
        )
        for warning in settings.security_warnings():
            logger.warning("config.warning", detail=warning)
        yield
        engine.dispose()
        logger.info("app.shutdown")

    docs_enabled = settings.enable_api_docs
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.storage = storage
    app.state.error_tracker = error_tracker
    app.state.task_queue = task_queue
    app.state.health_service = HealthService(
        engine=engine, storage=storage, redis_url=settings.redis_dsn, task_queue=task_queue
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    # Added last = outermost: every request (and every unhandled error) gets a request id.
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str | None]:
        return {
            "name": settings.app_name,
            "version": __version__,
            "docs": "/docs" if docs_enabled else None,
            "health": f"{settings.api_prefix}/health/live",
        }

    return app
