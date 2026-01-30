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
class FacetBucket:
    """Represents a single bucket in a facet aggregation."""

    value: str
    count: int


@dataclass
class Facet:
    """Represents a facet with its buckets."""

    field: str
    buckets: List[FacetBucket]
    total_other: int = 0  # Count of documents not in top buckets


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
    facets: Optional[Dict[str, Facet]] = None


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
                            "sync_config_id": {"type": "keyword"},
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
        sync_config_id: Optional[UUID] = None,
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
            sync_config_id: SharePoint sync config ID (optional)
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
                "sync_config_id": str(sync_config_id) if sync_config_id else None,
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
        sync_config_ids: Optional[List[UUID]] = None,
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
            sync_config_ids: Filter by SharePoint sync config IDs (optional)
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
            if sync_config_ids:
                filters.append(
                    {"terms": {"sync_config_id": [str(c) for c in sync_config_ids]}}
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

    async def search_with_facets(
        self,
        organization_id: UUID,
        query: str,
        source_types: Optional[List[str]] = None,
        content_types: Optional[List[str]] = None,
        collection_ids: Optional[List[UUID]] = None,
        sync_config_ids: Optional[List[UUID]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 20,
        offset: int = 0,
        facet_size: int = 10,
    ) -> SearchResults:
        """
        Execute a search query with filters and return faceted counts.

        Uses post_filter for filters so aggregations see the full dataset
        (cross-filtering). Each facet excludes its own filter to show what
        counts would be if that filter were changed.

        Args:
            organization_id: Organization UUID (for index selection)
            query: Search query string
            source_types: Filter by source types (optional)
            content_types: Filter by content/MIME types (optional)
            collection_ids: Filter by collection IDs (optional)
            sync_config_ids: Filter by SharePoint sync config IDs (optional)
            date_from: Filter by creation date >= (optional)
            date_to: Filter by creation date <= (optional)
            limit: Maximum results to return (default 20)
            offset: Offset for pagination (default 0)
            facet_size: Maximum buckets per facet (default 10)

        Returns:
            SearchResults with total count, matching hits, and facets
        """
        if not self._client:
            logger.warning("OpenSearch not available, returning empty results")
            return SearchResults(total=0, hits=[], facets=None)

        try:
            index_name = self.get_index_name(organization_id)

            # Check if index exists
            if not self._client.indices.exists(index=index_name):
                logger.debug(f"Index {index_name} does not exist, returning empty results")
                return SearchResults(total=0, hits=[], facets=None)

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

            # Build date filter (always applied to both query and aggregations)
            date_filter = None
            if date_from or date_to:
                date_range: Dict[str, str] = {}
                if date_from:
                    date_range["gte"] = date_from.isoformat()
                if date_to:
                    date_range["lte"] = date_to.isoformat()
                date_filter = {"range": {"created_at": date_range}}

            # Build collection filter (always applied to both query and aggregations)
            collection_filter = None
            if collection_ids:
                collection_filter = {
                    "terms": {"collection_id": [str(c) for c in collection_ids]}
                }

            # Build sync_config filter for SharePoint (always applied)
            sync_config_filter = None
            if sync_config_ids:
                sync_config_filter = {
                    "terms": {"sync_config_id": [str(c) for c in sync_config_ids]}
                }

            # Build post_filter for source_types and content_types
            # These are the filters we want to cross-filter on
            post_filters = []
            if source_types:
                post_filters.append({"terms": {"source_type": source_types}})
            if content_types:
                post_filters.append({"terms": {"content_type": content_types}})

            # Combine with date, collection, and sync_config filters for post_filter
            if date_filter:
                post_filters.append(date_filter)
            if collection_filter:
                post_filters.append(collection_filter)
            if sync_config_filter:
                post_filters.append(sync_config_filter)

            # Build aggregations with cross-filtering
            # source_type facet: filter by content_type only
            # content_type facet: filter by source_type only
            aggs = {}

            # Source type facet - applies content_type filter but NOT source_type filter
            source_type_agg_filters = []
            if content_types:
                source_type_agg_filters.append({"terms": {"content_type": content_types}})
            if date_filter:
                source_type_agg_filters.append(date_filter)
            if collection_filter:
                source_type_agg_filters.append(collection_filter)
            if sync_config_filter:
                source_type_agg_filters.append(sync_config_filter)

            if source_type_agg_filters:
                aggs["source_type_facet"] = {
                    "filter": {"bool": {"filter": source_type_agg_filters}},
                    "aggs": {
                        "buckets": {
                            "terms": {
                                "field": "source_type",
                                "size": facet_size,
                            }
                        }
                    },
                }
            else:
                aggs["source_type_facet"] = {
                    "terms": {
                        "field": "source_type",
                        "size": facet_size,
                    }
                }

            # Content type facet - applies source_type filter but NOT content_type filter
            content_type_agg_filters = []
            if source_types:
                content_type_agg_filters.append({"terms": {"source_type": source_types}})
            if date_filter:
                content_type_agg_filters.append(date_filter)
            if collection_filter:
                content_type_agg_filters.append(collection_filter)
            if sync_config_filter:
                content_type_agg_filters.append(sync_config_filter)

            if content_type_agg_filters:
                aggs["content_type_facet"] = {
                    "filter": {"bool": {"filter": content_type_agg_filters}},
                    "aggs": {
                        "buckets": {
                            "terms": {
                                "field": "content_type",
                                "size": facet_size,
                            }
                        }
                    },
                }
            else:
                aggs["content_type_facet"] = {
                    "terms": {
                        "field": "content_type",
                        "size": facet_size,
                    }
                }

            # Build query body
            body: Dict[str, Any] = {
                "query": {
                    "bool": {
                        "must": must,
                    }
                },
                "aggs": aggs,
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

            # Add post_filter if any filters exist
            if post_filters:
                body["post_filter"] = {"bool": {"filter": post_filters}}

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

            # Parse facets
            facets: Dict[str, Facet] = {}

            # Parse source_type facet
            source_type_agg = response.get("aggregations", {}).get("source_type_facet", {})
            # Handle both nested (with filter) and direct (without filter) aggregation structures
            if "buckets" in source_type_agg and isinstance(source_type_agg["buckets"], dict):
                # Nested structure: {"filter": ..., "aggs": {"buckets": ...}}
                source_type_data = source_type_agg["buckets"]
            elif "buckets" in source_type_agg and isinstance(source_type_agg["buckets"], list):
                # Direct terms aggregation
                source_type_data = source_type_agg
            else:
                source_type_data = source_type_agg

            source_type_buckets = []
            for bucket in source_type_data.get("buckets", []):
                source_type_buckets.append(
                    FacetBucket(value=bucket["key"], count=bucket["doc_count"])
                )
            facets["source_type"] = Facet(
                field="source_type",
                buckets=source_type_buckets,
                total_other=source_type_data.get("sum_other_doc_count", 0),
            )

            # Parse content_type facet
            content_type_agg = response.get("aggregations", {}).get("content_type_facet", {})
            if "buckets" in content_type_agg and isinstance(content_type_agg["buckets"], dict):
                content_type_data = content_type_agg["buckets"]
            elif "buckets" in content_type_agg and isinstance(content_type_agg["buckets"], list):
                content_type_data = content_type_agg
            else:
                content_type_data = content_type_agg

            content_type_buckets = []
            for bucket in content_type_data.get("buckets", []):
                content_type_buckets.append(
                    FacetBucket(value=bucket["key"], count=bucket["doc_count"])
                )
            facets["content_type"] = Facet(
                field="content_type",
                buckets=content_type_buckets,
                total_other=content_type_data.get("sum_other_doc_count", 0),
            )

            logger.debug(
                f"Search with facets query '{query}' returned {total} results (showing {len(hits)})"
            )
            return SearchResults(total=total, hits=hits, facets=facets)

        except Exception as e:
            logger.error(f"Search with facets failed: {e}")
            return SearchResults(total=0, hits=[], facets=None)

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


    # =========================================================================
    # SAM.gov Indexing Methods (Phase 7)
    # =========================================================================

    def get_sam_notice_index_name(self, organization_id: UUID) -> str:
        """
        Get the SAM notices index name for an organization.

        Args:
            organization_id: Organization UUID

        Returns:
            Index name in format: {prefix}-sam-notices-{org_id}
        """
        prefix = self._config.get("index_prefix", "curatore") if self._config else "curatore"
        return f"{prefix}-sam-notices-{organization_id}"

    def get_sam_solicitation_index_name(self, organization_id: UUID) -> str:
        """
        Get the SAM solicitations index name for an organization.

        Args:
            organization_id: Organization UUID

        Returns:
            Index name in format: {prefix}-sam-solicitations-{org_id}
        """
        prefix = self._config.get("index_prefix", "curatore") if self._config else "curatore"
        return f"{prefix}-sam-solicitations-{organization_id}"

    async def ensure_sam_indices(self, organization_id: UUID) -> bool:
        """
        Create SAM notice and solicitation indices if they don't exist.

        Args:
            organization_id: Organization UUID

        Returns:
            True if indices exist or were created, False on error
        """
        if not self._client:
            return False

        notice_index = self.get_sam_notice_index_name(organization_id)
        solicitation_index = self.get_sam_solicitation_index_name(organization_id)

        # SAM Notice mapping
        notice_mapping = {
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
                    "notice_id": {"type": "keyword"},
                    "sam_notice_id": {"type": "keyword"},
                    "solicitation_id": {"type": "keyword"},
                    "solicitation_number": {"type": "keyword"},
                    "title": {"type": "text", "analyzer": "content_analyzer"},
                    "description": {"type": "text", "analyzer": "content_analyzer"},
                    "notice_type": {"type": "keyword"},
                    "agency": {"type": "keyword"},
                    "sub_agency": {"type": "keyword"},
                    "office": {"type": "keyword"},
                    "posted_date": {"type": "date"},
                    "response_deadline": {"type": "date"},
                    "naics_codes": {"type": "keyword"},
                    "psc_codes": {"type": "keyword"},
                    "set_aside": {"type": "keyword"},
                    "place_of_performance": {"type": "text"},
                    "version_number": {"type": "integer"},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                }
            },
        }

        # SAM Solicitation mapping
        solicitation_mapping = {
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
                    "solicitation_id": {"type": "keyword"},
                    "solicitation_number": {"type": "keyword"},
                    "title": {"type": "text", "analyzer": "content_analyzer"},
                    "description": {"type": "text", "analyzer": "content_analyzer"},
                    "notice_type": {"type": "keyword"},
                    "agency": {"type": "keyword"},
                    "sub_agency": {"type": "keyword"},
                    "office": {"type": "keyword"},
                    "posted_date": {"type": "date"},
                    "response_deadline": {"type": "date"},
                    "naics_codes": {"type": "keyword"},
                    "psc_codes": {"type": "keyword"},
                    "set_aside": {"type": "keyword"},
                    "place_of_performance": {"type": "text"},
                    "notice_count": {"type": "integer"},
                    "attachment_count": {"type": "integer"},
                    "summary_status": {"type": "keyword"},
                    "is_active": {"type": "boolean"},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                }
            },
        }

        try:
            # Create notice index
            if not self._client.indices.exists(index=notice_index):
                self._client.indices.create(index=notice_index, body=notice_mapping)
                logger.info(f"Created OpenSearch SAM notices index: {notice_index}")

            # Create solicitation index
            if not self._client.indices.exists(index=solicitation_index):
                self._client.indices.create(index=solicitation_index, body=solicitation_mapping)
                logger.info(f"Created OpenSearch SAM solicitations index: {solicitation_index}")

            return True

        except Exception as e:
            logger.error(f"Failed to create SAM indices: {e}")
            return False

    async def index_sam_notice(
        self,
        organization_id: UUID,
        notice_id: UUID,
        sam_notice_id: str,
        solicitation_id: UUID,
        solicitation_number: str,
        title: str,
        description: Optional[str] = None,
        notice_type: Optional[str] = None,
        agency: Optional[str] = None,
        sub_agency: Optional[str] = None,
        office: Optional[str] = None,
        posted_date: Optional[datetime] = None,
        response_deadline: Optional[datetime] = None,
        naics_codes: Optional[List[str]] = None,
        psc_codes: Optional[List[str]] = None,
        set_aside: Optional[str] = None,
        place_of_performance: Optional[str] = None,
        version_number: int = 1,
        created_at: Optional[datetime] = None,
    ) -> bool:
        """
        Index a SAM.gov notice for full-text search.

        Args:
            organization_id: Organization UUID
            notice_id: SamNotice UUID (used as document ID)
            sam_notice_id: Original SAM.gov notice ID
            solicitation_id: Parent solicitation UUID
            solicitation_number: Solicitation number for linking
            title: Notice title
            description: Notice description text
            notice_type: Type of notice (Combined Synopsis/Solicitation, etc.)
            agency: Contracting agency
            sub_agency: Sub-agency
            office: Contracting office
            posted_date: When notice was posted
            response_deadline: Response deadline
            naics_codes: NAICS codes
            psc_codes: PSC codes
            set_aside: Set-aside type
            place_of_performance: Place of performance
            version_number: Notice version number
            created_at: Creation timestamp

        Returns:
            True if indexed successfully, False otherwise
        """
        if not self._client:
            logger.debug("OpenSearch not available, skipping SAM notice indexing")
            return False

        try:
            await self.ensure_sam_indices(organization_id)
            index_name = self.get_sam_notice_index_name(organization_id)

            # Truncate description if too long
            max_length = self._config.get("max_content_length", 100000) if self._config else 100000
            if description and len(description) > max_length:
                description = description[:max_length]

            doc = {
                "notice_id": str(notice_id),
                "sam_notice_id": sam_notice_id,
                "solicitation_id": str(solicitation_id),
                "solicitation_number": solicitation_number,
                "title": title,
                "description": description or "",
                "notice_type": notice_type,
                "agency": agency,
                "sub_agency": sub_agency,
                "office": office,
                "posted_date": posted_date.isoformat() if posted_date else None,
                "response_deadline": response_deadline.isoformat() if response_deadline else None,
                "naics_codes": naics_codes or [],
                "psc_codes": psc_codes or [],
                "set_aside": set_aside,
                "place_of_performance": place_of_performance,
                "version_number": version_number,
                "created_at": (created_at or datetime.utcnow()).isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }

            self._client.index(
                index=index_name,
                id=str(notice_id),
                body=doc,
                refresh=True,
            )

            logger.debug(f"Indexed SAM notice {notice_id} to OpenSearch")
            return True

        except Exception as e:
            logger.error(f"Failed to index SAM notice {notice_id}: {e}")
            return False

    async def index_sam_solicitation(
        self,
        organization_id: UUID,
        solicitation_id: UUID,
        solicitation_number: str,
        title: str,
        description: Optional[str] = None,
        notice_type: Optional[str] = None,
        agency: Optional[str] = None,
        sub_agency: Optional[str] = None,
        office: Optional[str] = None,
        posted_date: Optional[datetime] = None,
        response_deadline: Optional[datetime] = None,
        naics_codes: Optional[List[str]] = None,
        psc_codes: Optional[List[str]] = None,
        set_aside: Optional[str] = None,
        place_of_performance: Optional[str] = None,
        notice_count: int = 0,
        attachment_count: int = 0,
        summary_status: Optional[str] = None,
        is_active: bool = True,
        created_at: Optional[datetime] = None,
    ) -> bool:
        """
        Index a SAM.gov solicitation for full-text search.

        Args:
            organization_id: Organization UUID
            solicitation_id: SamSolicitation UUID (used as document ID)
            solicitation_number: Solicitation number
            title: Solicitation title
            description: Solicitation description/summary
            notice_type: Latest notice type
            agency: Contracting agency
            sub_agency: Sub-agency
            office: Contracting office
            posted_date: Original posted date
            response_deadline: Response deadline
            naics_codes: NAICS codes
            psc_codes: PSC codes
            set_aside: Set-aside type
            place_of_performance: Place of performance
            notice_count: Number of notices
            attachment_count: Number of attachments
            summary_status: AI summary status
            is_active: Whether solicitation is active
            created_at: Creation timestamp

        Returns:
            True if indexed successfully, False otherwise
        """
        if not self._client:
            logger.debug("OpenSearch not available, skipping SAM solicitation indexing")
            return False

        try:
            await self.ensure_sam_indices(organization_id)
            index_name = self.get_sam_solicitation_index_name(organization_id)

            # Truncate description if too long
            max_length = self._config.get("max_content_length", 100000) if self._config else 100000
            if description and len(description) > max_length:
                description = description[:max_length]

            doc = {
                "solicitation_id": str(solicitation_id),
                "solicitation_number": solicitation_number,
                "title": title,
                "description": description or "",
                "notice_type": notice_type,
                "agency": agency,
                "sub_agency": sub_agency,
                "office": office,
                "posted_date": posted_date.isoformat() if posted_date else None,
                "response_deadline": response_deadline.isoformat() if response_deadline else None,
                "naics_codes": naics_codes or [],
                "psc_codes": psc_codes or [],
                "set_aside": set_aside,
                "place_of_performance": place_of_performance,
                "notice_count": notice_count,
                "attachment_count": attachment_count,
                "summary_status": summary_status,
                "is_active": is_active,
                "created_at": (created_at or datetime.utcnow()).isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }

            self._client.index(
                index=index_name,
                id=str(solicitation_id),
                body=doc,
                refresh=True,
            )

            logger.debug(f"Indexed SAM solicitation {solicitation_id} to OpenSearch")
            return True

        except Exception as e:
            logger.error(f"Failed to index SAM solicitation {solicitation_id}: {e}")
            return False

    async def search_sam(
        self,
        organization_id: UUID,
        query: str,
        source_types: Optional[List[str]] = None,
        notice_types: Optional[List[str]] = None,
        agencies: Optional[List[str]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResults:
        """
        Search across SAM notices and solicitations.

        Args:
            organization_id: Organization UUID
            query: Search query string
            source_types: Filter by type (notices, solicitations, or both)
            notice_types: Filter by notice types
            agencies: Filter by agencies
            date_from: Filter by posted date >= (optional)
            date_to: Filter by posted date <= (optional)
            limit: Maximum results to return (default 20)
            offset: Offset for pagination (default 0)

        Returns:
            SearchResults with total count and matching hits
        """
        if not self._client:
            logger.warning("OpenSearch not available, returning empty SAM results")
            return SearchResults(total=0, hits=[])

        # Determine which indices to search
        indices = []
        if source_types is None or "notices" in source_types:
            indices.append(self.get_sam_notice_index_name(organization_id))
        if source_types is None or "solicitations" in source_types:
            indices.append(self.get_sam_solicitation_index_name(organization_id))

        if not indices:
            return SearchResults(total=0, hits=[])

        try:
            # Check which indices exist
            existing_indices = [
                idx for idx in indices if self._client.indices.exists(index=idx)
            ]
            if not existing_indices:
                return SearchResults(total=0, hits=[])

            # Build multi_match query
            must = [
                {
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "title^3",
                            "description^2",
                            "solicitation_number^2",
                            "agency",
                            "office",
                        ],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                    }
                }
            ]

            # Build filters
            filters = []
            if notice_types:
                filters.append({"terms": {"notice_type": notice_types}})
            if agencies:
                filters.append({"terms": {"agency": agencies}})
            if date_from or date_to:
                date_range: Dict[str, str] = {}
                if date_from:
                    date_range["gte"] = date_from.isoformat()
                if date_to:
                    date_range["lte"] = date_to.isoformat()
                filters.append({"range": {"posted_date": date_range}})

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
                        "description": {
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
                    "notice_id",
                    "solicitation_id",
                    "solicitation_number",
                    "title",
                    "notice_type",
                    "agency",
                    "sub_agency",
                    "office",
                    "posted_date",
                    "response_deadline",
                ],
            }

            # Execute search across indices
            response = self._client.search(index=",".join(existing_indices), body=body)

            # Parse results
            total = response["hits"]["total"]["value"]
            hits = []
            for hit in response["hits"]["hits"]:
                source = hit["_source"]
                # Determine if this is a notice or solicitation based on presence of notice_id
                is_notice = "notice_id" in source
                asset_id = source.get("notice_id") if is_notice else source.get("solicitation_id", "")

                hits.append(
                    SearchHit(
                        asset_id=asset_id,
                        score=hit.get("_score", 0.0),
                        title=source.get("title"),
                        filename=source.get("solicitation_number"),  # Use sol # as filename
                        source_type="sam_notice" if is_notice else "sam_solicitation",
                        content_type=source.get("notice_type"),
                        url=None,
                        created_at=source.get("posted_date"),
                        highlights=hit.get("highlight", {}),
                    )
                )

            logger.debug(
                f"SAM search query '{query}' returned {total} results (showing {len(hits)})"
            )
            return SearchResults(total=total, hits=hits)

        except Exception as e:
            logger.error(f"SAM search failed: {e}")
            return SearchResults(total=0, hits=[])

    async def delete_sam_notice(self, organization_id: UUID, notice_id: UUID) -> bool:
        """Delete a SAM notice from the index."""
        if not self._client:
            return False

        try:
            index_name = self.get_sam_notice_index_name(organization_id)
            self._client.delete(index=index_name, id=str(notice_id), ignore=[404])
            return True
        except Exception as e:
            logger.error(f"Failed to delete SAM notice {notice_id}: {e}")
            return False

    async def delete_sam_solicitation(self, organization_id: UUID, solicitation_id: UUID) -> bool:
        """Delete a SAM solicitation from the index."""
        if not self._client:
            return False

        try:
            index_name = self.get_sam_solicitation_index_name(organization_id)
            self._client.delete(index=index_name, id=str(solicitation_id), ignore=[404])
            return True
        except Exception as e:
            logger.error(f"Failed to delete SAM solicitation {solicitation_id}: {e}")
            return False


# Global service instance
opensearch_service = OpenSearchService()
