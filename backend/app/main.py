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
from .core.models import ErrorResponse
from .api.v1 import api_router as v1_router
from .core.shared.document_service import document_service
from .core.storage.storage_service import storage_service
from .core.shared.database_service import database_service

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

class LevelColorFormatter(logging.Formatter):
    """Formatter that injects ANSI colors based on record level."""

    RESET = "\033[0m"
    LEVEL_COLORS = {
        logging.DEBUG: "\033[36m",    # Cyan
        logging.INFO: "\033[32m",     # Green
        logging.WARNING: "\033[33m",  # Yellow
        logging.ERROR: "\033[31m",    # Red
        logging.CRITICAL: "\033[35m", # Magenta
    }

    def __init__(self, fmt: str, datefmt: str | None = None, use_color: bool = True) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        original_levelname = record.levelname
        if self._use_color:
            color = self.LEVEL_COLORS.get(record.levelno)
            if color:
                record.levelname = f"{color}{original_levelname}{self.RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


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

    fmt_pattern = "%(asctime)s %(levelname)s [%(name)s] [%(request_id)s] %(message)s"
    file_fmt = logging.Formatter(fmt_pattern)
    console_fmt = LevelColorFormatter(
        fmt_pattern,
        use_color=os.getenv("NO_COLOR") is None
    )

    fh = RotatingFileHandler(os.path.join(log_dir, "api.log"), maxBytes=5*1024*1024, backupCount=3)
    ch = logging.StreamHandler()
    fh.setFormatter(file_fmt)
    ch.setFormatter(console_fmt)
    # Console/file levels: DEBUG when in debug mode, otherwise INFO
    ch.setLevel(logging.DEBUG if settings.debug else logging.INFO)
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
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
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
    
    # Log current working directory and storage configuration
    print(f"📍 Current working directory: {os.getcwd()}")
    print(f"📦 Object Storage Configuration:")
    print(f"   USE_OBJECT_STORAGE: {settings.use_object_storage}")
    print(f"   MINIO_ENDPOINT: {getattr(settings, 'minio_endpoint', 'Not configured')}")
    print(f"   MINIO_BUCKET_UPLOADS: {getattr(settings, 'minio_bucket_uploads', 'curatore-uploads')}")
    print(f"   MINIO_BUCKET_PROCESSED: {getattr(settings, 'minio_bucket_processed', 'curatore-processed')}")

    # Extraction engine summary
    try:
        print("🔧 Extraction Engine Configuration:")
        print(f"   EXTRACTION_SERVICE_URL: {settings.extraction_service_url}")
        print(f"   DOCLING_SERVICE_URL: {getattr(settings, 'docling_service_url', None)}")
    except Exception:
        pass
    
    try:
        # Initialize database
        print("🗄️  Initializing database...")
        try:
            # Check database health first
            db_health = await database_service.health_check()
            if db_health["status"] == "healthy":
                print(f"   ✅ Database connected ({db_health.get('database_type', 'unknown')})")
            else:
                print(f"   ⚠️  Database connection issue: {db_health.get('error', 'unknown')}")

            # Initialize database tables (safe to run multiple times)
            await database_service.init_db()
            print("   ✅ Database tables initialized")

            # Log authentication status
            auth_enabled = settings.enable_auth
            auth_status = "enabled" if auth_enabled else "disabled (backward compatibility mode)"
            print(f"   🔐 Authentication: {auth_status}")

        except Exception as e:
            print(f"   ⚠️  Database initialization warning: {e}")
            if settings.enable_auth:
                print("   ❌ CRITICAL: Authentication is enabled but database failed to initialize")
                raise
            else:
                print("   ℹ️  Continuing without database (authentication disabled)")

        # Initialize queue registry
        try:
            print("📋 Initializing queue registry...")
            from .core.ops.queue_registry import initialize_queue_registry
            initialize_queue_registry()
            print("   ✅ Queue registry initialized")
        except Exception as e:
            print(f"   ⚠️  Queue registry initialization warning: {e}")
            # Non-fatal - registry will use defaults

        # Discover and register procedures and pipelines
        try:
            print("🔄 Discovering procedures and pipelines...")
            async with database_service.get_session() as session:
                from .cwr.procedures.store.discovery import procedure_discovery_service
                from .cwr.pipelines.store.discovery import pipeline_discovery_service
                from sqlalchemy import select
                from .core.database.models import Organization

                # Get organizations to register procedures/pipelines for
                result = await session.execute(select(Organization))
                orgs = result.scalars().all()

                for org in orgs:
                    # Discover and register procedures
                    proc_result = await procedure_discovery_service.discover_and_register(
                        session, org.id
                    )
                    proc_removed = proc_result.get('removed', 0)
                    proc_msg = f"   ✅ Procedures: {proc_result.get('registered', 0)} registered, {proc_result.get('updated', 0)} updated"
                    if proc_removed > 0:
                        proc_msg += f", {proc_removed} removed"
                    proc_msg += f" for org {org.name}"
                    print(proc_msg)

                    # Discover and register pipelines
                    pipe_result = await pipeline_discovery_service.discover_and_register(
                        session, org.id
                    )
                    pipe_removed = pipe_result.get('removed', 0)
                    pipe_msg = f"   ✅ Pipelines: {pipe_result.get('registered', 0)} registered, {pipe_result.get('updated', 0)} updated"
                    if pipe_removed > 0:
                        pipe_msg += f", {pipe_removed} removed"
                    pipe_msg += f" for org {org.name}"
                    print(pipe_msg)

        except ImportError as e:
            print(f"   ⚠️  Procedure/pipeline discovery not available: {e}")
        except Exception as e:
            print(f"   ⚠️  Procedure/pipeline discovery warning: {e}")
            # Non-fatal - procedures can be loaded on-demand

        # Sync default connections from environment variables
        try:
            print("🔗 Syncing default connections from environment variables...")
            async with database_service.get_session() as session:
                from .core.auth.connection_service import sync_default_connections_from_env
                from sqlalchemy import select
                from .core.database.models import Organization
                from uuid import UUID

                # Determine which organization to sync for
                org_id = None
                if settings.enable_auth and settings.default_org_id:
                    # Multi-tenant mode: sync for default org
                    try:
                        org_id = UUID(settings.default_org_id)
                    except (ValueError, AttributeError):
                        print(f"   ⚠️  Invalid DEFAULT_ORG_ID: {settings.default_org_id}")
                else:
                    # Backward compatibility mode: sync for first org
                    result = await session.execute(select(Organization).limit(1))
                    org = result.scalar_one_or_none()
                    if org:
                        org_id = org.id

                if org_id:
                    results = await sync_default_connections_from_env(session, org_id)

                    for conn_type, status in results.items():
                        if status == "error":
                            print(f"   ⚠️  {conn_type}: failed to sync")
                        elif status == "created":
                            print(f"   ✅ {conn_type}: created default connection")
                        elif status == "updated":
                            print(f"   🔄 {conn_type}: updated default connection")
                        elif status == "unchanged":
                            print(f"   ➡️  {conn_type}: unchanged")
                        elif status == "skipped":
                            print(f"   ⏭️  {conn_type}: skipped (env vars not set)")
                else:
                    print("   ⚠️  No organization found, skipping connection sync")

        except Exception as e:
            print(f"   ⚠️  Failed to sync default connections: {e}")
            # Don't fail startup if connection sync fails

        # The DocumentService handles directory creation and validation
        # This is called during service import/initialization

        # Clear files and storage on startup in debug or when explicitly requested
        # Preserve batch files by default; only clear batch when CLEAR_BATCH_ON_STARTUP is set.
        clear_on_startup = bool(os.getenv("CLEAR_ON_STARTUP", "").lower() in {"1", "true", "yes"})
        clear_batch = bool(os.getenv("CLEAR_BATCH_ON_STARTUP", "").lower() in {"1", "true", "yes"})
        if settings.debug or clear_on_startup:
            print("🧹 Cleaning up previous session data (debug/explicit)…")

            # Clear object storage if enabled
            if settings.use_object_storage:
                try:
                    from .core.storage.minio_service import get_minio_service
                    minio = get_minio_service()

                    if minio and minio.enabled:
                        if clear_batch:
                            print("   - Clearing all MinIO buckets (uploads, processed, temp)")
                            minio.delete_all_objects_in_bucket(minio.bucket_uploads)
                            minio.delete_all_objects_in_bucket(minio.bucket_processed)
                            minio.delete_all_objects_in_bucket(minio.bucket_temp)
                        else:
                            print("   - Clearing MinIO uploads and processed buckets (preserving temp)")
                            minio.delete_all_objects_in_bucket(minio.bucket_uploads)
                            minio.delete_all_objects_in_bucket(minio.bucket_processed)
                        print("   ✓ Object storage cleared")
                    else:
                        print("   ⚠️  MinIO not configured, skipping storage cleanup")
                except Exception as e:
                    print(f"   ⚠️  Failed to clear object storage: {e}")

            # Clear in-memory storage cache
            storage_service.clear_all()
            print("✅ Storage cleared")
        else:
            print("↩️  Preserving existing storage (production mode)")

        # Initialize object storage (MinIO) if enabled
        if settings.use_object_storage:
            print("📦 Initializing MinIO object storage...")
            try:
                from .core.storage.minio_service import get_minio_service
                minio = get_minio_service()
                if minio:
                    # Ensure buckets exist
                    buckets = [
                        settings.minio_bucket_uploads,
                        settings.minio_bucket_processed,
                        settings.minio_bucket_temp,
                    ]
                    for bucket in buckets:
                        minio.ensure_bucket(bucket)

                    print("   ✅ MinIO storage initialized")
                    print(f"      MinIO Endpoint: {settings.minio_endpoint}")
                    print(f"      Buckets: {settings.minio_bucket_uploads}, {settings.minio_bucket_processed}, {settings.minio_bucket_temp}")
                else:
                    print("   ⚠️  Object storage disabled in settings")
            except Exception as e:
                print(f"   ❌ Failed to initialize MinIO storage: {e}")
                raise
        else:
            print("📁 Using filesystem storage (USE_OBJECT_STORAGE=false)")

        # Log LLM service status
        from .core.llm.llm_service import llm_service
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
    - Database connection cleanup
    - Temporary file cleanup
    - Connection cleanup
    - Resource deallocation
    """
    print("🛑 Shutting down Curatore v2...")

    try:
        # Close database connections
        print("🧹 Performing shutdown cleanup...")
        try:
            await database_service.close()
            print("   ✅ Database connections closed")
        except Exception as e:
            print(f"   ⚠️  Database cleanup warning: {e}")

        # Clean up any temporary files or connections
        # Note: In-memory storage will be garbage collected

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

# Primary, versioned API
app.include_router(
    v1_router,
    prefix="/api/v1",
)

# ============================================================================
# OPENAPI CUSTOMIZATION
# ============================================================================

def _build_tag_description(base: str) -> str:
    base_desc = {
        "System": "System health, status, and maintenance endpoints.",
        "Configuration": "Configuration and capability metadata endpoints.",
        "Documents": "Document management: upload, list, and delete.",
        "Processing": "Document processing operations and workflows.",
        "Results": "Accessing, editing, and downloading processing results.",
        "Storage": "Object storage operations for uploads and downloads.",
        "Legacy": "Legacy compatibility endpoints.",
    }.get(base, f"Endpoints for {base}.")
    return f"{base_desc} API v1."


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
    tag_meta = {}  # base -> (name, desc)
    for path, methods in list(schema.get("paths", {}).items()):
        if not isinstance(methods, dict):
            continue
        # Only process v1 API endpoints
        if not path.startswith("/api/v1/"):
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
                name = f"v1: {base}"
                new_tags.append(name)
                # Record tag metadata
                if name not in seen_tags:
                    desc = _build_tag_description(base)
                    seen_tags[name] = desc
                    tag_meta[base] = (name, desc)
            operation["tags"] = new_tags

    # Inject descriptive tag metadata with deterministic ordering
    bases_order = ["System", "Documents", "Processing", "Results", "Storage", "Configuration", "Legacy", "General"]
    ordered = []
    for b in bases_order:
        if b in tag_meta:
            name, desc = tag_meta[b]
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



@app.get("/docs/v1", include_in_schema=False)
async def docs_v1():
    return get_swagger_ui_html(
        openapi_url="/openapi-v1.json",
        title=f"{settings.api_title} — API V1 Docs",
    )



# Also expose versioned Swagger UI under the API prefixes for convenience
@app.get("/api/v1/docs", include_in_schema=False)
async def api_v1_docs():
    return get_swagger_ui_html(
        openapi_url="/openapi-v1.json",
        title=f"{settings.api_title} — API V1 Docs",
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
        },
        "health": {
            "v1": "/api/v1/health",
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
