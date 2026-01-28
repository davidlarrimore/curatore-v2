"""
Document Metadata Extractor

Extracts metadata from various document types (PDF, Office docs, images).
Returns standardized metadata including author, creator, dates, size, etc.
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def extract_document_metadata(
    path: str,
    filename: str,
    content: str,
    extraction_method: str,
) -> Dict[str, Any]:
    """
    Extract metadata from a document.

    Args:
        path: Absolute path to the file
        filename: Original filename
        content: Extracted markdown content
        extraction_method: Method used for extraction (pdfminer, ocr, markitdown, etc.)

    Returns:
        Dictionary with document metadata including:
        - file_info: size, extension, mime_type
        - content_info: character_count, word_count, line_count
        - extraction_info: method used, timestamps
        - document_properties: author, creator, title, dates (if available)
    """
    ext = (os.path.splitext(filename)[1] or "").lower()

    metadata = {
        "file_info": _extract_file_info(path, filename, ext),
        "content_info": _extract_content_info(content),
        "extraction_info": {
            "method": extraction_method,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
        "document_properties": {},
    }

    # Extract document-specific properties based on type
    if ext == ".pdf":
        metadata["document_properties"] = _extract_pdf_metadata(path)
    elif ext in {".docx", ".pptx", ".xlsx"}:
        metadata["document_properties"] = _extract_office_metadata(path, ext)
    elif ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
        metadata["document_properties"] = _extract_image_metadata(path)

    return metadata


def _extract_file_info(path: str, filename: str, ext: str) -> Dict[str, Any]:
    """Extract basic file information."""
    try:
        file_stats = os.stat(path)
        return {
            "filename": filename,
            "extension": ext,
            "size_bytes": file_stats.st_size,
            "size_human": _format_bytes(file_stats.st_size),
            "modified_time": datetime.fromtimestamp(file_stats.st_mtime).isoformat() + "Z",
        }
    except Exception as e:
        logger.warning(f"Failed to extract file info: {e}")
        return {
            "filename": filename,
            "extension": ext,
        }


def _extract_content_info(content: str) -> Dict[str, Any]:
    """Extract content statistics."""
    lines = content.split("\n")
    words = content.split()

    return {
        "character_count": len(content),
        "word_count": len(words),
        "line_count": len(lines),
        "non_whitespace_chars": len(content.replace(" ", "").replace("\n", "").replace("\t", "")),
    }


def _extract_pdf_metadata(path: str) -> Dict[str, Any]:
    """Extract PDF metadata using pypdf or pdfminer."""
    metadata = {}

    # Try pypdf first (if available)
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)

        if reader.metadata:
            metadata.update({
                "title": reader.metadata.get("/Title"),
                "author": reader.metadata.get("/Author"),
                "subject": reader.metadata.get("/Subject"),
                "creator": reader.metadata.get("/Creator"),
                "producer": reader.metadata.get("/Producer"),
                "creation_date": _parse_pdf_date(reader.metadata.get("/CreationDate")),
                "modification_date": _parse_pdf_date(reader.metadata.get("/ModDate")),
            })

        metadata["page_count"] = len(reader.pages)

        # Get first page dimensions
        if len(reader.pages) > 0:
            page = reader.pages[0]
            box = page.mediabox
            metadata["page_width"] = float(box.width)
            metadata["page_height"] = float(box.height)
            metadata["page_size"] = _detect_page_size(float(box.width), float(box.height))

    except ModuleNotFoundError:
        logger.debug("pypdf not installed, trying pdfminer for metadata")
    except Exception as e:
        logger.warning(f"pypdf metadata extraction failed: {e}")

    # Fallback to pdfminer
    if not metadata:
        try:
            from pdfminer.pdfparser import PDFParser
            from pdfminer.pdfdocument import PDFDocument

            with open(path, "rb") as f:
                parser = PDFParser(f)
                doc = PDFDocument(parser)

                if doc.info:
                    info = doc.info[0] if doc.info else {}
                    metadata.update({
                        "title": _decode_pdf_string(info.get(b"Title")),
                        "author": _decode_pdf_string(info.get(b"Author")),
                        "subject": _decode_pdf_string(info.get(b"Subject")),
                        "creator": _decode_pdf_string(info.get(b"Creator")),
                        "producer": _decode_pdf_string(info.get(b"Producer")),
                        "creation_date": _parse_pdf_date(_decode_pdf_string(info.get(b"CreationDate"))),
                        "modification_date": _parse_pdf_date(_decode_pdf_string(info.get(b"ModDate"))),
                    })

        except ModuleNotFoundError:
            logger.debug("pdfminer not installed, skipping PDF metadata")
        except Exception as e:
            logger.warning(f"pdfminer metadata extraction failed: {e}")

    # Clean up None values
    return {k: v for k, v in metadata.items() if v is not None}


def _extract_office_metadata(path: str, ext: str) -> Dict[str, Any]:
    """Extract Office document metadata (DOCX, PPTX, XLSX)."""
    metadata = {}

    try:
        from zipfile import ZipFile
        import xml.etree.ElementTree as ET

        with ZipFile(path, "r") as zip_file:
            # Try to read core properties
            try:
                core_xml = zip_file.read("docProps/core.xml")
                root = ET.fromstring(core_xml)

                # Define namespaces
                ns = {
                    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
                    "dc": "http://purl.org/dc/elements/1.1/",
                    "dcterms": "http://purl.org/dc/terms/",
                }

                metadata.update({
                    "title": _get_xml_text(root, ".//dc:title", ns),
                    "subject": _get_xml_text(root, ".//dc:subject", ns),
                    "creator": _get_xml_text(root, ".//dc:creator", ns),
                    "keywords": _get_xml_text(root, ".//cp:keywords", ns),
                    "description": _get_xml_text(root, ".//dc:description", ns),
                    "last_modified_by": _get_xml_text(root, ".//cp:lastModifiedBy", ns),
                    "revision": _get_xml_text(root, ".//cp:revision", ns),
                    "creation_date": _get_xml_text(root, ".//dcterms:created", ns),
                    "modification_date": _get_xml_text(root, ".//dcterms:modified", ns),
                })

            except KeyError:
                logger.debug("core.xml not found in Office document")
            except Exception as e:
                logger.warning(f"Failed to parse core.xml: {e}")

            # Extract app-specific properties
            try:
                app_xml = zip_file.read("docProps/app.xml")
                root = ET.fromstring(app_xml)
                ns_app = {
                    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
                }

                if ext == ".docx":
                    metadata.update({
                        "pages": _get_xml_int(root, ".//ep:Pages", ns_app),
                        "words": _get_xml_int(root, ".//ep:Words", ns_app),
                        "characters": _get_xml_int(root, ".//ep:Characters", ns_app),
                        "paragraphs": _get_xml_int(root, ".//ep:Paragraphs", ns_app),
                        "lines": _get_xml_int(root, ".//ep:Lines", ns_app),
                    })
                elif ext == ".pptx":
                    metadata.update({
                        "slides": _get_xml_int(root, ".//ep:Slides", ns_app),
                        "notes": _get_xml_int(root, ".//ep:Notes", ns_app),
                        "words": _get_xml_int(root, ".//ep:Words", ns_app),
                    })
                elif ext == ".xlsx":
                    metadata.update({
                        "worksheets": _get_xml_int(root, ".//ep:Worksheets", ns_app),
                    })

                metadata["application"] = _get_xml_text(root, ".//ep:Application", ns_app)
                metadata["app_version"] = _get_xml_text(root, ".//ep:AppVersion", ns_app)

            except KeyError:
                logger.debug("app.xml not found in Office document")
            except Exception as e:
                logger.warning(f"Failed to parse app.xml: {e}")

    except Exception as e:
        logger.warning(f"Office metadata extraction failed: {e}")

    # Clean up None values
    return {k: v for k, v in metadata.items() if v is not None}


def _extract_image_metadata(path: str) -> Dict[str, Any]:
    """Extract image metadata using PIL/Pillow."""
    metadata = {}

    try:
        from PIL import Image

        with Image.open(path) as img:
            metadata["format"] = img.format
            metadata["mode"] = img.mode
            metadata["width"] = img.width
            metadata["height"] = img.height
            metadata["size"] = f"{img.width}x{img.height}"

            # Extract EXIF data if available
            if hasattr(img, "_getexif") and img._getexif():
                exif = img._getexif()
                if exif:
                    # Common EXIF tags
                    exif_tags = {
                        271: "make",  # Camera manufacturer
                        272: "model",  # Camera model
                        274: "orientation",
                        306: "datetime",  # Date taken
                        36867: "datetime_original",
                        36868: "datetime_digitized",
                    }

                    for tag_id, tag_name in exif_tags.items():
                        if tag_id in exif:
                            metadata[tag_name] = str(exif[tag_id])

    except ModuleNotFoundError:
        logger.debug("PIL/Pillow not installed, skipping image metadata")
    except Exception as e:
        logger.warning(f"Image metadata extraction failed: {e}")

    return {k: v for k, v in metadata.items() if v is not None}


# Helper functions

def _format_bytes(bytes_size: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"


def _parse_pdf_date(date_str: Optional[str]) -> Optional[str]:
    """Parse PDF date string to ISO format."""
    if not date_str:
        return None

    try:
        # PDF date format: D:YYYYMMDDHHmmSSOHH'mm'
        if date_str.startswith("D:"):
            date_str = date_str[2:]

        # Extract just the date/time part (ignore timezone)
        date_part = date_str[:14]
        if len(date_part) >= 8:
            year = date_part[0:4]
            month = date_part[4:6]
            day = date_part[6:8]
            hour = date_part[8:10] if len(date_part) >= 10 else "00"
            minute = date_part[10:12] if len(date_part) >= 12 else "00"
            second = date_part[12:14] if len(date_part) >= 14 else "00"

            return f"{year}-{month}-{day}T{hour}:{minute}:{second}Z"

    except Exception as e:
        logger.debug(f"Failed to parse PDF date '{date_str}': {e}")

    return None


def _decode_pdf_string(value: Any) -> Optional[str]:
    """Decode PDF string value."""
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return value.decode("latin-1")
            except:
                return None
    return str(value)


def _detect_page_size(width: float, height: float) -> str:
    """Detect common page sizes (in points, 72 points = 1 inch)."""
    sizes = {
        "Letter": (612, 792),
        "Legal": (612, 1008),
        "A4": (595, 842),
        "A3": (842, 1191),
        "Tabloid": (792, 1224),
    }

    for name, (w, h) in sizes.items():
        if abs(width - w) < 5 and abs(height - h) < 5:
            return name
        if abs(width - h) < 5 and abs(height - w) < 5:
            return f"{name} (Landscape)"

    return "Custom"


def _get_xml_text(root, xpath: str, namespaces: Dict[str, str]) -> Optional[str]:
    """Get text from XML element."""
    try:
        elem = root.find(xpath, namespaces)
        if elem is not None and elem.text:
            return elem.text.strip()
    except Exception:
        pass
    return None


def _get_xml_int(root, xpath: str, namespaces: Dict[str, str]) -> Optional[int]:
    """Get integer from XML element."""
    text = _get_xml_text(root, xpath, namespaces)
    if text:
        try:
            return int(text)
        except ValueError:
            pass
    return None
