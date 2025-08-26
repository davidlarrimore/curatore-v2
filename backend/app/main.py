# backend/app/main.py
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from .config import settings
from .models import (
    ErrorResponse
)
from .api.v1 import api_router
from .services.document_service import document_service
from .services.storage_service import storage_service

# Create FastAPI app
app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description="Curatore v2 - RAG Document Processing API"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Clear directories on startup
@app.on_event("startup")
async def startup_event():
    """Application startup event handler."""
    print("🚀 Starting Curatore v2...")
    
    print(f"📍 Current working directory: {os.getcwd()}")
    print(f"📁 Settings paths:")
    print(f"   FILES_ROOT: {settings.files_root}")
    print(f"   UPLOAD_DIR: {settings.upload_dir}")
    print(f"   PROCESSED_DIR: {settings.processed_dir}")
    print(f"   BATCH_DIR: {settings.batch_dir}")

    # The DocumentService will handle directory creation in its __init__
    # which is called when document_service is imported.
    
    # Clear files and in-memory storage on startup
    document_service.clear_all_files()
    storage_service.clear_all()
    print("✅ File directories and in-memory storage cleared on startup")
    
    print("✅ Startup complete")


# Include the main API router
app.include_router(api_router, prefix="/api")

# Error handler
@app.exception_handler(ValidationError)
async def validation_exception_handler(request, exc):
    return HTTPException(
        status_code=422,
        detail=ErrorResponse(
            error="Validation Error",
            detail=str(exc),
            timestamp=datetime.now()
        ).dict()
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)