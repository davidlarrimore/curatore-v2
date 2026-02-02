"""
Fast PDF extraction engine using PyMuPDF.

This engine provides fast text extraction from simple PDFs that have
an embedded text layer. It uses PyMuPDF (fitz) directly without requiring
any external service calls.

For complex PDFs (scanned, complex layouts, tables), use the Docling engine instead.

Usage:
    engine = FastPdfEngine(name="fast-pdf-local")
    result = await engine.extract(Path("simple-document.pdf"))
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

from .base import BaseExtractionEngine, ExtractionResult


logger = logging.getLogger("curatore.extraction.fast_pdf")


class FastPdfEngine(BaseExtractionEngine):
    """
    Fast PDF extraction engine using PyMuPDF.

    This engine extracts text directly from PDFs using PyMuPDF's text extraction.
    It's designed for simple text-based PDFs where quality and speed are optimal
    with direct extraction.

    Features:
        - Direct text extraction (no external service required)
        - Fast processing (sub-second for most documents)
        - Preserves basic formatting as markdown
        - Handles multi-page documents

    Limitations:
        - No OCR capability (use Docling for scanned PDFs)
        - Limited table extraction (use Docling for complex tables)
        - No layout understanding (use Docling for complex layouts)
    """

    def __init__(
        self,
        name: str = "fast-pdf",
        service_url: str = "local://fast-pdf",  # Not used, but required by base class
        timeout: int = 60,
        verify_ssl: bool = True,
        api_key: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ):
        """Initialize the FastPdfEngine."""
        super().__init__(
            name=name,
            service_url=service_url,
            timeout=timeout,
            verify_ssl=verify_ssl,
            api_key=api_key,
            options=options
        )
        self._fitz_available = self._check_fitz()

    def _check_fitz(self) -> bool:
        """Check if PyMuPDF is available."""
        try:
            import fitz
            return True
        except ImportError:
            logger.error("PyMuPDF (fitz) is not installed. Install with: pip install PyMuPDF")
            return False

    @property
    def engine_type(self) -> str:
        return "fast_pdf"

    @property
    def display_name(self) -> str:
        return "Fast PDF"

    @property
    def description(self) -> str:
        return "Fast local extraction for simple text-based PDFs using PyMuPDF"

    def get_supported_formats(self) -> List[str]:
        """Get supported file formats."""
        return [".pdf"]

    async def extract(
        self,
        file_path: Path,
        max_retries: int = 2  # Not used for local extraction
    ) -> ExtractionResult:
        """
        Extract text from a PDF file.

        Args:
            file_path: Path to the PDF file
            max_retries: Not used for local extraction

        Returns:
            ExtractionResult with markdown content or error
        """
        if not self._fitz_available:
            return ExtractionResult(
                content="",
                success=False,
                error="PyMuPDF (fitz) is not installed",
                metadata={"engine": self.engine_type}
            )

        try:
            import fitz

            self._logger.info("Extracting PDF with FastPdfEngine: %s", file_path.name)

            doc = fitz.open(str(file_path))
            markdown_parts = []

            # Extract document metadata
            metadata = doc.metadata
            if metadata:
                title = metadata.get("title", "")
                author = metadata.get("author", "")

                if title:
                    markdown_parts.append(f"# {title}\n")
                if author:
                    markdown_parts.append(f"*Author: {author}*\n")
                if title or author:
                    markdown_parts.append("")  # Blank line after metadata

            # Extract text from each page
            total_pages = len(doc)
            for page_num in range(total_pages):
                page = doc[page_num]

                # Get text with layout preservation
                # Using "text" extraction with some structure
                text = page.get_text("text")

                if text.strip():
                    # Add page separator for multi-page docs
                    if total_pages > 1 and page_num > 0:
                        markdown_parts.append(f"\n---\n\n*Page {page_num + 1}*\n")

                    markdown_parts.append(text.strip())

            doc.close()

            # Combine all parts
            markdown_content = "\n\n".join(markdown_parts)

            if not markdown_content.strip():
                return ExtractionResult(
                    content="",
                    success=False,
                    error="PDF contains no extractable text. May be scanned or image-based.",
                    metadata={
                        "engine": self.engine_type,
                        "file": file_path.name,
                        "pages": total_pages,
                    }
                )

            self._logger.info(
                "FastPdfEngine extraction complete: %d pages, %d characters",
                total_pages, len(markdown_content)
            )

            return ExtractionResult(
                content=markdown_content,
                success=True,
                metadata={
                    "engine": self.engine_type,
                    "engine_name": self.display_name,
                    "file": file_path.name,
                    "pages": total_pages,
                    "characters": len(markdown_content),
                    "title": metadata.get("title", "") if metadata else "",
                }
            )

        except Exception as e:
            self._logger.error("FastPdfEngine extraction failed: %s", str(e))
            return ExtractionResult(
                content="",
                success=False,
                error=str(e),
                metadata={
                    "engine": self.engine_type,
                    "file": file_path.name,
                }
            )

    async def test_connection(self) -> Dict[str, Any]:
        """
        Test that PyMuPDF is available.

        Returns:
            Dict with health status
        """
        if self._fitz_available:
            try:
                import fitz
                version = fitz.version
                return {
                    "success": True,
                    "status": "healthy",
                    "message": f"PyMuPDF is available (version {version})",
                    "details": {
                        "version": version,
                        "engine_type": self.engine_type,
                    }
                }
            except Exception as e:
                return {
                    "success": False,
                    "status": "unhealthy",
                    "message": f"PyMuPDF error: {e}",
                    "details": {"error": str(e)}
                }
        else:
            return {
                "success": False,
                "status": "unhealthy",
                "message": "PyMuPDF is not installed",
                "details": {"install": "pip install PyMuPDF"}
            }
