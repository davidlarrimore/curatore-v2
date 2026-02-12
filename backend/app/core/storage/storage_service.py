# ============================================================================
# backend/app/services/storage_service.py
# ============================================================================
#
# In-Memory Storage Service for Curatore v2
#
# This module provides a simple in-memory storage solution for managing
# document processing results and batch processing results during the
# application lifecycle. All data is stored in RAM and will be lost when
# the application restarts.
#
# Key Features:
#   - Thread-safe in-memory storage for processing results
#   - CRUD operations for individual and batch processing results
#   - Automatic cross-referencing between batch and individual results
#   - Complete system reset functionality
#
# Author: Curatore v2 Development Team
# Version: 2.0.0
# ============================================================================

import json
import os
from typing import Dict, List, Optional

import redis

from app.core.models import BatchProcessingResult, ProcessingResult


class InMemoryStorage:
    """
    A simple in-memory storage service for document processing results.

    This service provides temporary storage for ProcessingResult and
    BatchProcessingResult objects during the application lifecycle. All data
    is stored in Python dictionaries and will be lost when the application
    restarts or the container is recreated.

    Thread Safety:
        This implementation is NOT thread-safe. If concurrent access is needed,
        external locking mechanisms should be implemented.

    Storage Structure:
        - processing_results: Dict[str, ProcessingResult] - Individual document results
        - batch_results: Dict[str, BatchProcessingResult] - Batch processing results

    Attributes:
        processing_results (Dict[str, ProcessingResult]): Storage for individual document results
        batch_results (Dict[str, BatchProcessingResult]): Storage for batch processing results
    """

    def __init__(self):
        """
        Initialize the in-memory storage with empty dictionaries.

        Creates two empty dictionaries to store processing results and batch results.
        This method is called once when the storage service is instantiated.
        """
        self.processing_results: Dict[str, ProcessingResult] = {}
        self.batch_results: Dict[str, BatchProcessingResult] = {}
        # Indices for organization, batch, and hash lookups
        self._org_index: Dict[str, List[str]] = {}  # org_id -> [doc_ids]
        self._batch_index: Dict[str, List[str]] = {}  # batch_id -> [doc_ids]
        self._hash_index: Dict[str, List[str]] = {}  # file_hash -> [doc_ids]

    def get_processing_result(self, document_id: str) -> Optional[ProcessingResult]:
        """
        Retrieve a processing result by document ID.

        Args:
            document_id (str): The unique identifier for the document

        Returns:
            Optional[ProcessingResult]: The processing result if found, None otherwise

        Example:
            >>> result = storage_service.get_processing_result("doc_123")
            >>> if result:
            >>>     print(f"Document status: {result.status}")
        """
        return self.processing_results.get(document_id)

    def get_all_processing_results(self) -> List[ProcessingResult]:
        """
        Retrieve all processing results as a list.

        Returns:
            List[ProcessingResult]: A list of all stored processing results.
                                  Returns empty list if no results exist.

        Note:
            The returned list is a snapshot and modifications to it will not
            affect the stored results.

        Example:
            >>> results = storage_service.get_all_processing_results()
            >>> successful_docs = [r for r in results if r.success]
        """
        return list(self.processing_results.values())

    def save_processing_result(self, result: ProcessingResult):
        """
        Save or update a processing result.

        Args:
            result (ProcessingResult): The processing result to store

        Note:
            If a result with the same document_id already exists, it will be
            overwritten with the new result.

        Example:
            >>> result = ProcessingResult(document_id="doc_123", ...)
            >>> storage_service.save_processing_result(result)
        """
        self.processing_results[result.document_id] = result
        # Track processed file path if available for downstream downloads
        try:
            path = getattr(result, 'markdown_path', None)
            if path:
                if not hasattr(self, '_processed_paths'):
                    self._processed_paths = {}
                self._processed_paths[result.document_id] = path
        except Exception:
            pass

    def delete_processing_result(self, document_id: str) -> bool:
        """
        Delete a processing result by document ID.

        Args:
            document_id (str): The unique identifier for the document to delete

        Returns:
            bool: True if the document was found and deleted, False if not found

        Example:
            >>> success = storage_service.delete_processing_result("doc_123")
            >>> if success:
            >>>     print("Document deleted successfully")
        """
        if document_id in self.processing_results:
            del self.processing_results[document_id]
            if hasattr(self, '_processed_paths') and document_id in self._processed_paths:
                try:
                    del self._processed_paths[document_id]
                except Exception:
                    pass
            return True
        return False

    def get_processed_path(self, document_id: str) -> Optional[str]:
        try:
            if hasattr(self, '_processed_paths'):
                return self._processed_paths.get(document_id)
            # Fallback: attempt to read from stored result
            res = self.get_processing_result(document_id)
            if res and getattr(res, 'markdown_path', None):
                return res.markdown_path
        except Exception:
            pass
        return None

    def get_batch_result(self, batch_id: str) -> Optional[BatchProcessingResult]:
        """
        Retrieve a batch processing result by batch ID.

        Args:
            batch_id (str): The unique identifier for the batch

        Returns:
            Optional[BatchProcessingResult]: The batch result if found, None otherwise

        Example:
            >>> batch_result = storage_service.get_batch_result("batch_456")
            >>> if batch_result:
            >>>     print(f"Processed {len(batch_result.results)} documents")
        """
        return self.batch_results.get(batch_id)

    def save_batch_result(self, result: BatchProcessingResult):
        """
        Save a batch processing result and all its individual results.

        This method performs two operations:
        1. Stores the batch result using the batch_id as the key
        2. Automatically stores all individual processing results from the batch

        Args:
            result (BatchProcessingResult): The batch processing result to store

        Side Effects:
            - Saves the batch result to batch_results
            - Saves each individual ProcessingResult to processing_results
            - May overwrite existing individual results with the same document_id

        Example:
            >>> batch_result = BatchProcessingResult(
            >>>     batch_id="batch_456",
            >>>     results=[result1, result2, result3]
            >>> )
            >>> storage_service.save_batch_result(batch_result)
        """
        self.batch_results[result.batch_id] = result
        for res in result.results:
            self.save_processing_result(res)

    def clear_all(self):
        """
        Clear all stored data from memory.

        This method removes all processing results and batch results from storage.
        This operation cannot be undone and all data will be permanently lost.

        Side Effects:
            - Clears processing_results dictionary
            - Clears batch_results dictionary
            - Frees memory used by stored results

        Use Cases:
            - Application startup/restart
            - System reset functionality
            - Testing cleanup

        Example:
            >>> storage_service.clear_all()
            >>> print(len(storage_service.get_all_processing_results()))  # Output: 0
        """
        self.processing_results.clear()
        self.batch_results.clear()
        if hasattr(self, '_org_index'):
            self._org_index.clear()
        if hasattr(self, '_batch_index'):
            self._batch_index.clear()
        if hasattr(self, '_hash_index'):
            self._hash_index.clear()

    def get_results_by_organization(self, organization_id: str) -> List[ProcessingResult]:
        """
        Get all processing results for a specific organization.

        Args:
            organization_id: Organization UUID

        Returns:
            List of processing results for the organization
        """
        if not hasattr(self, '_org_index'):
            return []

        doc_ids = self._org_index.get(organization_id, [])
        return [self.processing_results[doc_id] for doc_id in doc_ids if doc_id in self.processing_results]

    def get_results_by_batch(self, batch_id: str) -> List[ProcessingResult]:
        """
        Get all processing results for a specific batch.

        Args:
            batch_id: Batch UUID

        Returns:
            List of processing results for the batch
        """
        if not hasattr(self, '_batch_index'):
            return []

        doc_ids = self._batch_index.get(batch_id, [])
        return [self.processing_results[doc_id] for doc_id in doc_ids if doc_id in self.processing_results]

    def get_results_by_hash(self, file_hash: str) -> List[ProcessingResult]:
        """
        Get all processing results with a specific file hash (duplicates).

        Args:
            file_hash: File content hash (SHA-256)

        Returns:
            List of processing results with matching hash
        """
        if not hasattr(self, '_hash_index'):
            return []

        doc_ids = self._hash_index.get(file_hash, [])
        return [self.processing_results[doc_id] for doc_id in doc_ids if doc_id in self.processing_results]


# ============================================================================
# Global Storage Service Instance
# ============================================================================

# Create a single global instance of the storage service
# This ensures all parts of the application use the same storage instance
storage_service = InMemoryStorage()


# ----------------------------------------------------------------------------
# Optional Redis-backed storage (used when Celery is enabled)
# ----------------------------------------------------------------------------

class RedisStorage(InMemoryStorage):
    """
    Redis-backed storage following the same interface as InMemoryStorage.
    Stores serialized ProcessingResult and BatchProcessingResult for
    cross-process access (API and Celery workers).
    """

    def __init__(self):
        super().__init__()
        url = os.getenv("STORAGE_REDIS_URL") or os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
        self.r = redis.Redis.from_url(url)
        self.ttl = int(os.getenv("JOB_STATUS_TTL_SECONDS", "259200"))

    def _key_doc(self, doc_id: str) -> str:
        return f"storage:doc:{doc_id}"

    def _key_all_docs(self) -> str:
        return "storage:docs:index"

    def get_processing_result(self, document_id: str):  # type: ignore[override]
        raw = self.r.get(self._key_doc(document_id))
        if not raw:
            return super().get_processing_result(document_id)
        try:
            from app.api.v1.models import V1ProcessingResult
            data = json.loads(raw)
            return V1ProcessingResult(**data)
        except Exception:
            return super().get_processing_result(document_id)

    def get_all_processing_results(self):  # type: ignore[override]
        # Attempt to read all indexed doc IDs and fetch each
        try:
            ids = self.r.smembers(self._key_all_docs())
            results = []
            for b in ids:
                doc_id = b.decode()
                res = self.get_processing_result(doc_id)
                if res:
                    results.append(res)
            if results:
                return results
        except Exception:
            pass
        return super().get_all_processing_results()

    def save_processing_result(self, result):  # type: ignore[override]
        try:
            from app.api.v1.models import V1ProcessingResult
            payload = V1ProcessingResult.model_validate(result).model_dump()
            self.r.set(self._key_doc(result.document_id), json.dumps(payload, default=str), ex=self.ttl)
            self.r.sadd(self._key_all_docs(), result.document_id)
            self.r.expire(self._key_all_docs(), self.ttl)
            # Also persist processed file path for reliable downloads
            path = payload.get('markdown_path') or getattr(result, 'markdown_path', None)
            if path:
                self.r.set(f"storage:docpath:{result.document_id}", path, ex=self.ttl)
        except Exception:
            pass
        return super().save_processing_result(result)

    def delete_processing_result(self, document_id: str) -> bool:  # type: ignore[override]
        try:
            self.r.delete(self._key_doc(document_id))
            self.r.srem(self._key_all_docs(), document_id)
            self.r.delete(f"storage:docpath:{document_id}")
        except Exception:
            pass
        return super().delete_processing_result(document_id)

    def get_processed_path(self, document_id: str) -> Optional[str]:  # type: ignore[override]
        try:
            val = self.r.get(f"storage:docpath:{document_id}")
            if val:
                return val.decode()
        except Exception:
            pass
        return super().get_processed_path(document_id)

    def clear_all(self):  # type: ignore[override]
        try:
            # Delete all stored doc results and index
            cursor = 0
            while True:
                cursor, keys = self.r.scan(cursor=cursor, match="storage:doc:*", count=500)
                if keys:
                    self.r.delete(*keys)
                if cursor == 0:
                    break
            self.r.delete(self._key_all_docs())
            # Clear organization, batch, and hash indices
            self.r.delete("storage:org:index")
            self.r.delete("storage:batch:index")
            self.r.delete("storage:hash:index")
            cursor = 0
            while True:
                cursor, keys = self.r.scan(cursor=cursor, match="storage:org:*", count=500)
                if keys:
                    self.r.delete(*keys)
                if cursor == 0:
                    break
            cursor = 0
            while True:
                cursor, keys = self.r.scan(cursor=cursor, match="storage:batch:*", count=500)
                if keys:
                    self.r.delete(*keys)
                if cursor == 0:
                    break
            cursor = 0
            while True:
                cursor, keys = self.r.scan(cursor=cursor, match="storage:hash:*", count=500)
                if keys:
                    self.r.delete(*keys)
                if cursor == 0:
                    break
        except Exception:
            pass
        return super().clear_all()

    def get_results_by_organization(self, organization_id: str) -> List[ProcessingResult]:
        """Get all processing results for a specific organization."""
        try:
            doc_ids = self.r.smembers(f"storage:org:{organization_id}")
            results = []
            for b in doc_ids:
                doc_id = b.decode()
                res = self.get_processing_result(doc_id)
                if res:
                    results.append(res)
            return results
        except Exception:
            return super().get_results_by_organization(organization_id)

    def get_results_by_batch(self, batch_id: str) -> List[ProcessingResult]:
        """Get all processing results for a specific batch."""
        try:
            doc_ids = self.r.smembers(f"storage:batch:{batch_id}")
            results = []
            for b in doc_ids:
                doc_id = b.decode()
                res = self.get_processing_result(doc_id)
                if res:
                    results.append(res)
            return results
        except Exception:
            return super().get_results_by_batch(batch_id)

    def get_results_by_hash(self, file_hash: str) -> List[ProcessingResult]:
        """Get all processing results with a specific file hash."""
        try:
            doc_ids = self.r.smembers(f"storage:hash:{file_hash}")
            results = []
            for b in doc_ids:
                doc_id = b.decode()
                res = self.get_processing_result(doc_id)
                if res:
                    results.append(res)
            return results
        except Exception:
            return super().get_results_by_hash(file_hash)


# Swap storage backend if requested by env
if os.getenv("STORAGE_BACKEND", "memory").lower() == "redis":
    storage_service = RedisStorage()
