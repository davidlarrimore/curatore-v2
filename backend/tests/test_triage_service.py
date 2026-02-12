"""
Comprehensive tests for the triage service.

Tests the document analysis and extraction engine routing functionality
for PDFs, Office files, text files, images, and unknown file types.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest
from app.core.ingestion.triage_service import (
    IMAGE_EXTENSIONS,
    OFFICE_EXTENSIONS,
    PDF_EXTENSIONS,
    TEXT_EXTENSIONS,
    DocumentComplexity,
    ExtractionEngine,
    ExtractionPlan,
    TriageService,
    triage_service,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def service():
    """Create a fresh triage service instance."""
    return TriageService()


@pytest.fixture
def simple_pdf(tmp_path):
    """Create a simple PDF file for testing."""
    # Create a minimal PDF file (just header bytes)
    pdf_path = tmp_path / "simple.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%test")
    return pdf_path


@pytest.fixture
def small_docx(tmp_path):
    """Create a small DOCX file for testing."""
    docx_path = tmp_path / "small.docx"
    # Create a minimal file (less than 5MB)
    docx_path.write_bytes(b"PK\x03\x04" + b"0" * 1000)  # ~1KB
    return docx_path


@pytest.fixture
def large_docx(tmp_path):
    """Create a large DOCX file for testing."""
    docx_path = tmp_path / "large.docx"
    # Create a file larger than 5MB threshold
    docx_path.write_bytes(b"PK\x03\x04" + b"0" * (6 * 1024 * 1024))  # ~6MB
    return docx_path


@pytest.fixture
def text_file(tmp_path):
    """Create a text file for testing."""
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("Hello, World!")
    return txt_path


@pytest.fixture
def image_file(tmp_path):
    """Create an image file for testing."""
    img_path = tmp_path / "test.png"
    # PNG header bytes
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 100)
    return img_path


# =============================================================================
# ExtractionPlan Tests
# =============================================================================


class TestExtractionPlan:
    """Tests for ExtractionPlan dataclass."""

    def test_extraction_plan_creation(self):
        """Test basic ExtractionPlan creation."""
        plan = ExtractionPlan(
            file_type=".pdf",
            engine="fast_pdf",
            needs_ocr=False,
            needs_layout=False,
            complexity="low",
            reason="Simple PDF",
        )

        assert plan.file_type == ".pdf"
        assert plan.engine == "fast_pdf"
        assert plan.needs_ocr is False
        assert plan.needs_layout is False
        assert plan.complexity == "low"
        assert plan.triage_duration_ms == 0
        assert plan.reason == "Simple PDF"

    def test_extraction_plan_to_dict(self):
        """Test ExtractionPlan serialization."""
        plan = ExtractionPlan(
            file_type=".docx",
            engine="extraction-service",
            needs_ocr=False,
            needs_layout=True,
            complexity="medium",
            triage_duration_ms=50,
            reason="Office file",
        )

        result = plan.to_dict()

        assert result["file_type"] == ".docx"
        assert result["engine"] == "extraction-service"
        assert result["needs_ocr"] is False
        assert result["needs_layout"] is True
        assert result["complexity"] == "medium"
        assert result["triage_duration_ms"] == 50
        assert result["reason"] == "Office file"

    def test_extraction_plan_engines(self):
        """Test all valid engine values."""
        valid_engines = ["fast_pdf", "extraction-service", "docling", "unsupported"]

        for engine in valid_engines:
            plan = ExtractionPlan(
                file_type=".test",
                engine=engine,
                needs_ocr=False,
                needs_layout=False,
                complexity="low",
            )
            assert plan.engine == engine


# =============================================================================
# TriageService Initialization Tests
# =============================================================================


class TestTriageServiceInit:
    """Tests for TriageService initialization."""

    def test_service_initialization(self, service):
        """Test service initializes correctly."""
        assert service is not None
        # fitz availability depends on PyMuPDF being installed
        assert isinstance(service._fitz_available, bool)

    def test_global_singleton(self):
        """Test global triage_service singleton exists."""
        assert triage_service is not None
        assert isinstance(triage_service, TriageService)

    def test_fitz_availability_check(self, service):
        """Test PyMuPDF availability check."""
        result = service._check_fitz_available()
        # Should be True if PyMuPDF is installed, False otherwise
        assert isinstance(result, bool)


# =============================================================================
# Image Triage Tests
# =============================================================================


class TestImageTriage:
    """Tests for image file triage."""

    @pytest.mark.asyncio
    async def test_png_returns_unsupported(self, service, image_file):
        """Test PNG files return unsupported engine."""
        plan = await service.triage(image_file)

        assert plan.engine == "unsupported"
        assert plan.needs_ocr is False
        assert plan.complexity == "low"
        assert "not supported" in plan.reason.lower()

    @pytest.mark.asyncio
    async def test_all_image_extensions_unsupported(self, service, tmp_path):
        """Test all image extensions return unsupported."""
        for ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp"]:
            img_path = tmp_path / f"test{ext}"
            img_path.write_bytes(b"fake image data")

            plan = await service.triage(img_path)

            assert plan.engine == "unsupported", f"{ext} should be unsupported"
            assert plan.file_type == ext

    @pytest.mark.asyncio
    async def test_image_triage_direct(self, service):
        """Test _triage_image method directly."""
        plan = service._triage_image(".png")

        assert plan.engine == "unsupported"
        assert plan.file_type == ".png"
        assert "standalone image" in plan.reason.lower()


# =============================================================================
# Text File Triage Tests
# =============================================================================


class TestTextTriage:
    """Tests for text file triage."""

    @pytest.mark.asyncio
    async def test_txt_uses_extraction_service(self, service, text_file):
        """Test TXT files use extraction-service."""
        plan = await service.triage(text_file)

        assert plan.engine == "extraction-service"
        assert plan.needs_ocr is False
        assert plan.needs_layout is False
        assert plan.complexity == "low"

    @pytest.mark.asyncio
    async def test_all_text_extensions(self, service, tmp_path):
        """Test all text extensions use extraction-service."""
        text_exts = [".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm"]

        for ext in text_exts:
            file_path = tmp_path / f"test{ext}"
            file_path.write_text("test content")

            plan = await service.triage(file_path)

            assert plan.engine == "extraction-service", f"{ext} should use extraction-service"
            assert plan.complexity == "low"

    def test_triage_text_direct(self, service):
        """Test _triage_text method directly."""
        plan = service._triage_text(".md")

        assert plan.engine == "extraction-service"
        assert plan.file_type == ".md"
        assert "markitdown" in plan.reason.lower()


# =============================================================================
# Office File Triage Tests
# =============================================================================


class TestOfficeTriage:
    """Tests for Office file triage."""

    @pytest.mark.asyncio
    async def test_small_docx_uses_extraction_service(self, service, small_docx):
        """Test small DOCX uses extraction-service."""
        plan = await service.triage(small_docx)

        assert plan.engine == "extraction-service"
        assert plan.complexity == "low"
        assert "markitdown" in plan.reason.lower()

    @pytest.mark.asyncio
    async def test_large_docx_uses_docling(self, service, large_docx):
        """Test large DOCX uses docling."""
        plan = await service.triage(large_docx, docling_enabled=True)

        assert plan.engine == "docling"
        assert plan.complexity == "medium"
        assert "large" in plan.reason.lower()

    @pytest.mark.asyncio
    async def test_large_docx_fallback_when_docling_disabled(self, service, large_docx):
        """Test large DOCX falls back to extraction-service when Docling disabled."""
        plan = await service.triage(large_docx, docling_enabled=False)

        assert plan.engine == "extraction-service"
        # Reason format changed from "fallback" to more descriptive message
        assert "extraction-service" in plan.reason.lower() or "markitdown" in plan.reason.lower()

    @pytest.mark.asyncio
    async def test_all_office_extensions(self, service, tmp_path):
        """Test all Office extensions are triaged correctly."""
        office_exts = [".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"]

        for ext in office_exts:
            file_path = tmp_path / f"test{ext}"
            file_path.write_bytes(b"PK\x03\x04" + b"0" * 1000)  # Small file

            plan = await service.triage(file_path)

            assert plan.engine == "extraction-service", f"{ext} should use extraction-service"


# =============================================================================
# PDF Triage Tests
# =============================================================================


class TestPdfTriage:
    """Tests for PDF file triage."""

    @pytest.mark.asyncio
    async def test_pdf_triage_with_fitz_unavailable(self, service, simple_pdf):
        """Test PDF triage falls back when PyMuPDF unavailable."""
        # Mock fitz as unavailable
        service._fitz_available = False

        plan = await service.triage(simple_pdf, docling_enabled=True)

        # Should fall back to docling when fitz unavailable
        assert plan.engine == "docling"
        assert "fallback" in plan.reason.lower()

    @pytest.mark.asyncio
    async def test_pdf_triage_fallback_without_docling(self, service, simple_pdf):
        """Test PDF triage falls back to fast_pdf when both fitz and docling unavailable."""
        service._fitz_available = False

        plan = await service.triage(simple_pdf, docling_enabled=False)

        assert plan.engine == "fast_pdf"

    @pytest.mark.asyncio
    async def test_pdf_simple_uses_fast_pdf(self, service, simple_pdf):
        """Test simple PDF uses fast_pdf engine."""
        # Mock fitz module
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_page = MagicMock()
        mock_page.get_text.side_effect = [
            "A" * 500,  # Good text content
            {"blocks": [{}] * 10},  # Few blocks
        ]
        mock_page.get_images.return_value = []  # No images
        mock_page.get_drawings.return_value = []  # No drawings
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {'fitz': mock_fitz}):
            service._fitz_available = True
            plan = await service.triage(simple_pdf, docling_enabled=True)

        assert plan.engine == "fast_pdf"
        assert plan.needs_ocr is False
        assert plan.complexity == "low"

    @pytest.mark.asyncio
    async def test_pdf_scanned_uses_docling(self, service, simple_pdf):
        """Test scanned PDF uses docling engine."""
        # Mock fitz module
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_page = MagicMock()
        mock_page.get_text.side_effect = [
            "A" * 10,  # Very little text (scanned)
            {"blocks": [{}] * 5},
        ]
        mock_page.get_images.return_value = [(1,)]  # Has images
        mock_page.get_drawings.return_value = []
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {'fitz': mock_fitz}):
            service._fitz_available = True
            plan = await service.triage(simple_pdf, docling_enabled=True)

        assert plan.engine == "docling"
        assert plan.needs_ocr is True
        assert plan.complexity == "high"

    @pytest.mark.asyncio
    async def test_pdf_complex_layout_uses_docling(self, service, simple_pdf):
        """Test PDF with complex layout uses docling engine."""
        # Mock fitz module
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_page = MagicMock()
        mock_page.get_text.side_effect = [
            "A" * 500,  # Good text
            {"blocks": [{}] * 60},  # Many blocks (>50 threshold)
        ]
        mock_page.get_images.return_value = []
        mock_page.get_drawings.return_value = []
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {'fitz': mock_fitz}):
            service._fitz_available = True
            plan = await service.triage(simple_pdf, docling_enabled=True)

        assert plan.engine == "docling"
        assert plan.needs_layout is True
        assert plan.complexity == "medium"

    @pytest.mark.asyncio
    async def test_pdf_with_tables_uses_docling(self, service, simple_pdf):
        """Test PDF with tables uses docling engine."""
        # Mock fitz module
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_page = MagicMock()
        mock_page.get_text.side_effect = [
            "A" * 500,
            {"blocks": [{}] * 10},
        ]
        mock_page.get_images.return_value = []
        mock_page.get_drawings.return_value = [{"items": True}] * 25  # Many lines (>20)
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {'fitz': mock_fitz}):
            service._fitz_available = True
            plan = await service.triage(simple_pdf, docling_enabled=True)

        assert plan.engine == "docling"
        assert "tables" in plan.reason.lower()


# =============================================================================
# Unknown File Type Tests
# =============================================================================


class TestUnknownFileTriage:
    """Tests for unknown file type triage."""

    @pytest.mark.asyncio
    async def test_unknown_extension_uses_extraction_service(self, service, tmp_path):
        """Test unknown file extensions use extraction-service as fallback."""
        unknown_path = tmp_path / "test.xyz"
        unknown_path.write_bytes(b"unknown content")

        plan = await service.triage(unknown_path)

        assert plan.engine == "extraction-service"
        assert "fallback" in plan.reason.lower()

    @pytest.mark.asyncio
    async def test_no_extension_uses_extraction_service(self, service, tmp_path):
        """Test files without extension use extraction-service."""
        no_ext_path = tmp_path / "noextension"
        no_ext_path.write_bytes(b"content")

        plan = await service.triage(no_ext_path)

        assert plan.engine == "extraction-service"


# =============================================================================
# Docling Fallback Tests
# =============================================================================


class TestDoclingFallback:
    """Tests for Docling disabled fallback behavior."""

    @pytest.mark.asyncio
    async def test_docling_disabled_pdf_fallback(self, service, simple_pdf):
        """Test PDF falls back to fast_pdf when Docling disabled."""
        # Force docling selection first
        service._fitz_available = False

        plan = await service.triage(simple_pdf, docling_enabled=False)

        assert plan.engine == "fast_pdf"
        assert "fallback" in plan.reason.lower()

    @pytest.mark.asyncio
    async def test_docling_disabled_office_fallback(self, service, large_docx):
        """Test large Office file falls back to extraction-service when Docling disabled."""
        plan = await service.triage(large_docx, docling_enabled=False)

        assert plan.engine == "extraction-service"
        # Reason format changed from "fallback" to more descriptive message
        assert "extraction-service" in plan.reason.lower() or "markitdown" in plan.reason.lower()


# =============================================================================
# Triage Duration Tests
# =============================================================================


class TestTriageDuration:
    """Tests for triage timing."""

    @pytest.mark.asyncio
    async def test_triage_records_duration(self, service, text_file):
        """Test triage records duration in milliseconds."""
        plan = await service.triage(text_file)

        assert plan.triage_duration_ms >= 0
        # Should be fast (< 1 second for simple triage)
        assert plan.triage_duration_ms < 1000

    @pytest.mark.asyncio
    async def test_triage_duration_in_dict(self, service, text_file):
        """Test triage duration is included in to_dict output."""
        plan = await service.triage(text_file)
        result = plan.to_dict()

        assert "triage_duration_ms" in result
        assert isinstance(result["triage_duration_ms"], int)


# =============================================================================
# Extension Constants Tests
# =============================================================================


class TestExtensionConstants:
    """Tests for file extension constants."""

    def test_pdf_extensions(self):
        """Test PDF extensions constant."""
        assert ".pdf" in PDF_EXTENSIONS

    def test_office_extensions(self):
        """Test Office extensions constant."""
        expected = {".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"}
        for ext in expected:
            assert ext in OFFICE_EXTENSIONS, f"{ext} should be in OFFICE_EXTENSIONS"

    def test_image_extensions(self):
        """Test image extensions constant."""
        expected = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp"}
        for ext in expected:
            assert ext in IMAGE_EXTENSIONS, f"{ext} should be in IMAGE_EXTENSIONS"

    def test_text_extensions(self):
        """Test text extensions constant."""
        expected = {".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm"}
        for ext in expected:
            assert ext in TEXT_EXTENSIONS, f"{ext} should be in TEXT_EXTENSIONS"


# =============================================================================
# Enum Tests
# =============================================================================


class TestEnums:
    """Tests for triage enums."""

    def test_extraction_engine_values(self):
        """Test ExtractionEngine enum values."""
        assert ExtractionEngine.FAST_PDF.value == "fast_pdf"
        assert ExtractionEngine.EXTRACTION_SERVICE.value == "extraction-service"
        assert ExtractionEngine.DOCLING.value == "docling"
        assert ExtractionEngine.UNSUPPORTED.value == "unsupported"

    def test_document_complexity_values(self):
        """Test DocumentComplexity enum values."""
        assert DocumentComplexity.LOW.value == "low"
        assert DocumentComplexity.MEDIUM.value == "medium"
        assert DocumentComplexity.HIGH.value == "high"
