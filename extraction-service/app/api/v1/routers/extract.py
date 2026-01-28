import os
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from ....models import ExtractionOptions, ExtractionResult
from ....config import settings
from ....services.extraction_service import save_upload_to_disk, extract_markdown
from ....services.metadata_extractor import extract_document_metadata

router = APIRouter(prefix="/extract", tags=["extraction"])

def _ensure_size(file: UploadFile):
    # FastAPI streams; we rely on MAX_FILE_SIZE and Docker/nginx limits in production
    return

@router.post("", response_model=ExtractionResult)
async def extract(
    file: UploadFile = File(...),
    options: ExtractionOptions = Depends()
):
    _ensure_size(file)
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    path = save_upload_to_disk(file, settings.UPLOAD_DIR)

    content_md, method, ocr_used, page_count = extract_markdown(
        path=path,
        filename=file.filename,
        media_type=file.content_type or "",
        force_ocr=options.force_ocr,
        ocr_fallback=options.ocr_fallback,
        ocr_lang=(options.ocr_lang or settings.OCR_LANG),
        ocr_psm=(options.ocr_psm or settings.OCR_PSM),
    )

    if not content_md:
        raise HTTPException(status_code=422, detail="No text could be extracted from this file.")

    # Extract document metadata
    doc_metadata = extract_document_metadata(
        path=path,
        filename=file.filename,
        content=content_md,
        extraction_method=method,
    )

    # Merge extraction options with document metadata
    combined_metadata = {
        "upload_path": path,
        "ocr_lang": options.ocr_lang or settings.OCR_LANG,
        "ocr_psm": options.ocr_psm or settings.OCR_PSM,
        **doc_metadata,
    }

    return ExtractionResult(
        filename=file.filename,
        content_markdown=content_md,
        content_chars=len(content_md),
        method=method,
        ocr_used=ocr_used,
        page_count=page_count,
        media_type=file.content_type,
        metadata=combined_metadata,
    )
