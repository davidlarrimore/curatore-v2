"""Service adapter base and implementations for external service connections."""

from .document_service_adapter import (
    DocumentServiceAdapter,
    DocumentServiceError,
    DocumentServiceResponse,
    document_service_adapter,
)

__all__ = [
    "DocumentServiceAdapter",
    "DocumentServiceError",
    "DocumentServiceResponse",
    "document_service_adapter",
]
