from fastapi import APIRouter
from ....models import SupportedFormats
from ....services.extraction_service import SUPPORTED_EXTS

router = APIRouter(prefix="/system", tags=["system"])

@router.get("/health")
def health():
    return {"status": "ok", "service": "extraction-service"}

@router.get("/supported-formats", response_model=SupportedFormats)
def supported_formats():
    return SupportedFormats(extensions=sorted(list(SUPPORTED_EXTS)))
