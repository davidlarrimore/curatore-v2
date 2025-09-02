# backend/tests/test_v2_documents_processing.py
import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from datetime import datetime

from app.main import app
from app.services.document_service import document_service
from app.services.storage_service import storage_service
from app.models import ProcessingResult, ConversionResult, LLMEvaluation as LLMEvaluationResult


class TestV2DocumentsProcessingEndpoint:
    """Test suite for the missing V2 single document processing endpoint."""
    
    @pytest.fixture
    def client(self):
        """FastAPI test client."""
        return TestClient(app)
    
    @pytest.fixture
    def mock_document_file(self):
        """Create a temporary test document."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test document content for processing.")
            temp_path = f.name
        yield Path(temp_path)
        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    
    @pytest.fixture
    def mock_processing_result(self):
        """Mock processing result for tests."""
        return ProcessingResult(
            document_id="test-doc-123",
            filename="test_document.txt",
            original_path=Path("/tmp/test.txt"),
            markdown_path=Path("/tmp/test.md"),
            conversion_result=ConversionResult(
                conversion_score=85,
                content_coverage=0.95,
                structure_preservation=0.80,
                readability_score=0.90,
                total_characters=500,
                extracted_characters=475,
                processing_time=2.5,
                conversion_notes=["Successfully converted"]
            ),
            llm_evaluation=LLMEvaluationResult(
                clarity_score=8,
                completeness_score=9,
                relevance_score=8,
                markdown_score=9,
                overall_feedback="Well-structured document",
                processing_time=1.2,
                token_usage={"prompt": 100, "completion": 50}
            ),
            vector_optimized=True,
            is_rag_ready=True,
            processed_at=datetime.now(),
            processing_metadata={"version": "v2"}
        )
    
    def test_process_document_endpoint_exists(self, client):
        """Test that the previously missing endpoint now exists."""
        # This should NOT return 404 anymore
        response = client.post("/api/v2/documents/nonexistent-doc/process")
        # Should return 404 for missing document, not 404 for missing endpoint
        assert response.status_code == 404
        assert "Document not found" in response.json()["detail"]
    
    @patch('app.api.v2.routers.documents.document_service')
    @patch('app.api.v2.routers.documents.process_document_task')
    @patch('app.api.v2.routers.documents.set_active_job')
    @patch('app.api.v2.routers.documents.record_job_status')
    @patch('app.api.v2.routers.documents.append_job_log')
    def test_process_document_success(
        self, 
        mock_append_log,
        mock_record_status, 
        mock_set_job,
        mock_task,
        mock_doc_service,
        client,
        mock_document_file
    ):
        """Test successful document processing request."""
        # Setup mocks
        mock_doc_service.find_uploaded_file.return_value = mock_document_file
        mock_doc_service.find_batch_file.return_value = None
        
        mock_async_result = MagicMock()
        mock_async_result.id = "task-123"
        mock_task.apply_async.return_value = mock_async_result
        
        mock_set_job.return_value = True  # Job lock acquired successfully
        
        # Test request
        response = client.post(
            "/api/v2/documents/test-doc-123/process",
            json={
                # ProcessingOptions fields (domain model)
                "auto_improve": True,
                "vector_optimize": True,
                "quality_thresholds": {
                    # QualityThresholds fields (domain model)
                    "conversion_quality": 75,
                    "clarity_score": 7
                }
            }
        )
        
        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "task-123"
        assert data["document_id"] == "test-doc-123"
        assert data["status"] == "queued"
        assert "enqueued_at" in data
        
        # Verify service calls
        mock_doc_service.find_uploaded_file.assert_called_once_with("test-doc-123")
        mock_task.apply_async.assert_called_once()
        mock_set_job.assert_called_once()
        mock_record_status.assert_called_once()
        mock_append_log.assert_called_once()
    
    @patch('app.api.v2.routers.documents.document_service')
    def test_process_document_not_found(self, mock_doc_service, client):
        """Test processing request for nonexistent document."""
        # Setup: no file found in either location
        mock_doc_service.find_uploaded_file.return_value = None
        mock_doc_service.find_batch_file_by_document_id.return_value = None
        
        response = client.post("/api/v2/documents/nonexistent/process")
        
        assert response.status_code == 404
        assert "Document not found" in response.json()["detail"]
    
    @patch('app.api.v2.routers.documents.document_service')
    @patch('app.api.v2.routers.documents.process_document_task')
    @patch('app.api.v2.routers.documents.set_active_job')
    @patch('app.api.v2.routers.documents.get_active_job_for_document')
    def test_process_document_job_conflict(
        self,
        mock_get_active_job,
        mock_set_job,
        mock_task,
        mock_doc_service,
        client,
        mock_document_file
    ):
        """Test processing request when document already has an active job."""
        # Setup mocks
        mock_doc_service.find_uploaded_file.return_value = mock_document_file
        
        mock_async_result = MagicMock()
        mock_async_result.id = "task-123"
        mock_task.apply_async.return_value = mock_async_result
        
        mock_set_job.return_value = False  # Job lock acquisition failed
        mock_get_active_job.return_value = "existing-job-456"
        
        # Test request
        response = client.post("/api/v2/documents/test-doc-123/process")
        
        # Assertions
        assert response.status_code == 409
        data = response.json()
        assert data["error"] == "Another job is already running for this document"
        assert data["active_job_id"] == "existing-job-456"
        assert data["status"] == "conflict"
    
    @patch.dict(os.environ, {"ALLOW_SYNC_PROCESS": "true"})
    @patch('app.api.v2.routers.documents.document_service')
    @patch('app.api.v2.routers.documents.storage_service')
    def test_process_document_sync_mode(
        self,
        mock_storage_service,
        mock_doc_service,
        client,
        mock_document_file,
        mock_processing_result
    ):
        """Test synchronous processing mode (for testing)."""
        # Setup mocks
        mock_doc_service.find_uploaded_file.return_value = mock_document_file
        mock_doc_service.process_document = AsyncMock(return_value=mock_processing_result)
        mock_storage_service.save_processing_result.return_value = None
        
        # Test sync request
        response = client.post(
            "/api/v2/documents/test-doc-123/process",
            params={"sync": "true"}
        )
        
        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["document_id"] == "test-doc-123"
        assert data["filename"] == "test_document.txt"
        assert "conversion_result" in data
        assert "llm_evaluation" in data
        
        # Verify sync processing was called
        mock_doc_service.process_document.assert_called_once()
        mock_storage_service.save_processing_result.assert_called_once()
    
    @patch('app.api.v2.routers.documents.document_service')
    def test_process_document_finds_batch_file(self, mock_doc_service, client, mock_document_file):
        """Test that processing finds file in batch_files directory when not in uploads."""
        # Setup: not in uploads, but in batch_files
        mock_doc_service.find_uploaded_file.return_value = None
        mock_doc_service.find_batch_file_by_document_id.return_value = mock_document_file
        
        with patch('app.api.v2.routers.documents.process_document_task') as mock_task, \
             patch('app.api.v2.routers.documents.set_active_job', return_value=True), \
             patch('app.api.v2.routers.documents.record_job_status'), \
             patch('app.api.v2.routers.documents.append_job_log'):
            
            mock_async_result = MagicMock()
            mock_async_result.id = "task-456"
            mock_task.apply_async.return_value = mock_async_result
            
            response = client.post("/api/v2/documents/batch-doc-123/process")
            
            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "task-456"
            assert data["document_id"] == "batch-doc-123"
            
            # Verify it checked both locations
            mock_doc_service.find_uploaded_file.assert_called_once_with("batch-doc-123")
            mock_doc_service.find_batch_file_by_document_id.assert_called_once_with("batch-doc-123")
    
    def test_process_document_options_handling(self, client):
        """Test that processing options are properly handled."""
        with patch('app.api.v2.routers.documents.document_service') as mock_doc_service, \
             patch('app.api.v2.routers.documents.process_document_task') as mock_task, \
             patch('app.api.v2.routers.documents.set_active_job', return_value=True), \
             patch('app.api.v2.routers.documents.record_job_status'), \
             patch('app.api.v2.routers.documents.append_job_log'):
            
            # Setup mocks
            mock_doc_service.find_uploaded_file.return_value = Path("/tmp/test.txt")
            
            mock_async_result = MagicMock()
            mock_async_result.id = "task-options-test"
            mock_task.apply_async.return_value = mock_async_result
            
            # Test with complex processing options
            processing_options = {
                # Match app.models.ProcessingOptions
                "auto_improve": True,
                "vector_optimize": True,
                "quality_thresholds": {
                    "conversion_quality": 80,
                    "clarity_score": 8,
                    "completeness_score": 7,
                    "relevance_score": 8,
                    "markdown_quality": 9
                },
                "ocr_settings": {
                    "language": "eng",
                    "psm": 6
                },
                # Router accepts options; extra testing field is ignored in domain model
                "llm_prompt_override": "Custom analysis prompt"
            }
            
            response = client.post(
                "/api/v2/documents/test-options/process",
                json=processing_options
            )
            
            assert response.status_code == 200
            
            # Verify options were passed to the task
            mock_task.apply_async.assert_called_once()
            call_args = mock_task.apply_async.call_args
            
            # Check that document_id and options were passed correctly
            assert call_args[1]['args'][0] == "test-options"  # document_id
            passed_options = call_args[1]['args'][1]  # options dict
            assert passed_options["auto_improve"] is True
            assert passed_options["vector_optimize"] is True
            assert passed_options["quality_thresholds"]["conversion_quality"] == 80
            # Extra field is forwarded as part of options dict
            assert passed_options["llm_prompt_override"] == "Custom analysis prompt"


class TestV2DocumentsEndpointIntegration:
    """Integration tests for the complete V2 documents processing flow."""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    def test_upload_and_process_flow(self, client):
        """Test the complete upload -> process flow using v2 endpoints."""
        with patch('app.api.v2.routers.documents.document_service') as mock_doc_service, \
             patch('app.api.v2.routers.documents.process_document_task') as mock_task, \
             patch('app.api.v2.routers.documents.set_active_job', return_value=True), \
             patch('app.api.v2.routers.documents.record_job_status'), \
             patch('app.api.v2.routers.documents.append_job_log'):
            
            # Mock upload response
            mock_doc_service.save_uploaded_file = AsyncMock(
                return_value=("uploaded-doc-789", Path("/uploads/test.txt"))
            )
            mock_doc_service.is_supported_file.return_value = True
            
            # Mock processing setup
            mock_doc_service.find_uploaded_file.return_value = Path("/uploads/test.txt")
            mock_async_result = MagicMock()
            mock_async_result.id = "integration-task-123"
            mock_task.apply_async.return_value = mock_async_result
            
            # Step 1: Upload document
            upload_response = client.post(
                "/api/v2/documents/upload",
                files={"file": ("test.txt", b"Test content", "text/plain")}
            )
            
            assert upload_response.status_code == 200
            upload_data = upload_response.json()
            document_id = upload_data["document_id"]
            
            # Step 2: Process uploaded document
            process_response = client.post(
                f"/api/v2/documents/{document_id}/process",
                json={"auto_optimize": True}
            )
            
            assert process_response.status_code == 200
            process_data = process_response.json()
            assert process_data["document_id"] == document_id
            assert process_data["status"] == "queued"
            assert "job_id" in process_data
            
            # Verify the complete flow worked
            mock_doc_service.save_uploaded_file.assert_called_once()
            mock_doc_service.find_uploaded_file.assert_called_once_with(document_id)
            mock_task.apply_async.assert_called_once()
    
    def test_process_nonexistent_after_upload_delete(self, client):
        """Test processing fails correctly when document is deleted after upload."""
        with patch('app.api.v2.routers.documents.document_service') as mock_doc_service:
            
            # Simulate: document was uploaded but then deleted
            mock_doc_service.find_uploaded_file.return_value = None
            mock_doc_service.find_batch_file.return_value = None
            
            response = client.post("/api/v2/documents/deleted-doc/process")
            
            assert response.status_code == 404
            assert "Document not found" in response.json()["detail"]
    
    @patch('app.api.v2.routers.documents.os.getenv')
    def test_celery_queue_configuration(self, mock_getenv, client):
        """Test that Celery queue is configured correctly."""
        with patch('app.api.v2.routers.documents.document_service') as mock_doc_service, \
             patch('app.api.v2.routers.documents.process_document_task') as mock_task, \
             patch('app.api.v2.routers.documents.set_active_job', return_value=True), \
             patch('app.api.v2.routers.documents.record_job_status'), \
             patch('app.api.v2.routers.documents.append_job_log'):
            
            # Setup environment variable mock
            mock_getenv.return_value = "custom-processing-queue"
            
            mock_doc_service.find_uploaded_file.return_value = Path("/tmp/test.txt")
            mock_async_result = MagicMock()
            mock_async_result.id = "queue-test-task"
            mock_task.apply_async.return_value = mock_async_result
            
            response = client.post("/api/v2/documents/queue-test/process")
            
            assert response.status_code == 200
            
            # Verify correct queue was used
            mock_task.apply_async.assert_called_once()
            call_kwargs = mock_task.apply_async.call_args[1]
            assert call_kwargs["queue"] == "custom-processing-queue"


class TestV2DocumentsErrorHandling:
    """Test error handling scenarios for V2 documents processing."""
    
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    @patch('app.api.v2.routers.documents.document_service')
    @patch('app.api.v2.routers.documents.process_document_task')
    def test_task_creation_failure(self, mock_task, mock_doc_service, client):
        """Test handling when Celery task creation fails."""
        mock_doc_service.find_uploaded_file.return_value = Path("/tmp/test.txt")
        
        # Simulate task creation failure
        mock_task.apply_async.side_effect = Exception("Celery broker unavailable")
        
        response = client.post("/api/v2/documents/task-fail-test/process")
        
        # Should return 500 with error details
        assert response.status_code == 500
        assert "Celery broker unavailable" in response.json()["detail"]
    
    @patch('app.api.v2.routers.documents.document_service')
    @patch('app.api.v2.routers.documents.process_document_task')
    @patch('app.api.v2.routers.documents.set_active_job')
    def test_job_lock_failure_with_revoke(self, mock_set_job, mock_task, mock_doc_service, client):
        """Test job lock failure with proper task revocation."""
        mock_doc_service.find_uploaded_file.return_value = Path("/tmp/test.txt")
        
        mock_async_result = MagicMock()
        mock_async_result.id = "revoke-test-task"
        mock_task.apply_async.return_value = mock_async_result
        
        # Job lock fails
        mock_set_job.return_value = False
        
        with patch('app.api.v2.routers.documents.get_active_job_for_document', return_value="existing-job"), \
             patch('app.api.v2.routers.documents.celery_app') as mock_celery_app:
            
            response = client.post("/api/v2/documents/revoke-test/process")
            
            assert response.status_code == 409
            
            # Verify task was revoked
            mock_celery_app.control.revoke.assert_called_once_with("revoke-test-task", terminate=False)


# Test fixtures and utilities
@pytest.fixture(scope="session")
def temp_test_dir():
    """Create a temporary directory for test files."""
    import tempfile
    import shutil
    
    temp_dir = tempfile.mkdtemp(prefix="test_v2_docs_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    # Run tests with: python -m pytest backend/tests/test_v2_documents_processing.py -v
    pytest.main([__file__, "-v"])
