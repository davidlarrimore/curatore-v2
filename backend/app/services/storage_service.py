# backend/app/services/storage_service.py
from typing import Dict, Optional, List
from ..models import ProcessingResult, BatchProcessingResult

class InMemoryStorage:
    """A simple in-memory storage service for processing results."""
    def __init__(self):
        self.processing_results: Dict[str, ProcessingResult] = {}
        self.batch_results: Dict[str, BatchProcessingResult] = {}

    def get_processing_result(self, document_id: str) -> Optional[ProcessingResult]:
        return self.processing_results.get(document_id)

    def get_all_processing_results(self) -> List[ProcessingResult]:
        return list(self.processing_results.values())

    def save_processing_result(self, result: ProcessingResult):
        self.processing_results[result.document_id] = result

    def delete_processing_result(self, document_id: str) -> bool:
        if document_id in self.processing_results:
            del self.processing_results[document_id]
            return True
        return False

    def get_batch_result(self, batch_id: str) -> Optional[BatchProcessingResult]:
        return self.batch_results.get(batch_id)

    def save_batch_result(self, result: BatchProcessingResult):
        self.batch_results[result.batch_id] = result
        for res in result.results:
            self.save_processing_result(res)

    def clear_all(self):
        self.processing_results.clear()
        self.batch_results.clear()

storage_service = InMemoryStorage()