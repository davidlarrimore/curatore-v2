"""Data namespace — content, search, connectors."""
from fastapi import APIRouter

from .routers import (
    assets,
    forecasts,
    metadata,
    render,
    salesforce,
    sam,
    scrape,
    search,
    sharepoint,
    sharepoint_sync,
    storage,
    webhooks,
)

router = APIRouter(prefix="/data", tags=["Data"])
router.include_router(assets.router)
router.include_router(storage.router)
router.include_router(search.router)
router.include_router(metadata.router)
router.include_router(sam.router)
router.include_router(salesforce.router)
router.include_router(forecasts.router)
router.include_router(sharepoint_sync.router)
router.include_router(scrape.router)
router.include_router(sharepoint.router)
router.include_router(render.router)
router.include_router(webhooks.router)
