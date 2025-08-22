"""
Bridges the existing Streamlit pipeline into importable functions
usable by FastAPI services.

We reproduced the key behaviors seen in your current pipeline:
- multi-format convert -> OCR fallback (Tesseract)
- vector-DB-friendly optimization
- conversion quality scoring (coverage/structure/legibility)
- LLM evaluation (clarity/completeness/relevance/markdown) with JSON
"""
from __future__ import annotations
import io, re, json
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, List

from PIL import Image
import pytesseract
from pytesseract import Output
from pdfminer.high_level import extract_text as pdf_extract_text
import fitz  # pymupdf
from markitdown import MarkItDown
from docx import Document as DocxDocument

SUPPORTED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".md", ".txt", ".docx"}

def _images_from_pdf(path: Path, dpi: int = 200) -> List[Image.Image]:
    imgs: List[Image.Image] = []
    with fitz.open(path) as doc:
        mat = fitz.Matrix(dpi/72, dpi/72)
        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            imgs.append(img)
    return imgs

def _ocr_image(img: Image.Image, lang: str = "eng", psm: int = 3) -> Tuple[str, float]:
    config = f"--psm {psm}"
    text = pytesseract.image_to_string(img, lang=lang, config=config)
    data = pytesseract.image_to_data(img, lang=lang, config=config, output_type=Output.DICT)
    confs = []
    for c in data.get("conf", []):
        try:
            val = float(c)
            if val >= 0:
                confs.append(val)
        except Exception:
            pass
    avg_conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
    return text.strip(), avg_conf

def convert_to_markdown(path: Path, ocr_lang: str = "eng", ocr_psm: int = 3) -> Tuple[Optional[str], bool, str]:
    ext = path.suffix.lower()
    used_ocr = False
    try:
        # Prefer MarkItDown for structural preservation where possible
        if ext in {".md", ".txt"}:
            return path.read_text(encoding="utf-8"), False, "Loaded as text/markdown."
        if ext == ".docx":
            try:
                md = MarkItDown(enable_plugins=False).convert(path).text_content
                return md, False, "Converted with MarkItDown."
            except Exception:
                doc = DocxDocument(path)
                parts = []
                for p in doc.paragraphs:
                    parts.append(p.text)
                return "\n\n".join(parts), False, "Converted with python-docx."
        if ext == ".pdf":
            # Try direct text extraction
            text = pdf_extract_text(str(path)) or ""
            if text.strip():
                return text, False, "Extracted from PDF (text layer)."
            # Fallback OCR
            ocr_texts = []
            for img in _images_from_pdf(path):
                t, _ = _ocr_image(img, ocr_lang, ocr_psm)
                ocr_texts.append(t)
            used_ocr = True
            return "\n\n".join(ocr_texts), True, "OCR from PDF."
        if ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
            img = Image.open(path).convert("RGB")
            text, _ = _ocr_image(img, ocr_lang, ocr_psm)
            used_ocr = True
            return text, True, "OCR from image."
        # Final attempt via MarkItDown (for odd formats)
        md = MarkItDown(enable_plugins=False).convert(path).text_content
        return md, False, "Converted with MarkItDown (fallback)."
    except Exception as e:
        return None, used_ocr, f"Conversion failed: {e}"

def score_conversion(markdown_text: str, original_text: Optional[str]=None) -> Tuple[int, str]:
    if not markdown_text or not markdown_text.strip():
        return 0, "No markdown produced."
    # Content coverage
    content_score = 100
    if original_text:
        ow = original_text.split()
        mw = markdown_text.split()
        if len(ow) == 0:
            content_score = 0
        else:
            ratio = min(len(mw) / len(ow), 1.0)
            content_score = int(ratio * 100)
    # Structure markers
    headings = len(re.findall(r'^#{1,6}\s', markdown_text, flags=re.MULTILINE))
    lists = len(re.findall(r'^[\-\*]\s', markdown_text, flags=re.MULTILINE))
    tables = markdown_text.count('|')
    structure_score = 0
    if headings > 0: structure_score += 30
    if lists > 0:    structure_score += 30
    if tables > 3:   structure_score += 20
    # Legibility
    if "�" in markdown_text:
        legibility_score = 0
    else:
        lines = markdown_text.splitlines() or [markdown_text]
        avg_len = sum(len(l) for l in lines) / len(lines)
        legibility_score = 20 if avg_len < 200 else 10
    total = max(0, min(100, content_score + structure_score + legibility_score))
    feedback = "High-quality conversion." if total >= 80 else "Conversion acceptable." if total >= 60 else "Conversion needs improvement."
    return total, feedback

def vector_optimize(markdown_text: str) -> str:
    # Pure prompt-guided rewrite is done by LLM client in service layer; keep adapter pure if needed.
    return markdown_text

def llm_eval_prompt(md: str) -> str:
    return f"""
You are evaluating document quality for RAG. Return strict JSON with:
- clarity_score (1-10), clarity_feedback
- completeness_score (1-10), completeness_feedback
- relevance_score (1-10), relevance_feedback
- markdown_score (1-10), markdown_feedback
- overall_feedback
- pass_recommendation (true/false)

Document:
```markdown {md} Only JSON.```
Return only JSON.
"""