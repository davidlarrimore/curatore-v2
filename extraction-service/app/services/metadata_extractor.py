"""
Document Metadata Extractor

Extracts metadata from Office documents, text files, and emails.
Note: PDF and image metadata is extracted by fast_pdf/Docling engines.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

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
        extraction_method: Method used for extraction

    Returns:
        Dictionary with document metadata including:
        - file_info: size, extension
        - content_info: character_count, word_count, line_count
        - extraction_info: method used, timestamps
        - document_properties: author, creator, title, dates (for Office docs)
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

    # Extract Office document properties
    if ext in {".docx", ".pptx", ".xlsx"}:
        metadata["document_properties"] = _extract_office_metadata(path, ext)

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


def _extract_office_metadata(path: str, ext: str) -> Dict[str, Any]:
    """Extract Office document metadata (DOCX, PPTX, XLSX)."""
    metadata = {}

    try:
        import xml.etree.ElementTree as ET
        from zipfile import ZipFile

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


# Helper functions

def _format_bytes(bytes_size: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"


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
