"""Ops namespace — execution & monitoring."""
from fastapi import APIRouter

from .routers import (
    runs,
    queue_admin,
    websocket,
    metrics,
)

router = APIRouter(prefix="/ops", tags=["Ops"])
router.include_router(runs.router)
router.include_router(queue_admin.router)
router.include_router(websocket.router)
router.include_router(metrics.router)
