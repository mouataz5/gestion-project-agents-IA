from fastapi import APIRouter

from app.api.routes import (
    audit,
    candidate,
    companies,
    health,
    job_sources,
    jobs,
    master_cv,
    runs,
    system,
    tailored_cvs,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router)
api_router.include_router(runs.router)
api_router.include_router(audit.router)
api_router.include_router(candidate.router)
api_router.include_router(master_cv.router)
api_router.include_router(tailored_cvs.router)
api_router.include_router(jobs.router)
api_router.include_router(job_sources.router)
api_router.include_router(companies.router)
