# backend/app/pipeline.py
import os, io, re, json, time
from .config import Settings
from .services.extraction_client import ExtractionClient

# delete any globals related to MarkItDown, OCR, etc.

# REPLACE the existing convert_to_markdown(...) definition with:
def convert_to_markdown(file_path: Path, ocr_lang="eng", ocr_psm=3) -> Tuple[Optional[str], bool, str]:
    """
    Delegates document extraction to the external Content Extraction Service.
    Returns (markdown_text, success_boolean, note_string)
    """
    settings = Settings()  # env-backed
    client = ExtractionClient(settings)
    try:
        res = client.extract_file(str(file_path), ocr_lang=ocr_lang, ocr_psm=ocr_psm)
        md = (res.markdown or "").strip()
        if not md:
            return None, False, res.note or "Extractor returned empty content."
        return md, True, res.note or ("OCR used." if res.used_ocr else "Extracted by service.")
    except Exception as e:
        return None, False, f"Extraction service error: {e}"