"""
Comprehensive tests for extraction engines and factory.

Tests the FastPdfEngine, ExtractionServiceEngine, DoclingEngine,
and ExtractionEngineFactory functionality.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from app.core.ingestion.extraction.base import BaseExtractionEngine, ExtractionResult
from app.core.ingestion.extraction.factory import ExtractionEngineFactory
from app.core.ingestion.extraction.fast_pdf import FastPdfEngine

# =============================================================================
# ExtractionResult Tests
# =============================================================================


class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""

    def test_extraction_result_success(self):
        """Test successful extraction result."""
        result = ExtractionResult(
            content="# Document\n\nContent here",
            success=True,
            metadata={"engine": "fast_pdf", "pages": 5}
        )

        assert result.content == "# Document\n\nContent here"
        assert result.success is True
        assert result.error is None
        assert result.metadata["engine"] == "fast_pdf"

    def test_extraction_result_failure(self):
        """Test failed extraction result."""
        result = ExtractionResult(
            content="",
            success=False,
            error="PDF contains no text",
            metadata={"engine": "fast_pdf"}
        )

        assert result.content == ""
        assert result.success is False
        assert result.error == "PDF contains no text"


# =============================================================================
# FastPdfEngine Tests
# =============================================================================


class TestFastPdfEngine:
    """Tests for FastPdfEngine."""

    def test_engine_initialization(self):
        """Test FastPdfEngine initializes correctly."""
        engine = FastPdfEngine(name="test-fast-pdf")

        assert engine.name == "test-fast-pdf"
        assert engine.engine_type == "fast_pdf"
        assert engine.display_name == "Fast PDF"
        assert ".pdf" in engine.get_supported_formats()

    def test_engine_properties(self):
        """Test FastPdfEngine properties."""
        engine = FastPdfEngine()

        assert engine.engine_type == "fast_pdf"
        assert engine.display_name == "Fast PDF"
        assert "PyMuPDF" in engine.description

    def test_supported_formats(self):
        """Test FastPdfEngine supported formats."""
        engine = FastPdfEngine()
        formats = engine.get_supported_formats()

        assert ".pdf" in formats
        assert len(formats) == 1  # Only PDFs

    @pytest.mark.asyncio
    async def test_extract_without_fitz(self):
        """Test extraction fails gracefully without PyMuPDF."""
        engine = FastPdfEngine()
        engine._fitz_available = False

        result = await engine.extract(Path("test.pdf"))

        assert result.success is False
        assert "not installed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_extract_simple_pdf(self, tmp_path):
        """Test extraction of a simple PDF."""
        # Create test PDF
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\ntest")

        # Mock fitz module
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=2)
        mock_doc.metadata = {"title": "Test Doc", "author": "Test Author"}

        mock_page1 = MagicMock()
        mock_page1.get_text.return_value = "Page 1 content"
        mock_page2 = MagicMock()
        mock_page2.get_text.return_value = "Page 2 content"

        mock_doc.__getitem__ = MagicMock(side_effect=[mock_page1, mock_page2])
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {'fitz': mock_fitz}):
            engine = FastPdfEngine()
            engine._fitz_available = True

            result = await engine.extract(pdf_path)

        assert result.success is True
        assert "Test Doc" in result.content
        assert "Page 1 content" in result.content
        assert result.metadata["pages"] == 2

    @pytest.mark.asyncio
    async def test_extract_empty_pdf(self, tmp_path):
        """Test extraction of PDF with no text."""
        pdf_path = tmp_path / "empty.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")

        # Mock fitz module
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_doc.metadata = {}

        mock_page = MagicMock()
        mock_page.get_text.return_value = ""  # No text

        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {'fitz': mock_fitz}):
            engine = FastPdfEngine()
            engine._fitz_available = True

            result = await engine.extract(pdf_path)

        assert result.success is False
        assert "no extractable text" in result.error.lower()

    @pytest.mark.asyncio
    async def test_test_connection_with_fitz(self):
        """Test connection check when PyMuPDF available."""
        engine = FastPdfEngine()

        if engine._fitz_available:
            result = await engine.test_connection()
            assert result["success"] is True
            assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_test_connection_without_fitz(self):
        """Test connection check when PyMuPDF unavailable."""
        engine = FastPdfEngine()
        engine._fitz_available = False

        result = await engine.test_connection()

        assert result["success"] is False
        assert result["status"] == "unhealthy"


# =============================================================================
# ExtractionEngineFactory Tests
# =============================================================================


class TestExtractionEngineFactory:
    """Tests for ExtractionEngineFactory."""

    def test_get_supported_engines(self):
        """Test getting list of supported engines."""
        engines = ExtractionEngineFactory.get_supported_engines()

        assert "fast_pdf" in engines
        assert "extraction-service" in engines
        assert "docling" in engines
        assert "tika" in engines

    def test_is_supported(self):
        """Test checking if engine type is supported."""
        assert ExtractionEngineFactory.is_supported("fast_pdf") is True
        assert ExtractionEngineFactory.is_supported("extraction-service") is True
        assert ExtractionEngineFactory.is_supported("docling") is True
        assert ExtractionEngineFactory.is_supported("nonexistent") is False

    def test_create_fast_pdf_engine(self):
        """Test creating FastPdfEngine."""
        engine = ExtractionEngineFactory.create_engine(
            engine_type="fast_pdf",
            name="test-fast-pdf",
            service_url="local://fast-pdf",
        )

        assert isinstance(engine, FastPdfEngine)
        assert engine.name == "test-fast-pdf"
        assert engine.engine_type == "fast_pdf"

    def test_create_engine_invalid_type(self):
        """Test creating engine with invalid type raises error."""
        with pytest.raises(ValueError) as exc_info:
            ExtractionEngineFactory.create_engine(
                engine_type="invalid-engine",
                name="test",
                service_url="http://test",
            )

        assert "Unsupported engine type" in str(exc_info.value)
        assert "invalid-engine" in str(exc_info.value)

    def test_from_config(self):
        """Test creating engine from config dictionary."""
        config = {
            "engine_type": "fast_pdf",
            "name": "config-fast-pdf",
            "service_url": "local://fast-pdf",
            "timeout": 120,
            "options": {"some_option": True},
        }

        engine = ExtractionEngineFactory.from_config(config)

        assert engine.name == "config-fast-pdf"
        assert engine.engine_type == "fast_pdf"
        assert engine.timeout == 120

    def test_from_config_missing_required(self):
        """Test from_config raises error for missing required fields."""
        config = {
            "engine_type": "fast_pdf",
            # Missing name and service_url
        }

        with pytest.raises(ValueError) as exc_info:
            ExtractionEngineFactory.from_config(config)

        assert "Missing required config keys" in str(exc_info.value)

    def test_from_config_defaults(self):
        """Test from_config uses defaults for optional fields."""
        config = {
            "engine_type": "fast_pdf",
            "name": "minimal",
            "service_url": "local://fast-pdf",
        }

        engine = ExtractionEngineFactory.from_config(config)

        assert engine.timeout == 300  # Default timeout
        assert engine.verify_ssl is True  # Default SSL verification

    def test_register_custom_engine(self):
        """Test registering a custom engine type."""

        class CustomEngine(BaseExtractionEngine):
            @property
            def engine_type(self):
                return "custom"

            @property
            def display_name(self):
                return "Custom"

            @property
            def description(self):
                return "Custom engine"

            def get_supported_formats(self):
                return [".custom"]

            async def extract(self, file_path, max_retries=2):
                return ExtractionResult(content="", success=True)

            async def test_connection(self):
                return {"success": True}

        # Register the custom engine
        ExtractionEngineFactory.register_engine("custom", CustomEngine)

        assert ExtractionEngineFactory.is_supported("custom")

        # Create an instance
        engine = ExtractionEngineFactory.create_engine(
            engine_type="custom",
            name="my-custom",
            service_url="http://custom",
        )

        assert engine.engine_type == "custom"

    def test_register_invalid_engine(self):
        """Test registering non-BaseExtractionEngine raises error."""

        class NotAnEngine:
            pass

        with pytest.raises(TypeError) as exc_info:
            ExtractionEngineFactory.register_engine("invalid", NotAnEngine)

        assert "must inherit from BaseExtractionEngine" in str(exc_info.value)


# =============================================================================
# Engine Integration Tests
# =============================================================================


class TestEngineIntegration:
    """Integration tests for extraction engines."""

    def test_all_engines_have_required_properties(self):
        """Test all registered engines have required properties."""
        for engine_type in ExtractionEngineFactory.get_supported_engines():
            engine = ExtractionEngineFactory.create_engine(
                engine_type=engine_type,
                name=f"test-{engine_type}",
                service_url="http://test:8000",
            )

            # All engines must have these properties
            assert hasattr(engine, "engine_type")
            assert hasattr(engine, "display_name")
            assert hasattr(engine, "description")
            assert hasattr(engine, "get_supported_formats")
            assert hasattr(engine, "extract")
            assert hasattr(engine, "test_connection")

            # Properties should return valid values
            assert isinstance(engine.engine_type, str)
            assert isinstance(engine.display_name, str)
            assert isinstance(engine.description, str)
            assert isinstance(engine.get_supported_formats(), list)

    def test_engine_names_are_unique(self):
        """Test engine type names are unique in registry."""
        engines = ExtractionEngineFactory.get_supported_engines()
        assert len(engines) == len(set(engines))

    def test_fast_pdf_only_supports_pdf(self):
        """Test FastPdfEngine only supports PDF files."""
        engine = FastPdfEngine()
        formats = engine.get_supported_formats()

        assert formats == [".pdf"]


# =============================================================================
# Engine Configuration Tests
# =============================================================================


class TestEngineConfiguration:
    """Tests for engine configuration handling."""

    def test_engine_with_options(self):
        """Test engine respects options parameter."""
        engine = FastPdfEngine(
            name="test",
            options={"custom_option": True}
        )

        assert engine.options == {"custom_option": True}

    def test_engine_with_api_key(self):
        """Test engine stores API key."""
        engine = FastPdfEngine(
            name="test",
            api_key="secret-key"
        )

        assert engine.api_key == "secret-key"

    def test_engine_ssl_verification(self):
        """Test engine SSL verification flag."""
        engine_ssl = FastPdfEngine(name="test", verify_ssl=True)
        engine_no_ssl = FastPdfEngine(name="test", verify_ssl=False)

        assert engine_ssl.verify_ssl is True
        assert engine_no_ssl.verify_ssl is False

    def test_engine_timeout_configuration(self):
        """Test engine timeout configuration."""
        engine = FastPdfEngine(name="test", timeout=600)

        assert engine.timeout == 600
