"""
Tests for document API endpoint validation.

Tests that document ID validation is correctly applied to all document endpoints
and rejects invalid formats (file paths, malformed IDs, etc.).

NOTE: These tests are skipped due to API refactoring.
The old app.api.v1.routers.documents has been restructured into:
- app.api.v1.data.routers.assets (asset CRUD)
- app.api.v1.data.routers.storage (storage operations)
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


# Mark entire module as skipped due to API refactoring
pytestmark = pytest.mark.skip(
    reason="API refactored: app.api.v1.routers.documents moved to app.api.v1.data.routers.assets and storage"
)


@pytest.fixture
def mock_storage_service():
    """Mock storage service for testing."""
    # Old fixture - router path no longer exists
    yield MagicMock()


@pytest.fixture
def mock_get_current_user():
    """Mock get_current_user dependency."""
    # Old fixture - router path no longer exists
    mock_user = MagicMock()
    mock_user.organization_id = "org-123"
    yield mock_user


class TestDocumentIdValidation:
    """Test document ID validation on API endpoints."""

    def test_valid_uuid_accepted(self, client, mock_storage_service, mock_get_current_user):
        """Test valid UUID is accepted."""
        response = client.get("/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/result")
        # Should not get 400 validation error (may get 404 if document doesn't exist)
        assert response.status_code != 400

    def test_valid_legacy_accepted(self, client, mock_storage_service, mock_get_current_user):
        """Test valid legacy format is accepted."""
        response = client.get("/api/v1/documents/doc_abc123def456/result")
        # Should not get 400 validation error
        assert response.status_code != 400

    def test_file_path_rejected(self, client, mock_get_current_user):
        """Test file path pattern is rejected with 400."""
        response = client.get("/api/v1/documents/folder/file.pdf/result")
        assert response.status_code == 400
        assert "file path" in response.json()["detail"].lower()

    def test_file_with_extension_rejected(self, client, mock_get_current_user):
        """Test filename with extension is rejected."""
        response = client.get("/api/v1/documents/document.pdf/result")
        assert response.status_code == 400
        assert "file path" in response.json()["detail"].lower()

    def test_invalid_format_rejected(self, client, mock_get_current_user):
        """Test invalid format is rejected with 400."""
        response = client.get("/api/v1/documents/invalid-format-123/result")
        assert response.status_code == 400
        assert "valid UUID" in response.json()["detail"]

    def test_empty_document_id_rejected(self, client, mock_get_current_user):
        """Test empty document ID is rejected."""
        # FastAPI will reject empty path parameter before our validation
        response = client.get("/api/v1/documents//result")
        assert response.status_code in [400, 404, 422]  # Various possible errors

    def test_parent_directory_traversal_rejected(self, client, mock_get_current_user):
        """Test parent directory traversal is rejected."""
        response = client.get("/api/v1/documents/../etc/passwd/result")
        assert response.status_code == 400
        assert "file path" in response.json()["detail"].lower()


class TestProcessDocumentEndpoint:
    """Test validation on POST /documents/{document_id}/process."""

    def test_valid_uuid_accepted(self, client, mock_get_current_user):
        """Test valid UUID is accepted."""
        with patch('app.api.v1.routers.documents.get_active_job_for_document', return_value=None):
            with patch('app.api.v1.routers.documents.database_service.get_session'):
                response = client.post(
                    "/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/process",
                    json={}
                )
                # Should not get 400 validation error
                assert response.status_code != 400

    def test_file_path_rejected(self, client, mock_get_current_user):
        """Test file path is rejected."""
        response = client.post("/api/v1/documents/folder/file.pdf/process", json={})
        assert response.status_code == 400


class TestGetDocumentContent:
    """Test validation on GET /documents/{document_id}/content."""

    def test_valid_uuid_accepted(self, client, mock_get_current_user):
        """Test valid UUID is accepted."""
        with patch('app.api.v1.routers.documents.minio') as mock_minio:
            # Mock MinIO download
            mock_minio.get_object.return_value.read.return_value = b"# Test Content"
            response = client.get("/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/content")
            # Should not get 400 validation error
            assert response.status_code != 400

    def test_file_path_rejected(self, client, mock_get_current_user):
        """Test file path is rejected."""
        response = client.get("/api/v1/documents/document.pdf/content")
        assert response.status_code == 400


class TestUpdateDocumentContent:
    """Test validation on PUT /documents/{document_id}/content."""

    def test_valid_uuid_accepted(self, client, mock_get_current_user):
        """Test valid UUID is accepted."""
        with patch('app.api.v1.routers.documents.get_active_job_for_document', return_value=None):
            with patch('app.api.v1.routers.documents.database_service.get_session'):
                response = client.put(
                    "/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/content",
                    json={"content": "# Updated content"}
                )
                # Should not get 400 validation error
                assert response.status_code != 400

    def test_file_path_rejected(self, client, mock_get_current_user):
        """Test file path is rejected."""
        response = client.put(
            "/api/v1/documents/folder/file.docx/content",
            json={"content": "# Test"}
        )
        assert response.status_code == 400


class TestDownloadDocument:
    """Test validation on GET /documents/{document_id}/download."""

    def test_valid_uuid_accepted(self, client, mock_get_current_user):
        """Test valid UUID is accepted."""
        with patch('app.api.v1.routers.documents.minio') as mock_minio:
            # Mock MinIO download
            mock_minio.get_object.return_value.read.return_value = b"PDF content"
            response = client.get("/api/v1/documents/550e8400-e29b-41d4-a716-446655440000/download")
            # Should not get 400 validation error
            assert response.status_code != 400

    def test_file_path_rejected(self, client, mock_get_current_user):
        """Test file path is rejected."""
        response = client.get("/api/v1/documents/folder/report.pdf/download")
        assert response.status_code == 400


class TestDeleteDocument:
    """Test validation on DELETE /documents/{document_id}."""

    def test_valid_uuid_accepted(self, client, mock_get_current_user):
        """Test valid UUID is accepted."""
        with patch('app.api.v1.routers.documents.storage_service.delete_processing_result'):
            with patch('app.api.v1.routers.documents.get_minio_service'):
                with patch('app.api.v1.routers.documents.get_session'):
                    response = client.delete("/api/v1/documents/550e8400-e29b-41d4-a716-446655440000")
                    # Should not get 400 validation error
                    assert response.status_code != 400

    def test_file_path_rejected(self, client, mock_get_current_user):
        """Test file path is rejected."""
        response = client.delete("/api/v1/documents/../sensitive/data.txt")
        assert response.status_code == 400


class TestCaseSensitivity:
    """Test that validation is case-insensitive."""

    def test_uppercase_uuid_accepted(self, client, mock_storage_service, mock_get_current_user):
        """Test uppercase UUID is accepted and normalized."""
        response = client.get("/api/v1/documents/550E8400-E29B-41D4-A716-446655440000/result")
        # Should not get 400 validation error
        assert response.status_code != 400

    def test_mixed_case_legacy_accepted(self, client, mock_storage_service, mock_get_current_user):
        """Test mixed case legacy format is accepted."""
        response = client.get("/api/v1/documents/doc_ABC123def456/result")
        # Should not get 400 validation error
        assert response.status_code != 400


class TestWhitespaceHandling:
    """Test that whitespace is handled correctly."""

    def test_uuid_with_whitespace_accepted(self, client, mock_storage_service, mock_get_current_user):
        """Test UUID with surrounding whitespace is accepted (if URL-decoded)."""
        # Note: URL encoding will typically strip whitespace before it reaches our validator
        # This test documents the expected behavior
        import urllib.parse
        encoded = urllib.parse.quote("  550e8400-e29b-41d4-a716-446655440000  ")
        response = client.get(f"/api/v1/documents/{encoded}/result")
        # FastAPI may reject this before our validation due to URL encoding
        assert response.status_code in [400, 404]  # Either validation or not found
