"""
Crawl Service for Web Scraping Operations.

Provides web crawling functionality for Phase 4: Web Scraping as Durable Data Source.
Uses Playwright for JavaScript rendering and inline content extraction.

Key Features:
- Playwright-based page rendering for JavaScript-heavy sites
- Inline content extraction (markdown stored during crawl, no separate extraction job)
- Asset and ScrapedAsset creation with hierarchical path tracking
- Re-crawl versioning for content updates
- Document discovery and optional auto-download
- Run-attributed crawl tracking

Usage:
    from app.services.crawl_service import crawl_service

    # Start a crawl run
    run = await crawl_service.start_crawl(
        session=session,
        collection_id=collection_id,
        user_id=user_id,
    )

    # Crawl a single URL (uses Playwright for JS rendering)
    result = await crawl_service.crawl_url(
        session=session,
        collection_id=collection_id,
        url="https://example.com/page",
        crawl_run_id=run.id,
    )

    # Full crawl from sources
    await crawl_service.crawl_collection(
        session=session,
        collection_id=collection_id,
        user_id=user_id,
    )
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Any, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse
from uuid import UUID, uuid4
from io import BytesIO

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import (
    ScrapeCollection,
    ScrapeSource,
    ScrapedAsset,
    Asset,
    Run,
)
from ..config import settings
from .run_service import run_service
from .asset_service import asset_service
from .scrape_service import scrape_service, extract_url_path
from .minio_service import get_minio_service
from .extraction_result_service import extraction_result_service
from .storage_path_service import storage_paths
from .playwright_client import PlaywrightClient, PlaywrightError, get_playwright_client

logger = logging.getLogger("curatore.crawl_service")


# Default crawl configuration
DEFAULT_CRAWL_CONFIG = {
    "max_depth": 3,  # 0 means unlimited depth
    "max_pages": 100,
    "delay_seconds": 1.0,
    "timeout_seconds": 30,
    "respect_robots_txt": True,
    "user_agent": "Curatore/2.0 (+https://curatore.ai)",
    "follow_external_links": False,
    # Playwright-specific options
    "wait_for_selector": None,  # CSS selector to wait for
    "wait_timeout_ms": 5000,  # Wait timeout for selector
    "viewport_width": 1920,
    "viewport_height": 1080,
    "render_timeout_ms": 30000,  # Total render timeout
    # Document discovery
    "download_documents": False,  # Auto-download discovered documents
    "document_extensions": [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"],
}


class CrawlResult:
    """Result of a single URL crawl operation."""

    def __init__(
        self,
        url: str,
        success: bool,
        asset_id: Optional[UUID] = None,
        scraped_asset_id: Optional[UUID] = None,
        error: Optional[str] = None,
        discovered_urls: Optional[List[str]] = None,
        is_new: bool = True,
        was_updated: bool = False,
        documents_discovered: int = 0,
        documents_downloaded: int = 0,
    ):
        self.url = url
        self.success = success
        self.asset_id = asset_id
        self.scraped_asset_id = scraped_asset_id
        self.error = error
        self.discovered_urls = discovered_urls or []
        self.is_new = is_new
        self.was_updated = was_updated
        self.documents_discovered = documents_discovered
        self.documents_downloaded = documents_downloaded


class CrawlService:
    """
    Service for crawling web pages and managing scrape operations.

    Uses Playwright for JavaScript rendering and performs inline content
    extraction. Works in conjunction with ScrapeService for collection management.
    """

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._playwright_client: Optional[PlaywrightClient] = None

    async def _get_playwright_client(self) -> Optional[PlaywrightClient]:
        """Get Playwright client instance."""
        if self._playwright_client is None:
            self._playwright_client = get_playwright_client()
        return self._playwright_client

    async def _get_http_client(self, config: Dict[str, Any]) -> httpx.AsyncClient:
        """Get or create HTTP client for document downloads."""
        if self._http_client is None or self._http_client.is_closed:
            timeout = config.get("timeout_seconds", DEFAULT_CRAWL_CONFIG["timeout_seconds"])
            user_agent = config.get("user_agent", DEFAULT_CRAWL_CONFIG["user_agent"])

            self._http_client = httpx.AsyncClient(
                timeout=timeout,
                headers={"User-Agent": user_agent},
                follow_redirects=True,
                verify=True,
            )

        return self._http_client

    async def close(self) -> None:
        """Close HTTP and Playwright clients."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

        if self._playwright_client:
            await self._playwright_client.aclose()
            self._playwright_client = None

    # =========================================================================
    # URL UTILITIES
    # =========================================================================

    def normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        parsed = urlparse(url)

        # Normalize path: ensure root path is "/" and remove trailing slashes
        path = parsed.path or "/"  # Empty path becomes "/"
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        # Lowercase scheme and netloc
        normalized = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.params,
            parsed.query,
            "",  # Remove fragment
        ))

        return normalized

    def is_same_domain(self, url: str, base_url: str) -> bool:
        """Check if URL is on the same domain as base."""
        url_parsed = urlparse(url)
        base_parsed = urlparse(base_url)
        return url_parsed.netloc.lower() == base_parsed.netloc.lower()

    def matches_patterns(
        self,
        url: str,
        patterns: List[Dict[str, str]],
    ) -> bool:
        """
        Check if URL matches include/exclude patterns.

        Pattern format:
        [
            {"type": "include", "pattern": "/docs/*"},
            {"type": "exclude", "pattern": "/docs/archive/*"},
        ]
        """
        if not patterns:
            return True

        url_path = urlparse(url).path

        # Check exclude patterns first
        for pattern in patterns:
            if pattern.get("type") == "exclude":
                regex = pattern["pattern"].replace("*", ".*")
                if re.match(regex, url_path):
                    return False

        # Check include patterns
        include_patterns = [p for p in patterns if p.get("type") == "include"]
        if not include_patterns:
            return True

        for pattern in include_patterns:
            regex = pattern["pattern"].replace("*", ".*")
            if re.match(regex, url_path):
                return True

        return False

    def extract_links_from_html(
        self,
        html: str,
        base_url: str,
        same_domain_only: bool = True,
    ) -> List[str]:
        """Extract links from HTML content (fallback when Playwright not available)."""
        soup = BeautifulSoup(html, "html.parser")
        links = set()

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]

            # Skip anchors, javascript, mailto, etc.
            if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            # Resolve relative URLs
            absolute_url = urljoin(base_url, href)

            # Normalize
            normalized = self.normalize_url(absolute_url)

            # Filter to same domain if requested
            if same_domain_only and not self.is_same_domain(normalized, base_url):
                continue

            # Only HTTP(S) URLs
            if urlparse(normalized).scheme in ("http", "https"):
                links.add(normalized)

        return list(links)

    def compute_content_hash(self, content: str) -> str:
        """Compute SHA-256 hash of content for change detection."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _url_to_filename(self, url: str) -> str:
        """Convert URL to a safe filename."""
        url_path = extract_url_path(url)
        safe_filename = url_path.replace("/", "_").strip("_") or "index"
        if not safe_filename.endswith(".html"):
            safe_filename += ".html"
        return safe_filename

    # =========================================================================
    # CRAWL OPERATIONS
    # =========================================================================

    async def start_crawl(
        self,
        session: AsyncSession,
        collection_id: UUID,
        user_id: Optional[UUID] = None,
    ) -> Run:
        """
        Start a crawl run for a collection.

        Creates a Run record to track the crawl operation.

        Args:
            session: Database session
            collection_id: Collection UUID
            user_id: User initiating the crawl

        Returns:
            Run instance for the crawl
        """
        collection = await scrape_service.get_collection(session, collection_id)
        if not collection:
            raise ValueError(f"Collection {collection_id} not found")

        # Create crawl run
        run = await run_service.create_run(
            session=session,
            organization_id=collection.organization_id,
            run_type="scrape",
            origin="user" if user_id else "system",
            config={
                "collection_id": str(collection_id),
                "collection_name": collection.name,
                "root_url": collection.root_url,
                "collection_mode": collection.collection_mode,
                **collection.crawl_config,
            },
            created_by=user_id,
        )

        # Update collection with run reference
        collection.last_crawl_run_id = run.id
        collection.last_crawl_at = datetime.utcnow()
        await session.commit()

        logger.info(f"Started crawl run {run.id} for collection {collection_id}")

        return run

    async def _render_page_with_playwright(
        self,
        url: str,
        config: Dict[str, Any],
    ) -> Tuple[Optional[str], Optional[str], Optional[List[str]], Optional[List[Dict]], Optional[str], Optional[str]]:
        """
        Render page using Playwright and extract content inline.

        Returns:
            Tuple of (html, markdown, discovered_urls, document_links, final_url, error)
        """
        playwright = await self._get_playwright_client()
        if not playwright:
            return None, None, None, None, None, "Playwright service not configured"

        try:
            result = await playwright.render_page(
                url=url,
                wait_for_selector=config.get("wait_for_selector"),
                wait_timeout_ms=config.get("wait_timeout_ms", 5000),
                viewport_width=config.get("viewport_width", 1920),
                viewport_height=config.get("viewport_height", 1080),
                timeout_ms=config.get("render_timeout_ms", 30000),
                extract_documents=config.get("download_documents", False),
                document_extensions=config.get("document_extensions", [".pdf", ".docx", ".doc"]),
            )

            # Extract URLs from links
            discovered_urls = [link.url for link in result.links]

            # Extract document links
            document_links = [
                {
                    "url": doc.url,
                    "filename": doc.filename,
                    "extension": doc.extension,
                    "link_text": doc.link_text,
                }
                for doc in result.document_links
            ]

            return (
                result.html,
                result.markdown,
                discovered_urls,
                document_links,
                result.final_url,
                None,
            )

        except PlaywrightError as e:
            return None, None, None, None, None, str(e)
        except Exception as e:
            logger.exception(f"Playwright rendering failed for {url}")
            return None, None, None, None, None, f"Rendering error: {e}"

    async def _fetch_page_fallback(
        self,
        url: str,
        config: Dict[str, Any],
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Fallback to httpx when Playwright is not available.

        Returns:
            Tuple of (html_content, content_type, error_message)
        """
        try:
            client = await self._get_http_client(config)
            response = await client.get(url)

            if response.status_code >= 400:
                return None, None, f"HTTP {response.status_code}"

            content_type = response.headers.get("content-type", "")

            # Only process HTML content
            if "text/html" not in content_type:
                return None, content_type, f"Unsupported content type: {content_type}"

            return response.text, content_type, None

        except httpx.RequestError as e:
            return None, None, f"Request failed: {str(e)}"
        except Exception as e:
            return None, None, f"Unexpected error: {str(e)}"

    async def crawl_url(
        self,
        session: AsyncSession,
        collection_id: UUID,
        url: str,
        crawl_run_id: UUID,
        source_id: Optional[UUID] = None,
        parent_url: Optional[str] = None,
        crawl_depth: int = 0,
        config: Optional[Dict[str, Any]] = None,
    ) -> CrawlResult:
        """
        Crawl a single URL using Playwright with inline extraction.

        Uses Playwright for JavaScript rendering. Content is extracted inline
        during the crawl (no separate extraction job needed for web pages).

        Args:
            session: Database session
            collection_id: Collection UUID
            url: URL to crawl
            crawl_run_id: Run UUID for this crawl
            source_id: Optional source that discovered this URL
            parent_url: URL of parent page
            crawl_depth: Current depth from seed URL
            config: Crawl configuration

        Returns:
            CrawlResult with crawl outcome
        """
        config = config or DEFAULT_CRAWL_CONFIG
        normalized_url = self.normalize_url(url)

        logger.debug(f"Crawling URL: {normalized_url} (depth: {crawl_depth})")

        # Check if URL already exists in collection
        existing = await scrape_service.get_scraped_asset_by_url(
            session, collection_id, normalized_url
        )

        # Get collection for organization ID
        collection = await scrape_service.get_collection(session, collection_id)
        if not collection:
            return CrawlResult(
                url=normalized_url,
                success=False,
                error="Collection not found",
            )

        # Try Playwright first, fallback to httpx
        playwright = await self._get_playwright_client()

        if playwright:
            # Use Playwright for JS rendering with inline extraction
            html_content, markdown_content, discovered_urls, document_links, final_url, error = \
                await self._render_page_with_playwright(normalized_url, config)

            if error:
                logger.warning(f"Playwright failed for {normalized_url}: {error}")
                return CrawlResult(
                    url=normalized_url,
                    success=False,
                    error=error,
                )

            # Filter discovered URLs to same domain if needed
            follow_external = config.get("follow_external_links", False)
            if not follow_external:
                discovered_urls = [
                    u for u in discovered_urls
                    if self.is_same_domain(u, normalized_url)
                ]

        else:
            # Fallback to httpx (no JS rendering)
            logger.warning(f"Playwright not configured, using httpx fallback for {normalized_url}")
            html_content, content_type, error = await self._fetch_page_fallback(normalized_url, config)

            if error:
                logger.warning(f"Failed to fetch {normalized_url}: {error}")
                return CrawlResult(
                    url=normalized_url,
                    success=False,
                    error=error,
                )

            # Extract links manually (no JS execution)
            follow_external = config.get("follow_external_links", False)
            discovered_urls = self.extract_links_from_html(
                html_content,
                normalized_url,
                same_domain_only=not follow_external,
            )
            markdown_content = None  # Will need extraction service
            document_links = []
            final_url = normalized_url

        # Compute content hash for change detection
        content_hash = self.compute_content_hash(html_content)

        # Handle existing asset
        if existing:
            existing_hash = existing.scrape_metadata.get("content_hash")
            if existing_hash == content_hash:
                logger.debug(f"Content unchanged for {normalized_url}")

                # Still download documents even if content unchanged
                # (documents may not have been downloaded on previous crawl)
                documents_downloaded = 0
                if config.get("download_documents", False) and document_links:
                    documents_downloaded = await self._download_discovered_documents(
                        session, collection, document_links, crawl_run_id
                    )

                return CrawlResult(
                    url=normalized_url,
                    success=True,
                    asset_id=existing.asset_id,
                    scraped_asset_id=existing.id,
                    discovered_urls=discovered_urls,
                    is_new=False,
                    was_updated=False,
                    documents_discovered=len(document_links) if document_links else 0,
                    documents_downloaded=documents_downloaded,
                )

            # Content changed - create new version
            logger.info(f"Content changed for {normalized_url}, creating new version")

            asset_id = await self._store_content_with_inline_extraction(
                session=session,
                collection=collection,
                url=normalized_url,
                html_content=html_content,
                markdown_content=markdown_content,
                content_hash=content_hash,
                crawl_run_id=crawl_run_id,
                is_update=True,
                existing_asset_id=existing.asset_id,
                final_url=final_url,
            )

            # Update scraped asset metadata
            existing.crawl_run_id = crawl_run_id
            existing.crawl_depth = crawl_depth
            existing.scrape_metadata = {
                **existing.scrape_metadata,
                "content_hash": content_hash,
                "last_crawled_at": datetime.utcnow().isoformat(),
                "version_count": existing.scrape_metadata.get("version_count", 1) + 1,
                "final_url": final_url,
            }
            await session.commit()

            # Handle document downloads
            documents_downloaded = 0
            if config.get("download_documents", False) and document_links:
                documents_downloaded = await self._download_discovered_documents(
                    session, collection, document_links, crawl_run_id
                )

            return CrawlResult(
                url=normalized_url,
                success=True,
                asset_id=asset_id,
                scraped_asset_id=existing.id,
                discovered_urls=discovered_urls,
                is_new=False,
                was_updated=True,
                documents_discovered=len(document_links) if document_links else 0,
                documents_downloaded=documents_downloaded,
            )

        # Create new asset with inline extraction
        asset_id = await self._store_content_with_inline_extraction(
            session=session,
            collection=collection,
            url=normalized_url,
            html_content=html_content,
            markdown_content=markdown_content,
            content_hash=content_hash,
            crawl_run_id=crawl_run_id,
            final_url=final_url,
        )

        # Create scraped asset record
        scraped_asset = await scrape_service.create_scraped_asset(
            session=session,
            asset_id=asset_id,
            collection_id=collection_id,
            url=normalized_url,
            asset_subtype="page",
            source_id=source_id,
            parent_url=parent_url,
            crawl_depth=crawl_depth,
            crawl_run_id=crawl_run_id,
            scrape_metadata={
                "content_hash": content_hash,
                "content_type": "text/html",
                "first_crawled_at": datetime.utcnow().isoformat(),
                "last_crawled_at": datetime.utcnow().isoformat(),
                "version_count": 1,
                "final_url": final_url,
                "extraction_method": "playwright_inline" if playwright else "httpx_fallback",
            },
        )

        logger.info(f"Created scraped asset {scraped_asset.id} for {normalized_url}")

        # Handle document downloads
        documents_downloaded = 0
        if config.get("download_documents", False) and document_links:
            documents_downloaded = await self._download_discovered_documents(
                session, collection, document_links, crawl_run_id
            )

        return CrawlResult(
            url=normalized_url,
            success=True,
            asset_id=asset_id,
            scraped_asset_id=scraped_asset.id,
            discovered_urls=discovered_urls,
            is_new=True,
            documents_discovered=len(document_links) if document_links else 0,
            documents_downloaded=documents_downloaded,
        )

    async def _store_content_with_inline_extraction(
        self,
        session: AsyncSession,
        collection: ScrapeCollection,
        url: str,
        html_content: str,
        markdown_content: Optional[str],
        content_hash: str,
        crawl_run_id: UUID,
        is_update: bool = False,
        existing_asset_id: Optional[UUID] = None,
        final_url: Optional[str] = None,
    ) -> UUID:
        """
        Store crawled content with inline extraction.

        This creates both the raw HTML and extracted markdown in a single operation,
        avoiding a separate extraction job for web-scraped content.

        Args:
            session: Database session
            collection: Collection instance
            url: Source URL
            html_content: HTML content
            markdown_content: Extracted markdown (from Playwright)
            content_hash: SHA-256 hash of content
            crawl_run_id: Run UUID
            is_update: Whether this is an update to existing asset
            existing_asset_id: Existing asset ID if updating
            final_url: Final URL after redirects

        Returns:
            Asset UUID
        """
        minio_svc = get_minio_service()
        if not minio_svc:
            raise ValueError("MinIO service is not available")

        org_id = str(collection.organization_id)
        collection_slug = collection.slug

        # Encode content to bytes
        html_bytes = html_content.encode("utf-8")
        html_length = len(html_bytes)

        # Generate human-readable storage path based on URL structure
        html_key = storage_paths.scrape_page(org_id, collection_slug, url, extracted=False)

        if is_update and existing_asset_id:
            # Create new version for existing asset
            version = await asset_service.create_asset_version(
                session=session,
                asset_id=existing_asset_id,
                raw_bucket=settings.minio_bucket_uploads,
                raw_object_key=html_key,
                file_size=html_length,
                file_hash=content_hash,
                content_type="text/html",
                trigger_extraction=False,  # Inline extraction - no separate job
            )

            # Upload HTML to storage
            minio_svc.put_object(
                bucket=settings.minio_bucket_uploads,
                key=html_key,
                data=BytesIO(html_bytes),
                length=html_length,
                content_type="text/html",
            )

            # Store extracted markdown if available
            if markdown_content:
                await self._store_extracted_markdown(
                    minio_svc, session, existing_asset_id, org_id,
                    collection_slug, url, markdown_content, crawl_run_id
                )

            return existing_asset_id

        else:
            # Check for existing asset at this storage path (prevents unique constraint violation)
            existing_by_path = await asset_service.get_asset_by_object_key(
                session, settings.minio_bucket_uploads, html_key
            )
            if existing_by_path:
                logger.info(f"Page already exists at path: {html_key}, reusing existing asset {existing_by_path.id}")
                # Update the existing asset with new content
                minio_svc.put_object(
                    bucket=settings.minio_bucket_uploads,
                    key=html_key,
                    data=BytesIO(html_bytes),
                    length=html_length,
                    content_type="text/html",
                )
                # Store extracted markdown if available
                if markdown_content:
                    await self._store_extracted_markdown(
                        minio_svc, session, existing_by_path.id, org_id,
                        collection_slug, url, markdown_content, crawl_run_id
                    )
                return existing_by_path.id

            # Create new asset - store directly at permanent path (no temp)
            # Determine initial status - "ready" if we have markdown, "pending" otherwise
            initial_status = "ready" if markdown_content else "pending"

            # Create asset record with final storage path
            asset = await asset_service.create_asset(
                session=session,
                organization_id=collection.organization_id,
                source_type="web_scrape",
                source_metadata={
                    "url": url,
                    "final_url": final_url or url,
                    "collection_id": str(collection.id),
                    "collection_name": collection.name,
                    "crawl_run_id": str(crawl_run_id),
                },
                original_filename=self._url_to_filename(url),
                raw_bucket=settings.minio_bucket_uploads,
                raw_object_key=html_key,
                content_type="text/html",
                file_size=html_length,
                file_hash=content_hash,
                status=initial_status,
            )

            # Upload HTML to permanent location
            minio_svc.put_object(
                bucket=settings.minio_bucket_uploads,
                key=html_key,
                data=BytesIO(html_bytes),
                length=html_length,
                content_type="text/html",
            )

            # Store extracted markdown if available
            if markdown_content:
                await self._store_extracted_markdown(
                    minio_svc, session, asset.id, org_id,
                    collection_slug, url, markdown_content, crawl_run_id
                )

            return asset.id

    async def _store_extracted_markdown(
        self,
        minio_svc,
        session: AsyncSession,
        asset_id: UUID,
        org_id: str,
        collection_slug: str,
        url: str,
        markdown_content: str,
        crawl_run_id: UUID,
    ) -> None:
        """
        Store extracted markdown and create ExtractionResult record.

        This is the inline extraction path - no separate Celery job needed.

        Args:
            minio_svc: MinIO service instance
            session: Database session
            asset_id: Asset UUID
            org_id: Organization ID string
            collection_slug: Collection slug for path generation
            url: Source URL for path generation
            markdown_content: Extracted markdown content
            crawl_run_id: Crawl run UUID
        """
        # Store markdown to processed bucket using human-readable path
        md_key = storage_paths.scrape_page(org_id, collection_slug, url, extracted=True)
        md_bytes = markdown_content.encode("utf-8")

        minio_svc.put_object(
            bucket=settings.minio_bucket_processed,
            key=md_key,
            data=BytesIO(md_bytes),
            length=len(md_bytes),
            content_type="text/markdown",
        )

        # Create a Run record for this inline extraction
        run = await run_service.create_run(
            session=session,
            organization_id=UUID(org_id),
            run_type="extraction",
            origin="system",
            config={
                "extractor_version": "playwright-inline-1.0",
                "asset_id": str(asset_id),
                "method": "playwright_inline",
                "crawl_run_id": str(crawl_run_id),
            },
            input_asset_ids=[str(asset_id)],
            created_by=None,
        )

        # Mark run as started and immediately completed
        await run_service.start_run(session, run.id)

        # Create ExtractionResult with completed status
        extraction = await extraction_result_service.create_extraction_result(
            session=session,
            asset_id=asset_id,
            run_id=run.id,
            extractor_version="playwright-inline-1.0",
        )

        # Record success
        await extraction_result_service.record_extraction_success(
            session=session,
            extraction_id=extraction.id,
            bucket=settings.minio_bucket_processed,
            key=md_key,
            extraction_time_seconds=0.0,  # Inline - negligible
            structure_metadata={
                "method": "playwright_inline",
                "markdown_length": len(markdown_content),
            },
        )

        # Complete the run
        await run_service.complete_run(
            session=session,
            run_id=run.id,
            results_summary={
                "status": "completed",
                "method": "playwright_inline",
                "markdown_length": len(markdown_content),
            },
        )

        logger.debug(f"Stored inline extraction for asset {asset_id}")

    async def _download_discovered_documents(
        self,
        session: AsyncSession,
        collection: ScrapeCollection,
        document_links: List[Dict],
        crawl_run_id: UUID,
    ) -> int:
        """
        Download discovered documents and create assets for extraction.

        Downloaded documents go through the normal extraction pipeline (Docling).

        Args:
            session: Database session
            collection: Collection instance
            document_links: List of document link info dicts
            crawl_run_id: Crawl run UUID

        Returns:
            Number of documents successfully downloaded
        """
        from .upload_integration_service import upload_integration_service

        downloaded = 0
        config = collection.crawl_config or {}

        for doc_link in document_links:
            try:
                doc_url = doc_link["url"]
                doc_filename = doc_link["filename"]
                doc_extension = doc_link["extension"]

                logger.info(f"Downloading document: {doc_filename} from {doc_url}")

                # Download the file
                client = await self._get_http_client(config)
                response = await client.get(doc_url)

                if response.status_code != 200:
                    logger.warning(f"Failed to download {doc_url}: HTTP {response.status_code}")
                    continue

                content = response.content
                content_hash = hashlib.sha256(content).hexdigest()

                # Determine content type
                content_type = response.headers.get("content-type", "application/octet-stream")
                if ";" in content_type:
                    content_type = content_type.split(";")[0].strip()

                # Store to MinIO using human-readable path
                minio_svc = get_minio_service()
                org_id = str(collection.organization_id)
                collection_slug = collection.slug

                # Generate document path: {org}/scrape/{collection}/documents/{filename}
                doc_key = storage_paths.scrape_document(
                    org_id, collection_slug, doc_filename, extracted=False
                )

                # Check for duplicates by hash first
                existing = await asset_service.get_asset_by_hash(
                    session, collection.organization_id, content_hash
                )
                if existing:
                    logger.info(f"Document already exists (hash match): {doc_filename}")
                    continue

                # Check for existing asset at this storage path (prevents unique constraint violation)
                existing_by_path = await asset_service.get_asset_by_object_key(
                    session, settings.minio_bucket_uploads, doc_key
                )
                if existing_by_path:
                    logger.info(f"Document already exists at path (path match): {doc_key}")
                    continue

                minio_svc.put_object(
                    bucket=settings.minio_bucket_uploads,
                    key=doc_key,
                    data=BytesIO(content),
                    length=len(content),
                    content_type=content_type,
                )

                # Create asset with final storage path
                asset = await asset_service.create_asset(
                    session=session,
                    organization_id=collection.organization_id,
                    source_type="web_scrape_document",
                    source_metadata={
                        "source_url": doc_url,
                        "collection_id": str(collection.id),
                        "collection_name": collection.name,
                        "crawl_run_id": str(crawl_run_id),
                        "link_text": doc_link.get("link_text", ""),
                    },
                    original_filename=doc_filename,
                    raw_bucket=settings.minio_bucket_uploads,
                    raw_object_key=doc_key,
                    content_type=content_type,
                    file_size=len(content),
                    file_hash=content_hash,
                    status="pending",  # Will go through extraction
                )

                # Trigger extraction (will use Docling for PDFs, etc.)
                try:
                    await upload_integration_service.trigger_extraction(
                        session=session,
                        asset_id=asset.id,
                    )
                    logger.info(f"Triggered extraction for downloaded document {asset.id}")
                except Exception as e:
                    logger.warning(f"Failed to trigger extraction for {asset.id}: {e}")

                # Create scraped asset record for the document
                await scrape_service.create_scraped_asset(
                    session=session,
                    asset_id=asset.id,
                    collection_id=collection.id,
                    url=doc_url,
                    asset_subtype="document",
                    crawl_run_id=crawl_run_id,
                    scrape_metadata={
                        "document_type": doc_extension,
                        "original_filename": doc_filename,
                        "link_text": doc_link.get("link_text", ""),
                        "downloaded_at": datetime.utcnow().isoformat(),
                    },
                )

                downloaded += 1

            except Exception as e:
                logger.exception(f"Failed to download document {doc_link.get('url')}: {e}")
                continue

        return downloaded

    async def crawl_collection(
        self,
        session: AsyncSession,
        collection_id: UUID,
        user_id: Optional[UUID] = None,
        max_pages: Optional[int] = None,
        run_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Crawl all sources in a collection.

        Performs breadth-first crawl starting from seed URLs in sources,
        respecting depth limits and URL patterns. Uses Playwright for
        JavaScript rendering when available.

        Args:
            session: Database session
            collection_id: Collection UUID
            user_id: User initiating the crawl
            max_pages: Override max pages limit
            run_id: Optional existing Run ID to use (skips creating new run)

        Returns:
            Summary of crawl results
        """
        collection = await scrape_service.get_collection(session, collection_id)
        if not collection:
            raise ValueError(f"Collection {collection_id} not found")

        config = {**DEFAULT_CRAWL_CONFIG, **collection.crawl_config}
        if max_pages:
            config["max_pages"] = max_pages

        # Use existing run or start a new crawl run
        if run_id:
            run = await run_service.get_run(session, run_id)
            if not run:
                raise ValueError(f"Run {run_id} not found")
            await run_service.start_run(session, run.id)
        else:
            run = await self.start_crawl(session, collection_id, user_id)
            await run_service.start_run(session, run.id)

        # Get active sources
        sources = await scrape_service.list_sources(
            session, collection_id, is_active=True
        )

        if not sources:
            await run_service.complete_run(
                session,
                run.id,
                results_summary={"error": "No active sources", "pages_crawled": 0},
            )
            return {"error": "No active sources", "pages_crawled": 0}

        # Crawl tracking
        visited: Set[str] = set()
        queue: List[Tuple[str, Optional[UUID], Optional[str], int]] = []
        results: List[CrawlResult] = []

        # Initialize queue with seed URLs
        for source in sources:
            normalized = self.normalize_url(source.url)
            if normalized not in visited:
                queue.append((normalized, source.id, None, 0))
                visited.add(normalized)

        max_depth = config.get("max_depth", 3)  # 0 or None means unlimited
        max_pages_limit = config.get("max_pages", 100)
        delay = config.get("delay_seconds", 1.0)

        pages_crawled = 0
        pages_new = 0
        pages_updated = 0
        pages_failed = 0
        total_documents_discovered = 0
        total_documents_downloaded = 0

        try:
            while queue and pages_crawled < max_pages_limit:
                url, source_id, parent_url, depth = queue.pop(0)

                # Skip if exceeds depth (0 or None means unlimited)
                if max_depth and max_depth > 0 and depth > max_depth:
                    continue

                # Check URL patterns
                if not self.matches_patterns(url, collection.url_patterns):
                    logger.debug(f"Skipping {url} - doesn't match patterns")
                    continue

                # Crawl the URL
                result = await self.crawl_url(
                    session=session,
                    collection_id=collection_id,
                    url=url,
                    crawl_run_id=run.id,
                    source_id=source_id,
                    parent_url=parent_url,
                    crawl_depth=depth,
                    config=config,
                )

                results.append(result)
                pages_crawled += 1
                total_documents_discovered += result.documents_discovered
                total_documents_downloaded += result.documents_downloaded

                if result.success:
                    if result.is_new:
                        pages_new += 1
                    elif result.was_updated:
                        pages_updated += 1

                    # Add discovered URLs to queue
                    for discovered_url in result.discovered_urls:
                        normalized_discovered = self.normalize_url(discovered_url)
                        if normalized_discovered not in visited:
                            visited.add(normalized_discovered)
                            queue.append((normalized_discovered, source_id, url, depth + 1))
                else:
                    pages_failed += 1

                # Update progress
                await run_service.update_run_progress(
                    session=session,
                    run_id=run.id,
                    current=pages_crawled,
                    total=min(len(visited), max_pages_limit),
                    unit="pages",
                )

                # Rate limiting
                if delay > 0:
                    await asyncio.sleep(delay)

            # Update collection stats
            await scrape_service.update_collection_stats(session, collection_id)

            # Complete run
            summary = {
                "pages_crawled": pages_crawled,
                "pages_new": pages_new,
                "pages_updated": pages_updated,
                "pages_failed": pages_failed,
                "urls_discovered": len(visited),
                "urls_remaining": len(queue),
                "documents_discovered": total_documents_discovered,
                "documents_downloaded": total_documents_downloaded,
            }

            await run_service.complete_run(session, run.id, results_summary=summary)

            logger.info(
                f"Completed crawl for collection {collection_id}: "
                f"{pages_crawled} pages ({pages_new} new, {pages_updated} updated, {pages_failed} failed), "
                f"{total_documents_downloaded} documents downloaded"
            )

            return summary

        except Exception as e:
            logger.error(f"Crawl failed for collection {collection_id}: {e}")
            await run_service.fail_run(session, run.id, str(e))
            raise

        finally:
            await self.close()


# Singleton instance
crawl_service = CrawlService()
