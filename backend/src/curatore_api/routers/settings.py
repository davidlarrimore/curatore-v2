# backend/src/curatore_api/routers/settings.py

from fastapi import APIRouter
from ..config import settings

# Create a new APIRouter instance for organizing settings-related endpoints.
router = APIRouter()

@router.get("/settings")
def get_settings():
    """
    Exposes a limited, read-only set of backend settings to the frontend.
    This is useful for the UI to know about backend defaults (e.g., for LLM and OCR).
    """
    return {
        "openai_model": settings.OPENAI_MODEL,
        "openai_base_url": settings.OPENAI_BASE_URL,
        "ocr_lang": settings.OCR_LANG,
        "ocr_psm": settings.OCR_PSM,
    }