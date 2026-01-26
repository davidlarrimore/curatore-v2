"""
Document ID validation utilities for Curatore v2.

Provides centralized validation logic for document identifiers, supporting:
- Full UUID format (36 characters with hyphens)
- Legacy doc_* format (doc_ prefix + 12 hex characters)
- File path pattern detection and rejection

Usage:
    from app.utils.validators import validate_document_id, is_valid_uuid

    # Validate document ID (allows both UUID and legacy formats)
    try:
        doc_id = validate_document_id(user_input)
    except ValueError as e:
        return {"error": str(e)}

    # Check if strict UUID
    if is_valid_uuid(doc_id):
        # Use UUID-specific logic
        pass
"""

import re
import uuid
from typing import Optional


# Regex patterns
UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)
LEGACY_DOC_PATTERN = re.compile(r'^doc_[0-9a-f]{12}$', re.IGNORECASE)
FILE_PATH_PATTERN = re.compile(r'[/\\]|\.\.|\.[a-z]{2,4}$', re.IGNORECASE)


def is_valid_uuid(value: str) -> bool:
    """
    Check if a string is a valid UUID v4 format.

    Args:
        value: String to validate

    Returns:
        True if valid UUID format (36 chars with hyphens), False otherwise

    Examples:
        >>> is_valid_uuid("550e8400-e29b-41d4-a716-446655440000")
        True
        >>> is_valid_uuid("doc_abc123def456")
        False
        >>> is_valid_uuid("invalid")
        False
    """
    if not value or not isinstance(value, str):
        return False

    if len(value) != 36:
        return False

    # Try parsing with uuid module for validation
    try:
        uuid_obj = uuid.UUID(value)
        return str(uuid_obj) == value.lower()
    except (ValueError, AttributeError):
        return False


def is_legacy_document_id(value: str) -> bool:
    """
    Check if a string matches the legacy doc_* format.

    Args:
        value: String to validate

    Returns:
        True if matches doc_{12 hex chars} format, False otherwise

    Examples:
        >>> is_legacy_document_id("doc_abc123def456")
        True
        >>> is_legacy_document_id("550e8400-e29b-41d4-a716-446655440000")
        False
        >>> is_legacy_document_id("doc_short")
        False
    """
    if not value or not isinstance(value, str):
        return False

    if len(value) != 16:  # "doc_" (4) + 12 hex chars
        return False

    return LEGACY_DOC_PATTERN.match(value) is not None


def is_valid_document_id(value: str, allow_legacy: bool = True) -> bool:
    """
    Check if a string is a valid document ID.

    Accepts both UUID format and legacy doc_* format (if allow_legacy=True).

    Args:
        value: String to validate
        allow_legacy: Whether to accept legacy doc_* format (default: True)

    Returns:
        True if valid document ID, False otherwise

    Examples:
        >>> is_valid_document_id("550e8400-e29b-41d4-a716-446655440000")
        True
        >>> is_valid_document_id("doc_abc123def456")
        True
        >>> is_valid_document_id("doc_abc123def456", allow_legacy=False)
        False
        >>> is_valid_document_id("invalid/path/file.pdf")
        False
    """
    if not value or not isinstance(value, str):
        return False

    # Check UUID format first
    if is_valid_uuid(value):
        return True

    # Check legacy format if allowed
    if allow_legacy and is_legacy_document_id(value):
        return True

    return False


def detect_file_path_pattern(value: str) -> bool:
    """
    Detect if a string looks like a file path.

    Checks for:
    - Forward or backward slashes (/ or \\)
    - Parent directory references (..)
    - Common file extensions (.pdf, .docx, etc.)

    Args:
        value: String to check

    Returns:
        True if looks like a file path, False otherwise

    Examples:
        >>> detect_file_path_pattern("document.pdf")
        True
        >>> detect_file_path_pattern("folder/file.docx")
        True
        >>> detect_file_path_pattern("../etc/passwd")
        True
        >>> detect_file_path_pattern("550e8400-e29b-41d4-a716-446655440000")
        False
    """
    if not value or not isinstance(value, str):
        return False

    return FILE_PATH_PATTERN.search(value) is not None


def validate_document_id(
    value: str,
    allow_legacy: bool = True,
    reject_file_paths: bool = True
) -> str:
    """
    Validate and normalize a document ID.

    Args:
        value: Document ID to validate
        allow_legacy: Whether to accept legacy doc_* format (default: True)
        reject_file_paths: Whether to reject strings that look like file paths (default: True)

    Returns:
        Validated document ID (normalized to lowercase for UUIDs)

    Raises:
        ValueError: If document ID is invalid

    Examples:
        >>> validate_document_id("550E8400-E29B-41D4-A716-446655440000")
        '550e8400-e29b-41d4-a716-446655440000'
        >>> validate_document_id("doc_ABC123DEF456")
        'doc_abc123def456'
        >>> validate_document_id("invalid/path.pdf")
        Traceback (most recent call last):
        ValueError: Document ID appears to be a file path
    """
    if not value or not isinstance(value, str):
        raise ValueError("Document ID must be a non-empty string")

    # Strip whitespace
    value = value.strip()

    if not value:
        raise ValueError("Document ID must be a non-empty string")

    # Check for file path patterns first
    if reject_file_paths and detect_file_path_pattern(value):
        raise ValueError(
            "Document ID appears to be a file path. "
            "Use the /documents/search endpoint to search by filename."
        )

    # Validate format
    if not is_valid_document_id(value, allow_legacy=allow_legacy):
        if allow_legacy:
            raise ValueError(
                "Document ID must be a valid UUID "
                "(e.g., 550e8400-e29b-41d4-a716-446655440000) "
                "or legacy format (e.g., doc_abc123def456)"
            )
        else:
            raise ValueError(
                "Document ID must be a valid UUID "
                "(e.g., 550e8400-e29b-41d4-a716-446655440000)"
            )

    # Normalize to lowercase
    return value.lower()


def generate_document_id() -> str:
    """
    Generate a new document ID using UUID v4.

    Returns:
        New document ID as lowercase UUID string

    Examples:
        >>> doc_id = generate_document_id()
        >>> is_valid_uuid(doc_id)
        True
        >>> len(doc_id)
        36
    """
    return str(uuid.uuid4())


def extract_document_id_from_artifact_key(key: str) -> Optional[str]:
    """
    Extract document ID from an artifact storage key.

    Artifact keys follow the pattern:
    - {org_id}/{document_id}/uploaded/{filename}
    - {org_id}/{document_id}/processed/{filename}

    Args:
        key: Storage key to parse

    Returns:
        Extracted document ID if found and valid, None otherwise

    Examples:
        >>> extract_document_id_from_artifact_key(
        ...     "org123/550e8400-e29b-41d4-a716-446655440000/uploaded/file.pdf"
        ... )
        '550e8400-e29b-41d4-a716-446655440000'
        >>> extract_document_id_from_artifact_key("invalid/key")
        None
    """
    if not key or not isinstance(key, str):
        return None

    parts = key.split('/')
    if len(parts) < 3:
        return None

    # Document ID should be the second part (after org_id)
    potential_doc_id = parts[1]

    if is_valid_document_id(potential_doc_id, allow_legacy=True):
        return potential_doc_id.lower()

    return None
