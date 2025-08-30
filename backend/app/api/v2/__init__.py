from fastapi import APIRouter

# V2 routers (initially based on v1, now standalone for evolution)
from .routers import documents, system, jobs

api_router = APIRouter()
api_router.include_router(documents.router)
api_router.include_router(system.router)
api_router.include_router(jobs.router)

__all__ = ["api_router"]
