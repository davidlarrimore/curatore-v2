"""
Extraction Service engine implementation.

This module implements the extraction engine for the internal extraction-service
that uses MarkItDown and Tesseract OCR for document conversion.
"""

from pathlib import Path
from typing import Optional, Dict, Any
import httpx

from .base import BaseExtractionEngine, ExtractionResult


class ExtractionServiceEngine(BaseExtractionEngine):
    """
    Extraction engine for the internal extraction-service.

    Uses MarkItDown and Tesseract OCR for document conversion.
    Supports PDFs, Office documents, images, and text files.
    """

    @property
    def engine_type(self) -> str:
        return "extraction-service"

    @property
    def display_name(self) -> str:
        return "Internal Extraction Service"

    @property
    def description(self) -> str:
        return "Built-in extraction using MarkItDown and Tesseract OCR"

    @property
    def default_endpoint(self) -> str:
        return "/api/v1/extract"

    def get_supported_formats(self) -> list[str]:
        """
        Get supported file formats for extraction-service.

        The extraction-service uses MarkItDown, LibreOffice conversion,
        and Tesseract OCR to support a wide range of document types.

        Supported categories:
        - PDFs (native text + OCR fallback)
        - Office documents (doc/docx, ppt/pptx, xls/xlsx, xlsb)
        - Plain text and markdown
        - Images (via Tesseract OCR)
        - Email files (msg, eml)

        Returns:
            List of supported file extensions
        """
        return [
            # Documents
            ".pdf", ".doc", ".docx", ".ppt", ".pptx",
            # Spreadsheets (including xlsb via LibreOffice conversion)
            ".xls", ".xlsx", ".xlsb", ".csv",
            # Plain text
            ".txt", ".md",
            # Images (OCR)
            ".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp",
            # Email formats
            ".msg", ".eml",
        ]

    async def extract(
        self,
        file_path: Path,
        max_retries: int = 2
    ) -> ExtractionResult:
        """
        Extract markdown content using extraction-service.

        Args:
            file_path: Path to the document file
            max_retries: Maximum number of retry attempts

        Returns:
            ExtractionResult with extracted content or error
        """
        url = self.full_url
        timeout_extension = 30.0  # 30 seconds per retry

        for attempt in range(max_retries + 1):
            current_timeout = self.timeout + (attempt * timeout_extension)

            try:
                if attempt == 0:
                    self._logger.info(
                        "Using extraction-service: %s (timeout: %.0fs) for file: %s",
                        url, current_timeout, file_path.name
                    )
                else:
                    self._logger.info(
                        "Retrying extraction-service (attempt %d/%d, timeout: %.0fs): %s",
                        attempt + 1, max_retries + 1, current_timeout, file_path.name
                    )
            except Exception:
                pass

            headers = {"Accept": "application/json"}
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
                    else:
                        # Assume text/plain response
                        markdown_content = response.text

                    if markdown_content and markdown_content.strip():
                        self._logger.info(
                            "Extraction successful: %d characters extracted from %s",
                            len(markdown_content), file_path.name
                        )
                        return ExtractionResult(
                            content=markdown_content,
                            success=True,
                            metadata={
                                "engine": self.engine_type,
                                "url": url,
                                "attempts": attempt + 1,
                                "processing_time": current_timeout
                            }
                        )
                    else:
                        self._logger.warning("Extraction returned empty content for %s", file_path.name)

            except httpx.TimeoutException as e:
                self._logger.warning(
                    "Extraction timeout (attempt %d/%d) for %s: %s",
                    attempt + 1, max_retries + 1, file_path.name, str(e)
                )
                if attempt < max_retries:
                    continue  # Retry on timeout
                else:
                    return ExtractionResult(
                        content="",
                        success=False,
                        error=f"Timeout after {max_retries + 1} attempts",
                        metadata={
                            "engine": self.engine_type,
                            "url": url,
                            "attempts": attempt + 1
                        }
                    )

            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                self._logger.error(
                    "Extraction failed for %s: %s",
                    file_path.name, error_msg
                )
                return ExtractionResult(
                    content="",
                    success=False,
                    error=error_msg,
                    metadata={
                        "engine": self.engine_type,
                        "url": url,
                        "attempts": attempt + 1,
                        "status_code": e.response.status_code
                    }
                )

            except Exception as e:
                self._logger.error(
                    "Extraction error (attempt %d/%d) for %s: %s",
                    attempt + 1, max_retries + 1, file_path.name, str(e)
                )
                if attempt < max_retries:
                    continue  # Retry on other errors
                else:
                    return ExtractionResult(
                        content="",
                        success=False,
                        error=str(e),
                        metadata={
                            "engine": self.engine_type,
                            "url": url,
                            "attempts": attempt + 1
                        }
                    )

        # Should never reach here, but just in case
        return ExtractionResult(
            content="",
            success=False,
            error="Extraction failed after all retries",
            metadata={
                "engine": self.engine_type,
                "url": url,
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
