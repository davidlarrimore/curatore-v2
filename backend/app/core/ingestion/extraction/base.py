"""
Base abstraction for document extraction engines.

This module defines the abstract base class that all extraction engines must implement,
providing a consistent interface for document-to-markdown conversion.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional


class ExtractionResult:
    """
    Result of an extraction operation.

    Attributes:
        content: Extracted markdown content
        success: Whether extraction succeeded
        error: Error message if extraction failed
        metadata: Additional metadata about the extraction
    """

    def __init__(
        self,
        content: str,
        success: bool = True,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.content = content
        self.success = success
        self.error = error
        self.metadata = metadata or {}


class BaseExtractionEngine(ABC):
    """
    Abstract base class for document extraction engines.

    All extraction engines must implement this interface to provide:
    - Document extraction to markdown
    - Health/connectivity checks
    - Engine metadata and capabilities

    Subclasses should implement:
    - extract(): Convert document to markdown
    - test_connection(): Verify engine availability
    - get_supported_formats(): List supported file formats
    """

    def __init__(
        self,
        name: str,
        service_url: str,
        timeout: int = 300,
        verify_ssl: bool = True,
        api_key: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize extraction engine.

        Args:
            name: Engine identifier
            service_url: Base URL for the extraction service
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
            api_key: Optional API key for authentication
            options: Engine-specific options
        """
        self.name = name
        self.service_url = service_url.rstrip('/')
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.api_key = api_key
        self.options = options or {}
        self._logger = logging.getLogger(f"curatore.extraction.{self.engine_type}")

    @property
    @abstractmethod
    def engine_type(self) -> str:
        """
        Engine type identifier.

        Returns:
            Engine type string (e.g., 'extraction-service', 'docling', 'tika')
        """
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """
        Human-readable engine name.

        Returns:
            Display name for UI
        """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """
        Engine description and use cases.

        Returns:
            Description string
        """
        pass

    @property
    def default_endpoint(self) -> str:
        """
        Default API endpoint path for this engine.

        Returns:
            Default endpoint path
        """
        return "/"

    @property
    def full_url(self) -> str:
        """
        Full URL including endpoint path.

        Uses the engine's default_endpoint property.

        Returns:
            Complete URL for API requests
        """
        endpoint = self.default_endpoint
        if not endpoint.startswith('/'):
            endpoint = f'/{endpoint}'
        return f"{self.service_url}{endpoint}"

    @abstractmethod
    async def extract(
        self,
        file_path: Path,
        max_retries: int = 2
    ) -> ExtractionResult:
        """
        Extract markdown content from a document.

        Args:
            file_path: Path to the document file
            max_retries: Maximum number of retry attempts

        Returns:
            ExtractionResult with content or error

        Raises:
            Exception: If extraction fails after all retries
        """
        pass

    @abstractmethod
    async def test_connection(self) -> Dict[str, Any]:
        """
        Test connectivity to the extraction service.

        Returns:
            Dict with status information:
                {
                    "success": bool,
                    "status": "healthy" | "unhealthy",
                    "message": str,
                    "details": dict
                }
        """
        pass

    @abstractmethod
    def get_supported_formats(self) -> list[str]:
        """
        Get list of supported file formats.

        Returns:
            List of file extensions (e.g., ['.pdf', '.docx', '.txt'])
        """
        pass

    def get_metadata(self) -> Dict[str, Any]:
        """
        Get engine metadata.

        Returns:
            Dict with engine information
        """
        return {
            "name": self.name,
            "engine_type": self.engine_type,
            "display_name": self.display_name,
            "description": self.description,
            "service_url": self.service_url,
            "full_url": self.full_url,
            "timeout": self.timeout,
            "supported_formats": self.get_supported_formats(),
            "options": self.options
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name}, url={self.service_url})>"
