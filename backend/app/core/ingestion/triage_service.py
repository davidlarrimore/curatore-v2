"""
Triage Service for Intelligent Document Extraction Routing.

This service performs lightweight document analysis to select the optimal
extraction engine for each document. The triage phase runs before extraction
and determines whether to use:
- fast_pdf: PyMuPDF-based extraction for simple PDFs
- extraction-service: MarkItDown for Office files and text
- docling: Advanced extraction for complex documents (OCR, layout analysis)

Note: Standalone image files are NOT supported. Image OCR is only performed
within documents (e.g., scanned PDFs) via the Docling engine.

The goal is to maximize extraction speed while maintaining quality by routing
simple documents to fast extractors and complex documents to advanced engines.

Usage:
    from app.core.ingestion.triage_service import triage_service

    plan = await triage_service.triage(file_path, mime_type)
    print(f"Selected engine: {plan.engine}")
"""

import logging
import mimetypes
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal, Optional, Tuple

logger = logging.getLogger("curatore.services.triage")


class ExtractionEngine(str, Enum):
    """Available extraction engines."""
    FAST_PDF = "fast_pdf"
    EXTRACTION_SERVICE = "extraction-service"  # MarkItDown for Office files
    DOCLING = "docling"
    UNSUPPORTED = "unsupported"  # File type not supported


class DocumentComplexity(str, Enum):
    """Document complexity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ExtractionPlan:
    """
    Extraction plan determined by triage analysis.

    Attributes:
        file_type: Detected file type (extension)
        engine: Selected extraction engine
        needs_ocr: Whether document requires OCR
        needs_layout: Whether document has complex layout
        complexity: Overall document complexity
        triage_duration_ms: Time taken for triage in milliseconds
        reason: Human-readable explanation of engine selection
    """
    file_type: str
    engine: Literal["fast_pdf", "extraction-service", "docling", "unsupported"]
    needs_ocr: bool
    needs_layout: bool
    complexity: Literal["low", "medium", "high"]
    triage_duration_ms: int = 0
    reason: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/storage."""
        return {
            "file_type": self.file_type,
            "engine": self.engine,
            "needs_ocr": self.needs_ocr,
            "needs_layout": self.needs_layout,
            "complexity": self.complexity,
            "triage_duration_ms": self.triage_duration_ms,
            "reason": self.reason,
        }


# File extension groups
PDF_EXTENSIONS = {".pdf"}
OFFICE_DOCUMENT_EXTENSIONS = {".docx", ".doc"}
OFFICE_PRESENTATION_EXTENSIONS = {".pptx", ".ppt"}
OFFICE_SPREADSHEET_EXTENSIONS = {".xlsx", ".xls"}
OFFICE_EXTENSIONS = OFFICE_DOCUMENT_EXTENSIONS | OFFICE_PRESENTATION_EXTENSIONS | OFFICE_SPREADSHEET_EXTENSIONS
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp"}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".xml", ".html", ".htm"}

# Thresholds for PDF complexity analysis
PDF_BLOCK_THRESHOLD = 50  # More than this = complex layout
PDF_IMAGE_THRESHOLD = 3   # More than this = needs advanced handling
PDF_PAGES_TO_ANALYZE = 3  # Number of pages to sample for analysis


class TriageService:
    """
    Service for intelligent document triage and extraction routing.

    Performs lightweight analysis of documents to determine the optimal
    extraction engine. The triage process is designed to be fast (sub-second)
    while providing accurate routing decisions.
    """

    def __init__(self):
        """Initialize the triage service."""
        self._fitz_available = self._check_fitz_available()

    def _check_fitz_available(self) -> bool:
        """Check if PyMuPDF (fitz) is available for PDF analysis."""
        try:
            import fitz
            return True
        except ImportError:
            logger.warning(
                "PyMuPDF (fitz) not available. PDF triage will use fallback logic."
            )
            return False

    async def triage(
        self,
        file_path: Path,
        mime_type: Optional[str] = None,
        docling_enabled: bool = True,
    ) -> ExtractionPlan:
        """
        Analyze a document and determine the optimal extraction engine.

        This is the main entry point for triage. It performs lightweight
        analysis to route documents to the appropriate extraction engine.

        Args:
            file_path: Path to the document file
            mime_type: MIME type (optional, will be guessed from extension)
            docling_enabled: Whether Docling service is available

        Returns:
            ExtractionPlan with selected engine and analysis details

        Routing Logic:
            - Images -> unsupported (standalone images not supported)
            - PDFs:
                - Scanned/no text layer -> docling (with OCR)
                - Complex layout (>50 blocks, >3 images) -> docling
                - Simple text-based -> fast_pdf
            - Office files:
                - Large (>= 5MB) -> docling
                - Simple -> extraction-service (MarkItDown)
            - Text files -> extraction-service (MarkItDown)
        """
        start_time = time.time()

        # Get file extension
        ext = file_path.suffix.lower()
        if not ext and mime_type:
            # Try to guess extension from MIME type
            ext = mimetypes.guess_extension(mime_type) or ""

        # Determine file category and run appropriate analysis
        if ext in IMAGE_EXTENSIONS:
            plan = self._triage_image(ext)
        elif ext in PDF_EXTENSIONS:
            plan = await self._triage_pdf(file_path, ext, docling_enabled)
        elif ext in OFFICE_EXTENSIONS:
            plan = await self._triage_office(file_path, ext, docling_enabled)
        elif ext in TEXT_EXTENSIONS:
            plan = self._triage_text(ext)
        else:
            # Unknown file type - try extraction-service as fallback
            plan = ExtractionPlan(
                file_type=ext,
                engine="extraction-service",
                needs_ocr=False,
                needs_layout=False,
                complexity="low",
                reason=f"Unknown file type {ext}, using extraction-service as fallback",
            )

        # If Docling is not enabled, fall back to fast engines
        if not docling_enabled and plan.engine == "docling":
            original_engine = plan.engine
            if ext in PDF_EXTENSIONS:
                plan = ExtractionPlan(
                    file_type=ext,
                    engine="fast_pdf",
                    needs_ocr=plan.needs_ocr,
                    needs_layout=plan.needs_layout,
                    complexity=plan.complexity,
                    reason=f"Docling disabled, falling back from {original_engine} to fast_pdf",
                )
            else:
                plan = ExtractionPlan(
                    file_type=ext,
                    engine="extraction-service",
                    needs_ocr=plan.needs_ocr,
                    needs_layout=plan.needs_layout,
                    complexity=plan.complexity,
                    reason=f"Docling disabled, falling back from {original_engine} to extraction-service (MarkItDown)",
                )

        # Calculate triage duration
        duration_ms = int((time.time() - start_time) * 1000)
        plan.triage_duration_ms = duration_ms

        logger.info(
            "Triage complete: file=%s, engine=%s, complexity=%s, duration=%dms, reason=%s",
            file_path.name, plan.engine, plan.complexity, duration_ms, plan.reason
        )

        return plan

    def _triage_image(self, ext: str) -> ExtractionPlan:
        """Triage image files - not supported as standalone files."""
        return ExtractionPlan(
            file_type=ext,
            engine="unsupported",
            needs_ocr=False,
            needs_layout=False,
            complexity="low",
            reason="Standalone image files are not supported. Image OCR is only available within documents (e.g., scanned PDFs).",
        )

    async def _triage_pdf(
        self,
        file_path: Path,
        ext: str,
        docling_enabled: bool,
    ) -> ExtractionPlan:
        """
        Triage PDF files using PyMuPDF analysis.

        Checks:
        1. Whether PDF has extractable text (vs scanned/image-based)
        2. Layout complexity (number of blocks, images, tables)
        """
        if not self._fitz_available:
            # Fallback: assume medium complexity without analysis
            return ExtractionPlan(
                file_type=ext,
                engine="docling" if docling_enabled else "fast_pdf",
                needs_ocr=False,  # Unknown without analysis
                needs_layout=False,
                complexity="medium",
                reason="PyMuPDF not available, using fallback routing",
            )

        try:
            import fitz

            doc = fitz.open(str(file_path))
            total_pages = len(doc)

            # Analyze first few pages
            pages_to_check = min(PDF_PAGES_TO_ANALYZE, total_pages)
            total_text_length = 0
            total_blocks = 0
            total_images = 0
            has_tables = False

            for page_num in range(pages_to_check):
                page = doc[page_num]

                # Get text content
                text = page.get_text()
                total_text_length += len(text)

                # Get page structure
                blocks = page.get_text("dict")["blocks"]
                total_blocks += len(blocks)

                # Count images
                image_list = page.get_images(full=True)
                total_images += len(image_list)

                # Check for tables (simple heuristic: many lines/rectangles)
                drawings = page.get_drawings()
                line_count = sum(1 for d in drawings if d.get("items"))
                if line_count > 20:
                    has_tables = True

            doc.close()

            # Analyze results
            avg_text_per_page = total_text_length / pages_to_check if pages_to_check > 0 else 0
            avg_blocks_per_page = total_blocks / pages_to_check if pages_to_check > 0 else 0
            avg_images_per_page = total_images / pages_to_check if pages_to_check > 0 else 0

            # Determine if OCR is needed (very little text = likely scanned)
            needs_ocr = avg_text_per_page < 100  # Less than ~100 chars/page

            # Determine layout complexity
            is_complex_layout = (
                avg_blocks_per_page > PDF_BLOCK_THRESHOLD or
                avg_images_per_page > PDF_IMAGE_THRESHOLD or
                has_tables
            )

            # Determine overall complexity
            if needs_ocr:
                complexity = "high"
            elif is_complex_layout:
                complexity = "medium"
            else:
                complexity = "low"

            # Select engine
            if needs_ocr:
                engine = "docling"
                reason = f"PDF needs OCR (avg {avg_text_per_page:.0f} chars/page)"
            elif is_complex_layout:
                engine = "docling"
                reasons = []
                if avg_blocks_per_page > PDF_BLOCK_THRESHOLD:
                    reasons.append(f"{avg_blocks_per_page:.0f} blocks/page")
                if avg_images_per_page > PDF_IMAGE_THRESHOLD:
                    reasons.append(f"{avg_images_per_page:.0f} images/page")
                if has_tables:
                    reasons.append("tables detected")
                reason = f"Complex PDF layout: {', '.join(reasons)}"
            else:
                engine = "fast_pdf"
                reason = f"Simple text-based PDF ({avg_text_per_page:.0f} chars/page, {avg_blocks_per_page:.0f} blocks/page)"

            return ExtractionPlan(
                file_type=ext,
                engine=engine,
                needs_ocr=needs_ocr,
                needs_layout=is_complex_layout,
                complexity=complexity,
                reason=reason,
            )

        except Exception as e:
            logger.warning("PDF analysis failed for %s: %s", file_path.name, e)
            # Fallback: assume needs advanced processing
            return ExtractionPlan(
                file_type=ext,
                engine="docling" if docling_enabled else "fast_pdf",
                needs_ocr=False,
                needs_layout=True,
                complexity="medium",
                reason=f"PDF analysis failed ({e}), using cautious routing",
            )

    async def _triage_office(
        self,
        file_path: Path,
        ext: str,
        docling_enabled: bool,
    ) -> ExtractionPlan:
        """
        Triage Office files (DOCX, PPTX, XLSX).

        Uses file size as a proxy for complexity since we route all Office files
        to the extraction-service (which uses MarkItDown). Large files may benefit
        from Docling's advanced layout handling.

        Thresholds:
        - < 5MB: Simple, use extraction-service (MarkItDown)
        - >= 5MB: Complex, use Docling if available
        """
        # Get file size
        try:
            file_size = file_path.stat().st_size
            file_size_mb = file_size / (1024 * 1024)
        except Exception:
            file_size_mb = 0

        # Large files may have complex content (many images, charts, etc.)
        is_complex = file_size_mb >= 5.0

        if is_complex and docling_enabled:
            return ExtractionPlan(
                file_type=ext,
                engine="docling",
                needs_ocr=False,
                needs_layout=True,
                complexity="medium",
                reason=f"Large Office file ({file_size_mb:.1f}MB), using Docling for better layout",
            )
        else:
            return ExtractionPlan(
                file_type=ext,
                engine="extraction-service",
                needs_ocr=False,
                needs_layout=False,
                complexity="low",
                reason=f"Office file ({file_size_mb:.1f}MB), using MarkItDown via extraction-service",
            )

    def _triage_text(self, ext: str) -> ExtractionPlan:
        """Triage text files - always simple, use extraction-service (MarkItDown)."""
        return ExtractionPlan(
            file_type=ext,
            engine="extraction-service",
            needs_ocr=False,
            needs_layout=False,
            complexity="low",
            reason="Text-based file, using MarkItDown via extraction-service",
        )


# Singleton instance
triage_service = TriageService()
