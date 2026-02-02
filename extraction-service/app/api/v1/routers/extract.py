"""
Extraction API router.

Handles document extraction for Office files, text files, and emails.
PDFs and images are handled by fast_pdf (PyMuPDF) and Docling respectively.
"""

import os
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from ....models import ExtractionOptions, ExtractionResult
from ....config import settings
from ....services.extraction_service import save_upload_to_disk, extract_markdown
from ....services.metadata_extractor import extract_document_metadata

router = APIRouter(prefix="/extract", tags=["extraction"])


@router.post("", response_model=ExtractionResult)
async def extract(
    file: UploadFile = File(...),
    options: ExtractionOptions = Depends()
):
    """
    Extract text content from a document.

    Supported formats:
    - Office: DOCX, PPTX, XLSX, DOC, PPT, XLS, XLSB
    - Text: TXT, MD, CSV
    - Email: MSG, EML

    Note: PDFs and images should be sent to fast_pdf or Docling engines.
    """
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    path = save_upload_to_disk(file, settings.UPLOAD_DIR)

    content_md, method, ocr_used, page_count = extract_markdown(
        path=path,
        filename=file.filename,
        media_type=file.content_type or "",
    )

    if not content_md:
        raise HTTPException(
            status_code=422,
            detail="No text could be extracted from this file."
        )

    # Extract document metadata
    doc_metadata = extract_document_metadata(
        path=path,
        filename=file.filename,
        content=content_md,
        extraction_method=method,
    )

    return ExtractionResult(
        filename=file.filename,
        content_markdown=content_md,
        content_chars=len(content_md),
        method=method,
        ocr_used=ocr_used,
        page_count=page_count,
        media_type=file.content_type,
        metadata={"upload_path": path, **doc_metadata},
    )
