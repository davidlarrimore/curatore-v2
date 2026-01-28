"""
Document ID validation utilities for Curatore v2.

Provides centralized validation logic for document identifiers.
All document IDs must be valid UUIDs (36 characters with hyphens).

Usage:
    from app.utils.validators import validate_document_id, is_valid_uuid

    # Validate document ID (must be UUID)
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


def is_valid_document_id(value: str) -> bool:
    """
    Check if a string is a valid document ID (UUID format only).

    Args:
        value: String to validate

    Returns:
        True if valid UUID, False otherwise

    Examples:
        >>> is_valid_document_id("550e8400-e29b-41d4-a716-446655440000")
        True
        >>> is_valid_document_id("not-a-uuid")
        False
    """
    if not value or not isinstance(value, str):
        return False

    return is_valid_uuid(value)


def validate_document_id(value: str) -> str:
    """
    Validate and normalize a document ID.

    All document IDs must be valid UUIDs.

    Args:
        value: Document ID to validate

    Returns:
        Validated document ID (normalized to lowercase)

    Raises:
        ValueError: If document ID is not a valid UUID

    Examples:
        >>> validate_document_id("550E8400-E29B-41D4-A716-446655440000")
        '550e8400-e29b-41d4-a716-446655440000'
        >>> validate_document_id("not-a-uuid")
        Traceback (most recent call last):
        ValueError: Document ID must be a valid UUID
    """
    if not value or not isinstance(value, str):
        raise ValueError("Document ID must be a non-empty string")

    # Strip whitespace
    value = value.strip()

    if not value:
        raise ValueError("Document ID must be a non-empty string")

    # Validate UUID format
    if not is_valid_uuid(value):
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
    - New format: {org_id}/uploads/{document_id}-{filename}
    - Old format: {org_id}/{document_id}/uploaded/{filename} (legacy)
    - Old format: {org_id}/{document_id}/processed/{filename} (legacy)

    Args:
        key: Storage key to parse

    Returns:
        Extracted document ID if found and valid, None otherwise

    Examples:
        >>> extract_document_id_from_artifact_key(
        ...     "org123/uploads/550e8400-e29b-41d4-a716-446655440000-file.pdf"
        ... )
        '550e8400-e29b-41d4-a716-446655440000'
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

    # Check if new format: {org_id}/uploads/{document_id}-{filename}
    if parts[1] == 'uploads':
        # Extract UUID from filename prefix (first 36 characters)
        filename = parts[2]
        if len(filename) >= 36:
            potential_doc_id = filename[:36]
            if is_valid_uuid(potential_doc_id):
                return potential_doc_id.lower()

    # Check if old format: {org_id}/{document_id}/uploaded|processed/{filename}
    # Document ID should be the second part (after org_id)
    potential_doc_id = parts[1]
    if is_valid_uuid(potential_doc_id):
        return potential_doc_id.lower()

    return None
