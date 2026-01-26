"""
Tests for document ID validators.

Tests the validation utilities in app.utils.validators to ensure proper
validation of UUID and legacy document ID formats.
"""

import pytest
from app.utils.validators import (
    is_valid_uuid,
    is_legacy_document_id,
    is_valid_document_id,
    detect_file_path_pattern,
    validate_document_id,
    generate_document_id,
    extract_document_id_from_artifact_key,
)


class TestIsValidUuid:
    """Tests for is_valid_uuid function."""

    def test_valid_uuid_lowercase(self):
        """Test valid UUID in lowercase."""
        assert is_valid_uuid("550e8400-e29b-41d4-a716-446655440000") is True

    def test_valid_uuid_uppercase(self):
        """Test valid UUID in uppercase."""
        assert is_valid_uuid("550E8400-E29B-41D4-A716-446655440000") is True

    def test_valid_uuid_mixed_case(self):
        """Test valid UUID in mixed case."""
        assert is_valid_uuid("550e8400-E29B-41d4-A716-446655440000") is True

    def test_invalid_uuid_wrong_length(self):
        """Test invalid UUID with wrong length."""
        assert is_valid_uuid("550e8400-e29b-41d4-a716") is False
        assert is_valid_uuid("550e8400-e29b-41d4-a716-446655440000-extra") is False

    def test_invalid_uuid_no_hyphens(self):
        """Test invalid UUID without hyphens."""
        assert is_valid_uuid("550e8400e29b41d4a716446655440000") is False

    def test_invalid_uuid_wrong_format(self):
        """Test invalid UUID with wrong format."""
        assert is_valid_uuid("not-a-uuid-at-all-here") is False

    def test_empty_string(self):
        """Test empty string."""
        assert is_valid_uuid("") is False

    def test_none_value(self):
        """Test None value."""
        assert is_valid_uuid(None) is False


class TestIsLegacyDocumentId:
    """Tests for is_legacy_document_id function."""

    def test_valid_legacy_lowercase(self):
        """Test valid legacy format in lowercase."""
        assert is_legacy_document_id("doc_abc123def456") is True

    def test_valid_legacy_uppercase(self):
        """Test valid legacy format in uppercase."""
        assert is_legacy_document_id("doc_ABC123DEF456") is True

    def test_valid_legacy_mixed_case(self):
        """Test valid legacy format in mixed case."""
        assert is_legacy_document_id("doc_AbC123DeF456") is True

    def test_invalid_legacy_wrong_length(self):
        """Test invalid legacy format with wrong length."""
        assert is_legacy_document_id("doc_short") is False
        assert is_legacy_document_id("doc_toolongvalue123") is False

    def test_invalid_legacy_wrong_prefix(self):
        """Test invalid legacy format with wrong prefix."""
        assert is_legacy_document_id("file_abc123def456") is False
        assert is_legacy_document_id("docdabc123def456") is False

    def test_invalid_legacy_no_prefix(self):
        """Test invalid legacy format without prefix."""
        assert is_legacy_document_id("abc123def456") is False

    def test_empty_string(self):
        """Test empty string."""
        assert is_legacy_document_id("") is False

    def test_none_value(self):
        """Test None value."""
        assert is_legacy_document_id(None) is False


class TestIsValidDocumentId:
    """Tests for is_valid_document_id function."""

    def test_valid_uuid(self):
        """Test valid UUID format."""
        assert is_valid_document_id("550e8400-e29b-41d4-a716-446655440000") is True

    def test_valid_legacy_with_allow(self):
        """Test valid legacy format with allow_legacy=True."""
        assert is_valid_document_id("doc_abc123def456", allow_legacy=True) is True

    def test_valid_legacy_without_allow(self):
        """Test valid legacy format with allow_legacy=False."""
        assert is_valid_document_id("doc_abc123def456", allow_legacy=False) is False

    def test_invalid_format(self):
        """Test invalid document ID format."""
        assert is_valid_document_id("invalid-format") is False
        assert is_valid_document_id("123456") is False

    def test_file_path_rejected(self):
        """Test file path patterns are rejected."""
        assert is_valid_document_id("folder/file.pdf") is False
        assert is_valid_document_id("../etc/passwd") is False

    def test_empty_string(self):
        """Test empty string."""
        assert is_valid_document_id("") is False


class TestDetectFilePathPattern:
    """Tests for detect_file_path_pattern function."""

    def test_forward_slash(self):
        """Test detection of forward slash."""
        assert detect_file_path_pattern("folder/file.pdf") is True

    def test_backward_slash(self):
        """Test detection of backward slash."""
        assert detect_file_path_pattern("folder\\file.pdf") is True

    def test_parent_directory(self):
        """Test detection of parent directory reference."""
        assert detect_file_path_pattern("../etc/passwd") is True

    def test_file_extension(self):
        """Test detection of common file extensions."""
        assert detect_file_path_pattern("document.pdf") is True
        assert detect_file_path_pattern("file.docx") is True
        assert detect_file_path_pattern("data.txt") is True

    def test_valid_uuid_not_detected(self):
        """Test UUID is not detected as file path."""
        assert detect_file_path_pattern("550e8400-e29b-41d4-a716-446655440000") is False

    def test_valid_legacy_not_detected(self):
        """Test legacy format is not detected as file path."""
        assert detect_file_path_pattern("doc_abc123def456") is False

    def test_empty_string(self):
        """Test empty string."""
        assert detect_file_path_pattern("") is False


class TestValidateDocumentId:
    """Tests for validate_document_id function."""

    def test_valid_uuid_normalized(self):
        """Test valid UUID is normalized to lowercase."""
        result = validate_document_id("550E8400-E29B-41D4-A716-446655440000")
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_valid_legacy_normalized(self):
        """Test valid legacy format is normalized to lowercase."""
        result = validate_document_id("doc_ABC123DEF456")
        assert result == "doc_abc123def456"

    def test_whitespace_stripped(self):
        """Test whitespace is stripped."""
        result = validate_document_id("  550e8400-e29b-41d4-a716-446655440000  ")
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_file_path_rejected(self):
        """Test file path pattern raises ValueError."""
        with pytest.raises(ValueError, match="appears to be a file path"):
            validate_document_id("folder/file.pdf")

    def test_invalid_format_raises(self):
        """Test invalid format raises ValueError."""
        with pytest.raises(ValueError, match="must be a valid UUID"):
            validate_document_id("invalid-format")

    def test_empty_string_raises(self):
        """Test empty string raises ValueError."""
        with pytest.raises(ValueError, match="must be a non-empty string"):
            validate_document_id("")

    def test_legacy_rejected_when_not_allowed(self):
        """Test legacy format is rejected when allow_legacy=False."""
        with pytest.raises(ValueError, match="must be a valid UUID"):
            validate_document_id("doc_abc123def456", allow_legacy=False)

    def test_file_path_allowed_when_not_rejected(self):
        """Test file path is allowed when reject_file_paths=False."""
        # Note: This should still fail due to invalid format, not file path detection
        with pytest.raises(ValueError, match="must be a valid UUID"):
            validate_document_id("document.pdf", reject_file_paths=False)


class TestGenerateDocumentId:
    """Tests for generate_document_id function."""

    def test_generates_valid_uuid(self):
        """Test generated document ID is valid UUID."""
        doc_id = generate_document_id()
        assert is_valid_uuid(doc_id) is True

    def test_generates_unique_ids(self):
        """Test multiple generated IDs are unique."""
        ids = {generate_document_id() for _ in range(100)}
        assert len(ids) == 100  # All should be unique

    def test_generates_lowercase(self):
        """Test generated IDs are lowercase."""
        doc_id = generate_document_id()
        assert doc_id == doc_id.lower()


class TestExtractDocumentIdFromArtifactKey:
    """Tests for extract_document_id_from_artifact_key function."""

    def test_valid_key_with_uuid(self):
        """Test extraction from valid key with UUID."""
        key = "org123/550e8400-e29b-41d4-a716-446655440000/uploaded/file.pdf"
        result = extract_document_id_from_artifact_key(key)
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_valid_key_with_legacy(self):
        """Test extraction from valid key with legacy format."""
        key = "org123/doc_abc123def456/processed/output.md"
        result = extract_document_id_from_artifact_key(key)
        assert result == "doc_abc123def456"

    def test_uppercase_normalized(self):
        """Test uppercase document ID is normalized."""
        key = "org123/550E8400-E29B-41D4-A716-446655440000/uploaded/file.pdf"
        result = extract_document_id_from_artifact_key(key)
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_invalid_key_too_short(self):
        """Test invalid key with too few parts."""
        assert extract_document_id_from_artifact_key("org123/file.pdf") is None

    def test_invalid_key_bad_document_id(self):
        """Test invalid key with bad document ID."""
        key = "org123/invalid-doc-id/uploaded/file.pdf"
        assert extract_document_id_from_artifact_key(key) is None

    def test_empty_string(self):
        """Test empty string."""
        assert extract_document_id_from_artifact_key("") is None

    def test_none_value(self):
        """Test None value."""
        assert extract_document_id_from_artifact_key(None) is None
