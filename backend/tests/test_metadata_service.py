"""
Unit tests for MetadataService.

Tests batch metadata creation, retrieval, updates, and expiration tracking.
"""

import pytest
import tempfile
import shutil
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from app.services.metadata_service import MetadataService
from app.services.path_service import PathService
from app.config import settings


@pytest.fixture
def temp_storage():
    """Create temporary storage directory for tests."""
    temp_dir = tempfile.mkdtemp()

    # Override settings for testing
    original_files_root = settings.files_root

    settings.files_root = temp_dir

    yield Path(temp_dir)

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)
    settings.files_root = original_files_root


@pytest.fixture
def metadata_service(temp_storage):
    """Create MetadataService instance with temp storage."""
    return MetadataService()


@pytest.fixture
def path_service(temp_storage):
    """Create PathService instance with temp storage."""
    return PathService()


class TestMetadataServiceInitialization:
    """Test MetadataService initialization."""

    def test_initialization(self, metadata_service):
        """Test service initializes correctly."""
        assert metadata_service.path_service is not None
        assert hasattr(metadata_service, 'default_retention_days')

    def test_default_retention_period(self, metadata_service):
        """Test default retention period is set."""
        assert metadata_service.default_retention_days > 0


class TestBatchMetadataCreation:
    """Test batch metadata creation."""

    def test_create_minimal_metadata(self, metadata_service, path_service):
        """Test creating metadata with minimal parameters."""
        metadata = metadata_service.create_batch_metadata(
            batch_id="batch-123",
            organization_id="org-456",
        )

        assert metadata["batch_id"] == "batch-123"
        assert metadata["organization_id"] == "org-456"
        assert "created_at" in metadata
        assert "expires_at" in metadata
        assert metadata["document_count"] == 0
        assert isinstance(metadata["documents"], list)

    def test_create_metadata_with_user(self, metadata_service):
        """Test creating metadata with created_by user."""
        metadata = metadata_service.create_batch_metadata(
            batch_id="batch-789",
            organization_id="org-123",
            created_by="user-456",
        )

        assert metadata["created_by"] == "user-456"

    def test_create_metadata_with_documents(self, metadata_service):
        """Test creating metadata with document list."""
        docs = [
            {
                "document_id": "doc-1",
                "filename": "file1.pdf",
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "document_id": "doc-2",
                "filename": "file2.pdf",
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            },
        ]

        metadata = metadata_service.create_batch_metadata(
            batch_id="batch-abc",
            organization_id="org-xyz",
            documents=docs,
        )

        assert metadata["document_count"] == 2
        assert len(metadata["documents"]) == 2
        assert metadata["documents"][0]["document_id"] == "doc-1"

    def test_create_metadata_expiration_calculation(self, metadata_service):
        """Test that expiration date is calculated correctly."""
        metadata = metadata_service.create_batch_metadata(
            batch_id="batch-exp",
            organization_id="org-exp",
        )

        created_at = datetime.fromisoformat(metadata["created_at"].replace('Z', '+00:00'))
        expires_at = datetime.fromisoformat(metadata["expires_at"].replace('Z', '+00:00'))

        # Should be approximately retention_days in the future
        time_diff = expires_at - created_at
        expected_days = metadata_service.default_retention_days
        assert abs(time_diff.days - expected_days) <= 1

    def test_create_metadata_writes_to_disk(self, metadata_service, path_service, temp_storage):
        """Test that metadata is written to disk."""
        batch_id = "batch-disk"
        org_id = "org-disk"

        metadata = metadata_service.create_batch_metadata(
            batch_id=batch_id,
            organization_id=org_id,
        )

        # Get expected metadata path
        org_path = path_service.resolve_organization_path(org_id)
        batch_path = path_service.resolve_batch_path(org_path, batch_id)
        metadata_path = batch_path / "metadata.json"

        assert metadata_path.exists()

        # Verify content
        with open(metadata_path, 'r') as f:
            saved_metadata = json.load(f)

        assert saved_metadata["batch_id"] == batch_id


class TestBatchMetadataRetrieval:
    """Test batch metadata retrieval."""

    def test_get_existing_metadata(self, metadata_service):
        """Test retrieving existing metadata."""
        # Create metadata first
        metadata_service.create_batch_metadata(
            batch_id="batch-get",
            organization_id="org-get",
        )

        # Retrieve it
        retrieved = metadata_service.get_batch_metadata(
            batch_id="batch-get",
            organization_id="org-get",
        )

        assert retrieved is not None
        assert retrieved["batch_id"] == "batch-get"

    def test_get_nonexistent_metadata(self, metadata_service):
        """Test retrieving non-existent metadata."""
        retrieved = metadata_service.get_batch_metadata(
            batch_id="nonexistent",
            organization_id="org-none",
        )

        assert retrieved is None

    def test_get_metadata_shared_organization(self, metadata_service):
        """Test retrieving metadata for shared (no org)."""
        # Create metadata with no org
        metadata_service.create_batch_metadata(
            batch_id="batch-shared",
            organization_id=None,
        )

        # Retrieve it
        retrieved = metadata_service.get_batch_metadata(
            batch_id="batch-shared",
            organization_id=None,
        )

        assert retrieved is not None
        assert retrieved["batch_id"] == "batch-shared"


class TestBatchMetadataUpdate:
    """Test batch metadata updates."""

    def test_update_existing_metadata(self, metadata_service):
        """Test updating existing metadata."""
        # Create metadata
        metadata_service.create_batch_metadata(
            batch_id="batch-update",
            organization_id="org-update",
        )

        # Update it
        updated = metadata_service.update_batch_metadata(
            batch_id="batch-update",
            organization_id="org-update",
            updates={"status": "completed", "document_count": 5},
        )

        assert updated is not None
        assert updated["status"] == "completed"
        assert updated["document_count"] == 5
        assert "updated_at" in updated

    def test_update_nonexistent_metadata(self, metadata_service):
        """Test updating non-existent metadata."""
        updated = metadata_service.update_batch_metadata(
            batch_id="nonexistent",
            organization_id="org-none",
            updates={"status": "completed"},
        )

        assert updated is None

    def test_update_preserves_existing_fields(self, metadata_service):
        """Test that update preserves existing fields."""
        # Create metadata
        original = metadata_service.create_batch_metadata(
            batch_id="batch-preserve",
            organization_id="org-preserve",
            created_by="user-123",
        )

        original_created_at = original["created_at"]
        original_created_by = original["created_by"]

        # Update with new field
        updated = metadata_service.update_batch_metadata(
            batch_id="batch-preserve",
            organization_id="org-preserve",
            updates={"status": "completed"},
        )

        assert updated["created_at"] == original_created_at
        assert updated["created_by"] == original_created_by
        assert updated["status"] == "completed"

    def test_update_writes_to_disk(self, metadata_service, path_service):
        """Test that updates are written to disk."""
        batch_id = "batch-write"
        org_id = "org-write"

        # Create metadata
        metadata_service.create_batch_metadata(
            batch_id=batch_id,
            organization_id=org_id,
        )

        # Update it
        metadata_service.update_batch_metadata(
            batch_id=batch_id,
            organization_id=org_id,
            updates={"status": "processing"},
        )

        # Read from disk directly
        org_path = path_service.resolve_organization_path(org_id)
        batch_path = path_service.resolve_batch_path(org_path, batch_id)
        metadata_path = batch_path / "metadata.json"

        with open(metadata_path, 'r') as f:
            saved_metadata = json.load(f)

        assert saved_metadata["status"] == "processing"


class TestBatchMetadataDeletion:
    """Test batch metadata deletion."""

    def test_delete_existing_metadata(self, metadata_service):
        """Test deleting existing metadata."""
        # Create metadata
        metadata_service.create_batch_metadata(
            batch_id="batch-delete",
            organization_id="org-delete",
        )

        # Delete it
        success = metadata_service.delete_batch_metadata(
            batch_id="batch-delete",
            organization_id="org-delete",
        )

        assert success is True

        # Verify it's gone
        retrieved = metadata_service.get_batch_metadata(
            batch_id="batch-delete",
            organization_id="org-delete",
        )
        assert retrieved is None

    def test_delete_nonexistent_metadata(self, metadata_service):
        """Test deleting non-existent metadata."""
        success = metadata_service.delete_batch_metadata(
            batch_id="nonexistent",
            organization_id="org-none",
        )

        assert success is False

    def test_delete_removes_file_from_disk(self, metadata_service, path_service):
        """Test that deletion removes file from disk."""
        batch_id = "batch-remove"
        org_id = "org-remove"

        # Create metadata
        metadata_service.create_batch_metadata(
            batch_id=batch_id,
            organization_id=org_id,
        )

        # Get metadata path
        org_path = path_service.resolve_organization_path(org_id)
        batch_path = path_service.resolve_batch_path(org_path, batch_id)
        metadata_path = batch_path / "metadata.json"

        assert metadata_path.exists()

        # Delete metadata
        metadata_service.delete_batch_metadata(
            batch_id=batch_id,
            organization_id=org_id,
        )

        assert not metadata_path.exists()


class TestBatchListing:
    """Test listing batches."""

    def test_list_batches_for_organization(self, metadata_service):
        """Test listing all batches for an organization."""
        org_id = "org-list"

        # Create multiple batches
        for i in range(3):
            metadata_service.create_batch_metadata(
                batch_id=f"batch-{i}",
                organization_id=org_id,
            )

        # List batches
        batches = metadata_service.list_batches(organization_id=org_id)

        assert len(batches) >= 3
        batch_ids = [b["batch_id"] for b in batches]
        assert "batch-0" in batch_ids
        assert "batch-1" in batch_ids
        assert "batch-2" in batch_ids

    def test_list_batches_empty_organization(self, metadata_service):
        """Test listing batches for organization with no batches."""
        batches = metadata_service.list_batches(organization_id="org-empty")

        assert isinstance(batches, list)
        assert len(batches) == 0


class TestExpirationChecking:
    """Test expiration checking."""

    def test_is_expired_past_expiration(self, metadata_service):
        """Test that expired metadata is detected."""
        # Create metadata with past expiration
        metadata = metadata_service.create_batch_metadata(
            batch_id="batch-expired",
            organization_id="org-expired",
        )

        # Manually set expiration to the past
        past_date = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        metadata_service.update_batch_metadata(
            batch_id="batch-expired",
            organization_id="org-expired",
            updates={"expires_at": past_date},
        )

        # Check expiration
        is_expired = metadata_service.is_batch_expired(
            batch_id="batch-expired",
            organization_id="org-expired",
        )

        assert is_expired is True

    def test_is_expired_future_expiration(self, metadata_service):
        """Test that non-expired metadata is detected."""
        # Create metadata (default expiration is in the future)
        metadata_service.create_batch_metadata(
            batch_id="batch-future",
            organization_id="org-future",
        )

        # Check expiration
        is_expired = metadata_service.is_batch_expired(
            batch_id="batch-future",
            organization_id="org-future",
        )

        assert is_expired is False

    def test_is_expired_nonexistent_batch(self, metadata_service):
        """Test expiration check for non-existent batch."""
        is_expired = metadata_service.is_batch_expired(
            batch_id="nonexistent",
            organization_id="org-none",
        )

        # Should return False or None for non-existent
        assert is_expired is False or is_expired is None

    def test_list_expired_batches(self, metadata_service):
        """Test listing all expired batches."""
        org_id = "org-expired-list"

        # Create expired batch
        metadata_service.create_batch_metadata(
            batch_id="batch-expired-1",
            organization_id=org_id,
        )
        past_date = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        metadata_service.update_batch_metadata(
            batch_id="batch-expired-1",
            organization_id=org_id,
            updates={"expires_at": past_date},
        )

        # Create non-expired batch
        metadata_service.create_batch_metadata(
            batch_id="batch-active-1",
            organization_id=org_id,
        )

        # List expired batches
        expired = metadata_service.list_expired_batches(organization_id=org_id)

        expired_ids = [b["batch_id"] for b in expired]
        assert "batch-expired-1" in expired_ids
        assert "batch-active-1" not in expired_ids


class TestErrorHandling:
    """Test error handling."""

    def test_corrupt_metadata_file(self, metadata_service, path_service, temp_storage):
        """Test handling of corrupt metadata file."""
        batch_id = "batch-corrupt"
        org_id = "org-corrupt"

        # Create valid metadata first
        metadata_service.create_batch_metadata(
            batch_id=batch_id,
            organization_id=org_id,
        )

        # Corrupt the file
        org_path = path_service.resolve_organization_path(org_id)
        batch_path = path_service.resolve_batch_path(org_path, batch_id)
        metadata_path = batch_path / "metadata.json"

        with open(metadata_path, 'w') as f:
            f.write("invalid json {{{")

        # Try to retrieve - should handle gracefully
        retrieved = metadata_service.get_batch_metadata(
            batch_id=batch_id,
            organization_id=org_id,
        )

        assert retrieved is None or isinstance(retrieved, dict)

    def test_missing_directory(self, metadata_service):
        """Test handling when batch directory doesn't exist."""
        retrieved = metadata_service.get_batch_metadata(
            batch_id="batch-nodir",
            organization_id="org-nodir",
        )

        assert retrieved is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
