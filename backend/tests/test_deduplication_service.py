"""
Unit tests for DeduplicationService.

Tests file hashing, deduplication, reference counting, and storage management.
"""

import pytest
import tempfile
import shutil
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.deduplication_service import DeduplicationService
from app.services.path_service import PathService
from app.config import settings


@pytest.fixture
def temp_storage():
    """Create temporary storage directory for tests."""
    temp_dir = tempfile.mkdtemp()

    # Override settings for testing
    original_files_root = settings.files_root
    original_dedupe_dir = settings.dedupe_dir

    settings.files_root = temp_dir
    settings.dedupe_dir = str(Path(temp_dir) / "dedupe")

    yield Path(temp_dir)

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)
    settings.files_root = original_files_root
    settings.dedupe_dir = original_dedupe_dir


@pytest.fixture
def dedupe_service(temp_storage):
    """Create DeduplicationService instance with temp storage."""
    return DeduplicationService()


@pytest.fixture
def path_service(temp_storage):
    """Create PathService instance with temp storage."""
    return PathService()


class TestDeduplicationServiceInitialization:
    """Test DeduplicationService initialization."""

    def test_initialization(self, dedupe_service):
        """Test service initializes correctly."""
        assert dedupe_service.path_service is not None
        assert dedupe_service.enabled is not None
        assert dedupe_service.strategy is not None
        assert dedupe_service.hash_algorithm is not None

    def test_default_configuration(self, dedupe_service):
        """Test default configuration values."""
        assert dedupe_service.hash_algorithm in ["sha256", "md5", "sha1"]
        assert dedupe_service.strategy in ["symlink", "hardlink", "copy"]


class TestFileHashCalculation:
    """Test file hash calculation."""

    @pytest.mark.asyncio
    async def test_calculate_hash_small_file(self, dedupe_service, temp_storage):
        """Test hash calculation for small file."""
        # Create test file
        test_file = temp_storage / "small.txt"
        test_file.write_text("Hello, World!")

        # Calculate hash
        hash_value = await dedupe_service.calculate_file_hash(test_file)

        # Verify hash format (SHA-256 = 64 hex chars)
        assert len(hash_value) == 64
        assert all(c in "0123456789abcdef" for c in hash_value)

    @pytest.mark.asyncio
    async def test_calculate_hash_large_file(self, dedupe_service, temp_storage):
        """Test hash calculation for large file (streaming)."""
        # Create large test file (1 MB)
        test_file = temp_storage / "large.bin"
        test_file.write_bytes(b"x" * (1024 * 1024))

        # Calculate hash
        hash_value = await dedupe_service.calculate_file_hash(test_file)

        assert len(hash_value) == 64
        assert all(c in "0123456789abcdef" for c in hash_value)

    @pytest.mark.asyncio
    async def test_calculate_hash_empty_file(self, dedupe_service, temp_storage):
        """Test hash calculation for empty file."""
        test_file = temp_storage / "empty.txt"
        test_file.write_text("")

        hash_value = await dedupe_service.calculate_file_hash(test_file)

        # Should still return valid hash
        assert len(hash_value) == 64

    @pytest.mark.asyncio
    async def test_calculate_hash_identical_content(self, dedupe_service, temp_storage):
        """Test that identical content produces identical hash."""
        content = "Test content for hashing"

        file1 = temp_storage / "file1.txt"
        file2 = temp_storage / "file2.txt"

        file1.write_text(content)
        file2.write_text(content)

        hash1 = await dedupe_service.calculate_file_hash(file1)
        hash2 = await dedupe_service.calculate_file_hash(file2)

        assert hash1 == hash2

    @pytest.mark.asyncio
    async def test_calculate_hash_different_content(self, dedupe_service, temp_storage):
        """Test that different content produces different hash."""
        file1 = temp_storage / "file1.txt"
        file2 = temp_storage / "file2.txt"

        file1.write_text("Content A")
        file2.write_text("Content B")

        hash1 = await dedupe_service.calculate_file_hash(file1)
        hash2 = await dedupe_service.calculate_file_hash(file2)

        assert hash1 != hash2

    @pytest.mark.asyncio
    async def test_calculate_hash_nonexistent_file(self, dedupe_service, temp_storage):
        """Test hash calculation for non-existent file."""
        nonexistent = temp_storage / "nonexistent.txt"

        with pytest.raises(FileNotFoundError):
            await dedupe_service.calculate_file_hash(nonexistent)

    @pytest.mark.asyncio
    async def test_calculate_hash_with_different_algorithm(self, dedupe_service, temp_storage):
        """Test hash calculation with different algorithm."""
        test_file = temp_storage / "test.txt"
        test_file.write_text("Test content")

        # Calculate with MD5
        hash_md5 = await dedupe_service.calculate_file_hash(test_file, algorithm="md5")
        assert len(hash_md5) == 32  # MD5 = 32 hex chars

        # Calculate with SHA-256
        hash_sha256 = await dedupe_service.calculate_file_hash(test_file, algorithm="sha256")
        assert len(hash_sha256) == 64  # SHA-256 = 64 hex chars


class TestDeduplicatedFileStorage:
    """Test storing deduplicated files."""

    @pytest.mark.asyncio
    async def test_store_new_file(self, dedupe_service, temp_storage):
        """Test storing a new file in dedupe storage."""
        # Create test file
        test_file = temp_storage / "original.pdf"
        test_file.write_text("Test content for deduplication")

        # Calculate hash
        hash_value = await dedupe_service.calculate_file_hash(test_file)

        # Store file
        content_path = await dedupe_service.store_deduplicated_file(
            file_path=test_file,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id="org-123",
            original_filename="original.pdf",
        )

        # Verify storage
        assert content_path.exists()
        assert "dedupe" in str(content_path)
        assert content_path.read_text() == "Test content for deduplication"

    @pytest.mark.asyncio
    async def test_store_creates_references_file(self, dedupe_service, temp_storage):
        """Test that storing creates references.json file."""
        test_file = temp_storage / "test.pdf"
        test_file.write_text("Test content")

        hash_value = await dedupe_service.calculate_file_hash(test_file)

        content_path = await dedupe_service.store_deduplicated_file(
            file_path=test_file,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id="org-123",
        )

        # Check for references file
        refs_path = content_path.parent / "refs.json"
        assert refs_path.exists()

        # Verify content
        with open(refs_path, 'r') as f:
            refs_data = json.load(f)

        assert refs_data["reference_count"] == 1
        assert len(refs_data["references"]) == 1
        assert refs_data["references"][0]["document_id"] == "doc-1"

    @pytest.mark.asyncio
    async def test_store_preserves_file_extension(self, dedupe_service, temp_storage):
        """Test that file extension is preserved in dedupe storage."""
        test_file = temp_storage / "document.pdf"
        test_file.write_text("PDF content")

        hash_value = await dedupe_service.calculate_file_hash(test_file)

        content_path = await dedupe_service.store_deduplicated_file(
            file_path=test_file,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id="org-123",
            original_filename="document.pdf",
        )

        assert content_path.suffix == ".pdf"

    @pytest.mark.asyncio
    async def test_store_duplicate_file(self, dedupe_service, temp_storage):
        """Test storing an already existing deduplicated file."""
        test_file = temp_storage / "test.txt"
        test_file.write_text("Shared content")

        hash_value = await dedupe_service.calculate_file_hash(test_file)

        # Store first time
        content_path1 = await dedupe_service.store_deduplicated_file(
            file_path=test_file,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id="org-123",
        )

        # Store second time (should skip actual storage)
        content_path2 = await dedupe_service.store_deduplicated_file(
            file_path=test_file,
            hash_value=hash_value,
            document_id="doc-2",
            organization_id="org-123",
        )

        # Both should point to same content
        assert content_path1 == content_path2
        assert content_path1.exists()


class TestDuplicateDetection:
    """Test duplicate file detection."""

    @pytest.mark.asyncio
    async def test_find_duplicate_by_hash_existing(self, dedupe_service, temp_storage):
        """Test finding existing duplicate by hash."""
        test_file = temp_storage / "test.txt"
        test_file.write_text("Test content")

        hash_value = await dedupe_service.calculate_file_hash(test_file)

        # Store file
        await dedupe_service.store_deduplicated_file(
            file_path=test_file,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id="org-123",
        )

        # Find duplicate
        existing = await dedupe_service.find_duplicate_by_hash(hash_value)

        assert existing is not None
        assert existing.exists()

    @pytest.mark.asyncio
    async def test_find_duplicate_by_hash_nonexistent(self, dedupe_service):
        """Test finding non-existent duplicate."""
        fake_hash = "0" * 64

        existing = await dedupe_service.find_duplicate_by_hash(fake_hash)

        assert existing is None


class TestReferenceManagement:
    """Test reference counting and management."""

    @pytest.mark.asyncio
    async def test_add_reference(self, dedupe_service, temp_storage):
        """Test adding a reference to existing deduplicated file."""
        test_file = temp_storage / "shared.txt"
        test_file.write_text("Shared content")

        hash_value = await dedupe_service.calculate_file_hash(test_file)

        # Store initial file
        await dedupe_service.store_deduplicated_file(
            file_path=test_file,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id="org-123",
        )

        # Add second reference
        content_path = await dedupe_service.add_reference(
            hash_value=hash_value,
            document_id="doc-2",
            organization_id="org-123",
        )

        assert content_path is not None

        # Check reference count
        refs = await dedupe_service.get_file_references(hash_value)
        assert refs["reference_count"] == 2
        assert len(refs["references"]) == 2

    @pytest.mark.asyncio
    async def test_remove_reference_with_remaining(self, dedupe_service, temp_storage):
        """Test removing reference when others remain."""
        test_file = temp_storage / "test.txt"
        test_file.write_text("Test")

        hash_value = await dedupe_service.calculate_file_hash(test_file)

        # Store with 2 references
        await dedupe_service.store_deduplicated_file(
            file_path=test_file,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id="org-123",
        )
        await dedupe_service.add_reference(
            hash_value=hash_value,
            document_id="doc-2",
            organization_id="org-123",
        )

        # Remove first reference
        should_delete = await dedupe_service.remove_reference(hash_value, "doc-1")

        assert should_delete is False  # Still has 1 reference

        # Verify reference count
        refs = await dedupe_service.get_file_references(hash_value)
        assert refs["reference_count"] == 1

    @pytest.mark.asyncio
    async def test_remove_last_reference(self, dedupe_service, temp_storage):
        """Test removing the last reference."""
        test_file = temp_storage / "test.txt"
        test_file.write_text("Test")

        hash_value = await dedupe_service.calculate_file_hash(test_file)

        # Store with 1 reference
        await dedupe_service.store_deduplicated_file(
            file_path=test_file,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id="org-123",
        )

        # Remove last reference
        should_delete = await dedupe_service.remove_reference(hash_value, "doc-1")

        assert should_delete is True  # No more references

    @pytest.mark.asyncio
    async def test_get_file_references(self, dedupe_service, temp_storage):
        """Test getting file reference information."""
        test_file = temp_storage / "test.txt"
        test_file.write_text("Test")

        hash_value = await dedupe_service.calculate_file_hash(test_file)

        # Store file
        await dedupe_service.store_deduplicated_file(
            file_path=test_file,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id="org-123",
            original_filename="test.txt",
        )

        # Get references
        refs = await dedupe_service.get_file_references(hash_value)

        assert refs is not None
        assert refs["hash"] == hash_value
        assert refs["reference_count"] == 1
        assert refs["references"][0]["document_id"] == "doc-1"
        assert refs["references"][0]["organization_id"] == "org-123"
        assert "added_at" in refs["references"][0]

    @pytest.mark.asyncio
    async def test_get_references_nonexistent(self, dedupe_service):
        """Test getting references for non-existent file."""
        fake_hash = "1" * 64

        refs = await dedupe_service.get_file_references(fake_hash)

        assert refs is None


class TestSymlinkCreation:
    """Test symlink/reference link creation."""

    @pytest.mark.asyncio
    async def test_create_symlink(self, dedupe_service, temp_storage):
        """Test creating symlink to deduplicated content."""
        # Create content file
        content_path = temp_storage / "content" / "file.txt"
        content_path.parent.mkdir(parents=True, exist_ok=True)
        content_path.write_text("Content")

        # Create symlink
        target_path = temp_storage / "link" / "file.txt"
        target_path.parent.mkdir(parents=True, exist_ok=True)

        await dedupe_service.create_reference_link(
            content_path=content_path,
            target_path=target_path,
        )

        # Verify link
        assert target_path.exists() or target_path.is_symlink()

    @pytest.mark.asyncio
    async def test_create_symlink_replaces_existing(self, dedupe_service, temp_storage):
        """Test that creating symlink replaces existing file."""
        content_path = temp_storage / "content.txt"
        content_path.write_text("New content")

        target_path = temp_storage / "target.txt"
        target_path.write_text("Old content")

        # Create symlink (should replace old file)
        await dedupe_service.create_reference_link(
            content_path=content_path,
            target_path=target_path,
        )

        # Verify it points to new content
        assert target_path.exists()


class TestDeduplicationStatistics:
    """Test deduplication statistics."""

    @pytest.mark.asyncio
    async def test_get_stats_with_duplicates(self, dedupe_service, temp_storage):
        """Test getting deduplication stats."""
        content = "Shared content"
        file1 = temp_storage / "file1.txt"
        file2 = temp_storage / "file2.txt"

        file1.write_text(content)
        file2.write_text(content)

        hash_value = await dedupe_service.calculate_file_hash(file1)

        # Store both as duplicates
        await dedupe_service.store_deduplicated_file(
            file_path=file1,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id="org-123",
        )
        await dedupe_service.add_reference(
            hash_value=hash_value,
            document_id="doc-2",
            organization_id="org-123",
        )

        # Get stats
        stats = await dedupe_service.get_deduplication_stats("org-123")

        assert stats["unique_files"] >= 1
        assert stats["total_references"] >= 2
        assert stats["duplicate_references"] >= 1
        assert stats["storage_saved_bytes"] > 0

    @pytest.mark.asyncio
    async def test_get_stats_no_duplicates(self, dedupe_service):
        """Test stats when no duplicates exist."""
        stats = await dedupe_service.get_deduplication_stats("org-empty")

        assert stats["unique_files"] == 0
        assert stats["total_references"] == 0
        assert stats["duplicate_references"] == 0
        assert stats["storage_saved_bytes"] == 0

    @pytest.mark.asyncio
    async def test_list_all_duplicates(self, dedupe_service, temp_storage):
        """Test listing all files with duplicates."""
        content = "Duplicate content"
        file1 = temp_storage / "dup1.txt"
        file1.write_text(content)

        hash_value = await dedupe_service.calculate_file_hash(file1)

        # Store with multiple references
        await dedupe_service.store_deduplicated_file(
            file_path=file1,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id="org-123",
        )
        await dedupe_service.add_reference(
            hash_value=hash_value,
            document_id="doc-2",
            organization_id="org-123",
        )

        # List duplicates
        duplicates = await dedupe_service.list_all_duplicates("org-123")

        assert len(duplicates) >= 1
        # Find our duplicate
        found = False
        for dup in duplicates:
            if dup["hash"] == hash_value:
                assert dup["reference_count"] >= 2
                found = True
        assert found


class TestErrorHandling:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_store_with_missing_file(self, dedupe_service, temp_storage):
        """Test storing with non-existent source file."""
        nonexistent = temp_storage / "missing.txt"
        fake_hash = "0" * 64

        with pytest.raises(FileNotFoundError):
            await dedupe_service.store_deduplicated_file(
                file_path=nonexistent,
                hash_value=fake_hash,
                document_id="doc-1",
                organization_id="org-123",
            )

    @pytest.mark.asyncio
    async def test_remove_reference_nonexistent_file(self, dedupe_service):
        """Test removing reference from non-existent file."""
        fake_hash = "9" * 64

        # Should handle gracefully
        should_delete = await dedupe_service.remove_reference(fake_hash, "doc-1")

        # Could return False or True depending on implementation
        assert should_delete is not None

    @pytest.mark.asyncio
    async def test_corrupt_references_file(self, dedupe_service, temp_storage, path_service):
        """Test handling corrupt references file."""
        test_file = temp_storage / "test.txt"
        test_file.write_text("Test")

        hash_value = await dedupe_service.calculate_file_hash(test_file)

        # Store file
        content_path = await dedupe_service.store_deduplicated_file(
            file_path=test_file,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id="org-123",
        )

        # Corrupt references file
        refs_path = content_path.parent / "refs.json"
        refs_path.write_text("invalid json {{{")

        # Try to get references - should handle gracefully
        try:
            refs = await dedupe_service.get_file_references(hash_value)
            # Should either return None or handle error
            assert refs is None or isinstance(refs, dict)
        except json.JSONDecodeError:
            pass  # Acceptable behavior


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
