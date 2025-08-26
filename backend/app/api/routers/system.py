# backend/app/api/routers/system.py
from datetime import datetime
from fastapi import APIRouter, HTTPException

from ...config import settings
from ...models import HealthStatus, LLMConnectionStatus
from ...services.llm_service import llm_service
from ...services.document_service import document_service
from ...services.storage_service import storage_service

router = APIRouter()

@router.get("/health", response_model=HealthStatus, tags=["System"])
async def health_check():
    """Health check endpoint."""
    llm_status = await llm_service.test_connection()
    
    return HealthStatus(
        status="healthy",
        timestamp=datetime.now(),
        version=settings.api_version,
        llm_connected=llm_status.connected,
        storage_available=True
    )

@router.get("/llm/status", response_model=LLMConnectionStatus, tags=["System"])
async def get_llm_status():
    """Get LLM connection status."""
    return await llm_service.test_connection()

@router.post("/system/reset", tags=["System"])
async def reset_system():
    """Reset the entire system - clear all files and data."""
    try:
        document_service.clear_all_files()
        storage_service.clear_all()
        document_service._ensure_directories()
        
        return {
            "success": True,
            "message": "System reset successfully",
            "timestamp": datetime.now()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")

@router.get("/config/supported-formats", tags=["Configuration"])
async def get_supported_formats():
    """Get list of supported file formats."""
    return {
        "supported_extensions": document_service.get_supported_extensions(),
        "max_file_size": settings.max_file_size
    }

@router.get("/config/defaults", tags=["Configuration"])
async def get_default_config():
    """Get default configuration values."""
    return {
        "quality_thresholds": {
            "conversion": settings.default_conversion_threshold,
            "clarity": settings.default_clarity_threshold,
            "completeness": settings.default_completeness_threshold,
            "relevance": settings.default_relevance_threshold,
            "markdown": settings.default_markdown_threshold
        },
        "ocr_settings": {
            "language": settings.ocr_lang,
            "psm": settings.ocr_psm
        },
        "auto_optimize": True
    }

@router.get("/items", tags=["Legacy"])
def list_items():
    """Legacy endpoint for frontend compatibility."""
    return [
        {"id": 1, "name": "Document Processing"},
        {"id": 2, "name": "LLM Integration"},
        {"id": 3, "name": "Quality Assessment"},
    ]