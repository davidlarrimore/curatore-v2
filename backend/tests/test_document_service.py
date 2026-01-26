# tests/test_document_service.py
#
# NOTE: Many tests in this file are DEPRECATED as they test filesystem storage methods
# that have been removed. These tests need to be updated or removed:
# - save_uploaded_file() - DELETED
# - list_uploaded_files_with_metadata() - DELETED
# - list_batch_files_with_metadata() - DELETED
# - clear_runtime_files() - DELETED
# - find_document_file_unified() - DELETED
#
# New tests should focus on:
# - Object storage integration via MinIO
# - Artifact tracking via artifact_service
# - Document processing with presigned URLs
#
import pytest
import tempfile
import os
import time
from pathlib import Path
from unittest.mock import patch, Mock
from datetime import datetime

from app.services.document_service import DocumentService
from app.models import FileInfo


class TestDocumentServiceFileListFix:
    """Tests for the fixed document service file listing functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def document_service(self, temp_dir):
        """Create a document service instance with temporary directories."""
        with patch('app.services.document_service.settings') as mock_settings:
            # Mock settings to use our temporary directory
            mock_settings.files_root = str(temp_dir)
            mock_settings.upload_dir = "uploaded_files"
            mock_settings.processed_dir = "processed_files"
            mock_settings.batch_dir = "batch_files"
            mock_settings.supported_file_extensions = [".pdf", ".docx", ".txt"]
            
            service = DocumentService()
            return service

    def create_test_file(self, directory: Path, filename: str, content: str = "test content") -> Path:
        """Helper to create a test file."""
        directory.mkdir(parents=True, exist_ok=True)
        file_path = directory / filename
        file_path.write_text(content)
        return file_path

    def test_list_files_for_api_format(self, document_service, temp_dir):
        """Test that _list_files_for_api returns correctly formatted data for FileInfo model."""
        # Create test files in upload directory
        upload_dir = temp_dir / "uploaded_files"
        test_files = [
            "abc123_test_document.pdf",
            "def456_another_file.docx",
            "ghi789_text_file.txt"
        ]
        
        created_files = []
        for filename in test_files:
            file_path = self.create_test_file(upload_dir, filename, "test content for " + filename)
            created_files.append(file_path)
        
        # Get file list from service
        result = document_service._list_files_for_api(upload_dir, "uploaded")
        
        # Verify we get the expected number of files
        assert len(result) == 3
        
        # Test the structure of each file entry
        for i, file_info in enumerate(result):
            # Verify all required fields are present
            assert "document_id" in file_info
            assert "filename" in file_info  # This was missing before the fix
            assert "original_filename" in file_info
            assert "file_size" in file_info
            assert "upload_time" in file_info
            assert "file_path" in file_info
            
            # Verify field types and values
            assert isinstance(file_info["document_id"], str)
            assert isinstance(file_info["filename"], str)
            assert isinstance(file_info["original_filename"], str)
            assert isinstance(file_info["file_size"], int)
            assert isinstance(file_info["upload_time"], int)  # Should be int, not string
            assert isinstance(file_info["file_path"], str)
            
            # Verify file_size is positive
            assert file_info["file_size"] > 0
            
            # Verify upload_time is a reasonable timestamp
            assert file_info["upload_time"] > 1000000000  # Should be after 2001
            assert file_info["upload_time"] < 2000000000  # Should be before 2033
            
            # Verify filename parsing
            expected_doc_id = test_files[i].split("_")[0]
            expected_filename = "_".join(test_files[i].split("_")[1:])
            assert file_info["document_id"] == expected_doc_id
            assert file_info["filename"] == expected_filename
            assert file_info["original_filename"] == expected_filename

    def test_list_uploaded_files_with_metadata(self, document_service, temp_dir):
        """Test the public method that returns uploaded files metadata."""
        # Create test files
        upload_dir = temp_dir / "uploaded_files"
        self.create_test_file(upload_dir, "abc123_test.pdf")
        self.create_test_file(upload_dir, "def456_example.docx")
        
        # Call the public method
        result = document_service.list_uploaded_files_with_metadata()
        
        # Verify result
        assert len(result) == 2
        
        # Test that this can be used to create FileInfo objects
        for file_data in result:
            # This should not raise validation errors
            file_info = FileInfo(**file_data)
            assert file_info.document_id
            assert file_info.filename
            assert file_info.file_size > 0
            assert file_info.upload_time > 0

    def test_upload_time_as_integer_not_string(self, document_service, temp_dir):
        """Test that upload_time is returned as integer timestamp, not ISO string."""
        # Create a test file
        upload_dir = temp_dir / "uploaded_files"
        test_file = self.create_test_file(upload_dir, "test123_sample.pdf")
        
        # Get the file's modification time
        expected_timestamp = int(test_file.stat().st_mtime)
        
        result = document_service._list_files_for_api(upload_dir, "uploaded")
        
        assert len(result) == 1
        file_info = result[0]
        
        # Verify upload_time is an integer timestamp
        assert isinstance(file_info["upload_time"], int)
        assert file_info["upload_time"] == expected_timestamp
        
        # Verify it's NOT a string (this was the bug)
        assert not isinstance(file_info["upload_time"], str)

    def test_pydantic_validation_compatibility(self, document_service, temp_dir):
        """Test that the returned data is compatible with FileInfo Pydantic model validation."""
        # Create test file
        upload_dir = temp_dir / "uploaded_files"
        self.create_test_file(upload_dir, "test123_validation_test.pdf", "test content for validation")
        
        result = document_service.list_uploaded_files_with_metadata()
        assert len(result) == 1
        
        file_data = result[0]
        
        # This should not raise any validation errors
        try:
            file_info = FileInfo(**file_data)
            assert file_info.document_id == "test123"
            assert file_info.filename == "validation_test.pdf"
            assert file_info.original_filename == "validation_test.pdf"
            assert file_info.file_size > 0
            assert file_info.upload_time > 0
            assert file_info.file_path == "test123_validation_test.pdf"
        except Exception as e:
            pytest.fail(f"FileInfo validation failed: {e}")

    def test_empty_directory(self, document_service, temp_dir):
        """Test behavior with empty directory."""
        upload_dir = temp_dir / "uploaded_files"
        upload_dir.mkdir(parents=True, exist_ok=True)
        
        result = document_service._list_files_for_api(upload_dir, "uploaded")
        assert result == []

    def test_nonexistent_directory(self, document_service, temp_dir):
        """Test behavior with nonexistent directory."""
        nonexistent_dir = temp_dir / "nonexistent"
        
        result = document_service._list_files_for_api(nonexistent_dir, "uploaded")
        assert result == []

    def test_unsupported_file_types_filtered(self, document_service, temp_dir):
        """Test that unsupported file types are filtered out."""
        upload_dir = temp_dir / "uploaded_files"
        
        # Create supported and unsupported files
        self.create_test_file(upload_dir, "test123_document.pdf")  # Supported
        self.create_test_file(upload_dir, "test456_image.png")     # Not in our mock supported extensions
        self.create_test_file(upload_dir, "test789_text.txt")      # Supported


def test_document_service_sets_processed_dir():
    service = DocumentService()
    assert hasattr(service, "processed_dir")
    assert service.processed_dir.exists()
        
        result = document_service._list_files_for_api(upload_dir, "uploaded")
        
        # Should only return supported file types
        assert len(result) == 2
        filenames = [f["filename"] for f in result]
        assert "document.pdf" in filenames
        assert "text.txt" in filenames
        assert "image.png" not in filenames

    def test_file_without_document_id_prefix(self, document_service, temp_dir):
        """Test handling of files that don't follow the document_id_filename pattern."""
        upload_dir = temp_dir / "uploaded_files"
        self.create_test_file(upload_dir, "no_underscore.pdf")
        
        result = document_service._list_files_for_api(upload_dir, "uploaded")
        
        assert len(result) == 1
        file_info = result[0]
        assert file_info["document_id"] == ""  # Should be empty string
        assert file_info["filename"] == "no_underscore.pdf"
        assert file_info["original_filename"] == "no_underscore.pdf"

    def test_legacy_methods_compatibility(self, document_service, temp_dir):
        """Test that legacy list methods still work for v1 API compatibility."""
        upload_dir = temp_dir / "uploaded_files"
        self.create_test_file(upload_dir, "test123_legacy.pdf")
        
        # Test legacy method
        result = document_service.list_uploaded_files()
        
        assert len(result) == 1
        file_info = result[0]
        
        # Legacy format should have ISO timestamp string
        assert isinstance(file_info["upload_time"], str)
        assert "T" in file_info["upload_time"]  # ISO format
        assert file_info["ext"] == ".pdf"

    @patch('builtins.print')  # Mock print to capture warning messages
    def test_error_handling_for_corrupted_files(self, mock_print, document_service, temp_dir):
        """Test error handling when file processing fails."""
        upload_dir = temp_dir / "uploaded_files"
        upload_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a valid file
        good_file = self.create_test_file(upload_dir, "good123_file.pdf")
        
        # Create a file then delete it to simulate a stat error
        bad_file_path = upload_dir / "bad456_file.pdf"
        bad_file_path.write_text("content")
        
        # Mock stat to raise an exception for the bad file
        original_stat = Path.stat
        def mock_stat(self, *args, **kwargs):
            if self.name == "bad456_file.pdf":
                raise OSError("Simulated file access error")
            return original_stat(self, *args, **kwargs)
        
        with patch.object(Path, 'stat', mock_stat):
            result = document_service._list_files_for_api(upload_dir, "uploaded")
            
        # Should get only the good file, bad file should be skipped
        assert len(result) == 1
        assert result[0]["filename"] == "file.pdf"
        
        # Should have printed warning
        mock_print.assert_called_once()
        assert "Warning: Error processing file bad456_file.pdf" in str(mock_print.call_args)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
