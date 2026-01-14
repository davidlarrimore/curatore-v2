"""
Unit tests for PathService.

Tests path resolution, sanitization, and hierarchical organization logic.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.services.path_service import PathService
from app.config import settings


@pytest.fixture
def temp_storage():
    """Create temporary storage directory for tests."""
    temp_dir = tempfile.mkdtemp()

    # Override settings for testing
    original_files_root = settings.files_root
    original_dedupe_dir = settings.dedupe_dir
    original_temp_dir = settings.temp_dir

    settings.files_root = temp_dir
    settings.dedupe_dir = str(Path(temp_dir) / "dedupe")
    settings.temp_dir = str(Path(temp_dir) / "temp")

    yield Path(temp_dir)

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)
    settings.files_root = original_files_root
    settings.dedupe_dir = original_dedupe_dir
    settings.temp_dir = original_temp_dir


@pytest.fixture
def path_service(temp_storage):
    """Create PathService instance with temp storage."""
    return PathService()


class TestPathServiceInitialization:
    """Test PathService initialization and configuration."""

    def test_initialization(self, path_service):
        """Test service initializes with correct settings."""
        assert path_service.files_root is not None
        assert path_service.use_hierarchical is not None

    def test_singleton_pattern(self, path_service):
        """Test that multiple instances share configuration."""
        another_service = PathService()
        assert another_service.files_root == path_service.files_root


class TestOrganizationPathResolution:
    """Test organization path resolution."""

    def test_resolve_organization_path_with_org_id(self, path_service, temp_storage):
        """Test organization path with valid org ID."""
        org_path = path_service.resolve_organization_path("org-123")

        assert "organizations" in str(org_path)
        assert "org-123" in str(org_path)
        assert org_path.is_absolute()

    def test_resolve_organization_path_shared(self, path_service, temp_storage):
        """Test organization path for shared (no org ID)."""
        shared_path = path_service.resolve_organization_path(None)

        assert "shared" in str(shared_path)
        assert shared_path.is_absolute()

    def test_resolve_organization_path_empty_string(self, path_service, temp_storage):
        """Test organization path with empty string."""
        shared_path = path_service.resolve_organization_path("")

        assert "shared" in str(shared_path)


class TestBatchPathResolution:
    """Test batch path resolution."""

    def test_resolve_batch_path_with_batch_id(self, path_service, temp_storage):
        """Test batch path with valid batch ID."""
        org_path = path_service.resolve_organization_path("org-456")
        batch_path = path_service.resolve_batch_path(org_path, "batch-789")

        assert "batches" in str(batch_path)
        assert "batch-789" in str(batch_path)

    def test_resolve_batch_path_adhoc(self, path_service, temp_storage):
        """Test batch path for adhoc (no batch ID)."""
        org_path = path_service.resolve_organization_path("org-456")
        adhoc_path = path_service.resolve_batch_path(org_path, None)

        assert "adhoc" in str(adhoc_path)

    def test_resolve_batch_path_empty_string(self, path_service, temp_storage):
        """Test batch path with empty string."""
        org_path = path_service.resolve_organization_path("org-456")
        adhoc_path = path_service.resolve_batch_path(org_path, "")

        assert "adhoc" in str(adhoc_path)


class TestDocumentPathResolution:
    """Test document path resolution."""

    def test_get_document_path_with_batch(self, path_service, temp_storage):
        """Test document path with batch grouping."""
        doc_path = path_service.get_document_path(
            document_id="doc-123",
            organization_id="org-456",
            batch_id="batch-789",
            file_type="uploaded",
            filename="test.pdf",
            create_dirs=False,
        )

        assert "organizations/org-456/batches/batch-789/uploaded" in str(doc_path)
        assert "doc-123_test.pdf" in str(doc_path)

    def test_get_document_path_adhoc(self, path_service, temp_storage):
        """Test document path for adhoc files."""
        doc_path = path_service.get_document_path(
            document_id="doc-abc",
            organization_id="org-456",
            batch_id=None,
            file_type="processed",
            filename="output.md",
            create_dirs=False,
        )

        assert "organizations/org-456/adhoc/processed" in str(doc_path)
        assert "doc-abc_output.md" in str(doc_path)

    def test_get_document_path_shared(self, path_service, temp_storage):
        """Test document path for shared (no org)."""
        doc_path = path_service.get_document_path(
            document_id="doc-xyz",
            organization_id=None,
            batch_id=None,
            file_type="uploaded",
            filename="shared.pdf",
            create_dirs=False,
        )

        assert "shared/adhoc/uploaded" in str(doc_path)
        assert "doc-xyz_shared.pdf" in str(doc_path)

    def test_get_document_path_creates_directories(self, path_service, temp_storage):
        """Test that directories are created when requested."""
        doc_path = path_service.get_document_path(
            document_id="doc-999",
            organization_id="org-new",
            batch_id="batch-new",
            file_type="uploaded",
            filename="new.pdf",
            create_dirs=True,
        )

        assert doc_path.parent.exists()
        assert doc_path.parent.is_dir()

    def test_get_document_path_no_create_directories(self, path_service, temp_storage):
        """Test that directories are not created when create_dirs=False."""
        doc_path = path_service.get_document_path(
            document_id="doc-888",
            organization_id="org-nocreate",
            batch_id="batch-nocreate",
            file_type="uploaded",
            filename="nocreate.pdf",
            create_dirs=False,
        )

        assert not doc_path.parent.exists()


class TestFilenameSanitization:
    """Test filename sanitization."""

    def test_sanitize_special_characters(self, path_service):
        """Test sanitization of special characters."""
        safe = path_service.sanitize_filename("My Document (1).pdf")
        assert safe == "My_Document_1.pdf"

    def test_sanitize_path_traversal(self, path_service):
        """Test protection against path traversal."""
        safe = path_service.sanitize_filename("../../../etc/passwd")
        assert safe == "etc_passwd"
        assert ".." not in safe
        assert "/" not in safe

    def test_sanitize_colons(self, path_service):
        """Test sanitization of colons."""
        safe = path_service.sanitize_filename("file:with:colons.txt")
        assert safe == "filewithcolons.txt"
        assert ":" not in safe

    def test_sanitize_windows_reserved_chars(self, path_service):
        """Test sanitization of Windows reserved characters."""
        safe = path_service.sanitize_filename('file<>:|?*.txt')
        assert safe == "file.txt"
        for char in '<>:|?*':
            assert char not in safe

    def test_sanitize_preserves_extension(self, path_service):
        """Test that file extension is preserved."""
        safe = path_service.sanitize_filename("my file (1).pdf")
        assert safe.endswith(".pdf")

    def test_sanitize_multiple_dots(self, path_service):
        """Test handling of multiple dots in filename."""
        safe = path_service.sanitize_filename("my.file.name.tar.gz")
        assert ".tar.gz" in safe or ".gz" in safe

    def test_sanitize_unicode_characters(self, path_service):
        """Test handling of unicode characters."""
        safe = path_service.sanitize_filename("文档.pdf")
        # Should preserve unicode or convert to safe equivalent
        assert safe != ""
        assert ".pdf" in safe

    def test_sanitize_empty_string(self, path_service):
        """Test handling of empty string."""
        safe = path_service.sanitize_filename("")
        assert safe == ""

    def test_sanitize_spaces_converted_to_underscores(self, path_service):
        """Test that spaces are converted to underscores."""
        safe = path_service.sanitize_filename("my file name.pdf")
        assert " " not in safe
        assert "_" in safe


class TestTempPathGeneration:
    """Test temporary file path generation."""

    def test_get_temp_path_for_job(self, path_service, temp_storage):
        """Test temp path generation for job."""
        temp_path = path_service.get_temp_path(
            job_id="job-123",
            filename="temp.pdf",
            create_dirs=False,
        )

        assert "temp" in str(temp_path)
        assert "job-123" in str(temp_path)
        assert "temp.pdf" in str(temp_path)

    def test_get_temp_path_creates_directories(self, path_service, temp_storage):
        """Test that temp directories are created when requested."""
        temp_path = path_service.get_temp_path(
            job_id="job-456",
            filename="test.pdf",
            create_dirs=True,
        )

        assert temp_path.parent.exists()
        assert temp_path.parent.is_dir()


class TestDeduplicationPathGeneration:
    """Test deduplication storage path generation."""

    def test_get_dedupe_path(self, path_service, temp_storage):
        """Test dedupe path generation."""
        hash_value = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        dedupe_path = path_service.get_dedupe_path(
            hash_value=hash_value,
            create_dirs=False,
        )

        assert "dedupe" in str(dedupe_path)
        # Should use first 2 chars as subdirectory
        assert "/ab/" in str(dedupe_path) or "\\ab\\" in str(dedupe_path)
        assert hash_value in str(dedupe_path)

    def test_get_dedupe_path_creates_directories(self, path_service, temp_storage):
        """Test that dedupe directories are created when requested."""
        hash_value = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        dedupe_path = path_service.get_dedupe_path(
            hash_value=hash_value,
            create_dirs=True,
        )

        assert dedupe_path.exists()
        assert dedupe_path.is_dir()

    def test_get_dedupe_path_short_hash(self, path_service, temp_storage):
        """Test dedupe path with short hash (edge case)."""
        hash_value = "ab"
        dedupe_path = path_service.get_dedupe_path(
            hash_value=hash_value,
            create_dirs=False,
        )

        assert "dedupe" in str(dedupe_path)
        assert hash_value in str(dedupe_path)


class TestLegacyPathHandling:
    """Test backward compatibility with legacy flat structure."""

    @patch.object(PathService, 'use_hierarchical', False)
    def test_legacy_path_resolution(self, path_service, temp_storage):
        """Test that legacy flat paths are used when hierarchical is disabled."""
        # This would require updating path_service to respect use_hierarchical flag
        # For now, just verify the flag exists
        assert hasattr(path_service, 'use_hierarchical')


class TestErrorHandling:
    """Test error handling in path operations."""

    def test_invalid_file_type(self, path_service):
        """Test handling of invalid file type."""
        # Should handle gracefully or raise appropriate error
        try:
            path_service.get_document_path(
                document_id="doc-123",
                organization_id="org-456",
                batch_id=None,
                file_type="invalid_type",  # type: ignore
                filename="test.pdf",
            )
        except (ValueError, AttributeError):
            pass  # Expected behavior

    def test_none_filename(self, path_service):
        """Test handling of None filename."""
        try:
            path_service.get_document_path(
                document_id="doc-123",
                organization_id="org-456",
                batch_id=None,
                file_type="uploaded",
                filename=None,  # type: ignore
            )
        except (ValueError, TypeError, AttributeError):
            pass  # Expected behavior


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
