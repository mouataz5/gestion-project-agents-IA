from fastapi import APIRouter

from app.api.routes import audit, candidate, health, master_cv, runs, system

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router)
api_router.include_router(runs.router)
api_router.include_router(audit.router)
api_router.include_router(candidate.router)
api_router.include_router(master_cv.router)
