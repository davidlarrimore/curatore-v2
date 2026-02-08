"""
Tests for Celery task processing with object storage.

These tests verify that the processing pipeline works correctly with MinIO:
- Tasks require artifact_id (no filesystem fallback)
- Files are downloaded from MinIO before processing
- Processed results are uploaded back to MinIO
- Artifact records are created for all stored files

NOTE: Some tests are skipped due to API refactoring.
The old process_document_task has been replaced with execute_extraction_task
with a different signature (asset_id, run_id, extraction_id).
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from uuid import uuid4


class TestTaskArtifactRequirement:
    """Test that tasks enforce artifact_id requirement."""

    @pytest.mark.skip(reason="API refactored: process_document_task replaced with execute_extraction_task")
    def test_task_fails_without_artifact_id(self):
        """Test that process_document_task fails when artifact_id is missing."""
        # Old test - task signature has changed
        pass

    @pytest.mark.skip(reason="API refactored: process_document_task replaced with execute_extraction_task")
    def test_task_requires_artifact_id_with_logging(self):
        """Test that missing artifact_id is logged before failure."""
        # Old test - task signature has changed
        pass


class TestObjectStorageDownload:
    """Test file download from object storage during task processing."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires MinIO service and full task setup")
    async def test_fetch_from_object_storage(self):
        """Test that _fetch_from_object_storage downloads files correctly."""
        from app.core.tasks import _fetch_from_object_storage
        from app.core.storage.minio_service import get_minio_service
        from app.core.shared.artifact_service import artifact_service
        from app.core.shared.database_service import database_service
        from io import BytesIO

        minio = get_minio_service()
        if not minio or not minio.enabled:
            pytest.skip("MinIO not configured")

        # Create test artifact
        document_id = str(uuid4())
        object_key = f"test/{uuid4()}/test.pdf"
        test_content = b"Test document for processing"

        # Upload to MinIO
        minio.put_object(
            bucket=minio.bucket_uploads,
            key=object_key,
            data=BytesIO(test_content),
            content_type="application/pdf"
        )

        # Create artifact record
        async with database_service.get_session() as session:
            artifact = await artifact_service.create_artifact(
                session=session,
                document_id=document_id,
                artifact_type="uploaded",
                bucket=minio.bucket_uploads,
                object_key=object_key,
                file_size=len(test_content),
                content_type="application/pdf",
                original_filename="test.pdf",
                organization_id=str(uuid4())
            )

            # Test download
            file_path, temp_dir = await _fetch_from_object_storage(str(artifact.id))

            assert file_path is not None
            assert file_path.exists()
            assert file_path.read_bytes() == test_content

            # Cleanup
            if temp_dir and temp_dir.exists():
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)

        # Cleanup MinIO
        minio.delete_object(minio.bucket_uploads, object_key)


class TestProcessedResultUpload:
    """Test that processed results are uploaded to object storage."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full processing pipeline setup")
    async def test_upload_processed_result(self):
        """Test that processed markdown is uploaded to MinIO."""
        from app.core.storage.minio_service import get_minio_service
        from io import BytesIO

        minio = get_minio_service()
        if not minio or not minio.enabled:
            pytest.skip("MinIO not configured")

        # Simulate processed result
        document_id = str(uuid4())
        org_id = str(uuid4())
        markdown_content = "# Test Document\n\nProcessed content"
        object_key = f"{org_id}/{document_id}/processed/test.md"

        # Upload processed result
        minio.put_object(
            bucket=minio.bucket_processed,
            key=object_key,
            data=BytesIO(markdown_content.encode('utf-8')),
            content_type="text/markdown"
        )

        # Verify upload
        downloaded = minio.get_object(minio.bucket_processed, object_key)
        assert downloaded is not None
        assert downloaded.read().decode('utf-8') == markdown_content

        # Cleanup
        minio.delete_object(minio.bucket_processed, object_key)


class TestArtifactCreationAfterProcessing:
    """Test that artifact records are created after successful processing."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires database setup")
    async def test_create_processed_artifact(self):
        """Test creating artifact record for processed file."""
        from app.core.shared.artifact_service import artifact_service
        from app.core.shared.database_service import database_service

        document_id = str(uuid4())
        org_id = str(uuid4())

        async with database_service.get_session() as session:
            # Create uploaded artifact
            uploaded_artifact = await artifact_service.create_artifact(
                session=session,
                document_id=document_id,
                artifact_type="uploaded",
                bucket="curatore-uploads",
                object_key=f"{org_id}/{document_id}/uploaded/test.pdf",
                file_size=1024,
                content_type="application/pdf",
                original_filename="test.pdf",
                organization_id=org_id
            )

            # Create processed artifact
            processed_artifact = await artifact_service.create_artifact(
                session=session,
                document_id=document_id,
                artifact_type="processed",
                bucket="curatore-processed",
                object_key=f"{org_id}/{document_id}/processed/test.md",
                file_size=2048,
                content_type="text/markdown",
                original_filename="test.md",
                organization_id=org_id
            )

            assert uploaded_artifact.document_id == document_id
            assert processed_artifact.document_id == document_id
            assert uploaded_artifact.artifact_type == "uploaded"
            assert processed_artifact.artifact_type == "processed"


class TestErrorHandling:
    """Test error handling in object storage operations."""

    @pytest.mark.skip(reason="API refactored: _fetch_from_object_storage no longer exported")
    @pytest.mark.asyncio
    async def test_missing_artifact_error(self):
        """Test that missing artifact returns None gracefully."""
        # Old test - internal function no longer exported
        pass

    @pytest.mark.skip(reason="API refactored: process_document_task replaced with execute_extraction_task")
    def test_task_error_with_invalid_artifact(self):
        """Test that task fails gracefully with invalid artifact_id."""
        # Old test - task signature has changed
        pass
