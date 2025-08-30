# ============================================================================
# Curatore v2 - FastAPI Application Entry Point
# ============================================================================
"""
Main FastAPI application module for Curatore v2, a RAG document processing API.

This module sets up the FastAPI application with:
- CORS middleware configuration for cross-origin requests
- Application startup/shutdown event handlers
- Error handling for validation errors
- API router integration
- Service initialization and cleanup

Environment Requirements:
    - Docker volume mount: /app/files (for document storage)
    - Environment variables (see config.py for full list)

Usage:
    Direct: python -m app.main
    Docker: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    
Architecture:
    - FastAPI for REST API framework
    - Pydantic for data validation and settings
    - Service layer pattern for business logic
    - In-memory storage for processing results
    - Volume-mounted file storage for documents

Author: Curatore Team
Version: 2.0.0
"""

import os
import json
import uuid
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from starlette.requests import Request as StarletteRequest
from starlette.types import Message
from pydantic import ValidationError

from .config import settings
from .models import ErrorResponse
from .api.v1 import api_router as v1_router
from .api.v2 import api_router as v2_router
from .services.document_service import document_service
from .services.storage_service import storage_service

# ============================================================================
# APPLICATION INITIALIZATION
# ============================================================================

# Initialize FastAPI application with metadata
app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description=(
        "Curatore v2 - RAG Document Processing API\n\n"
        "A comprehensive document processing pipeline that converts documents "
        "to markdown, evaluates quality, and optimizes content for RAG applications."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# ============================================================================
# LOGGING
# ============================================================================

def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("curatore.api")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG if settings.debug else logging.INFO)

    # Ensure logs dir exists (prefer /app/logs inside container)
    log_dir = "/app/logs"
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        log_dir = os.getcwd()

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] [%(request_id)s] %(message)s"
    )

    fh = RotatingFileHandler(os.path.join(log_dir, "api.log"), maxBytes=5*1024*1024, backupCount=3)
    ch = logging.StreamHandler()
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    # Console at INFO; file at DEBUG in debug mode, INFO otherwise
    ch.setLevel(logging.INFO)
    fh.setLevel(logging.DEBUG if settings.debug else logging.INFO)

    class ReqIdFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if not hasattr(record, "request_id"):
                record.request_id = "-"
            return True

    fh.addFilter(ReqIdFilter())
    ch.addFilter(ReqIdFilter())
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger

api_logger = _setup_logging()

# ============================================================================
# MIDDLEWARE CONFIGURATION
# ============================================================================

# Configure CORS middleware for cross-origin requests
# In debug, widen CORS to any localhost origin to avoid dev friction
allow_any_localhost = settings.debug and not settings.cors_origin_regex
cors_allow_origins = ["*"] if allow_any_localhost else settings.cors_origins
cors_allow_regex = r"^http://.+$" if allow_any_localhost else settings.cors_origin_regex
cors_allow_credentials = False if allow_any_localhost else True

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_origin_regex=cors_allow_regex,
    allow_credentials=cors_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"]
)

# ============================================================================
# REQUEST/RESPONSE LOGGING MIDDLEWARE
# ============================================================================

@app.middleware("http")
async def request_response_logger(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    method = request.method
    path = request.url.path
    query = str(request.url.query)
    content_type = request.headers.get("content-type", "")
    start = datetime.now()

    # Only buffer JSON bodies; avoid touching multipart bodies
    receive = None
    body_preview = None
    try:
        if content_type.startswith("application/json") and method in {"POST", "PUT", "PATCH"}:
            raw = await request.body()

            async def receive_with_body() -> Message:
                return {"type": "http.request", "body": raw, "more_body": False}

            receive = receive_with_body
            body_preview = raw[:2048].decode("utf-8", errors="ignore")
    except Exception:
        body_preview = None

    extra = {"request_id": request_id}
    api_logger.info(f"REQ {method} {path}{('?' + query) if query else ''} ct={content_type}", extra=extra)
    # Only log JSON request bodies when in debug mode to avoid noise
    if settings.debug and body_preview:
        api_logger.debug(f"REQ-BODY {body_preview}", extra=extra)

    response = await call_next(StarletteRequest(request.scope, receive) if receive else request)
    duration_ms = (datetime.now() - start).total_seconds() * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{duration_ms:.2f}ms"
    api_logger.info(f"RES {method} {path} -> {response.status_code} ({duration_ms:.1f} ms)", extra=extra)
    return response

# ============================================================================
# APPLICATION EVENT HANDLERS
# ============================================================================

@app.on_event("startup")
async def startup_event() -> None:
    """
    Application startup event handler.
    
    Performs initialization tasks including:
    - Directory structure validation
    - File system cleanup (development mode)
    - Service initialization
    - Storage cleanup
    
    Raises:
        Exception: If critical initialization fails
        
    Note:
        This handler runs once when the application starts.
        In development mode, it clears all files and storage for a clean start.
    """
    print("🚀 Starting Curatore v2...")
    print(f"   Version: {settings.api_version}")
    print(f"   Debug Mode: {settings.debug}")
    
    # Log current working directory and configured paths
    print(f"📍 Current working directory: {os.getcwd()}")
    print(f"📁 Configured storage paths:")
    print(f"   FILES_ROOT: {settings.files_root}")
    print(f"   UPLOAD_DIR: {settings.upload_dir}")
    print(f"   PROCESSED_DIR: {settings.processed_dir}")
    print(f"   BATCH_DIR: {settings.batch_dir}")
    
    # Validate that the main files directory exists (should be Docker volume)
    files_root = Path(settings.files_root)
    if not files_root.exists():
        print(f"⚠️  WARNING: Main files directory doesn't exist: {files_root}")
        print("   This may indicate Docker volume mount issues.")
    
    try:
        # The DocumentService handles directory creation and validation
        # This is called during service import/initialization
        
        # Clear files and storage on startup only in explicit dev mode
        clear_on_startup = bool(os.getenv("CLEAR_ON_STARTUP", "").lower() in {"1", "true", "yes"})
        if settings.debug or clear_on_startup:
            print("🧹 Cleaning up previous session data (debug/explicit)…")
            document_service.clear_all_files()
            storage_service.clear_all()
            print("✅ File directories and storage cleared")
        else:
            print("↩️  Preserving existing files and storage (production mode)")
        
        # Log LLM service status
        from .services.llm_service import llm_service
        llm_status = "available" if llm_service.is_available else "unavailable"
        print(f"🤖 LLM Service: {llm_status}")
        
        print("✅ Startup complete - Curatore v2 ready to process documents")
        
    except Exception as e:
        print(f"❌ Startup failed: {e}")
        raise


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """
    Application shutdown event handler.
    
    Performs cleanup tasks including:
    - Temporary file cleanup
    - Connection cleanup
    - Resource deallocation
    """
    print("🛑 Shutting down Curatore v2...")
    
    try:
        # Clean up any temporary files or connections
        # Note: In-memory storage will be garbage collected
        print("🧹 Performing shutdown cleanup...")
        
        print("✅ Shutdown complete")
        
    except Exception as e:
        print(f"⚠️  Shutdown cleanup warning: {e}")


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """
    Global exception handler for Pydantic validation errors.
    
    Args:
        request: The FastAPI request object
        exc: The Pydantic ValidationError exception
        
    Returns:
        JSONResponse: Formatted error response with 422 status code
        
    Note:
        This handler catches validation errors from Pydantic models
        and returns them in a consistent format.
    """
    error_response = ErrorResponse(
        error="Validation Error",
        detail=str(exc),
        timestamp=datetime.now()
    )
    # Attach request id if available
    try:
        error_response.request_id = getattr(request.state, "request_id", None)
    except Exception:
        pass
    
    return JSONResponse(status_code=422, content=jsonable_encoder(error_response))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Global exception handler for HTTP exceptions.
    
    Args:
        request: The FastAPI request object
        exc: The HTTPException
        
    Returns:
        JSONResponse: Formatted error response
    """
    error_response = ErrorResponse(
        error=f"HTTP {exc.status_code}",
        detail=str(exc.detail),
        timestamp=datetime.now()
    )
    try:
        error_response.request_id = getattr(request.state, "request_id", None)
    except Exception:
        pass
    
    return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(error_response))


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Global exception handler for unhandled exceptions.
    
    Args:
        request: The FastAPI request object
        exc: The unhandled exception
        
    Returns:
        JSONResponse: Generic error response with 500 status code
        
    Note:
        This is a catch-all handler for unexpected errors.
        In production, you may want to log these errors.
    """
    error_response = ErrorResponse(
        error="Internal Server Error",
        detail="An unexpected error occurred",
        timestamp=datetime.now()
    )
    
    # In debug mode, include the actual error details
    if settings.debug:
        error_response.detail = str(exc)
    # Log the exception with request id for correlation
    try:
        api_logger.exception(f"Unhandled exception for {request.method} {request.url.path}", extra={"request_id": getattr(request.state, "request_id", "-")})
    except Exception:
        pass
    try:
        error_response.request_id = getattr(request.state, "request_id", None)
    except Exception:
        pass
    
    return JSONResponse(status_code=500, content=jsonable_encoder(error_response))


# ============================================================================
# ROUTER CONFIGURATION
# ============================================================================

# API ROUTERS
# ----------------------------------------------------------------------------
# Expose versioned routes at /api/v1 following industry best practices.
# Keep non-versioned /api as a backward-compatible alias for v1 (deprecated).

# Primary, versioned API
app.include_router(
    v1_router,
    prefix="/api/v1",
)

# Future version scaffold (currently mirrors v1)
app.include_router(
    v2_router,
    prefix="/api/v2",
)

# Backward-compatible alias for existing clients/tests hitting /api/*
# This mirrors v1 and should be removed in a future major release.
app.include_router(
    v1_router,
    prefix="/api",
)

# Add deprecation headers for non-versioned /api/* requests to guide migration
@app.middleware("http")
async def legacy_api_deprecation_header(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/v"):
        # RFC 8594 style guidance via headers
        response.headers["Deprecation"] = "true"
        # Example sunset date ~90 days from now (adjust as needed)
        response.headers["Sunset"] = "Tue, 30 Nov 2027 23:59:59 GMT"
        response.headers["Link"] = "</api/v1>; rel=successor-version"
    return response

# ============================================================================
# OPENAPI CUSTOMIZATION
# ============================================================================

def _build_tag_description(base: str, version_label: str) -> str:
    base_desc = {
        "System": "System health, status, and maintenance endpoints.",
        "Configuration": "Configuration and capability metadata endpoints.",
        "Documents": "Document management: upload, list, and delete.",
        "Processing": "Document processing operations and workflows.",
        "Results": "Accessing, editing, and downloading processing results.",
        "Legacy": "Legacy compatibility endpoints.",
    }.get(base, f"Endpoints for {base}.")
    suffix = "API v1" if version_label == "v1" else ("API v2" if version_label == "v2" else "API v1 (legacy alias)")
    return f"{base_desc} {suffix}."


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    # Transform operation tags to be version-specific and add metadata
    seen_tags = {}
    tag_meta = {}  # (version, base) -> (name, desc)
    for path, methods in list(schema.get("paths", {}).items()):
        if not isinstance(methods, dict):
            continue
        # Determine version label from path
        if path.startswith("/api/v1/"):
            version_label = "v1"
        elif path.startswith("/api/v2/"):
            version_label = "v2"
        elif path.startswith("/api/"):
            version_label = "v1 (legacy)"
        else:
            # Non-API or root endpoints, skip
            continue

        for method, operation in methods.items():
            if not isinstance(operation, dict):
                continue
            tags = operation.get("tags", [])
            # Drop any router-level tags we might add in future
            base_tags = [t for t in tags if not t.startswith("api-")]
            if not base_tags:
                base_tags = ["General"]
            new_tags = []
            for t in base_tags:
                # Normalize base tag capitalization
                base = t.title()
                # Prefix with version for clarity
                vprefix = "v1: " if version_label.startswith("v1") and version_label != "v1 (legacy)" else (
                    "v2: " if version_label == "v2" else "v1 (legacy): "
                )
                name = f"{vprefix}{base}"
                new_tags.append(name)
                # Record tag metadata
                if name not in seen_tags:
                    # version id for description builder: 'v1', 'v2', or 'v1 (legacy)'
                    if vprefix.startswith("v1: "):
                        version_id = "v1"
                    elif vprefix.startswith("v2: "):
                        version_id = "v2"
                    else:
                        version_id = "v1 (legacy)"
                    desc = _build_tag_description(base, version_id)
                    seen_tags[name] = desc
                    tag_meta[(version_id, base)] = (name, desc)
            operation["tags"] = new_tags

    # Inject descriptive tag metadata with deterministic ordering
    versions_order = ["v1", "v2", "v1 (legacy)"]
    bases_order = ["System", "Documents", "Processing", "Results", "Configuration", "Legacy", "General"]
    ordered = []
    for v in versions_order:
        for b in bases_order:
            key = (v, b)
            if key in tag_meta:
                name, desc = tag_meta[key]
                ordered.append({"name": name, "description": desc})
    # Fallback for any unaccounted tags
    remaining = [{"name": name, "description": desc} for name, desc in seen_tags.items()
                 if name not in {t["name"] for t in ordered}]
    schema["tags"] = ordered + sorted(remaining, key=lambda t: t["name"])

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore


# ============================================================================
# PER-VERSION OPENAPI SCHEMAS AND DOCS
# ============================================================================

def _routes_for_version(ver: str):
    prefix = f"/api/{ver}/"
    return [r for r in app.routes if getattr(r, "path", "").startswith(prefix)]


def build_version_openapi(ver: str):
    routes = _routes_for_version(ver)
    title = f"{settings.api_title} — API {ver.upper()}"
    description = (
        f"{app.description}\n\nThis documentation covers API {ver.upper()} endpoints only."
    )
    schema = get_openapi(
        title=title,
        version=settings.api_version,
        description=description,
        routes=routes,
    )
    return schema


@app.get("/openapi-v1.json", include_in_schema=False)
async def openapi_v1():
    return JSONResponse(build_version_openapi("v1"))


@app.get("/openapi-v2.json", include_in_schema=False)
async def openapi_v2():
    return JSONResponse(build_version_openapi("v2"))


@app.get("/docs/v1", include_in_schema=False)
async def docs_v1():
    return get_swagger_ui_html(
        openapi_url="/openapi-v1.json",
        title=f"{settings.api_title} — API V1 Docs",
    )


@app.get("/docs/v2", include_in_schema=False)
async def docs_v2():
    return get_swagger_ui_html(
        openapi_url="/openapi-v2.json",
        title=f"{settings.api_title} — API V2 Docs",
    )

# Also expose versioned Swagger UI under the API prefixes for convenience
@app.get("/api/v1/docs", include_in_schema=False)
async def api_v1_docs():
    return get_swagger_ui_html(
        openapi_url="/openapi-v1.json",
        title=f"{settings.api_title} — API V1 Docs",
    )


@app.get("/api/v2/docs", include_in_schema=False)
async def api_v2_docs():
    return get_swagger_ui_html(
        openapi_url="/openapi-v2.json",
        title=f"{settings.api_title} — API V2 Docs",
    )

# ============================================================================
# ROOT ENDPOINT
# ============================================================================

@app.get("/", tags=["root"])
async def root() -> Dict[str, Any]:
    """
    Root endpoint providing API information.
    
    Returns:
        Dict[str, Any]: API metadata including version, status, and links
    """
    return {
        "name": settings.api_title,
        "version": settings.api_version,
        "status": "running",
        "description": "Curatore v2 - RAG Document Processing API",
        "docs_url": "/docs",
        "health_check": "/api/v1/health",
        "docs": {
            "v1": "/api/v1/docs",
            "v2": "/api/v2/docs",
        },
        "health": {
            "v1": "/api/v1/health",
            "v2": "/api/v2/health",
        },
        "timestamp": datetime.now()
    }


# ============================================================================
# DEVELOPMENT SERVER
# ============================================================================

if __name__ == "__main__":
    """
    Development server entry point.
    
    This runs the application using uvicorn for development.
    In production, use a proper ASGI server configuration.
    """
    import uvicorn
    
    # Development server configuration
    uvicorn.run(
        "app.main:app",  # Application path
        host="0.0.0.0",  # Accept connections from any IP
        port=8000,       # Port to listen on
        reload=True,     # Auto-reload on code changes
        log_level="info" # Logging level
    )
