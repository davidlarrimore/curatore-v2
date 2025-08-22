from fastapi import APIRouter
from ..config import settings

router = APIRouter()

@router.get("/settings")
def get_settings():
    # limited read-only exposure for UI defaults
    return {
        "openai_model": settings.OPENAI_MODEL,
        "openai_base_url": settings.OPENAI_BASE_URL,
        "ocr_lang": settings.OCR_LANG,
        "ocr_psm": settings.OCR_PSM,
    }