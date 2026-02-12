"""
Extraction API router.

Handles document extraction for Office files, text files, and emails.
PDFs and images are handled by fast_pdf (PyMuPDF) and Docling respectively.
"""

import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile

from ....config import settings
from ....models import ExtractionOptions, ExtractionResult
from ....services.extraction_service import extract_markdown, save_upload_to_disk
from ....services.metadata_extractor import extract_document_metadata

router = APIRouter(prefix="/extract", tags=["extraction"])
logger = logging.getLogger("extraction.api")


@router.post("", response_model=ExtractionResult)
async def extract(
    file: UploadFile = File(...),
    options: ExtractionOptions = Depends(),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
):
    """
    Extract text content from a document.

    Supported formats:
    - Office: DOCX, PPTX, XLSX, DOC, PPT, XLS, XLSB
    - Text: TXT, MD, CSV
    - Email: MSG, EML

    Note: PDFs and images should be sent to fast_pdf or Docling engines.

    Headers:
    - X-Request-ID: Optional correlation ID for request tracing
    """
    start_time = time.time()
    request_id = x_request_id or "no-id"

    # Log request received
    logger.info(
        "[%s] EXTRACT_START: filename=%s, content_type=%s, size=%s",
        request_id,
        file.filename,
        file.content_type,
        file.size if hasattr(file, 'size') else 'unknown',
    )

    try:
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        path = save_upload_to_disk(file, settings.UPLOAD_DIR)

        logger.info(
            "[%s] EXTRACT_PROCESSING: saved to %s, starting extraction",
            request_id,
            path,
        )

        content_md, method, ocr_used, page_count = extract_markdown(
            path=path,
            filename=file.filename,
            media_type=file.content_type or "",
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        if not content_md:
            logger.warning(
                "[%s] EXTRACT_EMPTY: No content extracted from %s after %dms",
                request_id,
                file.filename,
                elapsed_ms,
            )
            raise HTTPException(
                status_code=422,
                detail=f"No text could be extracted from this file. Request ID: {request_id}"
            )

        # Extract document metadata
        doc_metadata = extract_document_metadata(
            path=path,
            filename=file.filename,
            content=content_md,
            extraction_method=method,
        )

        logger.info(
            "[%s] EXTRACT_SUCCESS: filename=%s, chars=%d, method=%s, pages=%s, elapsed=%dms",
            request_id,
            file.filename,
            len(content_md),
            method,
            page_count,
            elapsed_ms,
        )

        return ExtractionResult(
            filename=file.filename,
            content_markdown=content_md,
            content_chars=len(content_md),
            method=method,
            ocr_used=ocr_used,
            page_count=page_count,
            media_type=file.content_type,
            metadata={
                "upload_path": path,
                "request_id": request_id,
                "elapsed_ms": elapsed_ms,
                **doc_metadata,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "[%s] EXTRACT_ERROR: filename=%s, error=%s, elapsed=%dms",
            request_id,
            file.filename,
            str(e),
            elapsed_ms,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Extraction failed: {str(e)}. Request ID: {request_id}"
        )
