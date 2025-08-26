# backend/app/api/v1.py
from fastapi import APIRouter
from .routers import documents, system

api_router = APIRouter()
api_router.include_router(documents.router)
api_router.include_router(system.router)