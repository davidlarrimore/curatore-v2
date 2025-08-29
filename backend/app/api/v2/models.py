"""
Versioned models for API v2.

Initially mirrors v1 domain models; evolve independently as needed.
"""

from ...models import (
    FileUploadResponse,
    ProcessingResult,
    BatchProcessingRequest,
    BatchProcessingResult,
    DocumentEditRequest,
    ProcessingOptions,
    BulkDownloadRequest,
    ZipArchiveInfo,
    HealthStatus,
    LLMConnectionStatus,
)

__all__ = [
    "FileUploadResponse",
    "ProcessingResult",
    "BatchProcessingRequest",
    "BatchProcessingResult",
    "DocumentEditRequest",
    "ProcessingOptions",
    "BulkDownloadRequest",
    "ZipArchiveInfo",
    "HealthStatus",
    "LLMConnectionStatus",
]

