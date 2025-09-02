from pydantic import BaseModel, Field
from typing import Optional, List, Dict

class ExtractionOptions(BaseModel):
    ocr_fallback: bool = Field(default=True, description="Use OCR if conversion yields little text")
    force_ocr: bool = Field(default=False, description="Always run OCR for PDFs/images")
    ocr_lang: Optional[str] = None
    ocr_psm: Optional[str] = None

class ExtractionResult(BaseModel):
    filename: str
    content_markdown: str
    content_chars: int
    method: str                       # "markitdown" | "ocr" | "markitdown+ocr"
    ocr_used: bool
    page_count: Optional[int] = None
    media_type: Optional[str] = None
    metadata: Dict = Field(default_factory=dict)

class SupportedFormats(BaseModel):
    extensions: List[str]
