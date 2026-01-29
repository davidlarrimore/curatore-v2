"""
Crawl Service for Web Scraping Operations.

Provides web crawling functionality for Phase 4: Web Scraping as Durable Data Source.
Handles URL fetching, content extraction, asset creation, and version tracking
for re-crawls. Integrates with Run system for traceability.

Key Features:
- Rate-limited web page fetching with configurable delays
- Content extraction via extraction service or raw HTML storage
- Asset and ScrapedAsset creation with hierarchical path tracking
- Re-crawl versioning for content updates
- Run-attributed crawl tracking
- Support for snapshot and record_preserving collection modes

Usage:
    from app.services.crawl_service import crawl_service

    # Start a crawl run
    run = await crawl_service.start_crawl(
        session=session,
        collection_id=collection_id,
        user_id=user_id,
    )

    # Crawl a single URL
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
from uuid import UUID
from io import BytesIO
from pathlib import Path

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
from .upload_integration_service import upload_integration_service

logger = logging.getLogger("curatore.crawl_service")


# Default crawl configuration
DEFAULT_CRAWL_CONFIG = {
    "max_depth": 3,
    "max_pages": 100,
    "delay_seconds": 1.0,
    "timeout_seconds": 30,
    "respect_robots_txt": True,
    "user_agent": "Curatore/2.0 (+https://curatore.ai)",
    "follow_external_links": False,
    "extract_content": True,
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
    ):
        self.url = url
        self.success = success
        self.asset_id = asset_id
        self.scraped_asset_id = scraped_asset_id
        self.error = error
        self.discovered_urls = discovered_urls or []
        self.is_new = is_new
        self.was_updated = was_updated


class CrawlService:
    """
    Service for crawling web pages and managing scrape operations.

    Handles the actual fetching, parsing, and storage of web content.
    Works in conjunction with ScrapeService for collection management.
    """

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self, config: Dict[str, Any]) -> httpx.AsyncClient:
        """Get or create HTTP client with configured settings."""
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
        """Close the HTTP client."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    # =========================================================================
    # URL UTILITIES
    # =========================================================================

    def normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        parsed = urlparse(url)

        # Remove trailing slash from path
        path = parsed.path.rstrip("/") if parsed.path != "/" else "/"

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

    def extract_links(
        self,
        html: str,
        base_url: str,
        same_domain_only: bool = True,
    ) -> List[str]:
        """Extract links from HTML content."""
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

    async def fetch_page(
        self,
        url: str,
        config: Dict[str, Any],
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Fetch a web page and return its content.

        Args:
            url: URL to fetch
            config: Crawl configuration

        Returns:
            Tuple of (html_content, content_type, error_message)
        """
        try:
            client = await self._get_client(config)
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
        Crawl a single URL and create/update the scraped asset.

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

        # Fetch the page
        html_content, content_type, error = await self.fetch_page(normalized_url, config)

        if error:
            logger.warning(f"Failed to fetch {normalized_url}: {error}")
            return CrawlResult(
                url=normalized_url,
                success=False,
                error=error,
            )

        # Extract links for discovery
        follow_external = config.get("follow_external_links", False)
        discovered_urls = self.extract_links(
            html_content,
            normalized_url,
            same_domain_only=not follow_external,
        )

        # Compute content hash for change detection
        content_hash = self.compute_content_hash(html_content)

        # Get collection for organization ID
        collection = await scrape_service.get_collection(session, collection_id)
        if not collection:
            return CrawlResult(
                url=normalized_url,
                success=False,
                error="Collection not found",
            )

        # Handle existing asset
        if existing:
            # Check if content changed
            existing_hash = existing.scrape_metadata.get("content_hash")
            if existing_hash == content_hash:
                logger.debug(f"Content unchanged for {normalized_url}")
                return CrawlResult(
                    url=normalized_url,
                    success=True,
                    asset_id=existing.asset_id,
                    scraped_asset_id=existing.id,
                    discovered_urls=discovered_urls,
                    is_new=False,
                    was_updated=False,
                )

            # Content changed - create new version
            logger.info(f"Content changed for {normalized_url}, creating new version")

            # Store new content and create new version
            asset_id, object_key = await self._store_content(
                session,
                collection,
                normalized_url,
                html_content,
                content_hash,
                crawl_run_id,
                is_update=True,
                existing_asset_id=existing.asset_id,
            )

            # Trigger extraction for the updated asset
            try:
                await upload_integration_service.trigger_extraction(
                    session=session,
                    asset_id=asset_id,
                )
                logger.debug(f"Triggered extraction for updated asset {asset_id}")
            except Exception as e:
                logger.warning(f"Failed to trigger extraction for {asset_id}: {e}")
                # Continue - extraction failure shouldn't block crawl

            # Update scraped asset metadata
            existing.crawl_run_id = crawl_run_id
            existing.crawl_depth = crawl_depth
            existing.scrape_metadata = {
                **existing.scrape_metadata,
                "content_hash": content_hash,
                "last_crawled_at": datetime.utcnow().isoformat(),
                "version_count": existing.scrape_metadata.get("version_count", 1) + 1,
            }
            await session.commit()

            return CrawlResult(
                url=normalized_url,
                success=True,
                asset_id=asset_id,
                scraped_asset_id=existing.id,
                discovered_urls=discovered_urls,
                is_new=False,
                was_updated=True,
            )

        # Create new asset and scraped asset
        asset_id, object_key = await self._store_content(
            session,
            collection,
            normalized_url,
            html_content,
            content_hash,
            crawl_run_id,
        )

        # Trigger extraction for the new asset
        try:
            await upload_integration_service.trigger_extraction(
                session=session,
                asset_id=asset_id,
            )
            logger.debug(f"Triggered extraction for scraped asset {asset_id}")
        except Exception as e:
            logger.warning(f"Failed to trigger extraction for {asset_id}: {e}")
            # Continue - extraction failure shouldn't block crawl

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
                "content_type": content_type,
                "first_crawled_at": datetime.utcnow().isoformat(),
                "last_crawled_at": datetime.utcnow().isoformat(),
                "version_count": 1,
            },
        )

        logger.info(f"Created scraped asset {scraped_asset.id} for {normalized_url}")

        return CrawlResult(
            url=normalized_url,
            success=True,
            asset_id=asset_id,
            scraped_asset_id=scraped_asset.id,
            discovered_urls=discovered_urls,
            is_new=True,
        )

    async def _store_content(
        self,
        session: AsyncSession,
        collection: ScrapeCollection,
        url: str,
        content: str,
        content_hash: str,
        crawl_run_id: UUID,
        is_update: bool = False,
        existing_asset_id: Optional[UUID] = None,
    ) -> Tuple[UUID, str]:
        """
        Store crawled content in object storage and create/update asset.

        Args:
            session: Database session
            collection: Collection instance
            url: Source URL
            content: HTML content
            content_hash: SHA-256 hash of content
            crawl_run_id: Run UUID
            is_update: Whether this is an update to existing asset
            existing_asset_id: Existing asset ID if updating

        Returns:
            Tuple of (asset_id, object_key)
        """
        # Get MinIO service instance
        minio_svc = get_minio_service()
        if not minio_svc:
            raise ValueError("MinIO service is not available")

        org_id = str(collection.organization_id)
        url_path = extract_url_path(url)

        # Generate filename from URL path
        safe_filename = url_path.replace("/", "_").strip("_") or "index"
        if not safe_filename.endswith(".html"):
            safe_filename += ".html"

        # Encode content to bytes
        content_bytes = content.encode("utf-8")
        content_length = len(content_bytes)

        if is_update and existing_asset_id:
            # Create new version for existing asset
            version = await asset_service.create_asset_version(
                session=session,
                asset_id=existing_asset_id,
                raw_bucket=settings.minio_bucket_uploads,
                raw_object_key=f"{org_id}/{existing_asset_id}/raw/{safe_filename}",
                file_size=content_length,
                file_hash=content_hash,
                content_type="text/html",
                trigger_extraction=True,
            )

            # Upload to storage using put_object (synchronous)
            object_key = f"{org_id}/{existing_asset_id}/raw/{safe_filename}"
            minio_svc.put_object(
                bucket=settings.minio_bucket_uploads,
                key=object_key,
                data=BytesIO(content_bytes),
                length=content_length,
                content_type="text/html",
            )

            return existing_asset_id, object_key

        else:
            # Create new asset
            # First, upload to storage with temp key
            temp_key = f"{org_id}/temp/{content_hash}/{safe_filename}"
            minio_svc.put_object(
                bucket=settings.minio_bucket_uploads,
                key=temp_key,
                data=BytesIO(content_bytes),
                length=content_length,
                content_type="text/html",
            )

            # Create asset record
            asset = await asset_service.create_asset(
                session=session,
                organization_id=collection.organization_id,
                source_type="web_scrape",
                source_metadata={
                    "url": url,
                    "collection_id": str(collection.id),
                    "collection_name": collection.name,
                    "crawl_run_id": str(crawl_run_id),
                },
                original_filename=safe_filename,
                raw_bucket=settings.minio_bucket_uploads,
                raw_object_key=temp_key,
                content_type="text/html",
                file_size=content_length,
                file_hash=content_hash,
                status="pending",
            )

            # Move to permanent location (synchronous)
            permanent_key = f"{org_id}/{asset.id}/raw/{safe_filename}"
            minio_svc.copy_object(
                source_bucket=settings.minio_bucket_uploads,
                source_key=temp_key,
                dest_bucket=settings.minio_bucket_uploads,
                dest_key=permanent_key,
            )

            # Update asset with permanent key
            asset.raw_object_key = permanent_key
            await session.commit()

            # Clean up temp (synchronous)
            try:
                minio_svc.delete_object(
                    settings.minio_bucket_uploads,
                    temp_key,
                )
            except Exception:
                pass  # Ignore cleanup errors

            return asset.id, permanent_key

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
        respecting depth limits and URL patterns.

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
                {"error": "No active sources", "pages_crawled": 0},
            )
            return {"error": "No active sources", "pages_crawled": 0}

        # Crawl tracking
        visited: Set[str] = set()
        queue: List[Tuple[str, Optional[UUID], Optional[str], int]] = []  # (url, source_id, parent_url, depth)
        results: List[CrawlResult] = []

        # Initialize queue with seed URLs
        for source in sources:
            normalized = self.normalize_url(source.url)
            if normalized not in visited:
                queue.append((normalized, source.id, None, 0))
                visited.add(normalized)

        max_depth = config.get("max_depth", 3)
        max_pages_limit = config.get("max_pages", 100)
        delay = config.get("delay_seconds", 1.0)

        pages_crawled = 0
        pages_new = 0
        pages_updated = 0
        pages_failed = 0

        try:
            while queue and pages_crawled < max_pages_limit:
                url, source_id, parent_url, depth = queue.pop(0)

                # Skip if exceeds depth
                if depth > max_depth:
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
            }

            await run_service.complete_run(session, run.id, summary)

            logger.info(
                f"Completed crawl for collection {collection_id}: "
                f"{pages_crawled} pages ({pages_new} new, {pages_updated} updated, {pages_failed} failed)"
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
