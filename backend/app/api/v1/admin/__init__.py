"""Admin namespace — system config, auth, users, organizations, services."""
from fastapi import APIRouter

from .routers import (
    api_keys,
    auth,
    connections,
    data_connections,
    organizations,
    roles,
    scheduled_tasks,
    service_accounts,
    services,
    system,
    system_cwr,
    users,
)

router = APIRouter(prefix="/admin", tags=["Admin"])
router.include_router(auth.router)
router.include_router(organizations.router)
router.include_router(users.router)
router.include_router(roles.router)
router.include_router(api_keys.router)
router.include_router(connections.router)
router.include_router(data_connections.router)
router.include_router(services.router)
router.include_router(service_accounts.router)
router.include_router(system.router)
router.include_router(scheduled_tasks.router)
router.include_router(system_cwr.router)
