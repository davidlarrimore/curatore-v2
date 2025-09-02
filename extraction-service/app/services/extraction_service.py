import os
import logging
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

from markitdown import MarkItDown
# Guard import of internal exception across versions
try:
    from markitdown._exceptions import FileConversionException  # type: ignore
except Exception:  # pragma: no cover
    class FileConversionException(Exception):
        pass

from .ocr import ocr_image_bytes, ocr_pdf_path
from ..config import settings

logger = logging.getLogger(__name__)

__all__ = [
    "SUPPORTED_EXTS",
    "save_upload_to_disk",
    "extract_markdown",
    "extraction_service",  # alias for compatibility
]

# Supported file extensions we advertise via /system/supported-formats.
# NOTE: PDFs are handled by pdfminer/ocr (not MarkItDown) to match backend behavior.
SUPPORTED_EXTS = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".csv",
    ".txt", ".md",
    ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff",
}

# ---------------------------------------------------------------------------
# Tunables & quality assessment (defined AFTER settings import)
# ---------------------------------------------------------------------------
def _get_setting(name: str, default):
    return getattr(settings, name, default)

PDF_TEXT_MIN_ALPHA_RATIO: float = _get_setting("PDF_TEXT_MIN_ALPHA_RATIO", 0.20)   # 20% letters
PDF_TEXT_MAX_NON_ASCII_RATIO: float = _get_setting("PDF_TEXT_MAX_NON_ASCII_RATIO", 0.70)
PDF_CID_TOKENS_TRIGGER_OCR: bool = _get_setting("PDF_CID_TOKENS_TRIGGER_OCR", True)

def assess_pdf_text_quality(text: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Return (is_gibberish, metrics) for pdfminer output.
      - (cid:...) tokens -> bad mapping
      - Too few alphabetic characters
      - Too many non-ascii characters
    """
    n = max(len(text), 1)
    has_cid = "(cid:" in text
    alpha = sum(ch.isalpha() for ch in text) / n
    non_ascii = sum(ord(ch) > 126 for ch in text) / n

    gib = False
    reasons = []
    if PDF_CID_TOKENS_TRIGGER_OCR and has_cid:
        gib = True
        reasons.append("cid_tokens")
    if alpha < PDF_TEXT_MIN_ALPHA_RATIO:
        gib = True
        reasons.append(f"alpha<{PDF_TEXT_MIN_ALPHA_RATIO}")
    if non_ascii > PDF_TEXT_MAX_NON_ASCII_RATIO:
        gib = True
        reasons.append(f"non_ascii>{PDF_TEXT_MAX_NON_ASCII_RATIO}")

    return gib, {
        "len": n,
        "alpha_ratio": round(alpha, 4),
        "non_ascii_ratio": round(non_ascii, 4),
        "has_cid_tokens": has_cid,
        "reasons": reasons,
    }

# ---------------------------------------------------------------------------

def _safe_mkdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def save_upload_to_disk(file_obj, upload_dir: str) -> str:
    """Persist the uploaded file to disk and return the absolute path."""
    _safe_mkdir(upload_dir)
    dest_path = os.path.join(upload_dir, file_obj.filename)
    with open(dest_path, "wb") as f:
        f.write(file_obj.file.read())
    return dest_path


def markitdown_convert(path: str) -> str:
    """
    Convert non-PDF files (Office/text) to markdown/text using MarkItDown.
    Hardened to never raise upstream: returns "" on conversion failures or missing extras.
    """
    try:
        md = MarkItDown()
        out = md.convert(path)
    except FileConversionException as e:
        logger.info("MarkItDown conversion failed (handled): %s", e)
        return ""
    except Exception as e:
        logger.warning("MarkItDown unexpected error (handled): %s", e, exc_info=True)
        return ""

    # Normalize across MarkItDown versions
    if hasattr(out, "text_content"):
        return out.text_content or ""
    if isinstance(out, str):
        return out
    return getattr(out, "markdown", "") or getattr(out, "text", "") or ""


def libreoffice_convert(src_path: str, target: str) -> Optional[str]:
    """Convert office legacy formats using LibreOffice headless.

    target examples: 'docx', 'xlsx', 'pptx', 'pdf'
    Returns absolute path to converted file or None if conversion fails.
    """
    try:
        src = Path(src_path)
        if not src.exists():
            return None
        with tempfile.TemporaryDirectory(prefix="extract_conv_") as tmpdir:
            cmd = [
                "soffice", "--headless", "--convert-to", target,
                "--outdir", tmpdir, str(src)
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if proc.returncode != 0:
                logger.warning("LibreOffice convert failed rc=%s: %s", proc.returncode, proc.stderr.decode(errors="ignore"))
                return None
            # Find output file (same stem, new extension)
            out = Path(tmpdir) / (src.stem + "." + target)
            if out.exists():
                # Move to stable location alongside source
                final = src.with_suffix("." + target)
                try:
                    shutil.move(str(out), str(final))
                except Exception:
                    return str(out)
                return str(final)
            # Some conversions may add extra suffixes; fallback to first file in tmpdir
            for p in Path(tmpdir).glob("*"):
                if p.is_file():
                    return str(p)
    except Exception as e:
        logger.warning("LibreOffice convert exception: %s", e, exc_info=True)
    return None


def _tuple(
    content_md: str,
    method: str,
    ocr_used: bool,
    page_count: Optional[int],
) -> Tuple[str, str, bool, Optional[int]]:
    """Make returns explicit and consistent."""
    return (content_md or "", method, bool(ocr_used), page_count)


def extract_markdown(
    path: str,
    filename: str,
    media_type: str,
    force_ocr: bool,
    ocr_fallback: bool,
    ocr_lang: str,
    ocr_psm: str,
) -> Tuple[str, str, bool, Optional[int]]:
    """
    Extract textual content and report the method used.

    Always returns: (content_md, method, ocr_used, page_count)
    method ∈ {"pdfminer", "ocr", "pdfminer+ocr", "markitdown", "markitdown+ocr", "error"}
    """
    try:
        ext = (os.path.splitext(filename)[1] or "").lower()
        page_count: Optional[int] = None

        # -------- Forced OCR path --------
        if force_ocr:
            if ext == ".pdf":
                md_text, page_count = ocr_pdf_path(path, ocr_lang, ocr_psm)
                logger.info("extract_markdown: forced OCR for PDF; pages=%s chars=%s",
                            page_count, len(md_text))
                return _tuple(md_text, "ocr", True, page_count)

            if ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
                with open(path, "rb") as f:
                    ocr_text = ocr_image_bytes(f.read(), ocr_lang, ocr_psm)
                logger.info("extract_markdown: forced OCR for image; chars=%s", len(ocr_text))
                return _tuple(ocr_text, "ocr", True, None)
            # For Office/text files, forced OCR is not meaningful; continue below.

        # -------- PDF chain (backend parity: pdfminer -> OCR) --------
        if ext == ".pdf":
            # Lazy import pdfminer so a missing dep never breaks app startup
            try:
                from pdfminer.high_level import extract_text as pdf_extract_text  # type: ignore
            except ModuleNotFoundError:
                logger.warning("pdfminer.six not installed; skipping text-layer extract and using OCR")
                text_layer = ""
                quality = {"reasons": ["no_pdfminer"], "len": 0, "alpha_ratio": 0.0, "non_ascii_ratio": 0.0, "has_cid_tokens": False}
            else:
                try:
                    text_layer = pdf_extract_text(str(path)) or ""
                except Exception as e:
                    logger.warning("pdfminer failed; will try OCR. err=%s", e, exc_info=True)
                    text_layer = ""
                    quality = {"reasons": ["pdfminer_exc"], "len": 0, "alpha_ratio": 0.0, "non_ascii_ratio": 0.0, "has_cid_tokens": False}
                else:
                    is_gib, quality = assess_pdf_text_quality(text_layer)
                    logger.info(
                        "pdfminer quality: len=%s alpha=%.3f non_ascii=%.3f cid=%s reasons=%s",
                        quality["len"], quality["alpha_ratio"], quality["non_ascii_ratio"],
                        quality["has_cid_tokens"], ",".join(quality["reasons"]) or "none",
                    )
                    # If caller didn't request fallback and text looks OK, accept pdfminer
                    if text_layer.strip() and not (is_gib or ocr_fallback):
                        logger.info("extract_markdown: pdfminer accepted; chars=%s", len(text_layer))
                        return _tuple(text_layer, "pdfminer", False, None)

            # Scanned/image-only or gibberish PDF -> OCR
            ocr_md, page_count = ocr_pdf_path(path, ocr_lang, ocr_psm)
            method = "pdfminer+ocr" if (locals().get("text_layer", "").strip()) else "ocr"
            logger.info(
                "extract_markdown: %s for PDF; pages=%s chars=%s (reasons=%s)",
                method, page_count, len(ocr_md), ",".join(quality.get("reasons", [])) if "quality" in locals() else "n/a",
            )
            return _tuple(ocr_md, method, True, page_count)

        # -------- CSV/plain text --------
        if ext in {".txt", ".md", ".csv"}:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                return _tuple(content, "text", False, page_count)
            except Exception as e:
                logger.warning("text read failed: %s", e)
                return _tuple("", "error", False, None)

        # -------- Office/Text via MarkItDown (with PDF fallback if weak) --------
        if ext in {".docx", ".pptx", ".xlsx"}:
            md_text = markitdown_convert(path)
            if md_text and len(md_text.strip()) >= settings.MIN_TEXT_CHARS_FOR_NO_OCR:
                logger.info("extract_markdown: markitdown success for %s; chars=%s", ext, len(md_text))
                return _tuple(md_text, "markitdown", False, page_count)
            # Fallback: convert to PDF then run PDF extraction chain (text-layer or OCR)
            pdf_path = libreoffice_convert(path, "pdf")
            if pdf_path and os.path.exists(pdf_path):
                # Try pdfminer first; if gibberish, OCR internally decides
                from pdfminer.high_level import extract_text as pdf_extract_text  # type: ignore
                try:
                    text_layer = pdf_extract_text(str(pdf_path)) or ""
                except Exception:
                    text_layer = ""
                if text_layer.strip():
                    logger.info("fallback: docx/xlsx/pptx->pdf->pdfminer; chars=%s", len(text_layer))
                    return _tuple(text_layer, "pdfminer", False, None)
                ocr_md, page_count = ocr_pdf_path(pdf_path, settings.OCR_LANG, settings.OCR_PSM)
                logger.info("fallback: docx/xlsx/pptx->pdf->ocr; chars=%s", len(ocr_md))
                return _tuple(ocr_md, "ocr", True, page_count)
            # Return whatever markitdown yielded (may be empty) as last resort
            return _tuple(md_text, "markitdown", False, page_count)

        # -------- Legacy Office via LibreOffice -> modern -> MarkItDown --------
        if ext in {".doc", ".xls", ".ppt"}:
            target = {".doc": "docx", ".xls": "xlsx", ".ppt": "pptx"}[ext]
            conv_path = libreoffice_convert(path, target)
            if conv_path:
                md_text = markitdown_convert(conv_path)
                if md_text:
                    logger.info("extract_markdown: libreoffice+markitdown success for %s -> %s; chars=%s", ext, target, len(md_text))
                    return _tuple(md_text, f"libreoffice+markitdown", False, page_count)
            # Fallback: convert to PDF then OCR
            pdf_path = libreoffice_convert(path, "pdf")
            if pdf_path and os.path.exists(pdf_path):
                ocr_md, page_count = ocr_pdf_path(pdf_path, settings.OCR_LANG, settings.OCR_PSM)
                return _tuple(ocr_md, "libreoffice+ocr", True, page_count)

        # -------- Images (OCR) --------
        if ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
            with open(path, "rb") as f:
                img_ocr = ocr_image_bytes(f.read(), ocr_lang, ocr_psm)
            logger.info("extract_markdown: OCR for image; chars=%s", len(img_ocr))
            return _tuple(img_ocr, "ocr", True, page_count)

        # -------- Unknown extension --------
        md_text = markitdown_convert(path)
        if not md_text and ocr_fallback and (media_type or "").startswith("image/"):
            with open(path, "rb") as f:
                img_ocr = ocr_image_bytes(f.read(), ocr_lang, ocr_psm)
            logger.info("extract_markdown: unknown ext OCR fallback; chars=%s", len(img_ocr))
            return _tuple(img_ocr, "ocr", True, page_count)

        logger.info("extract_markdown: unknown ext markitdown; chars=%s", len(md_text))
        return _tuple(md_text, "markitdown", False, page_count)

    except Exception as e:
        # Last-resort guard: never bubble None/uncaught exceptions to caller unpack
        logger.error("extract_markdown: unexpected error (handled): %s", e, exc_info=True)
        return _tuple("", "error", False, None)


# Compatibility alias: some callers may expect a function literally named "extraction_service".
def extraction_service(
    path: str,
    filename: str,
    media_type: str,
    force_ocr: bool,
    ocr_fallback: bool,
    ocr_lang: str,
    ocr_psm: str,
) -> Tuple[str, str, bool, Optional[int]]:
    return extract_markdown(
        path=path,
        filename=filename,
        media_type=media_type,
        force_ocr=force_ocr,
        ocr_fallback=ocr_fallback,
        ocr_lang=ocr_lang,
        ocr_psm=ocr_psm,
    )
