from fastapi import APIRouter

# Aggregate all v1 routers here
from .routers import (
    auth,
    documents,
    system,
    sharepoint,
    organizations,
    users,
    api_keys,
    connections,
    storage,
    assets,
    runs,
    scrape,
    scheduled_tasks,
    render,
    search,
    sam,
    sharepoint_sync,
    queue_admin,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(users.router)
api_router.include_router(api_keys.router)
api_router.include_router(connections.router)
api_router.include_router(documents.router)
api_router.include_router(system.router)
api_router.include_router(sharepoint.router)
api_router.include_router(storage.router)
# Phase 0: Asset and Run endpoints
api_router.include_router(assets.router)
api_router.include_router(runs.router)
# Phase 4: Web Scraping endpoints
api_router.include_router(scrape.router)
# Phase 5: Scheduled Tasks endpoints
api_router.include_router(scheduled_tasks.router)
# General web rendering endpoints (Playwright)
api_router.include_router(render.router)
# Phase 6: Search endpoints
api_router.include_router(search.router)
# Phase 7: SAM.gov Integration endpoints
api_router.include_router(sam.router)
# Phase 8: SharePoint Sync Integration endpoints
api_router.include_router(sharepoint_sync.router)
# Extraction Queue Admin endpoints
api_router.include_router(queue_admin.router)

__all__ = ["api_router"]
