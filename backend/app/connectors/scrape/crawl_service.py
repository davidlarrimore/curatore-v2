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
- HTTP conditional requests (ETag/If-None-Match, Last-Modified/If-Modified-Since)
  for efficient re-crawling - skips unchanged pages without re-downloading
- Content hash-based change detection for pages that don't support conditional requests
- Automatic search indexing for inline-extracted content
- Locale/language variant URL filtering to avoid duplicate content

Efficiency Optimizations:
- Uses HTTP 304 Not Modified responses to skip unchanged pages
- Stores ETag and Last-Modified headers in scrape_metadata for future requests
- URL-based skip for documents already in collection (avoids redundant downloads)
- Smart external document filtering with CDN pattern recognition

Usage:
    from app.connectors.scrape.crawl_service import crawl_service

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
import random
import re
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse
from uuid import UUID

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database.models import (
    Run,
    ScrapeCollection,
)
from app.core.ingestion.extraction_result_service import extraction_result_service
from app.core.shared.asset_service import asset_service
from app.core.shared.run_log_service import run_log_service
from app.core.shared.run_service import run_service
from app.core.storage.minio_service import get_minio_service
from app.core.storage.storage_path_service import storage_paths

from .playwright_client import PlaywrightClient, PlaywrightError, get_playwright_client
from .scrape_service import extract_url_path, scrape_service

logger = logging.getLogger("curatore.crawl_service")


# Default crawl configuration
DEFAULT_CRAWL_CONFIG = {
    "max_depth": 3,  # 0 means unlimited depth
    "max_pages": 100,
    "delay_seconds": 2.0,  # Base delay between requests (increased for rate limiting)
    "delay_jitter": 1.0,  # Random jitter added to delay (0-1.0 seconds)
    "timeout_seconds": 30,
    "respect_robots_txt": True,
    "user_agent": "Curatore/2.0 (+https://curatore.ai)",
    "follow_external_links": False,
    # Rate limiting / backoff
    "backoff_on_error": True,  # Exponential backoff on 403/429 errors
    "max_consecutive_errors": 5,  # Stop crawl after N consecutive errors
    # Locale exclusion
    "exclude_locales": True,  # Exclude common locale/language variant paths
    # Playwright-specific options
    "wait_for_selector": None,  # CSS selector to wait for
    "wait_timeout_ms": 5000,  # Wait timeout for selector
    "viewport_width": 1920,
    "viewport_height": 1080,
    "render_timeout_ms": 30000,  # Total render timeout
    # Document discovery
    "download_documents": False,  # Auto-download discovered documents
    "document_extensions": [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"],
    # External document handling (when download_documents=True)
    # Modes: "smart" (default), "same_domain_only", "all", "none"
    #   - "smart": Allow same domain, subdomains, known CDNs, and URLs containing site name
    #   - "same_domain_only": Only allow documents from same domain/subdomains
    #   - "all": Download all documents (legacy behavior)
    #   - "none": Skip all external documents
    "external_document_mode": "smart",
    "allowed_document_domains": [],  # Additional domains to allow (e.g., ["company-assets.s3.amazonaws.com"])
    "blocked_document_domains": [],  # Domains to always block (e.g., ["ads.example.com"])
}

# Known CDN patterns - these are commonly used to host legitimate site assets
# Used when external_document_mode="smart"
KNOWN_CDN_PATTERNS = [
    # AWS
    r".*\.cloudfront\.net$",
    r".*\.s3\.amazonaws\.com$",
    r".*\.s3-[\w-]+\.amazonaws\.com$",
    r".*\.s3\.[\w-]+\.amazonaws\.com$",
    # Azure
    r".*\.blob\.core\.windows\.net$",
    r".*\.azureedge\.net$",
    # Google Cloud
    r".*\.storage\.googleapis\.com$",
    r".*\.googleusercontent\.com$",
    # Akamai
    r".*\.akamaized\.net$",
    r".*\.akamai\.net$",
    r".*\.akamaitechnologies\.com$",
    # Cloudflare
    r".*\.cloudflare\.com$",
    r".*\.r2\.dev$",
    # Fastly
    r".*\.fastly\.net$",
    r".*\.fastlylb\.net$",
    # Generic CDN patterns
    r".*\.cdn\.com$",
    r".*-cdn\..*",
    r"cdn\..*",
    r"assets\..*",
    r"static\..*",
    r"files\..*",
    r"media\..*",
    r"downloads\..*",
]

# Common locale path patterns to exclude (when exclude_locales=True)
# Matches paths like /en-us/, /en-gb/, /de-de/, /fr/, /es/, etc.
LOCALE_PATTERNS = [
    r"^/[a-z]{2}-[a-z]{2}/",  # /en-us/, /en-gb/, /de-de/, /fr-fr/
    r"^/[a-z]{2}-[a-z]{2}$",  # /en-us, /en-gb (without trailing slash)
    r"^/(?:af|sq|ar|hy|az|eu|be|bn|bs|bg|ca|zh|hr|cs|da|nl|et|fi|fr|gl|ka|de|el|gu|ht|he|hi|hu|is|id|ga|it|ja|kn|kk|ko|lv|lt|mk|ms|ml|mt|mr|mn|no|fa|pl|pt|pa|ro|ru|sr|sk|sl|es|sw|sv|ta|te|th|tr|uk|ur|uz|vi|cy)/",  # ISO 639-1 codes
]


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

    def is_locale_url(self, url: str, base_url: str) -> bool:
        """
        Check if URL is a locale/language variant of the base URL.

        Detects paths like:
        - /en-us/, /en-gb/, /de-de/, /fr-fr/ (region variants)
        - /fr/, /de/, /es/, /ja/ (language-only paths)

        Args:
            url: URL to check
            base_url: Original root URL to compare against

        Returns:
            True if URL appears to be a locale variant
        """
        url_path = urlparse(url).path.lower()
        base_path = urlparse(base_url).path.lower()

        # If base URL already has a locale path, don't exclude URLs with the same locale
        # e.g., if root is /en-us/, allow /en-us/about but not /fr/about
        for pattern in LOCALE_PATTERNS:
            base_match = re.match(pattern, base_path)
            url_match = re.match(pattern, url_path)

            if url_match:
                # URL has a locale prefix
                if base_match:
                    # Base also has locale - only allow if same locale
                    return url_match.group(0) != base_match.group(0)
                else:
                    # Base doesn't have locale - this is a locale variant
                    return True

        return False

    def _should_download_document(
        self,
        doc_url: str,
        base_url: str,
        config: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """
        Determine if a document should be downloaded based on its URL and config.

        Uses a tiered approach to handle external documents:
        1. Always allow same domain and subdomains
        2. Allow if document hostname contains the site's brand/name
        3. Allow known CDN patterns (CloudFront, S3, Azure, etc.)
        4. Check explicit allow/block lists
        5. Block everything else (for "smart" mode)

        Args:
            doc_url: Full URL of the document to download
            base_url: Root URL of the site being crawled
            config: Crawl configuration dict

        Returns:
            Tuple of (should_download, reason)
        """
        mode = config.get("external_document_mode", "smart")
        allowed_domains = config.get("allowed_document_domains", [])
        blocked_domains = config.get("blocked_document_domains", [])

        doc_parsed = urlparse(doc_url)
        base_parsed = urlparse(base_url)

        doc_host = doc_parsed.netloc.lower()
        base_host = base_parsed.netloc.lower()

        # Extract base domain name (e.g., "steampunk" from "www.steampunk.com")
        base_domain_parts = base_host.replace("www.", "").split(".")
        site_name = base_domain_parts[0] if base_domain_parts else ""

        # Mode: "all" - download everything (legacy behavior)
        if mode == "all":
            return True, "mode=all"

        # Mode: "none" - skip all external documents
        if mode == "none":
            if doc_host == base_host:
                return True, "same_host"
            return False, "mode=none, external document"

        # Check explicit block list first (applies to all modes)
        for blocked in blocked_domains:
            blocked_lower = blocked.lower()
            if doc_host == blocked_lower or doc_host.endswith("." + blocked_lower):
                return False, f"blocked_domain: {blocked}"

        # Check explicit allow list (applies to all modes)
        for allowed in allowed_domains:
            allowed_lower = allowed.lower()
            if doc_host == allowed_lower or doc_host.endswith("." + allowed_lower):
                return True, f"allowed_domain: {allowed}"

        # Tier 1: Same domain or subdomain - always allow
        if doc_host == base_host:
            return True, "same_host"

        # Check if doc_host is a subdomain of base_host
        # e.g., assets.steampunk.com is subdomain of steampunk.com
        base_domain = ".".join(base_domain_parts[-2:]) if len(base_domain_parts) >= 2 else base_host
        if doc_host.endswith("." + base_domain) or doc_host == base_domain:
            return True, "subdomain"

        # For same_domain_only mode, stop here
        if mode == "same_domain_only":
            return False, "external_domain (same_domain_only mode)"

        # Tier 2: Document hostname contains site name (likely their CDN)
        # e.g., "steampunk" in "steampunk-assets.s3.amazonaws.com"
        if site_name and len(site_name) >= 3:  # Avoid matching short names like "a" or "io"
            if site_name in doc_host:
                return True, f"hostname_contains_site_name: {site_name}"

        # Tier 3: Known CDN patterns
        for pattern in KNOWN_CDN_PATTERNS:
            if re.match(pattern, doc_host, re.IGNORECASE):
                return True, f"known_cdn_pattern: {pattern}"

        # Default: block external domains
        return False, f"external_domain: {doc_host}"

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

    def is_locale_path(self, path: str) -> bool:
        """
        Check if a path represents a locale/language variant.

        Used for filtering locale-specific URLs during crawling.
        Matches patterns like /en-us/, /de-de/, /fr/, etc.

        Args:
            path: URL path to check (e.g., "/en-us/about")

        Returns:
            True if path starts with a locale pattern
        """
        path_lower = path.lower()
        for pattern in LOCALE_PATTERNS:
            if re.match(pattern, path_lower):
                return True
        return False

    def extract_document_links_from_html(
        self,
        html: str,
        base_url: str,
        extensions: Optional[List[str]] = None,
    ) -> List[Dict[str, str]]:
        """
        Extract document download links from HTML content.

        Scans for links pointing to downloadable documents (PDF, DOCX, etc.)
        and returns structured metadata for each discovered document.

        Args:
            html: HTML content to parse
            base_url: Base URL for resolving relative links
            extensions: List of file extensions to look for (e.g., [".pdf", ".docx"])

        Returns:
            List of dicts with keys: url, filename, extension, link_text
        """
        if extensions is None:
            extensions = DEFAULT_CRAWL_CONFIG["document_extensions"]

        documents = []
        soup = BeautifulSoup(html, "html.parser")

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]

            # Resolve relative URLs
            absolute_url = urljoin(base_url, href)

            # Check if URL ends with a document extension
            url_lower = absolute_url.lower()
            for ext in extensions:
                if url_lower.endswith(ext.lower()):
                    # Extract filename from URL
                    parsed = urlparse(absolute_url)
                    path_parts = parsed.path.split("/")
                    filename = path_parts[-1] if path_parts else f"document{ext}"

                    # Clean up filename
                    if not filename:
                        filename = f"document{ext}"

                    documents.append({
                        "url": absolute_url,
                        "filename": filename,
                        "extension": ext.lower(),
                        "link_text": anchor.get_text(strip=True)[:100],
                    })
                    break  # Don't check other extensions for this link

        return documents

    def compute_content_hash(self, content: str) -> str:
        """
        Compute SHA-256 hash of content for change detection.

        Used to determine if page content has changed since last crawl,
        avoiding unnecessary re-processing of unchanged pages.

        Args:
            content: HTML content string

        Returns:
            64-character lowercase hex SHA-256 hash
        """
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
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str], bool, Optional[str], Optional[str]]:
        """
        Fallback to httpx when Playwright is not available.

        Supports HTTP conditional requests for efficient re-crawling.

        Args:
            url: URL to fetch
            config: Crawl configuration
            etag: ETag from previous response (for If-None-Match header)
            last_modified: Last-Modified from previous response (for If-Modified-Since header)

        Returns:
            Tuple of (html_content, content_type, error_message, not_modified, new_etag, new_last_modified)
            - not_modified: True if server returned 304 (content unchanged)
            - new_etag/new_last_modified: Headers from response for future conditional requests
        """
        try:
            client = await self._get_http_client(config)

            # Build conditional request headers
            headers = {}
            if etag:
                headers["If-None-Match"] = etag
            if last_modified:
                headers["If-Modified-Since"] = last_modified

            response = await client.get(url, headers=headers if headers else None)

            # Handle 304 Not Modified - content unchanged
            if response.status_code == 304:
                logger.debug(f"304 Not Modified for {url}")
                return None, None, None, True, etag, last_modified

            if response.status_code >= 400:
                return None, None, f"HTTP {response.status_code}", False, None, None

            content_type = response.headers.get("content-type", "")

            # Only process HTML content
            if "text/html" not in content_type:
                return None, content_type, f"Unsupported content type: {content_type}", False, None, None

            # Extract caching headers for future conditional requests
            new_etag = response.headers.get("etag")
            new_last_modified = response.headers.get("last-modified")

            return response.text, content_type, None, False, new_etag, new_last_modified

        except httpx.RequestError as e:
            return None, None, f"Request failed: {str(e)}", False, None, None
        except Exception as e:
            return None, None, f"Unexpected error: {str(e)}", False, None, None

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
        group_id: Optional[UUID] = None,
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
            group_id: Optional RunGroup ID for child extraction tracking

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

        # HTTP cache headers for conditional requests (only populated for httpx fallback)
        http_cache_headers = {}

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

            # Get cached headers for conditional request (if page was crawled before)
            cached_etag = None
            cached_last_modified = None
            if existing and existing.scrape_metadata:
                cached_etag = existing.scrape_metadata.get("http_etag")
                cached_last_modified = existing.scrape_metadata.get("http_last_modified")

            html_content, content_type, error, not_modified, new_etag, new_last_modified = \
                await self._fetch_page_fallback(
                    normalized_url, config,
                    etag=cached_etag,
                    last_modified=cached_last_modified,
                )

            # Handle 304 Not Modified - page unchanged, skip processing
            if not_modified and existing:
                logger.info(f"Page unchanged (304): {normalized_url}")

                # Still check for new documents on unchanged pages
                documents_downloaded = 0
                if config.get("download_documents", False):
                    # Re-extract links from stored content to find any new documents
                    pass  # Documents handled separately

                return CrawlResult(
                    url=normalized_url,
                    success=True,
                    asset_id=existing.asset_id,
                    scraped_asset_id=existing.id,
                    discovered_urls=[],  # Don't re-discover, page unchanged
                    is_new=False,
                    was_updated=False,
                    documents_discovered=0,
                    documents_downloaded=0,
                )

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

            # Store HTTP caching headers for future conditional requests
            http_cache_headers = {}
            if new_etag:
                http_cache_headers["http_etag"] = new_etag
            if new_last_modified:
                http_cache_headers["http_last_modified"] = new_last_modified

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
                        session, collection, document_links, crawl_run_id, group_id
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
                **http_cache_headers,  # Include ETag/Last-Modified for future conditional requests
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
                    session, collection, document_links, crawl_run_id, group_id
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
            organization_id=collection.organization_id,
            asset_id=asset_id,
            collection_id=collection_id,
            url=normalized_url,
            asset_subtype="page",
            source_id=source_id,
            parent_url=parent_url,
            crawl_depth=crawl_depth,
            crawl_run_id=crawl_run_id,
            scrape_metadata={
                **http_cache_headers,  # Include ETag/Last-Modified for future conditional requests
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
                session, collection, document_links, crawl_run_id, group_id
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
                    "source": {
                        "storage_folder": "/".join(html_key.split("/")[1:-1]) if "/" in html_key else "",
                    },
                    "scrape": {
                        "url": url,
                        "final_url": final_url or url,
                        "collection_id": str(collection.id),
                        "collection_name": collection.name,
                        "crawl_run_id": str(crawl_run_id),
                    },
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

        # Trigger search indexing if enabled
        from app.core.ingestion.extraction_orchestrator import _is_search_enabled
        if _is_search_enabled():
            try:
                from app.core.tasks import index_asset_task
                index_asset_task.delay(asset_id=str(asset_id))
                logger.debug(f"Queued asset {asset_id} for search indexing")
            except Exception as e:
                logger.warning(f"Failed to queue search indexing for {asset_id}: {e}")

        logger.debug(f"Stored inline extraction for asset {asset_id}")

    async def _download_discovered_documents(
        self,
        session: AsyncSession,
        collection: ScrapeCollection,
        document_links: List[Dict],
        crawl_run_id: UUID,
        group_id: Optional[UUID] = None,
    ) -> int:
        """
        Download discovered documents and create assets for extraction.

        Downloaded documents go through the normal extraction pipeline (Docling).

        Args:
            session: Database session
            collection: Collection instance
            document_links: List of document link info dicts
            crawl_run_id: Crawl run UUID
            group_id: Optional RunGroup ID for child extraction tracking

        Returns:
            Number of documents successfully downloaded
        """

        downloaded = 0
        config = collection.crawl_config or {}

        for doc_link in document_links:
            try:
                doc_url = doc_link["url"]
                doc_filename = doc_link["filename"]
                doc_extension = doc_link["extension"]

                # Check if this document should be downloaded based on external domain rules
                should_download, reason = self._should_download_document(
                    doc_url, collection.root_url, config
                )
                if not should_download:
                    logger.info(f"Skipping external document: {doc_filename} ({reason})")
                    # Log as info, not warning - this is expected behavior
                    await run_log_service.log_event(
                        session=session,
                        run_id=crawl_run_id,
                        level="INFO",
                        event_type="skip",
                        message=f"Skipped external document: {doc_filename}",
                        context={"url": doc_url, "reason": reason},
                    )
                    continue

                # Check if document URL already exists in this collection (skip re-download)
                existing_doc = await scrape_service.get_scraped_asset_by_url(
                    session, collection.id, doc_url
                )
                if existing_doc:
                    logger.debug(f"Document already scraped (URL match): {doc_filename}")
                    continue

                logger.info(f"Downloading document: {doc_filename} from {doc_url}")

                # Get cached headers for conditional request (from any previous partial attempt)
                cached_etag = None
                cached_last_modified = None

                # Build conditional request headers
                headers = {}
                if cached_etag:
                    headers["If-None-Match"] = cached_etag
                if cached_last_modified:
                    headers["If-Modified-Since"] = cached_last_modified

                # Download the file
                client = await self._get_http_client(config)
                response = await client.get(doc_url, headers=headers if headers else None)

                # Handle 304 Not Modified
                if response.status_code == 304:
                    logger.debug(f"Document unchanged (304): {doc_filename}")
                    continue

                if response.status_code != 200:
                    logger.warning(f"Failed to download {doc_url}: HTTP {response.status_code}")
                    continue

                content = response.content
                content_hash = hashlib.sha256(content).hexdigest()

                # Determine content type
                content_type = response.headers.get("content-type", "application/octet-stream")
                if ";" in content_type:
                    content_type = content_type.split(";")[0].strip()

                # Extract HTTP cache headers for future conditional requests
                doc_etag = response.headers.get("etag")
                doc_last_modified = response.headers.get("last-modified")

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
                # Extraction is automatically queued by asset_service.create_asset()
                asset = await asset_service.create_asset(
                    session=session,
                    organization_id=collection.organization_id,
                    source_type="web_scrape_document",
                    source_metadata={
                        "source": {
                            "storage_folder": "/".join(doc_key.split("/")[1:-1]) if "/" in doc_key else "",
                        },
                        "scrape": {
                            "source_url": doc_url,
                            "collection_id": str(collection.id),
                            "collection_name": collection.name,
                            "crawl_run_id": str(crawl_run_id),
                            "link_text": doc_link.get("link_text", ""),
                        },
                    },
                    original_filename=doc_filename,
                    raw_bucket=settings.minio_bucket_uploads,
                    raw_object_key=doc_key,
                    content_type=content_type,
                    file_size=len(content),
                    file_hash=content_hash,
                    status="pending",  # Will go through extraction (auto-queued)
                    group_id=group_id,  # Link extraction to parent job's group
                )

                # Create scraped asset record for the document
                doc_scrape_metadata = {
                    "document_type": doc_extension,
                    "original_filename": doc_filename,
                    "link_text": doc_link.get("link_text", ""),
                    "downloaded_at": datetime.utcnow().isoformat(),
                    "content_hash": content_hash,
                }
                # Store HTTP cache headers for future conditional requests
                if doc_etag:
                    doc_scrape_metadata["http_etag"] = doc_etag
                if doc_last_modified:
                    doc_scrape_metadata["http_last_modified"] = doc_last_modified

                await scrape_service.create_scraped_asset(
                    session=session,
                    organization_id=collection.organization_id,
                    asset_id=asset.id,
                    collection_id=collection.id,
                    url=doc_url,
                    asset_subtype="document",
                    crawl_run_id=crawl_run_id,
                    scrape_metadata=doc_scrape_metadata,
                )

                downloaded += 1

                # Log document download
                await run_log_service.log_event(
                    session=session,
                    run_id=crawl_run_id,
                    level="INFO",
                    event_type="progress",
                    message=f"Downloaded document: {doc_filename}",
                    context={
                        "url": doc_url,
                        "type": doc_extension,
                        "size_bytes": len(content),
                    },
                )

            except Exception as e:
                # Get meaningful error message - some exceptions have empty str()
                error_msg = str(e) if str(e) else type(e).__name__
                logger.exception(f"Failed to download document {doc_link.get('url')}: {error_msg}")
                # Log document download failure
                await run_log_service.log_event(
                    session=session,
                    run_id=crawl_run_id,
                    level="WARN",
                    event_type="error",
                    message=f"Failed to download document: {doc_link.get('filename', 'unknown')}",
                    context={"url": doc_link.get("url"), "error": error_msg},
                )
                continue

        return downloaded

    async def crawl_collection(
        self,
        session: AsyncSession,
        collection_id: UUID,
        user_id: Optional[UUID] = None,
        max_pages: Optional[int] = None,
        run_id: Optional[UUID] = None,
        group_id: Optional[UUID] = None,
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
            group_id: Optional RunGroup ID for parent-child job tracking

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
        delay = config.get("delay_seconds", 2.0)
        delay_jitter = config.get("delay_jitter", 1.0)
        exclude_locales = config.get("exclude_locales", True)
        backoff_on_error = config.get("backoff_on_error", True)
        max_consecutive_errors = config.get("max_consecutive_errors", 5)

        pages_crawled = 0
        pages_new = 0
        pages_updated = 0
        pages_failed = 0
        pages_skipped_locale = 0
        consecutive_errors = 0
        current_backoff = 0  # Additional delay after errors
        total_documents_discovered = 0
        total_documents_downloaded = 0

        # Set initial progress before crawling starts
        await run_service.update_run_progress(
            session=session,
            run_id=run.id,
            current=0,
            total=min(len(visited), max_pages_limit),
            unit="pages",
            phase="starting",
        )

        # Log crawl start
        await run_log_service.log_event(
            session=session,
            run_id=run.id,
            level="INFO",
            event_type="start",
            message=f"Starting crawl for {collection.name} ({len(sources)} sources, max {max_pages_limit} pages, depth {max_depth})",
        )

        try:
            while queue and pages_crawled < max_pages_limit:
                # Check for too many consecutive errors (likely rate limited)
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning(
                        f"Stopping crawl after {consecutive_errors} consecutive errors - likely rate limited"
                    )
                    await run_log_service.log_event(
                        session=session,
                        run_id=run.id,
                        level="WARN",
                        event_type="error",
                        message=f"Stopping crawl after {consecutive_errors} consecutive errors (likely rate limited)",
                    )
                    break

                url, source_id, parent_url, depth = queue.pop(0)

                # Skip if exceeds depth (0 or None means unlimited)
                if max_depth and max_depth > 0 and depth > max_depth:
                    continue

                # Check URL patterns
                if not self.matches_patterns(url, collection.url_patterns):
                    logger.debug(f"Skipping {url} - doesn't match patterns")
                    continue

                # Check for locale URLs (if enabled)
                if exclude_locales and self.is_locale_url(url, collection.root_url):
                    logger.debug(f"Skipping {url} - locale variant")
                    pages_skipped_locale += 1
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
                    group_id=group_id,
                )

                results.append(result)
                pages_crawled += 1
                total_documents_discovered += result.documents_discovered
                total_documents_downloaded += result.documents_downloaded

                # Extract page title/path for logging
                url_path = extract_url_path(url)
                short_url = url_path if len(url_path) <= 60 else url_path[:57] + "..."

                if result.success:
                    # Reset error tracking on success
                    consecutive_errors = 0
                    current_backoff = 0

                    if result.is_new:
                        pages_new += 1
                        # Log new page
                        await run_log_service.log_event(
                            session=session,
                            run_id=run.id,
                            level="INFO",
                            event_type="progress",
                            message=f"New page: {short_url}",
                            context={
                                "url": url,
                                "depth": depth,
                                "links_found": len(result.discovered_urls),
                                "documents_found": result.documents_discovered,
                            },
                        )
                    elif result.was_updated:
                        pages_updated += 1
                        # Log updated page
                        await run_log_service.log_event(
                            session=session,
                            run_id=run.id,
                            level="INFO",
                            event_type="progress",
                            message=f"Updated page: {short_url}",
                            context={"url": url, "depth": depth},
                        )

                    # Add discovered URLs to queue
                    for discovered_url in result.discovered_urls:
                        normalized_discovered = self.normalize_url(discovered_url)
                        if normalized_discovered not in visited:
                            visited.add(normalized_discovered)
                            queue.append((normalized_discovered, source_id, url, depth + 1))
                else:
                    pages_failed += 1
                    consecutive_errors += 1

                    # Check for rate limiting errors (403, 429)
                    is_rate_limited = result.error and ("403" in result.error or "429" in result.error)
                    if is_rate_limited and backoff_on_error:
                        # Exponential backoff: 5s, 10s, 20s, 40s...
                        current_backoff = min(5 * (2 ** (consecutive_errors - 1)), 60)
                        logger.warning(
                            f"Rate limited ({result.error}), backing off for {current_backoff}s"
                        )

                    # Log failed page
                    await run_log_service.log_event(
                        session=session,
                        run_id=run.id,
                        level="WARN",
                        event_type="error",
                        message=f"Failed to crawl: {short_url}" + (f" (backing off {current_backoff}s)" if current_backoff > 0 else ""),
                        context={"url": url, "error": result.error, "consecutive_errors": consecutive_errors},
                    )

                # Update progress with detailed stats
                await run_service.update_run_progress(
                    session=session,
                    run_id=run.id,
                    current=pages_crawled,
                    total=min(len(visited), max_pages_limit),
                    unit="pages",
                    phase="crawling",
                    details={
                        "pages_new": pages_new,
                        "pages_updated": pages_updated,
                        "pages_failed": pages_failed,
                        "urls_queued": len(queue),
                        "documents_discovered": total_documents_discovered,
                    },
                )

                # Rate limiting with jitter and backoff
                total_delay = delay + random.uniform(0, delay_jitter) + current_backoff
                if total_delay > 0:
                    await asyncio.sleep(total_delay)

            # Update collection stats
            await scrape_service.update_collection_stats(session, collection_id)

            # Complete run
            summary = {
                "pages_crawled": pages_crawled,
                "pages_new": pages_new,
                "pages_updated": pages_updated,
                "pages_failed": pages_failed,
                "pages_skipped_locale": pages_skipped_locale,
                "urls_discovered": len(visited),
                "urls_remaining": len(queue),
                "documents_discovered": total_documents_discovered,
                "documents_downloaded": total_documents_downloaded,
                "stopped_early": consecutive_errors >= max_consecutive_errors,
            }

            # Log completion summary
            await run_log_service.log_summary(
                session=session,
                run_id=run.id,
                message=(
                    f"Crawl completed: {pages_crawled} pages processed "
                    f"({pages_new} new, {pages_updated} updated, {pages_failed} failed)"
                    + (f", {total_documents_downloaded} documents downloaded" if total_documents_downloaded > 0 else "")
                ),
                context=summary,
            )

            await run_service.complete_run(session, run.id, results_summary=summary)

            logger.info(
                f"Completed crawl for collection {collection_id}: "
                f"{pages_crawled} pages ({pages_new} new, {pages_updated} updated, {pages_failed} failed), "
                f"{total_documents_downloaded} documents downloaded"
            )

            return summary

        except Exception as e:
            logger.error(f"Crawl failed for collection {collection_id}: {e}")
            # Log error
            await run_log_service.log_event(
                session=session,
                run_id=run.id,
                level="ERROR",
                event_type="error",
                message=f"Crawl failed: {str(e)}",
            )
            await run_service.fail_run(session, run.id, str(e))
            raise

        finally:
            await self.close()


# Singleton instance
crawl_service = CrawlService()
