"""
Extraction engine abstraction layer.

This package provides a clean abstraction for document extraction engines,
making it easy to integrate multiple extraction services and add new ones.

Usage:
    from app.services.extraction import ExtractionEngineFactory

    # Create engine from configuration
    config = {
        "engine_type": "docling",
        "name": "docling-prod",
        "service_url": "http://docling:5001",
        "timeout": 300
    }
    engine = ExtractionEngineFactory.from_config(config)

    # Extract document
    result = await engine.extract(file_path)
    if result.success:
        print(result.content)
    else:
        print(f"Error: {result.error}")

Available Engines:
    - extraction-service: MarkItDown for Office files and text files
    - docling: IBM Docling for complex PDFs and OCR
    - fast_pdf: PyMuPDF for simple text-based PDFs
    - tika: Apache Tika (stub - not yet implemented)
"""

from .base import BaseExtractionEngine, ExtractionResult
from .extraction_service import ExtractionServiceEngine
from .docling import DoclingEngine
from .tika import TikaEngine
from .fast_pdf import FastPdfEngine
from .factory import ExtractionEngineFactory
from .file_type_registry import FileTypeRegistry, file_type_registry

__all__ = [
    # Base classes
    "BaseExtractionEngine",
    "ExtractionResult",
    # Service-based engines
    "ExtractionServiceEngine",  # MarkItDown for Office files and general extraction
    "DoclingEngine",  # IBM Docling for complex documents
    "TikaEngine",
    # Local engines (triage-based)
    "FastPdfEngine",  # PyMuPDF for simple PDFs
    # Factory
    "ExtractionEngineFactory",
    # File type registry
    "FileTypeRegistry",
    "file_type_registry",
]

__version__ = "1.0.0"
