# ============================================================================
# backend/app/services/extraction_client.py
# ============================================================================
# Minimal HTTP client for the external Extraction Service.
# Centralizes retries, timeouts, and error handling.
#
# Environment-driven configuration (see settings in config.py):
#   - settings.extractor_base_url (e.g., http://extraction:8000)
#   - settings.extractor_extract_path (default: /v1/extract)
#   - settings.extractor_timeout (float seconds)
#   - settings.extractor_max_retries (int)
#   - settings.extractor_api_key (optional; sent as Bearer token)
# ============================================================================

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings


class ExtractionError(RuntimeError):
    """Raised when the extraction service fails or returns an invalid response."""


class ExtractionClient:
    """Async client to call the extraction service."""

    @classmethod
    async def from_database(
        cls,
        organization_id: UUID,
        session: AsyncSession,
    ) -> "ExtractionClient":
        """
        Create ExtractionClient from database connection or ENV fallback.

        Args:
            organization_id: Organization UUID for connection lookup
            session: Database session

        Returns:
            ExtractionClient: Client configured from database or ENV

        Priority:
            1. Database connection (if found)
            2. ENV variables (fallback)
        """
        try:
            from ..connection_service import connection_service

            connection = await connection_service.get_default_connection(
                session, organization_id, "extraction"
            )

            if connection and connection.is_active:
                config = connection.config
                return cls(
                    base_url=config.get("service_url", settings.extractor_base_url),
                    timeout=config.get("timeout", settings.extractor_timeout),
                    api_key=config.get("api_key", settings.extractor_api_key),
                )
        except Exception as e:
            print(f"Warning: Failed to get extraction connection from database: {e}")

        # Fallback to ENV settings
        return cls()

    def __init__(
        self,
        base_url: Optional[str] = None,
        extract_path: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self.base_url = base_url or settings.extractor_base_url
        self.extract_path = extract_path or settings.extractor_extract_path
        self.timeout = timeout or settings.extractor_timeout
        self.max_retries = max_retries if max_retries is not None else settings.extractor_max_retries
        self.api_key = api_key or settings.extractor_api_key

        if not self.base_url:
            raise ValueError("ExtractionClient requires a base URL. Set EXTRACTOR_BASE_URL or settings.extractor_base_url")

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            verify=settings.extractor_verify_ssl,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _detect_mime(self, path: Path) -> str:
        mime, _ = mimetypes.guess_type(str(path))
        return mime or "application/octet-stream"

    async def _post_file(
        self,
        path: Path,
        filename: str,
        mime: Optional[str],
        params: Optional[dict] = None,
    ) -> httpx.Response:
        headers = self._headers()
        actual_mime = mime or self._detect_mime(path)

        files = {
            "file": (filename, path.open("rb"), actual_mime),
        }
        data = {
            # Many extractors support specifying a target format; default to markdown.
            "target": "markdown",
        }
        if params:
            data.update(params)

        return await self._client.post(self.extract_path, headers=headers, files=files, data=data)

    async def extract_markdown(
        self,
        file_path: Path,
        original_filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        extra_params: Optional[dict] = None,
    ) -> str:
        """
        Send a file to the extraction service and return Markdown.

        Expected success responses:
          - JSON: {"markdown": "..."}  (preferred)
          - text/plain body containing Markdown
        """
        retries = max(0, int(self.max_retries))
        attempt = 0
        last_error: Optional[BaseException] = None

        while attempt <= retries:
            try:
                response = await self._post_file(
                    path=file_path,
                    filename=original_filename or file_path.name,
                    mime=mime_type,
                    params=extra_params,
                )

                if response.status_code >= 400:
                    raise ExtractionError(f"Extractor HTTP {response.status_code}: {response.text[:1000]}")

                ctype = response.headers.get("content-type", "")
                if "application/json" in ctype:
                    data = response.json()
                    md = data.get("markdown")
                    if not isinstance(md, str):
                        raise ExtractionError("Extractor JSON missing 'markdown' field")
                    return md

                # Fallback: plain text body
                text = response.text
                if not text.strip():
                    raise ExtractionError("Extractor returned empty body")
                return text

            except (httpx.RequestError, httpx.HTTPStatusError, ExtractionError) as e:
                last_error = e
                if attempt >= retries:
                    break
                # Exponential backoff
                sleep_for = min(2 ** attempt * 0.5, 6.0)
                await asyncio.sleep(sleep_for)
                attempt += 1

        raise ExtractionError(f"Extraction failed after {retries + 1} attempt(s): {last_error!s}")


# Reusable singleton
extraction_client = ExtractionClient()
