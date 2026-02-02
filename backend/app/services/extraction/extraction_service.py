"""
Extraction Service engine implementation.

This module implements the extraction engine for the internal extraction-service
that uses MarkItDown for document conversion.
"""

import uuid
from pathlib import Path
from typing import Optional, Dict, Any
import httpx

from .base import BaseExtractionEngine, ExtractionResult


class ExtractionServiceEngine(BaseExtractionEngine):
    """
    Extraction engine for the internal extraction-service.

    Uses MarkItDown for document conversion.
    Supports Office documents, text files, and emails.
    """

    @property
    def engine_type(self) -> str:
        return "extraction-service"

    @property
    def display_name(self) -> str:
        return "Internal Extraction Service"

    @property
    def description(self) -> str:
        return "Built-in extraction using MarkItDown"

    @property
    def default_endpoint(self) -> str:
        return "/api/v1/extract"

    def get_supported_formats(self) -> list[str]:
        """
        Get supported file formats for extraction-service.

        The extraction-service uses MarkItDown and LibreOffice conversion.

        Supported categories:
        - Office documents (doc/docx, ppt/pptx, xls/xlsx, xlsb)
        - Plain text, markup, and data files
        - Email files (msg, eml)

        Note: PDFs are handled by fast_pdf engine. Images are not supported
        as standalone files (only OCR within documents via Docling).

        Returns:
            List of supported file extensions
        """
        return [
            # Office documents
            ".doc", ".docx", ".ppt", ".pptx",
            # Spreadsheets (including xlsb via LibreOffice conversion)
            ".xls", ".xlsx", ".xlsb", ".csv",
            # Plain text and markup
            ".txt", ".md", ".html", ".htm", ".xml", ".json",
            # Email formats
            ".msg", ".eml",
        ]

    async def extract(
        self,
        file_path: Path,
        max_retries: int = 2,
        request_id: Optional[str] = None
    ) -> ExtractionResult:
        """
        Extract markdown content using extraction-service.

        Args:
            file_path: Path to the document file
            max_retries: Maximum number of retry attempts
            request_id: Optional correlation ID (generated if not provided)

        Returns:
            ExtractionResult with extracted content or error
        """
        url = self.full_url
        timeout_extension = 30.0  # 30 seconds per retry

        # Generate request ID for correlation if not provided
        if not request_id:
            request_id = str(uuid.uuid4())[:8]

        for attempt in range(max_retries + 1):
            current_timeout = self.timeout + (attempt * timeout_extension)

            if attempt == 0:
                self._logger.info(
                    "[%s] SEND_REQUEST: url=%s, file=%s, timeout=%.0fs",
                    request_id, url, file_path.name, current_timeout
                )
            else:
                self._logger.info(
                    "[%s] RETRY_REQUEST: attempt=%d/%d, file=%s, timeout=%.0fs",
                    request_id, attempt + 1, max_retries + 1, file_path.name, current_timeout
                )

            headers = {
                "Accept": "application/json",
                "X-Request-ID": request_id,
            }
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            try:
                async with httpx.AsyncClient(
                    timeout=current_timeout,
                    verify=self.verify_ssl
                ) as client:
                    with file_path.open('rb') as f:
                        files = {"file": (file_path.name, f, None)}
                        response = await client.post(url, headers=headers, files=files)

                    response.raise_for_status()

                    # Parse response
                    content_type = response.headers.get('content-type', '').lower()
                    if 'application/json' in content_type:
                        data = response.json()
                        markdown_content = data.get('content_markdown', '') or data.get('markdown', '') or data.get('content', '')
                        service_request_id = data.get('metadata', {}).get('request_id', '')
                        elapsed_ms = data.get('metadata', {}).get('elapsed_ms', 0)
                    else:
                        # Assume text/plain response
                        markdown_content = response.text
                        service_request_id = ''
                        elapsed_ms = 0

                    if markdown_content and markdown_content.strip():
                        self._logger.info(
                            "[%s] EXTRACT_SUCCESS: chars=%d, file=%s, service_elapsed=%dms",
                            request_id, len(markdown_content), file_path.name, elapsed_ms
                        )
                        return ExtractionResult(
                            content=markdown_content,
                            success=True,
                            metadata={
                                "engine": self.engine_type,
                                "url": url,
                                "request_id": request_id,
                                "service_request_id": service_request_id,
                                "attempts": attempt + 1,
                                "service_elapsed_ms": elapsed_ms,
                            }
                        )
                    else:
                        self._logger.warning(
                            "[%s] EXTRACT_EMPTY: file=%s returned no content",
                            request_id, file_path.name
                        )
                        # Return error immediately instead of continuing
                        return ExtractionResult(
                            content="",
                            success=False,
                            error="Extraction service returned empty content",
                            metadata={
                                "engine": self.engine_type,
                                "url": url,
                                "request_id": request_id,
                                "attempts": attempt + 1,
                            }
                        )

            except httpx.TimeoutException as e:
                self._logger.warning(
                    "[%s] TIMEOUT: attempt=%d/%d, file=%s, error=%s",
                    request_id, attempt + 1, max_retries + 1, file_path.name, str(e)
                )
                if attempt < max_retries:
                    continue  # Retry on timeout
                else:
                    return ExtractionResult(
                        content="",
                        success=False,
                        error=f"Timeout after {max_retries + 1} attempts (request_id: {request_id})",
                        metadata={
                            "engine": self.engine_type,
                            "url": url,
                            "request_id": request_id,
                            "attempts": attempt + 1,
                            "error_type": "timeout",
                        }
                    )

            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                self._logger.error(
                    "[%s] HTTP_ERROR: file=%s, status=%d, error=%s",
                    request_id, file_path.name, e.response.status_code, error_msg
                )
                return ExtractionResult(
                    content="",
                    success=False,
                    error=f"{error_msg} (request_id: {request_id})",
                    metadata={
                        "engine": self.engine_type,
                        "url": url,
                        "request_id": request_id,
                        "attempts": attempt + 1,
                        "status_code": e.response.status_code,
                        "error_type": "http_error",
                    }
                )

            except httpx.ConnectError as e:
                self._logger.error(
                    "[%s] CONNECT_ERROR: file=%s, url=%s, error=%s",
                    request_id, file_path.name, url, str(e)
                )
                if attempt < max_retries:
                    continue  # Retry on connection errors
                else:
                    return ExtractionResult(
                        content="",
                        success=False,
                        error=f"Connection failed: {str(e)} (request_id: {request_id})",
                        metadata={
                            "engine": self.engine_type,
                            "url": url,
                            "request_id": request_id,
                            "attempts": attempt + 1,
                            "error_type": "connection_error",
                        }
                    )

            except Exception as e:
                self._logger.error(
                    "[%s] EXTRACT_ERROR: attempt=%d/%d, file=%s, error=%s",
                    request_id, attempt + 1, max_retries + 1, file_path.name, str(e),
                    exc_info=True
                )
                if attempt < max_retries:
                    continue  # Retry on other errors
                else:
                    return ExtractionResult(
                        content="",
                        success=False,
                        error=f"{str(e)} (request_id: {request_id})",
                        metadata={
                            "engine": self.engine_type,
                            "url": url,
                            "request_id": request_id,
                            "attempts": attempt + 1,
                            "error_type": "exception",
                        }
                    )

        # Should never reach here, but just in case
        return ExtractionResult(
            content="",
            success=False,
            error=f"Extraction failed after all retries (request_id: {request_id})",
            metadata={
                "engine": self.engine_type,
                "url": url,
                "request_id": request_id,
                "attempts": max_retries + 1
            }
        )

    async def test_connection(self) -> Dict[str, Any]:
        """
        Test connectivity to extraction-service.

        Returns:
            Dict with health status
        """
        # Try health endpoint first
        health_paths = [
            "/api/v1/system/health",
            "/health",
            "/api/v1/health"
        ]

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(
            timeout=10.0,
            verify=self.verify_ssl
        ) as client:
            for path in health_paths:
                try:
                    url = f"{self.service_url}{path}"
                    response = await client.get(url, headers=headers)

                    if response.status_code == 200:
                        try:
                            data = response.json()
                            return {
                                "success": True,
                                "status": "healthy",
                                "message": "Extraction service is responding",
                                "details": {
                                    "url": url,
                                    "status_data": data
                                }
                            }
                        except Exception:
                            return {
                                "success": True,
                                "status": "healthy",
                                "message": "Extraction service is responding",
                                "details": {"url": url}
                            }
                except httpx.RequestError:
                    continue

        # If health check fails, return error
        return {
            "success": False,
            "status": "unhealthy",
            "message": "Cannot reach extraction service",
            "details": {
                "url": self.service_url,
                "tried_paths": health_paths
            }
        }
