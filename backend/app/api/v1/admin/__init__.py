"""Admin namespace — system config, auth, users, organizations."""
from fastapi import APIRouter

from .routers import (
    api_keys,
    auth,
    connections,
    organizations,
    scheduled_tasks,
    system,
    users,
)

router = APIRouter(prefix="/admin", tags=["Admin"])
router.include_router(auth.router)
router.include_router(organizations.router)
router.include_router(users.router)
router.include_router(api_keys.router)
router.include_router(connections.router)
router.include_router(system.router)
router.include_router(scheduled_tasks.router)
