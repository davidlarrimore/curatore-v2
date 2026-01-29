# ============================================================================
# backend/app/services/opensearch_service.py
# ============================================================================
"""
OpenSearch Service for Curatore v2 - Native Full-Text Search

This module provides full-text search capabilities using OpenSearch for indexing
and searching document content across all sources (uploads, SharePoint, web scrapes).

Key Features:
    - Organization-scoped indices for multi-tenancy
    - Full-text search with relevance scoring
    - Multi-match queries across title, filename, content, and URL
    - Filtering by source type, content type, and date range
    - Highlighted search results with snippets
    - Automatic index creation with appropriate mappings

Usage:
    from app.services.opensearch_service import opensearch_service

    # Check health
    is_healthy = await opensearch_service.health_check()

    # Index a document
    await opensearch_service.index_document(
        organization_id=org_id,
        asset_id=asset_id,
        title="Document Title",
        content="Full text content...",
        filename="document.pdf",
        source_type="upload",
        ...
    )

    # Search
    results = await opensearch_service.search(
        organization_id=org_id,
        query="search terms",
        source_types=["upload", "web_scrape"],
        limit=20,
        offset=0,
    )

Author: Curatore v2 Development Team
Version: 2.0.0
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from ..config import settings
from .config_loader import config_loader

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    """Represents a single search result."""

    asset_id: str
    score: float
    title: Optional[str] = None
    filename: Optional[str] = None
    source_type: Optional[str] = None
    content_type: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[str] = None
    highlights: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class SearchResults:
    """Container for search results."""

    total: int
    hits: List[SearchHit]


@dataclass
class IndexStats:
    """Statistics about a search index."""

    index_name: str
    document_count: int
    size_bytes: int
    status: str


class OpenSearchService:
    """
    OpenSearch client service for full-text search operations.

    This service manages OpenSearch connections, index lifecycle, and search
    operations. It provides organization-scoped indices for multi-tenant
    isolation and supports rich full-text search with filtering and highlighting.

    Index Naming:
        Indices are named as: {prefix}-assets-{organization_id}
        Example: curatore-assets-550e8400-e29b-41d4-a716-446655440000

    Index Mappings:
        - asset_id: keyword (unique document identifier)
        - title: text with content_analyzer (boosted 3x in search)
        - filename: text + keyword subfield (boosted 2x)
        - content: text with content_analyzer (main search field)
        - url: keyword (for web scrapes)
        - source_type: keyword (upload, sharepoint, web_scrape)
        - content_type: keyword (MIME type)
        - metadata: object (disabled for indexing, just stored)
        - created_at: date
        - updated_at: date

    Attributes:
        _client: OpenSearch client instance or None if unavailable
    """

    def __init__(self):
        """Initialize the OpenSearch service."""
        self._client = None
        self._config = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """
        Initialize OpenSearch client from config.yml or environment variables.

        Configuration priority:
        1. config.yml (opensearch section)
        2. Environment variables (OPENSEARCH_*)
        3. Built-in defaults

        Creates an OpenSearch client connection if OpenSearch is enabled
        in the configuration. Handles authentication and SSL settings.

        Side Effects:
            - Sets self._client to OpenSearch instance or None
            - Sets self._config with resolved configuration
            - Logs connection status and configuration source
        """
        # Try config.yml first
        opensearch_config = config_loader.get_opensearch_config()

        if opensearch_config:
            logger.info("Loading OpenSearch configuration from config.yml")
            enabled = opensearch_config.enabled
            service_url = opensearch_config.service_url
            username = opensearch_config.username
            password = opensearch_config.password
            verify_ssl = opensearch_config.verify_ssl
            index_prefix = opensearch_config.index_prefix
            timeout = opensearch_config.timeout
            batch_size = opensearch_config.batch_size
            max_content_length = opensearch_config.max_content_length
        else:
            # Fall back to environment variables
            logger.info("Loading OpenSearch configuration from environment variables")
            enabled = settings.opensearch_enabled
            service_url = f"http://{settings.opensearch_endpoint}"
            if "://" in settings.opensearch_endpoint:
                service_url = settings.opensearch_endpoint
            username = settings.opensearch_username if settings.opensearch_username else None
            password = settings.opensearch_password if settings.opensearch_password else None
            verify_ssl = settings.opensearch_verify_ssl
            index_prefix = settings.opensearch_index_prefix
            timeout = settings.opensearch_search_timeout
            batch_size = settings.opensearch_batch_size
            max_content_length = settings.opensearch_max_content_length

        # Store resolved config for later use
        self._config = {
            "enabled": enabled,
            "service_url": service_url,
            "username": username,
            "password": password,
            "verify_ssl": verify_ssl,
            "index_prefix": index_prefix,
            "timeout": timeout,
            "batch_size": batch_size,
            "max_content_length": max_content_length,
        }

        if not enabled:
            logger.info("OpenSearch is disabled")
            return

        try:
            from opensearchpy import OpenSearch

            # Parse service URL
            host = service_url
            if not host.startswith("http"):
                protocol = "https" if verify_ssl else "http"
                host = f"{protocol}://{service_url}"

            # Determine if SSL should be used based on URL scheme
            use_ssl = host.startswith("https://")

            # Build auth tuple if credentials provided
            auth = None
            if username and password:
                auth = (username, password)

            self._client = OpenSearch(
                hosts=[host],
                http_auth=auth,
                use_ssl=use_ssl,
                verify_certs=verify_ssl,
                ssl_show_warn=False,
                timeout=timeout,
            )

            logger.info(f"OpenSearch client initialized: {service_url}")

        except ImportError:
            logger.error("opensearch-py package not installed")
            self._client = None
        except Exception as e:
            logger.error(f"Failed to initialize OpenSearch client: {e}")
            self._client = None

    @property
    def is_available(self) -> bool:
        """Check if OpenSearch is available."""
        return self._client is not None

    def get_index_name(self, organization_id: UUID) -> str:
        """
        Get the index name for an organization.

        Args:
            organization_id: Organization UUID

        Returns:
            Index name in format: {prefix}-assets-{org_id}
        """
        prefix = self._config.get("index_prefix", "curatore") if self._config else "curatore"
        return f"{prefix}-assets-{organization_id}"

    async def health_check(self) -> bool:
        """
        Check OpenSearch cluster health.

        Returns:
            True if cluster is healthy, False otherwise
        """
        if not self._client:
            return False

        try:
            info = self._client.cluster.health()
            status = info.get("status", "unknown")
            logger.debug(f"OpenSearch cluster status: {status}")
            return status in ("green", "yellow")
        except Exception as e:
            logger.error(f"OpenSearch health check failed: {e}")
            return False

    async def ensure_index(self, organization_id: UUID) -> bool:
        """
        Create index with mappings if it doesn't exist.

        Args:
            organization_id: Organization UUID

        Returns:
            True if index exists or was created, False on error
        """
        if not self._client:
            return False

        index_name = self.get_index_name(organization_id)

        try:
            if self._client.indices.exists(index=index_name):
                return True

            # Create index with mappings
            self._client.indices.create(
                index=index_name,
                body={
                    "settings": {
                        "number_of_shards": 1,
                        "number_of_replicas": 0,
                        "analysis": {
                            "analyzer": {
                                "content_analyzer": {
                                    "type": "standard",
                                    "stopwords": "_english_",
                                }
                            }
                        },
                    },
                    "mappings": {
                        "properties": {
                            "asset_id": {"type": "keyword"},
                            "title": {
                                "type": "text",
                                "analyzer": "content_analyzer",
                            },
                            "content": {
                                "type": "text",
                                "analyzer": "content_analyzer",
                            },
                            "filename": {
                                "type": "text",
                                "fields": {"keyword": {"type": "keyword"}},
                            },
                            "source_type": {"type": "keyword"},
                            "content_type": {"type": "keyword"},
                            "url": {"type": "keyword"},
                            "collection_id": {"type": "keyword"},
                            "metadata": {"type": "object", "enabled": False},
                            "created_at": {"type": "date"},
                            "updated_at": {"type": "date"},
                        }
                    },
                },
            )

            logger.info(f"Created OpenSearch index: {index_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create index {index_name}: {e}")
            return False

    async def index_document(
        self,
        organization_id: UUID,
        asset_id: UUID,
        title: str,
        content: str,
        filename: str,
        source_type: str,
        content_type: Optional[str] = None,
        url: Optional[str] = None,
        collection_id: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
    ) -> bool:
        """
        Index or update a document.

        Args:
            organization_id: Organization UUID
            asset_id: Asset UUID (used as document ID)
            title: Document title
            content: Document text content (will be truncated if too long)
            filename: Original filename
            source_type: Source type (upload, sharepoint, web_scrape)
            content_type: MIME type (optional)
            url: URL for web scrapes (optional)
            collection_id: Collection ID for web scrapes (optional)
            metadata: Additional metadata to store (optional)
            created_at: Creation timestamp (optional)

        Returns:
            True if indexed successfully, False otherwise
        """
        if not self._client:
            logger.warning("OpenSearch not available, skipping indexing")
            return False

        try:
            # Ensure index exists
            await self.ensure_index(organization_id)

            index_name = self.get_index_name(organization_id)

            # Truncate content if too long
            max_length = self._config.get("max_content_length", 100000) if self._config else 100000
            if len(content) > max_length:
                content = content[:max_length]
                logger.debug(
                    f"Content truncated to {max_length} chars for asset {asset_id}"
                )

            # Build document
            doc = {
                "asset_id": str(asset_id),
                "title": title,
                "content": content,
                "filename": filename,
                "source_type": source_type,
                "content_type": content_type,
                "url": url,
                "collection_id": str(collection_id) if collection_id else None,
                "metadata": metadata or {},
                "created_at": (created_at or datetime.utcnow()).isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }

            # Index document (upsert)
            self._client.index(
                index=index_name,
                id=str(asset_id),
                body=doc,
                refresh=True,
            )

            logger.info(f"Indexed asset {asset_id} to OpenSearch")
            return True

        except Exception as e:
            logger.error(f"Failed to index asset {asset_id}: {e}")
            return False

    async def delete_document(self, organization_id: UUID, asset_id: UUID) -> bool:
        """
        Delete a document from the index.

        Args:
            organization_id: Organization UUID
            asset_id: Asset UUID

        Returns:
            True if deleted successfully or not found, False on error
        """
        if not self._client:
            return False

        try:
            index_name = self.get_index_name(organization_id)
            self._client.delete(
                index=index_name,
                id=str(asset_id),
                ignore=[404],  # Ignore not found
            )
            logger.info(f"Deleted asset {asset_id} from OpenSearch")
            return True

        except Exception as e:
            logger.error(f"Failed to delete asset {asset_id}: {e}")
            return False

    async def search(
        self,
        organization_id: UUID,
        query: str,
        source_types: Optional[List[str]] = None,
        content_types: Optional[List[str]] = None,
        collection_ids: Optional[List[UUID]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResults:
        """
        Execute a search query with filters.

        Args:
            organization_id: Organization UUID (for index selection)
            query: Search query string
            source_types: Filter by source types (optional)
            content_types: Filter by content/MIME types (optional)
            collection_ids: Filter by collection IDs (optional)
            date_from: Filter by creation date >= (optional)
            date_to: Filter by creation date <= (optional)
            limit: Maximum results to return (default 20)
            offset: Offset for pagination (default 0)

        Returns:
            SearchResults with total count and matching hits
        """
        if not self._client:
            logger.warning("OpenSearch not available, returning empty results")
            return SearchResults(total=0, hits=[])

        try:
            index_name = self.get_index_name(organization_id)

            # Check if index exists
            if not self._client.indices.exists(index=index_name):
                logger.debug(f"Index {index_name} does not exist, returning empty results")
                return SearchResults(total=0, hits=[])

            # Build multi_match query
            must = [
                {
                    "multi_match": {
                        "query": query,
                        "fields": ["title^3", "filename^2", "content", "url"],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                    }
                }
            ]

            # Build filters
            filters = []
            if source_types:
                filters.append({"terms": {"source_type": source_types}})
            if content_types:
                filters.append({"terms": {"content_type": content_types}})
            if collection_ids:
                filters.append(
                    {"terms": {"collection_id": [str(c) for c in collection_ids]}}
                )
            if date_from or date_to:
                date_range: Dict[str, str] = {}
                if date_from:
                    date_range["gte"] = date_from.isoformat()
                if date_to:
                    date_range["lte"] = date_to.isoformat()
                filters.append({"range": {"created_at": date_range}})

            # Build query body
            body = {
                "query": {
                    "bool": {
                        "must": must,
                        "filter": filters,
                    }
                },
                "highlight": {
                    "fields": {
                        "content": {
                            "fragment_size": 200,
                            "number_of_fragments": 3,
                        },
                        "title": {},
                    },
                    "pre_tags": ["<mark>"],
                    "post_tags": ["</mark>"],
                },
                "from": offset,
                "size": limit,
                "_source": [
                    "asset_id",
                    "title",
                    "filename",
                    "source_type",
                    "content_type",
                    "url",
                    "created_at",
                ],
            }

            # Execute search
            response = self._client.search(index=index_name, body=body)

            # Parse results
            total = response["hits"]["total"]["value"]
            hits = []
            for hit in response["hits"]["hits"]:
                source = hit["_source"]
                hits.append(
                    SearchHit(
                        asset_id=source.get("asset_id", ""),
                        score=hit.get("_score", 0.0),
                        title=source.get("title"),
                        filename=source.get("filename"),
                        source_type=source.get("source_type"),
                        content_type=source.get("content_type"),
                        url=source.get("url"),
                        created_at=source.get("created_at"),
                        highlights=hit.get("highlight", {}),
                    )
                )

            logger.debug(
                f"Search query '{query}' returned {total} results (showing {len(hits)})"
            )
            return SearchResults(total=total, hits=hits)

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return SearchResults(total=0, hits=[])

    async def get_index_stats(self, organization_id: UUID) -> Optional[IndexStats]:
        """
        Get statistics for an organization's index.

        Args:
            organization_id: Organization UUID

        Returns:
            IndexStats or None if unavailable
        """
        if not self._client:
            return None

        try:
            index_name = self.get_index_name(organization_id)

            if not self._client.indices.exists(index=index_name):
                return IndexStats(
                    index_name=index_name,
                    document_count=0,
                    size_bytes=0,
                    status="not_created",
                )

            stats = self._client.indices.stats(index=index_name)
            primaries = stats["_all"]["primaries"]

            return IndexStats(
                index_name=index_name,
                document_count=primaries["docs"]["count"],
                size_bytes=primaries["store"]["size_in_bytes"],
                status="active",
            )

        except Exception as e:
            logger.error(f"Failed to get index stats: {e}")
            return None

    async def delete_index(self, organization_id: UUID) -> bool:
        """
        Delete an organization's index.

        Args:
            organization_id: Organization UUID

        Returns:
            True if deleted successfully, False otherwise
        """
        if not self._client:
            return False

        try:
            index_name = self.get_index_name(organization_id)
            if self._client.indices.exists(index=index_name):
                self._client.indices.delete(index=index_name)
                logger.info(f"Deleted OpenSearch index: {index_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete index: {e}")
            return False

    async def bulk_index(
        self,
        organization_id: UUID,
        documents: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Bulk index multiple documents.

        Args:
            organization_id: Organization UUID
            documents: List of document dicts with required fields

        Returns:
            Dict with success/failure counts
        """
        if not self._client:
            return {"success": 0, "failed": len(documents), "errors": ["OpenSearch not available"]}

        if not documents:
            return {"success": 0, "failed": 0, "errors": []}

        try:
            await self.ensure_index(organization_id)
            index_name = self.get_index_name(organization_id)

            # Build bulk request body
            bulk_body = []
            for doc in documents:
                bulk_body.append(
                    {"index": {"_index": index_name, "_id": doc.get("asset_id")}}
                )
                # Add updated_at
                doc["updated_at"] = datetime.utcnow().isoformat()
                # Truncate content
                if "content" in doc:
                    max_length = self._config.get("max_content_length", 100000) if self._config else 100000
                    if len(doc["content"]) > max_length:
                        doc["content"] = doc["content"][:max_length]
                bulk_body.append(doc)

            # Execute bulk request
            response = self._client.bulk(body=bulk_body, refresh=True)

            # Parse results
            success = 0
            failed = 0
            errors = []
            for item in response.get("items", []):
                if "index" in item:
                    if item["index"].get("status") in (200, 201):
                        success += 1
                    else:
                        failed += 1
                        error_msg = item["index"].get("error", {}).get("reason", "Unknown error")
                        errors.append(error_msg)

            logger.info(
                f"Bulk indexed {success} documents, {failed} failures in {index_name}"
            )
            return {"success": success, "failed": failed, "errors": errors[:10]}

        except Exception as e:
            logger.error(f"Bulk indexing failed: {e}")
            return {"success": 0, "failed": len(documents), "errors": [str(e)]}


# Global service instance
opensearch_service = OpenSearchService()
