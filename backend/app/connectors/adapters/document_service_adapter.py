"""
Document Service Adapter — ServiceAdapter implementation for the Document Service.

HTTP client for the standalone Curatore Document Service that handles all document
extraction (triage, fast_pdf, markitdown, docling proxy) and generation.

Configuration Priority:
    1. Connection from database (per-organization)
    2. config.yml extraction section
    3. Environment variables (EXTRACTION_SERVICE_URL, etc.)

Usage:
    from app.connectors.adapters.document_service_adapter import document_service_adapter

    # Extract a document
    result = await document_service_adapter.extract(file_path)
    print(result.content_markdown)
    print(result.method)
    print(result.triage_engine)

    # Check health
    health = await document_service_adapter.health()

    # Get capabilities
    caps = await document_service_adapter.capabilities()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.adapters.base import ServiceAdapter

logger = logging.getLogger("curatore.document_service_adapter")


def _get_extraction_config_from_yaml():
    """Get extraction configuration from config.yml."""
    try:
        from app.core.shared.config_loader import config_loader
        return config_loader.get_extraction_config()
    except Exception as e:
        logger.debug(f"Failed to load extraction config from config.yml: {e}")
        return None


def _get_default_engine_from_yaml():
    """Get the default extraction engine from config.yml."""
    try:
        from app.core.shared.config_loader import config_loader
        return config_loader.get_default_extraction_engine()
    except Exception as e:
        logger.debug(f"Failed to load default engine from config.yml: {e}")
        return None


class DocumentServiceError(RuntimeError):
    """Raised when the Document Service fails or returns an invalid response."""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class DocumentServiceResponse:
    """Response from the Document Service extraction endpoint."""

    content_markdown: str
    method: str
    ocr_used: bool = False
    page_count: Optional[int] = None
    media_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Triage fields
    triage_engine: Optional[str] = None
    triage_needs_ocr: Optional[bool] = None
    triage_needs_layout: Optional[bool] = None
    triage_complexity: Optional[str] = None
    triage_duration_ms: Optional[int] = None
    triage_reason: Optional[str] = None


class DocumentServiceAdapter(ServiceAdapter):
    """Async client for the standalone Curatore Document Service."""

    CONNECTION_TYPE = "extraction"

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
        verify_ssl: Optional[bool] = None,
    ) -> None:
        # Resolve config from yaml first
        default_engine = _get_default_engine_from_yaml()

        # Resolve base_url: param > config.yml > env
        if base_url:
            self.base_url = base_url.rstrip("/")
        elif default_engine and default_engine.service_url:
            self.base_url = default_engine.service_url.rstrip("/")
        else:
            self.base_url = (getattr(settings, "extraction_service_url", None) or "").rstrip("/")

        # Resolve api_key: param > config.yml > env
        if api_key is not None:
            self.api_key = api_key
        elif default_engine and getattr(default_engine, "api_key", None):
            self.api_key = default_engine.api_key
        else:
            self.api_key = getattr(settings, "extraction_service_api_key", None)

        # Resolve timeout: param > config.yml > env
        if timeout is not None:
            self.timeout = timeout
        elif default_engine and getattr(default_engine, "timeout", None):
            self.timeout = float(default_engine.timeout)
        else:
            self.timeout = float(getattr(settings, "extraction_service_timeout", 180))

        # Resolve verify_ssl: param > config.yml > env
        if verify_ssl is not None:
            self.verify_ssl = verify_ssl
        elif default_engine and hasattr(default_engine, "verify_ssl"):
            self.verify_ssl = default_engine.verify_ssl
        else:
            self.verify_ssl = getattr(settings, "extraction_service_verify_ssl", True)

        # Circuit breaker state
        self._consecutive_failures: int = 0
        self._circuit_open_until: Optional[float] = None  # monotonic timestamp
        self._last_error: Optional[str] = None
        self._failure_threshold: int = 3       # failures before opening circuit
        self._recovery_timeout: float = 30.0   # seconds before half-open probe

    # ========================================================================
    # Circuit breaker
    # ========================================================================

    def _is_circuit_open(self) -> bool:
        """Return True if circuit is open and recovery timeout hasn't expired."""
        if self._circuit_open_until is None:
            return False
        if time.monotonic() >= self._circuit_open_until:
            return False  # half-open: allow a probe
        return True

    def _record_success(self) -> None:
        """Reset circuit breaker after a successful call."""
        self._consecutive_failures = 0
        self._circuit_open_until = None
        self._last_error = None

    def _record_failure(self, error: str) -> None:
        """Record a failure; open circuit at threshold."""
        self._consecutive_failures += 1
        self._last_error = error
        if self._consecutive_failures >= self._failure_threshold:
            self._circuit_open_until = time.monotonic() + self._recovery_timeout
            logger.warning(
                f"Circuit breaker OPEN after {self._consecutive_failures} consecutive "
                f"failures — blocking calls for {self._recovery_timeout}s"
            )

    def get_circuit_status(self) -> Dict[str, Any]:
        """Return current circuit breaker state for health/observability."""
        if self._circuit_open_until is None:
            state = "closed"
        elif time.monotonic() >= self._circuit_open_until:
            state = "half_open"
        else:
            state = "open"
        return {
            "state": state,
            "consecutive_failures": self._consecutive_failures,
            "last_error": self._last_error,
        }

    def _get_client(self) -> httpx.AsyncClient:
        """Create a fresh HTTP client per call to avoid event-loop-closed errors in Celery."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            verify=self.verify_ssl,
            headers=headers,
        )

    # ========================================================================
    # ServiceAdapter interface
    # ========================================================================

    def resolve_config(self) -> Dict[str, Any]:
        """Resolve configuration from config.yml / ENV (tiers 2+3)."""
        default_engine = _get_default_engine_from_yaml()

        if default_engine:
            return {
                "service_url": default_engine.service_url or getattr(settings, "extraction_service_url", None),
                "api_key": getattr(default_engine, "api_key", None) or getattr(settings, "extraction_service_api_key", None),
                "timeout": getattr(default_engine, "timeout", None) or getattr(settings, "extraction_service_timeout", 180),
                "verify_ssl": getattr(default_engine, "verify_ssl", True),
            }

        return {
            "service_url": getattr(settings, "extraction_service_url", None),
            "api_key": getattr(settings, "extraction_service_api_key", None),
            "timeout": getattr(settings, "extraction_service_timeout", 180),
            "verify_ssl": getattr(settings, "extraction_service_verify_ssl", True),
        }

    async def resolve_config_for_org(
        self, organization_id: UUID, session: AsyncSession
    ) -> Dict[str, Any]:
        """Resolve configuration with DB connection as tier 1."""
        connection = await self._get_db_connection(organization_id, session)
        if connection:
            return connection.config
        return self.resolve_config()

    async def test_connection(self) -> Dict[str, Any]:
        """Test the Document Service connection."""
        try:
            health_data = await self.health()
            is_healthy = health_data.get("status") == "ok"
            return {
                "success": is_healthy,
                "message": "Document service is healthy" if is_healthy else "Document service unhealthy",
                "service_url": self.base_url,
                "response": health_data,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Document service connection test failed: {e}",
                "service_url": self.base_url,
            }

    @property
    def is_available(self) -> bool:
        """Whether the adapter has a configured URL."""
        return bool(self.base_url)

    # ========================================================================
    # Document Service methods
    # ========================================================================

    async def extract(
        self,
        file_path: Path,
        engine: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> DocumentServiceResponse:
        """Extract content from a document via the Document Service.

        Args:
            file_path: Path to the file to extract
            engine: Engine hint (auto, fast_pdf, markitdown, docling). Default: auto
            request_id: Optional request ID for tracing

        Returns:
            DocumentServiceResponse with extracted content and triage info

        Raises:
            DocumentServiceError: If extraction fails
        """
        if not self.base_url:
            raise DocumentServiceError("Document service URL not configured", status_code=503)

        if self._is_circuit_open():
            raise DocumentServiceError(
                "Document service circuit breaker is open — fast-failing",
                status_code=503,
            )

        client = self._get_client()

        # Build query params
        params = {}
        if engine:
            params["engine"] = engine

        # Build headers
        headers = {}
        if request_id:
            headers["X-Request-ID"] = request_id

        try:
            async with client:
                with open(file_path, "rb") as f:
                    files = {"file": (file_path.name, f, "application/octet-stream")}
                    response = await client.post(
                        "/api/v1/extract",
                        files=files,
                        params=params,
                        headers=headers,
                    )

            if response.status_code == 422:
                detail = response.json().get("detail", "Unsupported format or no content")
                raise DocumentServiceError(f"Document service: {detail}", status_code=422)

            if response.status_code >= 400:
                error_detail = response.text[:500]
                raise DocumentServiceError(
                    f"Document service HTTP {response.status_code}: {error_detail}",
                    status_code=response.status_code,
                )

            self._record_success()

            data = response.json()
            triage = data.get("triage") or {}

            return DocumentServiceResponse(
                content_markdown=data.get("content_markdown", ""),
                method=data.get("method", "unknown"),
                ocr_used=data.get("ocr_used", False),
                page_count=data.get("page_count"),
                media_type=data.get("media_type"),
                metadata=data.get("metadata") or {},
                triage_engine=triage.get("engine"),
                triage_needs_ocr=triage.get("needs_ocr"),
                triage_needs_layout=triage.get("needs_layout"),
                triage_complexity=triage.get("complexity"),
                triage_duration_ms=triage.get("triage_duration_ms"),
                triage_reason=triage.get("reason"),
            )

        except DocumentServiceError:
            raise
        except httpx.TimeoutException as e:
            self._record_failure(f"Timeout: {e}")
            raise DocumentServiceError(
                f"Document service request timed out after {self.timeout}s: {e}",
                status_code=504,
            )
        except httpx.RequestError as e:
            self._record_failure(f"Connection error: {e}")
            raise DocumentServiceError(
                f"Document service connection error: {e}",
                status_code=502,
            )
        except Exception as e:
            self._record_failure(f"Unexpected: {e}")
            raise DocumentServiceError(f"Unexpected error calling document service: {e}")

    async def health(self) -> Dict[str, Any]:
        """Check Document Service health.

        On success, resets the circuit breaker (allows recovery after outage).
        Uses a short 5s timeout independent of the extraction timeout.

        Returns:
            Dict with health status from the service
        """
        if not self.base_url:
            return {"status": "not_configured", "error": "Document service URL not configured"}

        try:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=5.0, verify=self.verify_ssl, headers=headers,
            ) as client:
                response = await client.get("/api/v1/system/health")
                if response.status_code == 200:
                    self._record_success()
                    return response.json()
                return {"status": "unhealthy", "status_code": response.status_code}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def capabilities(self) -> Dict[str, Any]:
        """Get Document Service capabilities.

        Returns:
            Dict with capabilities (extraction_formats, generation_formats,
            triage_available, docling_available)
        """
        if not self.base_url:
            return {"error": "Document service URL not configured"}

        try:
            async with self._get_client() as client:
                response = await client.get("/api/v1/system/capabilities")
                if response.status_code == 200:
                    return response.json()
                return {"error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    async def supported_formats(self) -> Dict[str, Any]:
        """Get supported file formats from the Document Service.

        Returns:
            Dict with extensions list
        """
        if not self.base_url:
            return {"extensions": []}

        try:
            async with self._get_client() as client:
                response = await client.get("/api/v1/system/supported-formats")
                if response.status_code == 200:
                    return response.json()
                return {"extensions": []}
        except Exception as e:
            logger.warning(f"Failed to get supported formats: {e}")
            return {"extensions": []}


# Singleton instance
document_service_adapter = DocumentServiceAdapter()
