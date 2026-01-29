"""
System Router - Health and status endpoints.
"""

from fastapi import APIRouter

from ....models import HealthResponse
from ....services.browser_pool import browser_pool
from ....config import settings

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Check service health.

    Returns:
        HealthResponse with status and browser pool info
    """
    return HealthResponse(
        status="healthy",
        browser_pool_size=settings.browser_pool_size,
        active_browsers=browser_pool.active_contexts,
    )


@router.get("/")
async def root() -> dict:
    """Root endpoint."""
    return {
        "service": settings.api_title,
        "version": settings.api_version,
        "status": "running",
    }
