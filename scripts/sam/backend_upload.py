"""
Backend API Upload Helper for SAM.gov Scripts

TEMPORARY UTILITY - WILL BE REMOVED

This module provides temporary helper functions for external SAM.gov scripts
to upload files through the Curatore backend API instead of directly to MinIO.
This ensures proper UUID generation, artifact tracking, and database consistency.

CURRENT USAGE:
    - Consolidated JSON files (sam_pull_{date}.json)
    - Daily summary reports (Markdown and PDF)

    Resource files (PDFs, DOCs from SAM.gov) are NOT uploaded via this helper.
    They use direct MinIO upload to maintain custom folder structure by solicitation number.

⚠️  IMPORTANT - TEMPORARY CODE:
    This entire module and the scripts that use it are TEMPORARY workarounds
    until native SAM.gov integration is built into the Curatore backend/frontend.

    TODO: When native SAM.gov integration is implemented:
    1. Remove this file (backend_upload.py)
    2. Remove /api/v1/storage/upload/proxy endpoint from backend
    3. Remove all SAM.gov external scripts (scripts/sam/)
    4. Replace with native SAM import workflows in the backend/frontend
    5. Update documentation to reflect native integration

    DO NOT build new features that depend on this helper module.

Usage (for existing SAM scripts only):
    from backend_upload import upload_file_to_backend

    # Upload a file and get UUID document_id
    doc_id = upload_file_to_backend(
        file_content=file_bytes,
        filename="report.pdf",
        content_type="application/pdf",
        metadata={"source": "sam.gov"},
        api_url="http://localhost:8000",
        api_key="your-api-key"  # Optional
    )
"""

import requests
from io import BytesIO
from typing import Dict, Optional


def upload_file_to_backend(
    file_content: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
    metadata: Optional[Dict[str, str]] = None,
    api_url: str = "http://localhost:8000",
    api_key: Optional[str] = None,
) -> str:
    """
    Upload a file through the Curatore backend API.

    Args:
        file_content: File bytes to upload
        filename: Original filename (will be stored in artifact)
        content_type: MIME type of the file
        metadata: Optional metadata dict (stored as custom headers)
        api_url: Backend API base URL
        api_key: Optional API key for authentication (X-API-Key header)

    Returns:
        str: UUID document ID assigned by backend

    Raises:
        requests.HTTPError: If upload fails
        KeyError: If response doesn't contain document_id

    Example:
        >>> pdf_bytes = b"..."
        >>> doc_id = upload_file_to_backend(
        ...     file_content=pdf_bytes,
        ...     filename="report.pdf",
        ...     content_type="application/pdf",
        ...     metadata={"source": "sam.gov", "solicitation": "70ABC123"}
        ... )
        >>> print(f"Uploaded with ID: {doc_id}")
        Uploaded with ID: 550e8400-e29b-41d4-a716-446655440000
    """
    endpoint = f"{api_url}/api/v1/storage/upload/proxy"

    # Prepare headers
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

    # Add custom metadata as headers (X-Metadata-* pattern)
    if metadata:
        for key, value in metadata.items():
            headers[f"X-Metadata-{key}"] = str(value)

    # Prepare multipart form data
    files = {
        "file": (filename, BytesIO(file_content), content_type)
    }

    # Upload to backend
    response = requests.post(endpoint, files=files, headers=headers)
    response.raise_for_status()

    # Extract document_id from response
    result = response.json()
    document_id = result.get("document_id")

    if not document_id:
        raise KeyError("Backend response missing document_id")

    return document_id


def bulk_upload_files_to_backend(
    files: list[Dict],
    api_url: str = "http://localhost:8000",
    api_key: Optional[str] = None,
) -> Dict[str, str]:
    """
    Upload multiple files through the backend API.

    Args:
        files: List of file dicts with keys: content, filename, content_type, metadata
        api_url: Backend API base URL
        api_key: Optional API key for authentication

    Returns:
        Dict mapping original filenames to UUIDs

    Example:
        >>> files = [
        ...     {
        ...         "content": b"...",
        ...         "filename": "doc1.pdf",
        ...         "content_type": "application/pdf",
        ...         "metadata": {"source": "sam.gov"}
        ...     },
        ...     {
        ...         "content": b"...",
        ...         "filename": "doc2.docx",
        ...         "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ...         "metadata": {"source": "sam.gov"}
        ...     }
        ... ]
        >>> result = bulk_upload_files_to_backend(files)
        >>> print(result)
        {'doc1.pdf': '550e8400-...', 'doc2.docx': '7c9e6679-...'}
    """
    results = {}

    for file_info in files:
        try:
            doc_id = upload_file_to_backend(
                file_content=file_info["content"],
                filename=file_info["filename"],
                content_type=file_info.get("content_type", "application/octet-stream"),
                metadata=file_info.get("metadata"),
                api_url=api_url,
                api_key=api_key,
            )
            results[file_info["filename"]] = doc_id
        except Exception as e:
            print(f"Failed to upload {file_info['filename']}: {e}")
            # Continue with other files

    return results
