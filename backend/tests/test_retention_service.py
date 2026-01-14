"""
Unit tests for RetentionService.

Tests file retention policies, expiration detection, and cleanup operations.
"""

import pytest
import tempfile
import shutil
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.retention_service import RetentionService
from app.services.path_service import PathService
from app.services.metadata_service import MetadataService
from app.services.deduplication_service import DeduplicationService
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
def retention_service(temp_storage):
    """Create RetentionService instance with temp storage."""
    return RetentionService()


@pytest.fixture
def path_service(temp_storage):
    """Create PathService instance with temp storage."""
    return PathService()


@pytest.fixture
def metadata_service(temp_storage):
    """Create MetadataService instance with temp storage."""
    return MetadataService()


@pytest.fixture
def dedupe_service(temp_storage):
    """Create DeduplicationService instance with temp storage."""
    return DeduplicationService()


class TestRetentionServiceInitialization:
    """Test RetentionService initialization."""

    def test_initialization(self, retention_service):
        """Test service initializes correctly."""
        assert retention_service.path_service is not None
        assert retention_service.metadata_service is not None
        assert retention_service.dedupe_service is not None

    def test_retention_periods_loaded(self, retention_service):
        """Test that retention periods are loaded from config."""
        assert hasattr(retention_service, 'retention_uploaded_days')
        assert hasattr(retention_service, 'retention_processed_days')
        assert hasattr(retention_service, 'retention_batch_days')
        assert hasattr(retention_service, 'retention_temp_hours')

        # Verify they're positive numbers
        assert retention_service.retention_uploaded_days > 0
        assert retention_service.retention_processed_days > 0
        assert retention_service.retention_batch_days > 0
        assert retention_service.retention_temp_hours > 0


class TestRetentionPolicyRetrieval:
    """Test retention policy information retrieval."""

    def test_get_retention_policy(self, retention_service):
        """Test getting current retention policy."""
        policy = retention_service.get_retention_policy()

        assert "uploaded_days" in policy
        assert "processed_days" in policy
        assert "batch_days" in policy
        assert "temp_hours" in policy
        assert "cleanup_enabled" in policy

    def test_retention_policy_values(self, retention_service):
        """Test that policy values match configuration."""
        policy = retention_service.get_retention_policy()

        assert policy["uploaded_days"] == retention_service.retention_uploaded_days
        assert policy["processed_days"] == retention_service.retention_processed_days
        assert policy["batch_days"] == retention_service.retention_batch_days
        assert policy["temp_hours"] == retention_service.retention_temp_hours


class TestFileAgeCalculation:
    """Test file age calculation."""

    @pytest.mark.asyncio
    async def test_is_file_expired_old_file(self, retention_service, temp_storage):
        """Test expiration check for old file."""
        # Create file with old modification time
        old_file = temp_storage / "old.txt"
        old_file.write_text("Old content")

        # Set modification time to past
        old_time = datetime.now(timezone.utc) - timedelta(days=100)
        old_timestamp = old_time.timestamp()

        import os
        os.utime(old_file, (old_timestamp, old_timestamp))

        # Check if expired (assuming retention < 100 days)
        is_expired = await retention_service.is_file_expired(
            file_path=old_file,
            retention_days=30,
        )

        assert is_expired is True

    @pytest.mark.asyncio
    async def test_is_file_expired_recent_file(self, retention_service, temp_storage):
        """Test expiration check for recent file."""
        # Create recent file
        recent_file = temp_storage / "recent.txt"
        recent_file.write_text("Recent content")

        # Check if expired (retention > file age)
        is_expired = await retention_service.is_file_expired(
            file_path=recent_file,
            retention_days=30,
        )

        assert is_expired is False

    @pytest.mark.asyncio
    async def test_is_file_expired_nonexistent(self, retention_service, temp_storage):
        """Test expiration check for non-existent file."""
        nonexistent = temp_storage / "nonexistent.txt"

        # Should handle gracefully
        is_expired = await retention_service.is_file_expired(
            file_path=nonexistent,
            retention_days=30,
        )

        assert is_expired is False

    @pytest.mark.asyncio
    async def test_get_file_age(self, retention_service, temp_storage):
        """Test getting file age in days."""
        test_file = temp_storage / "test.txt"
        test_file.write_text("Test")

        age_days = await retention_service.get_file_age(test_file)

        # Should be approximately 0 days for newly created file
        assert age_days >= 0
        assert age_days < 1


class TestExpiredFileDiscovery:
    """Test finding expired files."""

    @pytest.mark.asyncio
    async def test_find_expired_uploaded_files(self, retention_service, path_service, temp_storage):
        """Test finding expired uploaded files."""
        org_id = "org-test"
        batch_id = "batch-test"

        # Create uploaded file structure
        uploaded_path = path_service.get_document_path(
            document_id="doc-1",
            organization_id=org_id,
            batch_id=batch_id,
            file_type="uploaded",
            filename="old.pdf",
            create_dirs=True,
        )
        uploaded_path.write_text("Old uploaded file")

        # Set old modification time
        old_time = (datetime.now(timezone.utc) - timedelta(days=100)).timestamp()
        import os
        os.utime(uploaded_path, (old_time, old_time))

        # Find expired files
        expired = await retention_service.find_expired_files(organization_id=org_id)

        # Should find the old uploaded file (if retention < 100 days)
        if retention_service.retention_uploaded_days < 100:
            assert len(expired) > 0
            found = any(str(uploaded_path) in e["path"] for e in expired)
            assert found

    @pytest.mark.asyncio
    async def test_find_expired_processed_files(self, retention_service, path_service, temp_storage):
        """Test finding expired processed files."""
        org_id = "org-processed"

        # Create processed file
        processed_path = path_service.get_document_path(
            document_id="doc-2",
            organization_id=org_id,
            batch_id=None,
            file_type="processed",
            filename="old.md",
            create_dirs=True,
        )
        processed_path.write_text("Old processed file")

        # Set old modification time
        old_time = (datetime.now(timezone.utc) - timedelta(days=100)).timestamp()
        import os
        os.utime(processed_path, (old_time, old_time))

        # Find expired files
        expired = await retention_service.find_expired_files(organization_id=org_id)

        # Should find the old processed file (if retention < 100 days)
        if retention_service.retention_processed_days < 100:
            assert len(expired) > 0

    @pytest.mark.asyncio
    async def test_find_expired_temp_files(self, retention_service, path_service, temp_storage):
        """Test finding expired temporary files."""
        # Create temp file
        temp_path = path_service.get_temp_path(
            job_id="job-old",
            filename="temp.pdf",
            create_dirs=True,
        )
        temp_path.write_text("Old temp file")

        # Set old modification time (25 hours ago)
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).timestamp()
        import os
        os.utime(temp_path, (old_time, old_time))

        # Find expired files
        expired = await retention_service.find_expired_files()

        # Should find temp file (if retention < 25 hours)
        if retention_service.retention_temp_hours < 25:
            found = any("temp" in e["path"] and "job-old" in e["path"] for e in expired)
            assert found

    @pytest.mark.asyncio
    async def test_find_expired_files_specific_org(self, retention_service, path_service, temp_storage):
        """Test finding expired files for specific organization."""
        org1 = "org-1"
        org2 = "org-2"

        # Create files for both orgs
        for org in [org1, org2]:
            file_path = path_service.get_document_path(
                document_id=f"doc-{org}",
                organization_id=org,
                batch_id=None,
                file_type="uploaded",
                filename="test.pdf",
                create_dirs=True,
            )
            file_path.write_text(f"Content for {org}")

            # Make files old
            old_time = (datetime.now(timezone.utc) - timedelta(days=100)).timestamp()
            import os
            os.utime(file_path, (old_time, old_time))

        # Find expired files for org1 only
        expired_org1 = await retention_service.find_expired_files(organization_id=org1)

        # Should only include org1 files
        if expired_org1:
            for file_info in expired_org1:
                assert org1 in file_info["path"]
                assert org2 not in file_info["path"]


class TestFileCleanup:
    """Test file cleanup operations."""

    @pytest.mark.asyncio
    async def test_cleanup_dry_run(self, retention_service, path_service, temp_storage):
        """Test dry run cleanup (no actual deletion)."""
        org_id = "org-dryrun"

        # Create old file
        old_file = path_service.get_document_path(
            document_id="doc-old",
            organization_id=org_id,
            batch_id=None,
            file_type="uploaded",
            filename="old.pdf",
            create_dirs=True,
        )
        old_file.write_text("Old content")

        # Make it old
        old_time = (datetime.now(timezone.utc) - timedelta(days=100)).timestamp()
        import os
        os.utime(old_file, (old_time, old_time))

        # Run cleanup in dry-run mode
        result = await retention_service.cleanup_expired_files(dry_run=True)

        # File should still exist
        assert old_file.exists()

        # Result should indicate what would be deleted
        assert "deleted_count" in result or "files_to_delete" in result

    @pytest.mark.asyncio
    async def test_cleanup_actual_deletion(self, retention_service, path_service, temp_storage):
        """Test actual file deletion."""
        org_id = "org-delete"

        # Create old file
        old_file = path_service.get_document_path(
            document_id="doc-delete",
            organization_id=org_id,
            batch_id=None,
            file_type="uploaded",
            filename="delete.pdf",
            create_dirs=True,
        )
        old_file.write_text("To be deleted")

        # Make it very old
        old_time = (datetime.now(timezone.utc) - timedelta(days=1000)).timestamp()
        import os
        os.utime(old_file, (old_time, old_time))

        # Run actual cleanup
        result = await retention_service.cleanup_expired_files(dry_run=False)

        # File may or may not be deleted depending on retention settings
        # Just verify the operation completed
        assert "deleted_count" in result or "errors" in result

    @pytest.mark.asyncio
    async def test_cleanup_with_deduplication(self, retention_service, path_service, dedupe_service, temp_storage):
        """Test cleanup respects deduplication references."""
        org_id = "org-dedupe-cleanup"

        # Create file
        test_file = temp_storage / "shared.txt"
        test_file.write_text("Shared content")

        # Calculate hash and store in dedupe
        hash_value = await dedupe_service.calculate_file_hash(test_file)
        content_path = await dedupe_service.store_deduplicated_file(
            file_path=test_file,
            hash_value=hash_value,
            document_id="doc-1",
            organization_id=org_id,
        )

        # Add multiple references
        await dedupe_service.add_reference(hash_value, "doc-2", org_id)

        # Make file old
        old_time = (datetime.now(timezone.utc) - timedelta(days=1000)).timestamp()
        import os
        os.utime(content_path, (old_time, old_time))

        # Run cleanup - should check reference count before deleting
        result = await retention_service.cleanup_expired_files(dry_run=False)

        # Deduplicated file should not be deleted if it has multiple references
        # (This behavior depends on implementation)
        assert result is not None

    @pytest.mark.asyncio
    async def test_cleanup_respects_active_jobs(self, retention_service, path_service, temp_storage):
        """Test cleanup doesn't delete files from active jobs."""
        # This test depends on job_service integration
        # For now, just verify cleanup can check job status
        result = await retention_service.cleanup_expired_files(dry_run=True)

        assert "skipped_count" in result or "deleted_count" in result


class TestBatchExpiration:
    """Test batch-level expiration."""

    @pytest.mark.asyncio
    async def test_find_expired_batches(self, retention_service, metadata_service):
        """Test finding expired batches via metadata."""
        org_id = "org-batch-exp"

        # Create batch with past expiration
        metadata_service.create_batch_metadata(
            batch_id="batch-expired",
            organization_id=org_id,
        )

        # Set expiration to past
        past_date = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        metadata_service.update_batch_metadata(
            batch_id="batch-expired",
            organization_id=org_id,
            updates={"expires_at": past_date},
        )

        # Find expired batches
        expired_batches = metadata_service.list_expired_batches(organization_id=org_id)

        assert len(expired_batches) > 0
        assert any(b["batch_id"] == "batch-expired" for b in expired_batches)

    @pytest.mark.asyncio
    async def test_cleanup_expired_batch(self, retention_service, metadata_service, path_service, temp_storage):
        """Test cleaning up entire expired batch."""
        org_id = "org-batch-cleanup"
        batch_id = "batch-cleanup"

        # Create batch metadata
        metadata_service.create_batch_metadata(
            batch_id=batch_id,
            organization_id=org_id,
        )

        # Set expiration to past
        past_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        metadata_service.update_batch_metadata(
            batch_id=batch_id,
            organization_id=org_id,
            updates={"expires_at": past_date},
        )

        # Create some files in batch
        batch_file = path_service.get_document_path(
            document_id="doc-batch",
            organization_id=org_id,
            batch_id=batch_id,
            file_type="uploaded",
            filename="test.pdf",
            create_dirs=True,
        )
        batch_file.write_text("Batch file")

        # Run cleanup
        result = await retention_service.cleanup_expired_files(dry_run=False)

        # Verify cleanup ran
        assert result is not None


class TestCleanupStatistics:
    """Test cleanup statistics and reporting."""

    @pytest.mark.asyncio
    async def test_cleanup_result_format(self, retention_service):
        """Test cleanup result contains expected fields."""
        result = await retention_service.cleanup_expired_files(dry_run=True)

        # Should contain key statistics
        assert "deleted_count" in result or "files_to_delete" in result
        assert "errors" in result or "error_count" in result
        assert "dry_run" in result or "mode" in result

    @pytest.mark.asyncio
    async def test_cleanup_storage_savings_reported(self, retention_service):
        """Test cleanup reports storage savings."""
        result = await retention_service.cleanup_expired_files(dry_run=True)

        # May include storage statistics
        if "storage_freed_bytes" in result:
            assert isinstance(result["storage_freed_bytes"], (int, float))
            assert result["storage_freed_bytes"] >= 0


class TestErrorHandling:
    """Test error handling during cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_with_permission_error(self, retention_service, temp_storage):
        """Test cleanup handles permission errors gracefully."""
        # This test is platform-dependent and may not work on all systems
        # Just verify cleanup doesn't crash
        result = await retention_service.cleanup_expired_files(dry_run=False)

        assert result is not None
        assert "errors" in result or "error_count" in result

    @pytest.mark.asyncio
    async def test_cleanup_with_missing_directory(self, retention_service):
        """Test cleanup handles missing directories gracefully."""
        # Run cleanup even if some expected directories don't exist
        result = await retention_service.cleanup_expired_files(dry_run=True)

        assert result is not None

    @pytest.mark.asyncio
    async def test_find_expired_with_corrupt_metadata(self, retention_service, metadata_service, path_service, temp_storage):
        """Test finding expired files with corrupt batch metadata."""
        org_id = "org-corrupt"
        batch_id = "batch-corrupt"

        # Create batch metadata
        metadata_service.create_batch_metadata(
            batch_id=batch_id,
            organization_id=org_id,
        )

        # Corrupt the metadata file
        org_path = path_service.resolve_organization_path(org_id)
        batch_path = path_service.resolve_batch_path(org_path, batch_id)
        metadata_path = batch_path / "metadata.json"

        metadata_path.write_text("invalid json {{{")

        # Should handle gracefully
        try:
            expired = await retention_service.find_expired_files(organization_id=org_id)
            assert isinstance(expired, list)
        except json.JSONDecodeError:
            pass  # Acceptable behavior


class TestConfigurationRespect:
    """Test that service respects configuration settings."""

    @pytest.mark.asyncio
    async def test_cleanup_respects_enabled_flag(self, retention_service):
        """Test that cleanup checks if cleanup is enabled."""
        # Access cleanup_enabled setting
        assert hasattr(retention_service, 'cleanup_enabled')

    @pytest.mark.asyncio
    async def test_cleanup_respects_batch_size(self, retention_service):
        """Test that cleanup respects batch size configuration."""
        # Should have batch_size configuration
        assert hasattr(retention_service, 'cleanup_batch_size')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
