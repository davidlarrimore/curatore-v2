"""
File Type Support Registry for Extraction Engines.

This module provides a centralized registry for tracking what file types
each extraction engine supports. It can be used for:
- Pre-flight validation before queuing extraction jobs
- Frontend display of supported formats
- Engine selection based on file type

Usage:
    from app.core.ingestion.extraction.file_type_registry import file_type_registry

    # Check if a file type is supported by any engine
    is_supported, engines = file_type_registry.is_supported('.xlsb')

    # Get all supported formats across all engines
    all_formats = file_type_registry.get_all_supported_formats()

    # Get formats for a specific engine
    docling_formats = file_type_registry.get_engine_formats('docling')
"""

from typing import Dict, List, Optional, Set, Tuple
import logging

logger = logging.getLogger(__name__)


class FileTypeRegistry:
    """
    Registry for tracking file type support across extraction engines.

    This registry provides a centralized view of what file types are supported
    by each extraction engine, making it easy to validate file types before
    attempting extraction.
    """

    # Static registry of supported formats per engine
    # These lists are kept in sync with the engine implementations
    _ENGINE_FORMATS: Dict[str, Set[str]] = {
        "extraction-service": {
            # Documents
            ".pdf", ".doc", ".docx", ".ppt", ".pptx",
            # Spreadsheets (including xlsb via LibreOffice conversion)
            ".xls", ".xlsx", ".xlsb", ".csv",
            # Plain text
            ".txt", ".md",
            # Images (OCR)
            ".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp",
            # Email formats
            ".msg", ".eml",
        },
        "docling": {
            ".pdf", ".doc", ".docx", ".ppt", ".pptx",
            ".xls", ".xlsx", ".html", ".htm",
            ".png", ".jpg", ".jpeg", ".tif", ".tiff"
        },
        "tika": {
            # Documents
            ".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md",
            # Spreadsheets
            ".xls", ".xlsx", ".xlsb", ".ods", ".csv",
            # Presentations
            ".ppt", ".pptx", ".odp",
            # Images (with OCR support)
            ".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp", ".webp",
            # Archives (extracts contents)
            ".zip", ".tar", ".gz", ".7z", ".rar",
            # Web content
            ".html", ".htm", ".xml", ".xhtml",
            # Email
            ".eml", ".msg", ".mbox",
            # eBooks
            ".epub", ".mobi",
            # Other
            ".json", ".yaml", ".yml"
        },
    }

    # Human-readable engine names
    _ENGINE_NAMES: Dict[str, str] = {
        "extraction-service": "Internal Extraction Service (MarkItDown + OCR)",
        "docling": "IBM Docling",
        "tika": "Apache Tika",
    }

    # Engine descriptions
    _ENGINE_DESCRIPTIONS: Dict[str, str] = {
        "extraction-service": "Built-in extraction using MarkItDown and Tesseract OCR. Supports Office documents, PDFs, images, and email files.",
        "docling": "Advanced document understanding with rich layout analysis. Best for complex PDFs, academic papers, and technical documents.",
        "tika": "Wide format support (1000+ types) with metadata extraction. Supports archives, ebooks, and many specialized formats.",
    }

    def __init__(self):
        """Initialize the file type registry."""
        self._custom_formats: Dict[str, Set[str]] = {}

    def is_supported(self, file_extension: str, engine: Optional[str] = None) -> Tuple[bool, List[str]]:
        """
        Check if a file extension is supported.

        Args:
            file_extension: File extension including the dot (e.g., '.pdf')
            engine: Optional specific engine to check. If None, checks all engines.

        Returns:
            Tuple of (is_supported, list_of_engines_that_support_it)
        """
        ext = file_extension.lower()
        if not ext.startswith('.'):
            ext = f'.{ext}'

        if engine:
            # Check specific engine
            formats = self._ENGINE_FORMATS.get(engine, set())
            if ext in formats:
                return (True, [engine])
            return (False, [])

        # Check all engines
        supporting_engines = []
        for eng_name, formats in self._ENGINE_FORMATS.items():
            if ext in formats:
                supporting_engines.append(eng_name)

        return (len(supporting_engines) > 0, supporting_engines)

    def get_engine_formats(self, engine: str) -> Set[str]:
        """
        Get supported formats for a specific engine.

        Args:
            engine: Engine type (e.g., 'extraction-service', 'docling', 'tika')

        Returns:
            Set of supported file extensions
        """
        return self._ENGINE_FORMATS.get(engine, set()).copy()

    def get_all_supported_formats(self) -> Set[str]:
        """
        Get all file formats supported by any engine.

        Returns:
            Set of all supported file extensions
        """
        all_formats: Set[str] = set()
        for formats in self._ENGINE_FORMATS.values():
            all_formats.update(formats)
        return all_formats

    def get_engine_info(self, engine: str) -> Dict[str, any]:
        """
        Get detailed information about an engine.

        Args:
            engine: Engine type

        Returns:
            Dict with engine name, description, and supported formats
        """
        return {
            "engine_type": engine,
            "display_name": self._ENGINE_NAMES.get(engine, engine),
            "description": self._ENGINE_DESCRIPTIONS.get(engine, ""),
            "supported_formats": sorted(self.get_engine_formats(engine)),
        }

    def get_all_engines(self) -> List[Dict[str, any]]:
        """
        Get information about all registered engines.

        Returns:
            List of engine info dictionaries
        """
        return [self.get_engine_info(engine) for engine in self._ENGINE_FORMATS.keys()]

    def get_format_matrix(self) -> Dict[str, Dict[str, bool]]:
        """
        Get a matrix showing which formats are supported by which engines.

        Returns:
            Dict mapping extensions to dicts of engine support
            e.g., {'.pdf': {'extraction-service': True, 'docling': True, 'tika': True}}
        """
        all_formats = self.get_all_supported_formats()
        matrix: Dict[str, Dict[str, bool]] = {}

        for ext in sorted(all_formats):
            matrix[ext] = {}
            for engine in self._ENGINE_FORMATS.keys():
                matrix[ext][engine] = ext in self._ENGINE_FORMATS[engine]

        return matrix

    def suggest_engine(self, file_extension: str) -> Optional[str]:
        """
        Suggest the best engine for a given file type.

        Uses a priority order based on general performance characteristics:
        1. extraction-service (fast, general purpose)
        2. docling (best for complex documents)
        3. tika (widest format support)

        Args:
            file_extension: File extension including the dot

        Returns:
            Suggested engine type or None if no engine supports the format
        """
        ext = file_extension.lower()
        if not ext.startswith('.'):
            ext = f'.{ext}'

        # Priority order for engine selection
        priority = ["extraction-service", "docling", "tika"]

        for engine in priority:
            if ext in self._ENGINE_FORMATS.get(engine, set()):
                return engine

        return None


# Singleton instance
file_type_registry = FileTypeRegistry()
