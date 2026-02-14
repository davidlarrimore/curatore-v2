"""
Playwright Adapter — ServiceAdapter implementation for the Playwright rendering service.

HTTP client for the Playwright rendering microservice. Used by the crawl
service to render JavaScript-heavy pages and extract content.

Configuration Priority:
    1. Connection from database (per-organization)
    2. config.yml playwright section
    3. Environment variables (PLAYWRIGHT_SERVICE_URL, etc.)

Usage:
    from app.connectors.adapters.playwright_adapter import playwright_client

    # Render a page
    result = await playwright_client.render_page(
        url="https://example.com",
        wait_for_selector=".main-content",
    )

    # Access extracted content
    print(result.markdown)
    print(result.links)
    print(result.document_links)

    # Get client from database connection
    client = await PlaywrightClient.from_database(org_id, session)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.adapters.base import ServiceAdapter

logger = logging.getLogger("curatore.playwright_client")


def _get_playwright_config_from_yaml():
    """
    Get Playwright configuration from config.yml.

    Returns:
        PlaywrightConfig or None if not configured
    """
    try:
        from app.core.shared.config_loader import config_loader
        return config_loader.get_playwright_config()
    except Exception as e:
        logger.debug(f"Failed to load Playwright config from config.yml: {e}")
        return None


class PlaywrightError(RuntimeError):
    """Raised when the Playwright service fails or returns an invalid response."""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


# ============================================================================
# RESPONSE MODELS
# ============================================================================


class LinkInfo(BaseModel):
    """Information about a discovered link."""

    url: str
    text: str = ""
    rel: Optional[str] = None


class DocumentLink(BaseModel):
    """Information about a discovered document link."""

    url: str
    filename: str
    extension: str
    link_text: str = ""


class RenderResponse(BaseModel):
    """Response from the Playwright rendering service."""

    # Page content
    html: str
    markdown: str
    text: str
    title: str = ""

    # Links discovered
    links: List[LinkInfo] = Field(default_factory=list)
    document_links: List[DocumentLink] = Field(default_factory=list)

    # Metadata
    final_url: str
    status_code: int
    render_time_ms: int


# ============================================================================
# CLIENT
# ============================================================================


class PlaywrightClient(ServiceAdapter):
    """Async client to call the Playwright rendering service."""

    CONNECTION_TYPE = "playwright"

    @classmethod
    async def from_database(
        cls,
        organization_id: UUID,
        session: AsyncSession,
    ) -> "PlaywrightClient":
        """
        Create PlaywrightClient from database connection or config.yml/ENV fallback.

        Priority:
            1. Database connection (per-organization)
            2. config.yml playwright section
            3. Environment variables

        Args:
            organization_id: Organization UUID for connection lookup
            session: Database session

        Returns:
            PlaywrightClient configured from database, config.yml, or ENV
        """
        try:
            from app.core.auth.connection_service import connection_service

            connection = await connection_service.get_default_connection(
                session, organization_id, "playwright"
            )

            if connection and connection.is_active:
                config = connection.config
                return cls(
                    base_url=config.get("service_url"),
                    api_key=config.get("api_key"),
                    timeout=config.get("timeout"),
                    max_retries=config.get("max_retries"),
                    default_viewport_width=config.get("default_viewport_width"),
                    default_viewport_height=config.get("default_viewport_height"),
                    default_timeout_ms=config.get("default_timeout_ms"),
                    default_wait_timeout_ms=config.get("default_wait_timeout_ms"),
                    document_extensions=config.get("document_extensions"),
                )
        except Exception as e:
            logger.warning(f"Failed to get Playwright connection from database: {e}")

        # Fallback to config.yml / ENV settings
        return cls()

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        default_viewport_width: Optional[int] = None,
        default_viewport_height: Optional[int] = None,
        default_timeout_ms: Optional[int] = None,
        default_wait_timeout_ms: Optional[int] = None,
        document_extensions: Optional[List[str]] = None,
    ) -> None:
        # Try to load from config.yml first
        yaml_config = _get_playwright_config_from_yaml()

        # Resolve base_url with priority: param > config.yml > env var
        if base_url:
            self.base_url = base_url
        elif yaml_config and yaml_config.service_url:
            self.base_url = yaml_config.service_url
        else:
            self.base_url = settings.playwright_service_url

        # Resolve api_key: param > config.yml > env
        if api_key is not None:
            self.api_key = api_key
        elif yaml_config and getattr(yaml_config, "api_key", None):
            self.api_key = yaml_config.api_key
        else:
            self.api_key = settings.playwright_api_key

        # Resolve timeout
        if timeout is not None:
            self.timeout = timeout
        elif yaml_config:
            self.timeout = yaml_config.timeout
        else:
            self.timeout = settings.playwright_timeout

        # Resolve max_retries
        if max_retries is not None:
            self.max_retries = max_retries
        elif yaml_config:
            self.max_retries = yaml_config.max_retries
        else:
            self.max_retries = 3

        # Resolve viewport settings
        if default_viewport_width is not None:
            self.default_viewport_width = default_viewport_width
        elif yaml_config:
            self.default_viewport_width = yaml_config.default_viewport_width
        else:
            self.default_viewport_width = 1920

        if default_viewport_height is not None:
            self.default_viewport_height = default_viewport_height
        elif yaml_config:
            self.default_viewport_height = yaml_config.default_viewport_height
        else:
            self.default_viewport_height = 1080

        # Resolve timeout settings (milliseconds)
        if default_timeout_ms is not None:
            self.default_timeout_ms = default_timeout_ms
        elif yaml_config:
            self.default_timeout_ms = yaml_config.default_timeout_ms
        else:
            self.default_timeout_ms = 30000

        if default_wait_timeout_ms is not None:
            self.default_wait_timeout_ms = default_wait_timeout_ms
        elif yaml_config:
            self.default_wait_timeout_ms = yaml_config.default_wait_timeout_ms
        else:
            self.default_wait_timeout_ms = 5000

        # Resolve document extensions
        if document_extensions is not None:
            self.document_extensions = document_extensions
        elif yaml_config:
            self.document_extensions = yaml_config.document_extensions
        else:
            self.document_extensions = [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"]

        if not self.base_url:
            raise ValueError(
                "PlaywrightClient requires a base URL. "
                "Set PLAYWRIGHT_SERVICE_URL in config.yml or environment"
            )

    def _get_client(self) -> httpx.AsyncClient:
        """Create a fresh HTTP client per call to avoid event-loop-closed errors in Celery."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=headers,
        )

    # ========================================================================
    # ServiceAdapter interface
    # ========================================================================

    def resolve_config(self) -> Dict[str, Any]:
        """Resolve configuration from config.yml / ENV (tiers 2+3)."""
        yaml_config = _get_playwright_config_from_yaml()

        if yaml_config:
            return {
                "service_url": yaml_config.service_url or settings.playwright_service_url,
                "api_key": getattr(yaml_config, "api_key", None) or settings.playwright_api_key,
                "timeout": yaml_config.timeout,
                "max_retries": yaml_config.max_retries,
                "default_viewport_width": yaml_config.default_viewport_width,
                "default_viewport_height": yaml_config.default_viewport_height,
                "default_timeout_ms": yaml_config.default_timeout_ms,
                "default_wait_timeout_ms": yaml_config.default_wait_timeout_ms,
                "document_extensions": yaml_config.document_extensions,
            }

        return {
            "service_url": settings.playwright_service_url,
            "api_key": settings.playwright_api_key,
            "timeout": settings.playwright_timeout,
            "max_retries": 3,
            "default_viewport_width": 1920,
            "default_viewport_height": 1080,
            "default_timeout_ms": 30000,
            "default_wait_timeout_ms": 5000,
            "document_extensions": [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"],
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
        """Test the Playwright service connection."""
        try:
            healthy = await self.health_check()
            return {
                "success": healthy,
                "message": "Playwright service is healthy" if healthy else "Playwright service unhealthy",
                "service_url": self.base_url,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Playwright connection test failed: {e}",
                "service_url": self.base_url,
            }

    @property
    def is_available(self) -> bool:
        """Whether the adapter's client is initialized and ready."""
        return bool(self.base_url)

    # ========================================================================
    # Playwright-specific methods
    # ========================================================================

    async def render_page(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        wait_timeout_ms: Optional[int] = None,
        viewport_width: Optional[int] = None,
        viewport_height: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        extract_documents: bool = True,
        document_extensions: Optional[List[str]] = None,
    ) -> RenderResponse:
        """
        Render a URL using Playwright and extract content.

        Args:
            url: URL to render
            wait_for_selector: Optional CSS selector to wait for
            wait_timeout_ms: Wait timeout for selector (ms), defaults to client config
            viewport_width: Viewport width, defaults to client config
            viewport_height: Viewport height, defaults to client config
            timeout_ms: Total render timeout (ms), defaults to client config
            extract_documents: Whether to extract document links
            document_extensions: File extensions to identify as documents, defaults to client config

        Returns:
            RenderResponse with extracted content

        Raises:
            PlaywrightError: If rendering fails
        """
        # Use client defaults if not specified
        if wait_timeout_ms is None:
            wait_timeout_ms = self.default_wait_timeout_ms
        if viewport_width is None:
            viewport_width = self.default_viewport_width
        if viewport_height is None:
            viewport_height = self.default_viewport_height
        if timeout_ms is None:
            timeout_ms = self.default_timeout_ms
        if document_extensions is None:
            document_extensions = self.document_extensions

        payload = {
            "url": url,
            "wait_for_selector": wait_for_selector,
            "wait_timeout_ms": wait_timeout_ms,
            "viewport_width": viewport_width,
            "viewport_height": viewport_height,
            "timeout_ms": timeout_ms,
            "extract_documents": extract_documents,
            "document_extensions": document_extensions,
        }

        retries = max(0, self.max_retries)
        attempt = 0
        last_error: Optional[BaseException] = None

        while attempt <= retries:
            try:
                async with self._get_client() as client:
                    response = await client.post("/api/v1/render", json=payload)

                if response.status_code >= 400:
                    error_detail = response.text[:500]
                    raise PlaywrightError(
                        f"Playwright service HTTP {response.status_code}: {error_detail}",
                        status_code=response.status_code,
                    )

                data = response.json()
                return RenderResponse(**data)

            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                last_error = e
                if attempt >= retries:
                    break
                # Exponential backoff
                sleep_for = min(2**attempt * 0.5, 6.0)
                logger.warning(
                    f"Playwright request failed (attempt {attempt + 1}/{retries + 1}), "
                    f"retrying in {sleep_for}s: {e}"
                )
                await asyncio.sleep(sleep_for)
                attempt += 1

            except PlaywrightError:
                raise

            except Exception as e:
                raise PlaywrightError(f"Unexpected error calling Playwright service: {e}")

        raise PlaywrightError(
            f"Playwright rendering failed after {retries + 1} attempt(s): {last_error!s}",
            status_code=502,
        )

    async def health_check(self) -> bool:
        """
        Check if the Playwright service is healthy.

        Health endpoints are exempt from auth in the Playwright service.
        Uses a short 5s timeout independent of the render timeout.

        Returns:
            True if healthy, False otherwise
        """
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=5.0,
            ) as client:
                response = await client.get("/health")
                return response.status_code == 200
        except Exception:
            return False


def get_playwright_client() -> Optional[PlaywrightClient]:
    """
    Get a PlaywrightClient instance if configured.

    Returns:
        PlaywrightClient or None if not configured
    """
    if not settings.playwright_service_url:
        return None

    return PlaywrightClient()


# Singleton instance (may be None if not configured)
playwright_client: Optional[PlaywrightClient] = None

try:
    if settings.playwright_service_url:
        playwright_client = PlaywrightClient()
except ValueError:
    # Not configured - that's OK, it's optional
    pass
