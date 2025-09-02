from typing import Tuple
from PIL import Image, ImageSequence
import io
import logging

logger = logging.getLogger(__name__)

def _require_pdfium():
    try:
        import pypdfium2 as pdfium  # type: ignore
    except ModuleNotFoundError as e:
        raise RuntimeError("pypdfium2 is required for PDF OCR but is not installed") from e
    return pdfium

def _require_tesseract():
    try:
        import pytesseract  # type: ignore
    except ModuleNotFoundError as e:
        raise RuntimeError("pytesseract is required for OCR but is not installed") from e
    return pytesseract

def ocr_image_bytes(data: bytes, lang: str, psm: str) -> str:
    pytesseract = _require_tesseract()
    img = Image.open(io.BytesIO(data))
    texts = []
    for frame in ImageSequence.Iterator(img):
        texts.append(pytesseract.image_to_string(frame, lang=lang, config=f"--psm {psm}"))
    out = "\n".join(texts).strip()
    logger.info("ocr_image_bytes: chars=%s", len(out))
    return out

def ocr_pdf_path(pdf_path: str, lang: str, psm: str, scale: float = 2.0) -> Tuple[str, int]:
    pdfium = _require_pdfium()
    pytesseract = _require_tesseract()

    pdf = pdfium.PdfDocument(pdf_path)
    texts = []
    for i in range(len(pdf)):
        page = pdf[i]
        bitmap = page.render(scale=scale).to_pil()
        page_text = pytesseract.image_to_string(bitmap, lang=lang, config=f"--psm {psm}")
        if page_text.strip():
            texts.append(f"## Page {i+1}\n\n{page_text.strip()}")
    out = "\n\n".join(texts).strip()
    logger.info("ocr_pdf_path: pages=%s chars=%s", len(pdf), len(out))
    return (out, len(pdf))
