from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .api.v1.routers import extract as extract_router
from .api.v1.routers import system as system_router

app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    debug=settings.DEBUG,
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_CREDENTIALS,
    allow_methods=settings.CORS_METHODS,
    allow_headers=settings.CORS_HEADERS,
)

# Versioned API (mirrors backend style)
app.include_router(system_router.router, prefix="/api/v1")
app.include_router(extract_router.router, prefix="/api/v1")

# Legacy alias `/api` if needed later:
legacy = FastAPI(openapi_url="/api/openapi.json", docs_url="/api/docs")
