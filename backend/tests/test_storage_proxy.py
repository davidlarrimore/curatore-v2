"""
Tests for backend-proxied object storage downloads.

These tests verify that the proxy download endpoint works correctly,
replacing the need for presigned URLs and direct browser-to-MinIO communication.
"""

import pytest
from io import BytesIO
from unittest.mock import MagicMock, patch

from app.services.minio_service import MinIOService


@pytest.fixture
def mock_minio_service():
    """Mock MinIO service for testing."""
    service = MagicMock(spec=MinIOService)

    # Mock bucket_exists
    service.bucket_exists.return_value = True

    # Mock get_object_info
    service.get_object_info.return_value = {
        "bucket": "test-bucket",
        "key": "test/file.txt",
        "size": 100,
        "content_type": "text/plain",
        "etag": "test-etag",
        "last_modified": "2024-01-01T00:00:00Z",
    }

    # Mock get_object
    test_content = b"Test file content"
    service.get_object.return_value = BytesIO(test_content)

    return service


@pytest.mark.asyncio
async def test_proxy_download_success(client, mock_user, mock_minio_service):
    """Test successful proxy download of an object."""
    with patch("app.api.v1.routers.storage.get_minio_service", return_value=mock_minio_service):
        response = client.get(
            "/api/v1/storage/object/download",
            params={
                "bucket": "test-bucket",
                "key": "test/file.txt",
                "inline": False,
            },
            headers={"Authorization": f"Bearer {mock_user['token']}"}
        )

    assert response.status_code == 200
    assert response.content == b"Test file content"
    assert "attachment" in response.headers["content-disposition"]
    assert "file.txt" in response.headers["content-disposition"]
    assert response.headers["content-type"] == "text/plain"


@pytest.mark.asyncio
async def test_proxy_download_inline(client, mock_user, mock_minio_service):
    """Test proxy download with inline disposition for preview."""
    with patch("app.api.v1.routers.storage.get_minio_service", return_value=mock_minio_service):
        response = client.get(
            "/api/v1/storage/object/download",
            params={
                "bucket": "test-bucket",
                "key": "test/file.txt",
                "inline": True,
            },
            headers={"Authorization": f"Bearer {mock_user['token']}"}
        )

    assert response.status_code == 200
    assert response.content == b"Test file content"
    assert response.headers["content-disposition"] == "inline"


@pytest.mark.asyncio
async def test_proxy_download_bucket_not_found(client, mock_user, mock_minio_service):
    """Test proxy download when bucket doesn't exist."""
    mock_minio_service.bucket_exists.return_value = False

    with patch("app.api.v1.routers.storage.get_minio_service", return_value=mock_minio_service):
        response = client.get(
            "/api/v1/storage/object/download",
            params={
                "bucket": "nonexistent-bucket",
                "key": "test/file.txt",
            },
            headers={"Authorization": f"Bearer {mock_user['token']}"}
        )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_proxy_download_object_not_found(client, mock_user, mock_minio_service):
    """Test proxy download when object doesn't exist."""
    mock_minio_service.get_object_info.return_value = None

    with patch("app.api.v1.routers.storage.get_minio_service", return_value=mock_minio_service):
        response = client.get(
            "/api/v1/storage/object/download",
            params={
                "bucket": "test-bucket",
                "key": "nonexistent/file.txt",
            },
            headers={"Authorization": f"Bearer {mock_user['token']}"}
        )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_proxy_download_no_auth(client):
    """Test proxy download without authentication returns 401."""
    response = client.get(
        "/api/v1/storage/object/download",
        params={
            "bucket": "test-bucket",
            "key": "test/file.txt",
        },
    )

    # Should return 401 Unauthorized (or redirect to login depending on auth setup)
    assert response.status_code in [401, 403]


@pytest.mark.asyncio
async def test_proxy_download_protected_bucket(client, mock_user, mock_minio_service):
    """Test proxy download from protected bucket succeeds (read-only access)."""
    # Protected buckets should allow reads but not writes
    with patch("app.api.v1.routers.storage.get_minio_service", return_value=mock_minio_service):
        response = client.get(
            "/api/v1/storage/object/download",
            params={
                "bucket": "curatore-processed",  # Protected bucket
                "key": "test/file.md",
                "inline": False,
            },
            headers={"Authorization": f"Bearer {mock_user['token']}"}
        )

    assert response.status_code == 200
    assert response.content == b"Test file content"


@pytest.mark.asyncio
async def test_proxy_download_content_length(client, mock_user, mock_minio_service):
    """Test that Content-Length header is set correctly."""
    with patch("app.api.v1.routers.storage.get_minio_service", return_value=mock_minio_service):
        response = client.get(
            "/api/v1/storage/object/download",
            params={
                "bucket": "test-bucket",
                "key": "test/file.txt",
            },
            headers={"Authorization": f"Bearer {mock_user['token']}"}
        )

    assert response.status_code == 200
    assert "content-length" in response.headers
    assert int(response.headers["content-length"]) == len(b"Test file content")


@pytest.mark.asyncio
async def test_proxy_download_filename_extraction(client, mock_user, mock_minio_service):
    """Test that filename is correctly extracted from nested paths."""
    with patch("app.api.v1.routers.storage.get_minio_service", return_value=mock_minio_service):
        response = client.get(
            "/api/v1/storage/object/download",
            params={
                "bucket": "test-bucket",
                "key": "org_123/doc_abc/uploaded/my-document.pdf",
                "inline": False,
            },
            headers={"Authorization": f"Bearer {mock_user['token']}"}
        )

    assert response.status_code == 200
    assert "my-document.pdf" in response.headers["content-disposition"]
