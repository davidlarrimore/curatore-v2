from fastapi import APIRouter

# Aggregate all v1 routers here
from .routers import auth, documents, system, jobs, sharepoint, organizations, users, api_keys, connections, storage

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(users.router)
api_router.include_router(api_keys.router)
api_router.include_router(connections.router)
api_router.include_router(documents.router)
api_router.include_router(system.router)
api_router.include_router(jobs.router)
api_router.include_router(sharepoint.router)
api_router.include_router(storage.router)

__all__ = ["api_router"]
