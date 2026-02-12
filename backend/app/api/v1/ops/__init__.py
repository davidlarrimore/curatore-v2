"""Ops namespace — execution & monitoring."""
from fastapi import APIRouter

from .routers import (
    metrics,
    queue_admin,
    runs,
    websocket,
)

router = APIRouter(prefix="/ops", tags=["Ops"])
router.include_router(runs.router)
router.include_router(queue_admin.router)
router.include_router(websocket.router)
router.include_router(metrics.router)
