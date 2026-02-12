from fastapi import APIRouter

from .admin import router as admin_router
from .cwr import router as cwr_router
from .data import router as data_router
from .ops import router as ops_router

api_router = APIRouter()
api_router.include_router(admin_router)
api_router.include_router(data_router)
api_router.include_router(ops_router)
api_router.include_router(cwr_router)

__all__ = ["api_router"]
