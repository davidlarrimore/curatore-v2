"""
Models for the Extraction Service API.

Note: OCR is handled by the Docling service, not this extraction service.
This service handles Office documents, text files, and emails via MarkItDown.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict


class ExtractionOptions(BaseModel):
    """Options for document extraction (kept for API compatibility)."""
    # OCR options are deprecated - OCR is handled by Docling service
    ocr_fallback: bool = Field(default=False, description="Deprecated: OCR handled by Docling")
    force_ocr: bool = Field(default=False, description="Deprecated: OCR handled by Docling")
    ocr_lang: Optional[str] = None
    ocr_psm: Optional[str] = None


class ExtractionResult(BaseModel):
    """Result of document extraction."""
    filename: str
    content_markdown: str
    content_chars: int
    method: str  # "markitdown", "libreoffice+markitdown", "text", "email", "error"
    ocr_used: bool  # Always False for this service (OCR handled by Docling)
    page_count: Optional[int] = None
    media_type: Optional[str] = None
    metadata: Dict = Field(default_factory=dict)


class SupportedFormats(BaseModel):
    """List of supported file extensions."""
    extensions: List[str]
