"""
Playwright Rendering Service - FastAPI Application.

A microservice for rendering JavaScript-heavy web pages using Playwright
and extracting structured content (HTML, markdown, links).

This service is designed to be called by the Curatore backend's crawl service
for web scraping operations that require JavaScript rendering.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .services.browser_pool import browser_pool
from .api.v1.routers import render as render_router
from .api.v1.routers import system as system_router

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("playwright.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler - initialize and shutdown browser pool."""
    # Startup
    logger.info("Starting Playwright Rendering Service")
    await browser_pool.initialize()
    yield
    # Shutdown
    logger.info("Shutting down Playwright Rendering Service")
    await browser_pool.shutdown()


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    debug=settings.debug,
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_credentials,
    allow_methods=settings.cors_methods,
    allow_headers=settings.cors_headers,
)

# Include routers
app.include_router(system_router.router, prefix="/api/v1")
app.include_router(render_router.router, prefix="/api/v1")

# Root-level health check for Docker healthcheck
app.include_router(system_router.router, prefix="")
