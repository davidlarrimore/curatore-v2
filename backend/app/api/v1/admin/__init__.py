"""Admin namespace — system config, auth, users, organizations."""
from fastapi import APIRouter

from .routers import (
    auth,
    users,
    organizations,
    connections,
    system,
    scheduled_tasks,
    api_keys,
)

router = APIRouter(prefix="/admin", tags=["Admin"])
router.include_router(auth.router)
router.include_router(organizations.router)
router.include_router(users.router)
router.include_router(api_keys.router)
router.include_router(connections.router)
router.include_router(system.router)
router.include_router(scheduled_tasks.router)
