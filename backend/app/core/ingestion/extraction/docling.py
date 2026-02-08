"""
Docling engine implementation.

This module implements the extraction engine for IBM Docling Serve,
which provides advanced document conversion with rich layout understanding.
"""

from pathlib import Path
from typing import Optional, Dict, Any
import httpx
import mimetypes

from .base import BaseExtractionEngine, ExtractionResult


class DoclingEngine(BaseExtractionEngine):
    """
    Extraction engine for IBM Docling Serve.

    Docling provides advanced document conversion with rich layout understanding,
    making it ideal for complex PDFs, academic papers, and technical documents.
    Supports OCR, table extraction, and image handling.
    """

    @property
    def engine_type(self) -> str:
        return "docling"

    def __init__(
        self,
        name: str,
        service_url: str,
        timeout: int = 300,
        verify_ssl: bool = True,
        api_key: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            name=name,
            service_url=service_url,
            timeout=timeout,
            verify_ssl=verify_ssl,
            api_key=api_key,
            options=options
        )
        self._detected_endpoint: Optional[str] = None

    @property
    def display_name(self) -> str:
        return "IBM Docling"

    @property
    def description(self) -> str:
        return "Advanced extraction with rich layout understanding"

    @property
    def default_endpoint(self) -> str:
        """
        Get the default API endpoint based on service version.

        Returns:
            str: API endpoint path

        Note:
            - Docling v1.x uses /v1/convert/file
            - Docling v0.7.0 (alpha) uses /v1alpha/convert/file

        The engine will auto-detect the version by checking if the URL
        contains 'v1alpha', inspecting OpenAPI, or probing endpoints.
        """
        # Check if URL already specifies alpha version
        if 'v1alpha' in self.service_url.lower():
            return "/v1alpha/convert/file"

        # Default to v1 (latest)
        return "/v1/convert/file"

    def get_supported_formats(self) -> list[str]:
        """
        Get supported file formats for Docling.

        Returns:
            List of supported file extensions
        """
        return [
            ".pdf", ".doc", ".docx", ".ppt", ".pptx",
            ".xls", ".xlsx", ".html", ".htm",
            ".png", ".jpg", ".jpeg", ".tif", ".tiff"
        ]

    def _get_docling_params(self, endpoint: Optional[str] = None) -> Dict[str, Any]:
        """
        Get Docling-specific conversion parameters.

        Returns parameters from engine options, or uses sensible defaults
        matching the Docling API version in use.

        API Version Differences:
        - v1.9.0+: Uses /v1/convert/file with 'pipeline' parameter
        - v0.7.0 (alpha): Uses /v1alpha/convert/file, no 'pipeline' parameter

        Common changes in v1.9.0:
        - output_format → to_formats (array)
        - pipeline_type → pipeline (v1.9.0 only)
        - enable_ocr → do_ocr
        - Removed: include_annotations, generate_picture_images
        """
        # Detect API version
        endpoint_path = endpoint or self.default_endpoint
        is_alpha_api = 'v1alpha' in endpoint_path

        # Start with common defaults
        params = {
            # Output format (must be array)
            "to_formats": ["md"],
            # Image handling
            "image_export_mode": "placeholder",
            # OCR settings
            "do_ocr": True,
            "ocr_engine": "easyocr",
            # Table extraction mode
            "table_mode": "accurate",
            # Image inclusion
            "include_images": False,
        }

        # Add version-specific parameters
        if not is_alpha_api:
            # v1.9.0+ only: pipeline parameter
            params["pipeline"] = "standard"

        # Override with options if provided
        if self.options:
            # Map old parameter names to new ones for backward compatibility
            param_mapping = {
                "output_format": "to_formats",
                "pipeline_type": "pipeline",
                "enable_ocr": "do_ocr",
            }

            for old_key, new_key in param_mapping.items():
                if old_key in self.options:
                    value = self.options[old_key]
                    # Handle to_formats specifically (must be array)
                    if new_key == "to_formats":
                        if isinstance(value, str):
                            params[new_key] = [value]
                        elif isinstance(value, list):
                            params[new_key] = value
                    else:
                        params[new_key] = value

            # Direct mappings (same name in both old and new API)
            for key in ["ocr_engine", "table_mode", "include_images", "image_export_mode"]:
                if key in self.options:
                    params[key] = self.options[key]

        return params

    async def _detect_endpoint(self, client: httpx.AsyncClient) -> None:
        """Detect Docling API endpoint using OpenAPI or probing."""
        if self._detected_endpoint:
            return

        if 'v1alpha' in self.service_url.lower():
            self._detected_endpoint = "/v1alpha/convert/file"
            return

        if self.options:
            api_version = str(self.options.get('api_version') or '').lower()
            if api_version in {"v1", "v1alpha"}:
                self._detected_endpoint = "/v1alpha/convert/file" if api_version == "v1alpha" else "/v1/convert/file"
                return

        try:
            openapi_url = f"{self.service_url}/openapi.json"
            response = await client.get(openapi_url)
            if response.status_code == 200:
                payload = response.json()
                paths = payload.get("paths", {}) if isinstance(payload, dict) else {}
                if "/v1/convert/file" in paths:
                    self._detected_endpoint = "/v1/convert/file"
                    return
                if "/v1alpha/convert/file" in paths:
                    self._detected_endpoint = "/v1alpha/convert/file"
                    return
        except Exception:
            pass

        for endpoint in ["/v1/convert/file", "/v1alpha/convert/file"]:
            try:
                probe = await client.options(f"{self.service_url}{endpoint}")
                if probe.status_code != 404:
                    self._detected_endpoint = endpoint
                    return
            except Exception:
                continue

    def _build_endpoint_candidates(self, preferred: Optional[str]) -> list[str]:
        """Return endpoint candidates ordered by preference."""
        candidates = ["/v1/convert/file", "/v1alpha/convert/file"]
        if preferred in candidates:
            return [preferred] + [c for c in candidates if c != preferred]
        return candidates

    async def extract(
        self,
        file_path: Path,
        max_retries: int = 2
    ) -> ExtractionResult:
        """
        Extract markdown content using Docling.

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
                        "Using Docling: %s (timeout: %.0fs) for file: %s",
                        url, current_timeout, file_path.name
                    )
                else:
                    self._logger.info(
                        "Retrying Docling (attempt %d/%d, timeout: %.0fs): %s",
                        attempt + 1, max_retries + 1, current_timeout, file_path.name
                    )
            except Exception:
                pass

            headers = {"Accept": "application/json"}
            if self.api_key:
                headers["X-Api-Key"] = self.api_key

            try:
                async with httpx.AsyncClient(
                    timeout=current_timeout,
                    verify=self.verify_ssl
                ) as client:
                    # Guess MIME type for the file
                    mime = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

                    async def _post_with(
                        endpoint_url: str,
                        params: Dict[str, Any],
                        field_name: str
                    ) -> httpx.Response:
                        """Helper to post file with specific field name."""
                        with file_path.open('rb') as f:
                            # Docling expects multipart/form-data with:
                            # - 'files' field: the uploaded file (array)
                            # - form fields: conversion parameters
                            files = [(field_name, (file_path.name, f, mime))]

                            # Convert params to form data format
                            # Docling expects arrays as repeated form fields
                            form_data = {}
                            for key, value in params.items():
                                if isinstance(value, list):
                                    # Arrays: use repeated form fields (not JSON)
                                    form_data[key] = value
                                elif isinstance(value, bool):
                                    # Booleans: convert to lowercase strings
                                    form_data[key] = str(value).lower()
                                else:
                                    form_data[key] = str(value)

                            # Send file and params as multipart/form-data
                            # Do NOT use params (query string) - only use data (form fields)
                            return await client.post(
                                endpoint_url,
                                headers=headers,
                                files=files,
                                data=form_data
                            )

                    await self._detect_endpoint(client)

                    response = None
                    used_url = url
                    endpoints = self._build_endpoint_candidates(self._detected_endpoint)
                    for endpoint in endpoints:
                        endpoint_url = f"{self.service_url}{endpoint}"
                        used_url = endpoint_url
                        params = self._get_docling_params(endpoint=endpoint)

                        # Try with 'files' field first (Docling's documented parameter)
                        response = await _post_with(endpoint_url, params, 'files')

                        # Retry with alternative endpoint if this one is missing
                        if response.status_code == 404 and endpoint != endpoints[-1]:
                            next_endpoint = endpoints[1]
                            self._logger.warning(
                                "Docling endpoint %s returned 404; trying %s.",
                                endpoint, next_endpoint
                            )
                            continue

                        # Handle field name mismatches
                        if response.status_code == 422:
                            # Check if server validation error mentions 'file' field
                            try:
                                body = response.json() or {}
                                needs_file = any(
                                    any(str(x).lower() == 'file' for x in (d.get('loc') or []))
                                    for d in (body.get('detail') or [])
                                )
                                if needs_file:
                                    self._logger.warning(
                                        "Docling expects 'file' field. Retrying."
                                    )
                                    response = await _post_with(endpoint_url, params, 'file')
                            except Exception:
                                pass

                        break

                    response.raise_for_status()

                    # Parse response
                    content_type = response.headers.get('content-type', '').lower()
                    markdown_content = None

                    if 'application/json' in content_type:
                        payload = response.json()
                        if isinstance(payload, dict):
                            doc = payload.get('document')
                            if isinstance(doc, dict):
                                # Try md_content first (primary markdown field)
                                md_val = doc.get('md_content')
                                if isinstance(md_val, str) and md_val.strip():
                                    markdown_content = md_val
                                else:
                                    # Fallback to text_content
                                    txt_val = doc.get('text_content')
                                    if isinstance(txt_val, str) and txt_val.strip():
                                        markdown_content = txt_val
                                        self._logger.info(
                                            "Using text_content (md_content not available) for %s",
                                            file_path.name
                                        )
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
                                "url": used_url,
                                "attempts": attempt + 1,
                                "processing_time": current_timeout,
                                "options": self._get_docling_params(endpoint=endpoint),
                                "api_version": "v1alpha" if "v1alpha" in endpoint else "v1"
                            }
                        )
                    else:
                        self._logger.warning("Docling returned empty content for %s", file_path.name)

            except httpx.TimeoutException as e:
                self._logger.warning(
                    "Docling timeout (attempt %d/%d) for %s: %s",
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
                    "Docling extraction failed for %s: %s",
                    file_path.name, error_msg
                )
                return ExtractionResult(
                    content="",
                    success=False,
                    error=error_msg,
                    metadata={
                        "engine": self.engine_type,
                        "url": used_url,
                        "attempts": attempt + 1,
                        "status_code": e.response.status_code
                    }
                )

            except Exception as e:
                self._logger.error(
                    "Docling error (attempt %d/%d) for %s: %s",
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
                            "url": used_url,
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
        Test connectivity to Docling service.

        Returns:
            Dict with health status
        """
        # Try common health endpoint paths
        health_paths = [
            "/health",
            "/v1/health",
            "/api/health"
        ]

        headers = {}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key

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
                                "message": "Docling service is responding",
                                "details": {
                                    "url": url,
                                    "status_data": data
                                }
                            }
                        except Exception:
                            return {
                                "success": True,
                                "status": "healthy",
                                "message": "Docling service is responding",
                                "details": {"url": url}
                            }
                except httpx.RequestError:
                    continue

        # If health check fails, return error
        return {
            "success": False,
            "status": "unhealthy",
            "message": "Cannot reach Docling service",
            "details": {
                "url": self.service_url,
                "tried_paths": health_paths
            }
        }
