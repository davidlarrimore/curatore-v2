"""
Extraction service for document conversion to Markdown.

This service handles:
- Office documents (DOCX, PPTX, XLSX) via MarkItDown
- Legacy Office formats (DOC, PPT, XLS, XLSB) via LibreOffice + MarkItDown
- Text files (TXT, MD, CSV) via direct read
- Email files (MSG, EML) via extract-msg / Python email

Note: PDFs and images are handled by other engines:
- Simple PDFs: fast_pdf engine (PyMuPDF) in backend
- Complex PDFs: Docling service
- Images: Docling service with OCR
"""

import os
import logging
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Tuple, Optional

from ..config import settings

# Configure logging with more detail
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("curatore.extraction")

__all__ = [
    "SUPPORTED_EXTS",
    "save_upload_to_disk",
    "extract_markdown",
    "extraction_service",
]

# Supported file extensions
# Note: PDFs and images are handled by fast_pdf/Docling, not this service
SUPPORTED_EXTS = {
    # Office documents
    ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".xlsb",
    # Text and markup files
    ".txt", ".md", ".csv", ".html", ".htm", ".xml", ".json",
    # Email formats
    ".msg", ".eml",
}


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
    Convert Office files to markdown using MarkItDown.
    Returns empty string on failure.
    """
    try:
        from markitdown import MarkItDown
    except ModuleNotFoundError:
        logger.warning("MarkItDown not installed")
        return ""

    try:
        md = MarkItDown()
        out = md.convert(path)
    except Exception as e:
        logger.warning("MarkItDown conversion failed: %s", e)
        return ""

    # Normalize across MarkItDown versions
    if hasattr(out, "text_content"):
        return out.text_content or ""
    if isinstance(out, str):
        return out
    return getattr(out, "markdown", "") or getattr(out, "text", "") or ""


def libreoffice_convert(src_path: str, target: str) -> Optional[str]:
    """
    Convert legacy Office formats using LibreOffice headless.

    Args:
        src_path: Path to source file
        target: Target format (e.g., 'docx', 'xlsx', 'pptx')

    Returns:
        Path to converted file or None if conversion fails
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
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
            )
            if proc.returncode != 0:
                logger.warning(
                    "LibreOffice convert failed rc=%s: %s",
                    proc.returncode, proc.stderr.decode(errors="ignore")
                )
                return None

            # Find output file
            out = Path(tmpdir) / (src.stem + "." + target)
            if out.exists():
                final = src.with_suffix("." + target)
                try:
                    shutil.move(str(out), str(final))
                except Exception:
                    return str(out)
                return str(final)

            # Fallback: first file in tmpdir
            for p in Path(tmpdir).glob("*"):
                if p.is_file():
                    return str(p)

    except Exception as e:
        logger.warning("LibreOffice convert exception: %s", e, exc_info=True)
    return None


def extract_msg_email(path: str) -> str:
    """Extract content from Outlook .msg files."""
    try:
        import extract_msg

        msg = extract_msg.Message(path)
        parts = ["# Email Message\n", "## Headers\n"]

        if msg.subject:
            parts.append(f"**Subject:** {msg.subject}\n")
        if msg.sender:
            parts.append(f"**From:** {msg.sender}\n")
        if msg.to:
            parts.append(f"**To:** {msg.to}\n")
        if msg.cc:
            parts.append(f"**CC:** {msg.cc}\n")
        if msg.date:
            parts.append(f"**Date:** {msg.date}\n")

        parts.append("\n---\n\n## Body\n\n")

        if msg.body:
            parts.append(msg.body)
        elif msg.htmlBody:
            import re
            html_body = msg.htmlBody
            if isinstance(html_body, bytes):
                html_body = html_body.decode("utf-8", errors="ignore")
            text = re.sub(r'<[^>]+>', ' ', html_body)
            text = re.sub(r'\s+', ' ', text).strip()
            parts.append(text)

        if msg.attachments:
            parts.append("\n\n---\n\n## Attachments\n\n")
            for att in msg.attachments:
                att_name = getattr(att, 'longFilename', None) or getattr(att, 'shortFilename', 'Unknown')
                parts.append(f"- {att_name}\n")

        msg.close()
        return "\n".join(parts)

    except Exception as e:
        logger.warning("extract_msg failed: %s", e)
        return ""


def extract_eml_email(path: str) -> str:
    """Extract content from .eml files."""
    try:
        import email
        from email import policy

        with open(path, 'rb') as f:
            msg = email.message_from_binary_file(f, policy=policy.default)

        parts = ["# Email Message\n", "## Headers\n"]

        if msg.get('Subject'):
            parts.append(f"**Subject:** {msg.get('Subject')}\n")
        if msg.get('From'):
            parts.append(f"**From:** {msg.get('From')}\n")
        if msg.get('To'):
            parts.append(f"**To:** {msg.get('To')}\n")
        if msg.get('Cc'):
            parts.append(f"**CC:** {msg.get('Cc')}\n")
        if msg.get('Date'):
            parts.append(f"**Date:** {msg.get('Date')}\n")

        parts.append("\n---\n\n## Body\n\n")

        body = msg.get_body(preferencelist=('plain', 'html'))
        if body:
            content = body.get_content()
            if body.get_content_type() == 'text/html':
                import re
                content = re.sub(r'<[^>]+>', ' ', content)
                content = re.sub(r'\s+', ' ', content).strip()
            parts.append(content)

        attachments = [part.get_filename() or 'Unknown' for part in msg.iter_attachments()]
        if attachments:
            parts.append("\n\n---\n\n## Attachments\n\n")
            for att_name in attachments:
                parts.append(f"- {att_name}\n")

        return "\n".join(parts)

    except Exception as e:
        logger.warning("extract_eml failed: %s", e)
        return ""


def extract_markdown(
    path: str,
    filename: str,
    media_type: str,
    force_ocr: bool = False,
    ocr_fallback: bool = False,
    ocr_lang: str = "eng",
    ocr_psm: str = "3",
) -> Tuple[str, str, bool, Optional[int]]:
    """
    Extract textual content from a document.

    Logs extraction attempts and results for debugging.

    Returns: (content, method, ocr_used, page_count)
    - method: "markitdown", "libreoffice+markitdown", "text", "email", "error"
    - ocr_used: Always False (OCR is handled by Docling service)
    - page_count: Always None (page counting not supported)
    """
    ext = (os.path.splitext(filename)[1] or "").lower()
    file_size = os.path.getsize(path) if os.path.exists(path) else 0

    logger.info(
        "EXTRACT START: file=%s, ext=%s, size=%d bytes, media_type=%s",
        filename, ext, file_size, media_type
    )

    try:
        # Text files - direct read
        if ext in {".txt", ".md", ".csv"}:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                logger.info(
                    "EXTRACT SUCCESS: file=%s, method=text, chars=%d",
                    filename, len(content)
                )
                return (content, "text", False, None)
            except Exception as e:
                logger.warning("EXTRACT FAILED: file=%s, method=text, error=%s", filename, e)
                return ("", "error", False, None)

        # HTML and markup files - MarkItDown handles conversion to markdown
        if ext in {".html", ".htm", ".xml", ".json"}:
            logger.info("EXTRACT: Processing markup file with MarkItDown: %s", filename)
            content = markitdown_convert(path)
            if content:
                logger.info(
                    "EXTRACT SUCCESS: file=%s, method=markitdown, chars=%d",
                    filename, len(content)
                )
                return (content, "markitdown", False, None)
            # Fallback to direct read for markup files
            logger.info("EXTRACT: MarkItDown failed, falling back to direct read: %s", filename)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                logger.info(
                    "EXTRACT SUCCESS: file=%s, method=text (fallback), chars=%d",
                    filename, len(content)
                )
                return (content, "text", False, None)
            except Exception as e:
                logger.warning("EXTRACT FAILED: file=%s, method=text (fallback), error=%s", filename, e)
                return ("", "error", False, None)

        # Email files
        if ext == ".msg":
            logger.info("EXTRACT: Processing MSG email: %s", filename)
            content = extract_msg_email(path)
            if content:
                logger.info(
                    "EXTRACT SUCCESS: file=%s, method=email, chars=%d",
                    filename, len(content)
                )
                return (content, "email", False, None)
            logger.warning("EXTRACT FAILED: file=%s, method=email (msg)", filename)
            return ("", "error", False, None)

        if ext == ".eml":
            logger.info("EXTRACT: Processing EML email: %s", filename)
            content = extract_eml_email(path)
            if content:
                logger.info(
                    "EXTRACT SUCCESS: file=%s, method=email, chars=%d",
                    filename, len(content)
                )
                return (content, "email", False, None)
            logger.warning("EXTRACT FAILED: file=%s, method=email (eml)", filename)
            return ("", "error", False, None)

        # Modern Office formats - MarkItDown
        if ext in {".docx", ".pptx", ".xlsx"}:
            logger.info("EXTRACT: Processing Office file with MarkItDown: %s", filename)
            content = markitdown_convert(path)
            if content:
                logger.info(
                    "EXTRACT SUCCESS: file=%s, method=markitdown, chars=%d",
                    filename, len(content)
                )
                return (content, "markitdown", False, None)
            logger.warning("EXTRACT FAILED: file=%s, method=markitdown", filename)
            return ("", "error", False, None)

        # Legacy Office formats - LibreOffice + MarkItDown
        if ext in {".doc", ".xls", ".ppt", ".xlsb"}:
            target = {".doc": "docx", ".xls": "xlsx", ".ppt": "pptx", ".xlsb": "xlsx"}[ext]
            logger.info(
                "EXTRACT: Converting legacy Office file: %s -> %s",
                filename, target
            )
            conv_path = libreoffice_convert(path, target)
            if conv_path:
                content = markitdown_convert(conv_path)
                if content:
                    logger.info(
                        "EXTRACT SUCCESS: file=%s, method=libreoffice+markitdown, chars=%d",
                        filename, len(content)
                    )
                    return (content, "libreoffice+markitdown", False, None)
            logger.warning(
                "EXTRACT FAILED: file=%s, method=libreoffice+markitdown",
                filename
            )
            return ("", "error", False, None)

        # Unknown - try MarkItDown
        logger.info("EXTRACT: Trying MarkItDown for unknown type: %s", filename)
        content = markitdown_convert(path)
        if content:
            logger.info(
                "EXTRACT SUCCESS: file=%s, method=markitdown (fallback), chars=%d",
                filename, len(content)
            )
        else:
            logger.warning(
                "EXTRACT FAILED: file=%s, method=markitdown (fallback)",
                filename
            )
        return (content or "", "markitdown", False, None)

    except Exception as e:
        logger.error(
            "EXTRACT ERROR: file=%s, error=%s",
            filename, e, exc_info=True
        )
        return ("", "error", False, None)


# Compatibility alias
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
