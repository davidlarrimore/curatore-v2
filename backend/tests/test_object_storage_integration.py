"""
Integration tests for object storage (MinIO/S3) functionality.

These tests verify the complete object storage workflow:
- Presigned URL generation for uploads
- Direct upload to object storage
- Artifact tracking in database
- Presigned URL generation for downloads
- File retrieval from object storage
"""
import pytest
from io import BytesIO
from uuid import uuid4


class TestObjectStorageUploadFlow:
    """Test the upload workflow using presigned URLs."""

    @pytest.mark.skip(reason="Requires MinIO service running")
    def test_generate_upload_presigned_url(self):
        """Test generation of presigned URL for upload."""
        from app.services.minio_service import get_minio_service

        minio = get_minio_service()
        if not minio or not minio.enabled:
            pytest.skip("MinIO not configured")

        # Generate presigned URL
        object_key = f"test/{uuid4()}/test.pdf"
        presigned_url = minio.generate_presigned_upload_url(
            bucket=minio.bucket_uploads,
            object_key=object_key,
            expiration=3600
        )

        assert presigned_url is not None
        assert "http" in presigned_url.lower()
        assert object_key in presigned_url

    @pytest.mark.skip(reason="Requires MinIO service running")
    def test_upload_and_download_file(self):
        """Test uploading a file to MinIO and downloading it back."""
        from app.services.minio_service import get_minio_service

        minio = get_minio_service()
        if not minio or not minio.enabled:
            pytest.skip("MinIO not configured")

        # Create test file
        test_content = b"Test document content for object storage"
        test_file = BytesIO(test_content)
        object_key = f"test/{uuid4()}/test.txt"

        # Upload
        minio.put_object(
            bucket=minio.bucket_uploads,
            key=object_key,
            data=test_file,
            content_type="text/plain"
        )

        # Download
        downloaded = minio.get_object(minio.bucket_uploads, object_key)
        assert downloaded is not None

        downloaded_content = downloaded.read()
        assert downloaded_content == test_content

        # Cleanup
        minio.delete_object(minio.bucket_uploads, object_key)


class TestArtifactTracking:
    """Test artifact database tracking for stored files."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires database setup")
    async def test_create_artifact_record(self):
        """Test creating an artifact record in the database."""
        from app.services.artifact_service import artifact_service
        from app.services.database_service import database_service

        async with database_service.get_session() as session:
            artifact = await artifact_service.create_artifact(
                session=session,
                document_id=str(uuid4()),
                artifact_type="uploaded",
                bucket="curatore-uploads",
                object_key=f"test/{uuid4()}/test.pdf",
                file_size=1024,
                content_type="application/pdf",
                original_filename="test.pdf",
                organization_id=str(uuid4())
            )

            assert artifact is not None
            assert artifact.document_id is not None
            assert artifact.artifact_type == "uploaded"
            assert artifact.bucket == "curatore-uploads"

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires database setup")
    async def test_get_artifact_by_document(self):
        """Test retrieving artifacts by document ID."""
        from app.services.artifact_service import artifact_service
        from app.services.database_service import database_service

        document_id = str(uuid4())

        async with database_service.get_session() as session:
            # Create artifact
            await artifact_service.create_artifact(
                session=session,
                document_id=document_id,
                artifact_type="processed",
                bucket="curatore-processed",
                object_key=f"test/{uuid4()}/test.md",
                file_size=2048,
                content_type="text/markdown",
                original_filename="test.md",
                organization_id=str(uuid4())
            )

            # Retrieve artifact
            artifact = await artifact_service.get_artifact_by_document(
                session=session,
                document_id=document_id,
                artifact_type="processed"
            )

            assert artifact is not None
            assert artifact.document_id == document_id
            assert artifact.artifact_type == "processed"


class TestMultiTenantIsolation:
    """Test multi-tenant isolation in object storage."""

    @pytest.mark.skip(reason="Requires MinIO service running")
    def test_organization_prefix_isolation(self):
        """Test that files are isolated by organization_id prefix."""
        from app.services.minio_service import get_minio_service

        minio = get_minio_service()
        if not minio or not minio.enabled:
            pytest.skip("MinIO not configured")

        org1_id = str(uuid4())
        org2_id = str(uuid4())
        doc_id = str(uuid4())

        # Upload file for org1
        org1_key = f"{org1_id}/{doc_id}/uploaded/test.pdf"
        minio.put_object(
            bucket=minio.bucket_uploads,
            key=org1_key,
            data=BytesIO(b"Org1 content"),
            content_type="application/pdf"
        )

        # Upload file for org2 with same doc_id
        org2_key = f"{org2_id}/{doc_id}/uploaded/test.pdf"
        minio.put_object(
            bucket=minio.bucket_uploads,
            key=org2_key,
            data=BytesIO(b"Org2 content"),
            content_type="application/pdf"
        )

        # Verify isolation
        org1_content = minio.get_object(minio.bucket_uploads, org1_key).read()
        org2_content = minio.get_object(minio.bucket_uploads, org2_key).read()

        assert org1_content == b"Org1 content"
        assert org2_content == b"Org2 content"
        assert org1_content != org2_content

        # Cleanup
        minio.delete_object(minio.bucket_uploads, org1_key)
        minio.delete_object(minio.bucket_uploads, org2_key)


class TestPresignedURLDownload:
    """Test presigned URL generation for downloads."""

    @pytest.mark.skip(reason="Requires MinIO service running")
    def test_generate_download_presigned_url(self):
        """Test generation of presigned URL for download."""
        from app.services.minio_service import get_minio_service

        minio = get_minio_service()
        if not minio or not minio.enabled:
            pytest.skip("MinIO not configured")

        # Upload a test file first
        object_key = f"test/{uuid4()}/test.pdf"
        minio.put_object(
            bucket=minio.bucket_processed,
            key=object_key,
            data=BytesIO(b"Test content"),
            content_type="application/pdf"
        )

        # Generate presigned download URL
        presigned_url = minio.generate_presigned_download_url(
            bucket=minio.bucket_processed,
            object_key=object_key,
            expiration=3600
        )

        assert presigned_url is not None
        assert "http" in presigned_url.lower()
        assert object_key in presigned_url

        # Cleanup
        minio.delete_object(minio.bucket_processed, object_key)
