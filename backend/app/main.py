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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .config import settings
from .models import ErrorResponse
from .api.v1 import api_router
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
# MIDDLEWARE CONFIGURATION
# ============================================================================

# Configure CORS middleware for cross-origin requests
# This allows the frontend (localhost:3000) to communicate with the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,  # Configured via environment
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"]
)

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
        
        # Clear files and in-memory storage on startup (development behavior)
        print("🧹 Cleaning up previous session data...")
        document_service.clear_all_files()
        storage_service.clear_all()
        print("✅ File directories and in-memory storage cleared")
        
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
    
    return JSONResponse(
        status_code=422,
        content=error_response.dict()
    )


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
    
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.dict()
    )


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
    
    return JSONResponse(
        status_code=500,
        content=error_response.dict()
    )


# ============================================================================
# ROUTER CONFIGURATION
# ============================================================================

# Include the main API router with /api prefix
# This includes all document processing, system, and utility endpoints
app.include_router(
    api_router,
    prefix="/api",
    tags=["api"]
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
        "health_check": "/api/health",
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