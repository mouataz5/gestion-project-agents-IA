from fastapi import APIRouter

from app.api.routes import audit, health, runs, system

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router)
api_router.include_router(runs.router)
api_router.include_router(audit.router)
