"""
Integration tests for hierarchical storage with deduplication.

This test suite validates the complete hierarchical file organization system
including:
- Path resolution with organization/batch grouping
- File deduplication with SHA-256 hashing
- Reference counting for shared files
- Metadata tracking for batch operations
- Storage statistics and duplicate detection
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone

# Import services
from app.services.path_service import PathService
from app.services.deduplication_service import DeduplicationService
from app.services.metadata_service import MetadataService
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
def path_service_instance(temp_storage):
    """Create path service instance with temp storage."""
    return PathService()


@pytest.fixture
def dedupe_service_instance(temp_storage):
    """Create deduplication service instance with temp storage."""
    return DeduplicationService()


@pytest.fixture
def metadata_service_instance(temp_storage):
    """Create metadata service instance with temp storage."""
    return MetadataService()


class TestPathService:
    """Test path service for hierarchical organization."""

    def test_resolve_organization_path(self, path_service_instance, temp_storage):
        """Test organization path resolution."""
        # Test with organization ID
        org_path = path_service_instance.resolve_organization_path("org-123")
        assert "organizations/org-123" in str(org_path)

        # Test with None (shared)
        shared_path = path_service_instance.resolve_organization_path(None)
        assert "shared" in str(shared_path)

    def test_get_document_path_with_batch(self, path_service_instance, temp_storage):
        """Test document path with batch grouping."""
        doc_path = path_service_instance.get_document_path(
            document_id="doc-123",
            organization_id="org-456",
            batch_id="batch-789",
            file_type="uploaded",
            filename="test.pdf",
            create_dirs=True,
        )

        # Verify path structure
        assert "organizations/org-456/batches/batch-789/uploaded" in str(doc_path)
        assert "doc-123_test.pdf" in str(doc_path)

        # Verify directories were created
        assert doc_path.parent.exists()

    def test_get_document_path_adhoc(self, path_service_instance, temp_storage):
        """Test document path for adhoc (non-batch) files."""
        doc_path = path_service_instance.get_document_path(
            document_id="doc-abc",
            organization_id="org-456",
            batch_id=None,
            file_type="processed",
            filename="output.md",
            create_dirs=True,
        )

        # Verify adhoc path structure
        assert "organizations/org-456/adhoc/processed" in str(doc_path)
        assert "doc-abc_output.md" in str(doc_path)

    def test_sanitize_filename(self, path_service_instance):
        """Test filename sanitization."""
        # Test special characters
        safe = path_service_instance.sanitize_filename("My Document (1).pdf")
        assert safe == "My_Document_1.pdf"

        # Test path traversal
        safe = path_service_instance.sanitize_filename("../../../etc/passwd")
        assert safe == "etc_passwd"

        # Test colons and other unsafe chars
        safe = path_service_instance.sanitize_filename("file:with:colons.txt")
        assert safe == "filewithcolons.txt"


class TestDeduplicationService:
    """Test file deduplication with content hashing."""

    @pytest.mark.asyncio
    async def test_calculate_file_hash(self, dedupe_service_instance, temp_storage):
        """Test SHA-256 hash calculation."""
        # Create test file
        test_file = temp_storage / "test.txt"
        test_file.write_text("Hello, World!")

        # Calculate hash
        hash_value = await dedupe_service_instance.calculate_file_hash(test_file)

        # Verify hash format (SHA-256 = 64 hex chars)
        assert len(hash_value) == 64
        assert all(c in "0123456789abcdef" for c in hash_value)

    @pytest.mark.asyncio
    async def test_store_and_find_duplicate(self, dedupe_service_instance, temp_storage):
        """Test storing file and finding duplicates."""
        # Create test file
        test_file = temp_storage / "original.pdf"
        test_file.write_text("Test content for deduplication")

        # Calculate hash
        hash_value = await dedupe_service_instance.calculate_file_hash(test_file)

        # Store deduplicated file
        content_path = await dedupe_service_instance.store_deduplicated_file(
            file_path=test_file,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id="org-123",
            original_filename="original.pdf",
        )

        # Verify file was stored
        assert content_path.exists()
        assert "dedupe" in str(content_path)

        # Try to find duplicate
        existing = await dedupe_service_instance.find_duplicate_by_hash(hash_value)
        assert existing is not None
        assert existing == content_path

    @pytest.mark.asyncio
    async def test_reference_counting(self, dedupe_service_instance, temp_storage):
        """Test reference counting for deduplicated files."""
        # Create and store initial file
        test_file = temp_storage / "doc.pdf"
        test_file.write_text("Shared content")

        hash_value = await dedupe_service_instance.calculate_file_hash(test_file)

        # Store first reference
        await dedupe_service_instance.store_deduplicated_file(
            file_path=test_file,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id="org-123",
            original_filename="doc.pdf",
        )

        # Add second reference
        await dedupe_service_instance.add_reference(
            hash_value=hash_value,
            document_id="doc-2",
            organization_id="org-123",
        )

        # Check references
        refs = await dedupe_service_instance.get_file_references(hash_value)
        assert refs is not None
        assert refs["reference_count"] == 2
        assert len(refs["references"]) == 2

        # Remove first reference
        should_delete = await dedupe_service_instance.remove_reference(hash_value, "doc-1")
        assert not should_delete  # Still has 1 reference

        # Check updated count
        refs = await dedupe_service_instance.get_file_references(hash_value)
        assert refs["reference_count"] == 1

        # Remove last reference
        should_delete = await dedupe_service_instance.remove_reference(hash_value, "doc-2")
        assert should_delete  # No more references

    @pytest.mark.asyncio
    async def test_deduplication_stats(self, dedupe_service_instance, temp_storage):
        """Test deduplication statistics calculation."""
        # Create identical files
        content = "Test content for stats"
        file1 = temp_storage / "file1.txt"
        file2 = temp_storage / "file2.txt"
        file1.write_text(content)
        file2.write_text(content)

        # Store both (should detect as duplicate)
        hash_value = await dedupe_service_instance.calculate_file_hash(file1)

        await dedupe_service_instance.store_deduplicated_file(
            file_path=file1,
            hash_value=hash_value,
            document_id="doc-a",
            organization_id="org-123",
        )

        await dedupe_service_instance.add_reference(
            hash_value=hash_value,
            document_id="doc-b",
            organization_id="org-123",
        )

        # Get stats
        stats = await dedupe_service_instance.get_deduplication_stats("org-123")

        # Verify stats
        assert stats["unique_files"] >= 1
        assert stats["total_references"] >= 2
        assert stats["duplicate_references"] >= 1
        assert stats["storage_saved_bytes"] > 0


class TestMetadataService:
    """Test batch metadata management."""

    def test_create_batch_metadata(self, metadata_service_instance):
        """Test batch metadata creation."""
        metadata = metadata_service_instance.create_batch_metadata(
            batch_id="batch-123",
            organization_id="org-456",
            created_by="user-789",
            documents=[
                {
                    "document_id": "doc-1",
                    "filename": "file1.pdf",
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        )

        # Verify metadata structure
        assert metadata["batch_id"] == "batch-123"
        assert metadata["organization_id"] == "org-456"
        assert metadata["document_count"] == 1
        assert "created_at" in metadata
        assert "expires_at" in metadata

    def test_get_batch_metadata(self, metadata_service_instance):
        """Test retrieving batch metadata."""
        # Create metadata
        metadata_service_instance.create_batch_metadata(
            batch_id="batch-456",
            organization_id="org-789",
        )

        # Retrieve metadata
        retrieved = metadata_service_instance.get_batch_metadata(
            batch_id="batch-456",
            organization_id="org-789",
        )

        assert retrieved is not None
        assert retrieved["batch_id"] == "batch-456"

    def test_update_batch_metadata(self, metadata_service_instance):
        """Test updating batch metadata."""
        # Create metadata
        metadata_service_instance.create_batch_metadata(
            batch_id="batch-789",
            organization_id="org-123",
        )

        # Update metadata
        updated = metadata_service_instance.update_batch_metadata(
            batch_id="batch-789",
            organization_id="org-123",
            updates={"status": "completed", "document_count": 5},
        )

        assert updated is not None
        assert updated["status"] == "completed"
        assert updated["document_count"] == 5


class TestIntegrationScenarios:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_complete_upload_workflow(
        self,
        path_service_instance,
        dedupe_service_instance,
        metadata_service_instance,
        temp_storage,
    ):
        """Test complete file upload with deduplication."""
        # Setup
        org_id = "org-integration"
        batch_id = "batch-integration"
        doc_id = "doc-integration"

        # Create test file
        test_content = "Integration test content"
        temp_file = temp_storage / "upload.pdf"
        temp_file.write_text(test_content)

        # Calculate hash
        file_hash = await dedupe_service_instance.calculate_file_hash(temp_file)

        # Get document path
        doc_path = path_service_instance.get_document_path(
            document_id=doc_id,
            organization_id=org_id,
            batch_id=batch_id,
            file_type="uploaded",
            filename="upload.pdf",
            create_dirs=True,
        )

        # Store in dedupe storage
        content_path = await dedupe_service_instance.store_deduplicated_file(
            file_path=temp_file,
            hash_value=file_hash,
            document_id=doc_id,
            organization_id=org_id,
            original_filename="upload.pdf",
        )

        # Create symlink to deduplicated content
        await dedupe_service_instance.create_reference_link(
            content_path=content_path,
            target_path=doc_path,
        )

        # Create batch metadata
        metadata = metadata_service_instance.create_batch_metadata(
            batch_id=batch_id,
            organization_id=org_id,
            documents=[
                {
                    "document_id": doc_id,
                    "filename": "upload.pdf",
                    "file_hash": file_hash,
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        )

        # Verify everything worked
        assert doc_path.exists() or doc_path.is_symlink()
        assert content_path.exists()
        assert metadata["document_count"] == 1

        # Verify deduplication reference
        refs = await dedupe_service_instance.get_file_references(file_hash)
        assert refs["reference_count"] == 1
        assert refs["references"][0]["document_id"] == doc_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
