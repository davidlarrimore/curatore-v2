"""CWR namespace — AI workflows (functions, procedures, pipelines)."""
from fastapi import APIRouter

from .routers import (
    contracts,
    functions,
    pipelines,
    procedures,
)

router = APIRouter(prefix="/cwr", tags=["CWR"])
router.include_router(functions.router)
router.include_router(procedures.router)
router.include_router(pipelines.router)
router.include_router(contracts.router)
