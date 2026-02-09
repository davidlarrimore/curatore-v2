# ============================================================================
# backend/app/services/pg_search_service.py
# ============================================================================
"""
PostgreSQL Search Service for Curatore v2 - Hybrid Full-Text + Semantic Search

This module provides hybrid search capabilities using PostgreSQL's native
full-text search (tsvector/GIN) combined with pgvector semantic search.

Key Features:
    - Full-text search using PostgreSQL tsvector + GIN indexes
    - Semantic search using pgvector for embedding similarity
    - Hybrid search combining both for optimal results
    - Faceted search with aggregations
    - Organization-scoped search for multi-tenancy
    - Highlighted search results with snippets

Search Modes:
    - keyword: Full-text search only (fast, exact matches)
    - semantic: Vector similarity search only (finds related content)
    - hybrid: Combines both with configurable weighting (default, best quality)

Adding New Data Sources:
    To add search for a new data source (e.g., "widgets"):
    1. Define a display type mapper: WIDGET_DISPLAY_TYPES = {"widget_type": "Widget"}
    2. Create a thin wrapper method that builds filters and calls _execute_typed_search()

    Example:
        async def search_widgets(self, session, org_id, query, ...):
            filters, params = self._build_base_filters(org_id)
            filters.append("sc.source_type = 'widget'")
            return await self._execute_typed_search(
                session, filters, params, query, search_mode, semantic_weight,
                limit, offset, display_type_mapper=lambda st: WIDGET_DISPLAY_TYPES.get(st, st)
            )

Author: Curatore v2 Development Team
Version: 2.1.0
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import text, func, select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from .embedding_service import embedding_service

logger = logging.getLogger("curatore.pg_search_service")


# =============================================================================
# Display Type Mappers - Define friendly names for each source type
# =============================================================================

# Salesforce entity display names
SALESFORCE_DISPLAY_TYPES = {
    "salesforce_account": "Account",
    "salesforce_contact": "Contact",
    "salesforce_opportunity": "Opportunity",
}

# Forecast source display names
FORECAST_DISPLAY_TYPES = {
    "ag_forecast": "AG Forecast",
    "apfs_forecast": "APFS Forecast",
    "state_forecast": "State Forecast",
}

# SAM.gov display names (uses source_type directly)
SAM_DISPLAY_TYPES = {
    "sam_notice": "SAM Notice",
    "sam_solicitation": "SAM Solicitation",
}


def _identity_mapper(source_type: str) -> str:
    """Default mapper - returns source_type unchanged."""
    return source_type


# =============================================================================
# Data Classes
# =============================================================================

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
    total_other: int = 0


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
    keyword_score: Optional[float] = None
    semantic_score: Optional[float] = None


@dataclass
class SearchResults:
    """Container for search results."""
    total: int
    hits: List[SearchHit]
    facets: Optional[Dict[str, Facet]] = None


@dataclass
class IndexStats:
    """Statistics about the search index."""
    index_name: str
    document_count: int
    chunk_count: int
    size_bytes: int
    status: str


# =============================================================================
# Search Service
# =============================================================================

class PgSearchService:
    """
    PostgreSQL-based search service with hybrid full-text + semantic search.

    This service provides search capabilities using PostgreSQL's built-in
    full-text search combined with pgvector for semantic similarity search.

    Hybrid Search Algorithm:
        1. Full-text search: Uses ts_rank() on tsvector with query weights
        2. Semantic search: Uses vector cosine similarity on embeddings
        3. Combined score: (1 - weight) * keyword_score + weight * semantic_score

    The hybrid approach provides:
        - Exact keyword matching (important for technical terms)
        - Semantic understanding (finds related content)
        - Configurable balance between the two

    """

    # These are now derived from the metadata registry service.
    # Kept as fallbacks in case the registry is not loaded.
    _FALLBACK_FILTERABLE_FIELDS: Dict[str, List[str]] = {
        "sam": ["agency", "notice_type", "naics_code", "set_aside"],
        "salesforce": ["account_type", "stage_name", "industry"],
        "forecast": ["agency_name", "fiscal_year", "source_type"],
        "sharepoint": ["folder", "created_by"],
        "source": ["storage_folder"],
    }

    _FALLBACK_NAMESPACE_SOURCE_TYPES: Dict[str, List[str]] = {
        "sam": ["sam_notice", "sam_solicitation"],
        "salesforce": ["salesforce_account", "salesforce_contact", "salesforce_opportunity"],
        "forecast": ["ag_forecast", "apfs_forecast", "state_forecast"],
        "sharepoint": ["asset"],
        "source": ["asset"],
    }

    # Schema cache: {org_id: (timestamp, schema_dict)}
    SCHEMA_CACHE_TTL = 300  # 5 minutes

    def __init__(self):
        """Initialize the PostgreSQL search service."""
        self._metadata_schema_cache: Dict[str, Tuple[float, dict]] = {}

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _escape_fts_query(self, query: str) -> str:
        """
        Escape and format query for PostgreSQL full-text search.

        Handles special characters and converts to tsquery format.
        """
        # Remove special characters that could break tsquery
        query = re.sub(r"[^\w\s]", " ", query)
        # Split into words and join with &
        words = query.split()
        if not words:
            return ""
        # Use prefix matching for better UX
        return " & ".join(f"{word}:*" for word in words if word)

    def _build_base_filters(self, organization_id: UUID) -> Tuple[List[str], Dict[str, Any]]:
        """
        Build base filter clause and params for organization scoping.

        Returns:
            Tuple of (filters list, params dict)
        """
        filters = ["sc.organization_id = :org_id"]
        params: Dict[str, Any] = {"org_id": str(organization_id)}
        return filters, params

    # =========================================================================
    # Generic Typed Search - Core Abstraction
    # =========================================================================

    async def _execute_typed_search(
        self,
        session: AsyncSession,
        filter_clause: str,
        params: Dict[str, Any],
        query: str,
        search_mode: str,
        semantic_weight: float,
        limit: int,
        offset: int,
        display_type_mapper: Callable[[str], str] = _identity_mapper,
    ) -> SearchResults:
        """
        Execute a typed search with the specified mode.

        This is the core abstraction that all specific search methods use.
        It handles keyword, semantic, and hybrid search modes with a single
        implementation, reducing code duplication.

        Args:
            session: Database session
            filter_clause: SQL WHERE clause (joined filters)
            params: SQL parameters dict (must include 'fts_query')
            query: Original search query string
            search_mode: "keyword", "semantic", or "hybrid"
            semantic_weight: Weight for semantic scores (0-1)
            limit: Max results
            offset: Pagination offset
            display_type_mapper: Function to map source_type to display name

        Returns:
            SearchResults with hits and total count
        """
        if search_mode == "keyword":
            return await self._keyword_search_generic(
                session, filter_clause, params, limit, offset, display_type_mapper
            )
        elif search_mode == "semantic":
            return await self._semantic_search_generic(
                session, filter_clause, params, query, limit, offset, display_type_mapper
            )
        else:  # hybrid
            return await self._hybrid_search_generic(
                session, filter_clause, params, query, semantic_weight, limit, offset, display_type_mapper
            )

    async def _keyword_search_generic(
        self,
        session: AsyncSession,
        filter_clause: str,
        params: Dict[str, Any],
        limit: int,
        offset: int,
        display_type_mapper: Callable[[str], str],
    ) -> SearchResults:
        """Execute keyword-only search using full-text search."""
        # Count total
        count_sql = f"""
            SELECT COUNT(DISTINCT sc.source_id)
            FROM search_chunks sc
            WHERE {filter_clause}
            AND sc.search_vector @@ to_tsquery('english', :fts_query)
        """
        count_result = await session.execute(text(count_sql), params)
        total = count_result.scalar() or 0

        # Search with ranking
        search_sql = f"""
            WITH ranked_chunks AS (
                SELECT
                    sc.source_id,
                    sc.title,
                    sc.filename,
                    sc.source_type,
                    sc.source_type_filter,
                    sc.content_type,
                    sc.url,
                    sc.created_at,
                    sc.content,
                    ts_rank(sc.search_vector, to_tsquery('english', :fts_query)) as keyword_score,
                    ROW_NUMBER() OVER (
                        PARTITION BY sc.source_id
                        ORDER BY ts_rank(sc.search_vector, to_tsquery('english', :fts_query)) DESC
                    ) as rn
                FROM search_chunks sc
                WHERE {filter_clause}
                AND sc.search_vector @@ to_tsquery('english', :fts_query)
            )
            SELECT
                source_id,
                title,
                filename,
                source_type,
                source_type_filter,
                content_type,
                url,
                created_at::text,
                keyword_score as score,
                ts_headline(
                    'english',
                    content,
                    to_tsquery('english', :fts_query),
                    'StartSel=<mark>, StopSel=</mark>, MaxWords=50, MinWords=25, MaxFragments=3'
                ) as highlight
            FROM ranked_chunks
            WHERE rn = 1
            ORDER BY keyword_score DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = limit
        params["offset"] = offset

        result = await session.execute(text(search_sql), params)
        rows = result.fetchall()

        hits = []
        for row in rows:
            # Use display_type_mapper to get friendly name, fallback to source_type_filter
            display_type = display_type_mapper(row.source_type)
            if display_type == row.source_type and row.source_type_filter:
                display_type = row.source_type_filter

            hits.append(SearchHit(
                asset_id=str(row.source_id),
                score=float(row.score) * 100,
                title=row.title,
                filename=row.filename,
                source_type=display_type,
                content_type=row.content_type,
                url=row.url,
                created_at=row.created_at,
                highlights={"content": [row.highlight]} if row.highlight else {},
                keyword_score=float(row.score),
            ))

        return SearchResults(total=total, hits=hits)

    async def _semantic_search_generic(
        self,
        session: AsyncSession,
        filter_clause: str,
        params: Dict[str, Any],
        query: str,
        limit: int,
        offset: int,
        display_type_mapper: Callable[[str], str],
    ) -> SearchResults:
        """Execute semantic-only search using vector similarity."""
        # Generate query embedding
        query_embedding = await embedding_service.get_embedding(query)
        params["embedding"] = "[" + ",".join(str(f) for f in query_embedding) + "]"
        params["similarity_threshold"] = 0.3

        search_sql = f"""
            WITH top_candidates AS (
                SELECT
                    sc.source_id,
                    sc.title,
                    sc.filename,
                    sc.source_type,
                    sc.source_type_filter,
                    sc.content_type,
                    sc.url,
                    sc.created_at,
                    sc.content,
                    1 - (sc.embedding <=> CAST(:embedding AS vector)) as semantic_score
                FROM search_chunks sc
                WHERE {filter_clause}
                AND sc.embedding IS NOT NULL
                ORDER BY sc.embedding <=> CAST(:embedding AS vector)
                LIMIT 200
            ),
            ranked_chunks AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY source_id
                        ORDER BY semantic_score DESC
                    ) as rn
                FROM top_candidates
            )
            SELECT
                source_id,
                title,
                filename,
                source_type,
                source_type_filter,
                content_type,
                url,
                created_at::text,
                semantic_score as score,
                LEFT(content, 500) as snippet
            FROM ranked_chunks
            WHERE rn = 1
            AND semantic_score > :similarity_threshold
            ORDER BY semantic_score DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = limit
        params["offset"] = offset

        result = await session.execute(text(search_sql), params)
        rows = result.fetchall()

        hits = []
        for row in rows:
            display_type = display_type_mapper(row.source_type)
            if display_type == row.source_type and row.source_type_filter:
                display_type = row.source_type_filter

            hits.append(SearchHit(
                asset_id=str(row.source_id),
                score=float(row.score) * 100,
                title=row.title,
                filename=row.filename,
                source_type=display_type,
                content_type=row.content_type,
                url=row.url,
                created_at=row.created_at,
                highlights={"content": [row.snippet + "..."]} if row.snippet else {},
                semantic_score=float(row.score),
            ))

        # Estimate total
        total = len(hits) if len(hits) < limit else limit + 10
        return SearchResults(total=total, hits=hits)

    async def _hybrid_search_generic(
        self,
        session: AsyncSession,
        filter_clause: str,
        params: Dict[str, Any],
        query: str,
        semantic_weight: float,
        limit: int,
        offset: int,
        display_type_mapper: Callable[[str], str],
    ) -> SearchResults:
        """Execute hybrid search combining keyword and semantic results."""
        # Generate query embedding
        query_embedding = await embedding_service.get_embedding(query)
        params["embedding"] = "[" + ",".join(str(f) for f in query_embedding) + "]"
        params["keyword_weight"] = 1 - semantic_weight
        params["semantic_weight"] = semantic_weight

        search_sql = f"""
            WITH keyword_results AS (
                SELECT
                    sc.source_id,
                    sc.title,
                    sc.filename,
                    sc.source_type,
                    sc.source_type_filter,
                    sc.content_type,
                    sc.url,
                    sc.created_at,
                    sc.content,
                    ts_rank(sc.search_vector, to_tsquery('english', :fts_query)) as keyword_score,
                    ROW_NUMBER() OVER (
                        PARTITION BY sc.source_id
                        ORDER BY ts_rank(sc.search_vector, to_tsquery('english', :fts_query)) DESC
                    ) as rn
                FROM search_chunks sc
                WHERE {filter_clause}
                AND sc.search_vector @@ to_tsquery('english', :fts_query)
            ),
            semantic_candidates AS (
                SELECT
                    sc.source_id,
                    sc.title,
                    sc.filename,
                    sc.source_type,
                    sc.source_type_filter,
                    sc.content_type,
                    sc.url,
                    sc.created_at,
                    sc.content,
                    1 - (sc.embedding <=> CAST(:embedding AS vector)) as semantic_score
                FROM search_chunks sc
                WHERE {filter_clause}
                AND sc.embedding IS NOT NULL
                ORDER BY sc.embedding <=> CAST(:embedding AS vector)
                LIMIT 200
            ),
            semantic_results AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY source_id
                        ORDER BY semantic_score DESC
                    ) as rn
                FROM semantic_candidates
            ),
            keyword_top AS (
                SELECT * FROM keyword_results WHERE rn = 1
            ),
            semantic_top AS (
                SELECT * FROM semantic_results WHERE rn = 1 AND semantic_score > 0.3
            ),
            combined AS (
                SELECT
                    COALESCE(k.source_id, s.source_id) as source_id,
                    COALESCE(k.title, s.title) as title,
                    COALESCE(k.filename, s.filename) as filename,
                    COALESCE(k.source_type, s.source_type) as source_type,
                    COALESCE(k.source_type_filter, s.source_type_filter) as source_type_filter,
                    COALESCE(k.content_type, s.content_type) as content_type,
                    COALESCE(k.url, s.url) as url,
                    COALESCE(k.created_at, s.created_at) as created_at,
                    COALESCE(k.content, s.content) as content,
                    COALESCE(k.keyword_score, 0) as keyword_score,
                    COALESCE(s.semantic_score, 0) as semantic_score,
                    :keyword_weight * COALESCE(k.keyword_score, 0) +
                    :semantic_weight * COALESCE(s.semantic_score, 0) as combined_score
                FROM keyword_top k
                FULL OUTER JOIN semantic_top s ON k.source_id = s.source_id
            )
            SELECT
                source_id,
                title,
                filename,
                source_type,
                source_type_filter,
                content_type,
                url,
                created_at::text,
                combined_score as score,
                keyword_score,
                semantic_score,
                ts_headline(
                    'english',
                    content,
                    to_tsquery('english', :fts_query),
                    'StartSel=<mark>, StopSel=</mark>, MaxWords=50, MinWords=25, MaxFragments=3'
                ) as highlight
            FROM combined
            ORDER BY combined_score DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = limit
        params["offset"] = offset

        result = await session.execute(text(search_sql), params)
        rows = result.fetchall()

        hits = []
        for row in rows:
            display_type = display_type_mapper(row.source_type)
            if display_type == row.source_type and row.source_type_filter:
                display_type = row.source_type_filter

            hits.append(SearchHit(
                asset_id=str(row.source_id),
                score=float(row.score) * 100,
                title=row.title,
                filename=row.filename,
                source_type=display_type,
                content_type=row.content_type,
                url=row.url,
                created_at=row.created_at,
                highlights={"content": [row.highlight]} if row.highlight else {},
                keyword_score=float(row.keyword_score) if row.keyword_score else None,
                semantic_score=float(row.semantic_score) if row.semantic_score else None,
            ))

        # Get total count
        count_sql = f"""
            WITH keyword_results AS (
                SELECT DISTINCT sc.source_id
                FROM search_chunks sc
                WHERE {filter_clause}
                AND sc.search_vector @@ to_tsquery('english', :fts_query)
            ),
            semantic_results AS (
                SELECT DISTINCT sc.source_id
                FROM search_chunks sc
                WHERE {filter_clause}
                AND sc.embedding IS NOT NULL
                AND 1 - (sc.embedding <=> CAST(:embedding AS vector)) > 0.3
            )
            SELECT COUNT(*) FROM (
                SELECT source_id FROM keyword_results
                UNION
                SELECT source_id FROM semantic_results
            ) combined
        """
        count_result = await session.execute(text(count_sql), params)
        total = count_result.scalar() or 0

        return SearchResults(total=total, hits=hits)

    # =========================================================================
    # Metadata Schema Discovery
    # =========================================================================

    def invalidate_metadata_cache(self, organization_id: UUID) -> None:
        """Invalidate the cached metadata schema for an organization."""
        cache_key = str(organization_id)
        self._metadata_schema_cache.pop(cache_key, None)
        logger.debug(f"Invalidated metadata schema cache for org {organization_id}")

    async def get_metadata_schema(
        self,
        session: AsyncSession,
        organization_id: UUID,
        max_sample_values: int = 20,
    ) -> Dict[str, Any]:
        """
        Discover metadata schema from builder registry + targeted DB queries.

        Returns a dict describing available namespaces, their fields,
        sample values, and document counts. Results are cached for 5 minutes.

        Args:
            session: Database session
            organization_id: Organization UUID
            max_sample_values: Max sample values per field

        Returns:
            Dict with namespaces, total_indexed_docs, cached_at
        """
        cache_key = str(organization_id)
        now = time.time()

        # Check cache
        if cache_key in self._metadata_schema_cache:
            cached_at, cached_schema = self._metadata_schema_cache[cache_key]
            if now - cached_at < self.SCHEMA_CACHE_TTL:
                return cached_schema

        try:
            schema = await self._build_metadata_schema(
                session, organization_id, max_sample_values
            )
            self._metadata_schema_cache[cache_key] = (now, schema)
            return schema
        except Exception as e:
            logger.error(f"Failed to build metadata schema: {e}")
            return {
                "namespaces": {},
                "total_indexed_docs": 0,
                "cached_at": None,
            }

    async def _build_metadata_schema(
        self,
        session: AsyncSession,
        organization_id: UUID,
        max_sample_values: int,
    ) -> Dict[str, Any]:
        """Build the metadata schema from registry service + DB queries."""
        from app.core.metadata.registry_service import metadata_registry_service

        org_id_str = str(organization_id)

        # Load registry
        registry_namespaces = metadata_registry_service.get_namespaces()
        registry_fields = metadata_registry_service.get_all_fields()
        filterable_fields = metadata_registry_service.get_filterable_fields()
        ns_source_types_map = metadata_registry_service.get_namespace_source_types()

        # Query 1: Per-source_type chunk counts (uses B-tree index, no JSONB)
        count_sql = text("""
            SELECT source_type, COUNT(DISTINCT source_id) as doc_count, COUNT(*) as chunk_count
            FROM search_chunks
            WHERE organization_id = :org_id
            GROUP BY source_type
        """)
        count_result = await session.execute(count_sql, {"org_id": org_id_str})
        source_type_counts: Dict[str, Dict[str, int]] = {}
        total_docs = 0
        for row in count_result.fetchall():
            source_type_counts[row.source_type] = {
                "doc_count": row.doc_count,
                "chunk_count": row.chunk_count,
            }
            total_docs += row.doc_count

        namespaces: Dict[str, Any] = {}

        for ns, ns_def in registry_namespaces.items():
            ns_source_types = ns_source_types_map.get(ns, [])
            ns_doc_count = 0
            for st in ns_source_types:
                if st in source_type_counts:
                    ns_doc_count += source_type_counts[st]["doc_count"]

            display_name = ns_def.get("display_name", ns)

            # Get filterable fields and sample values from registry
            ns_filterable = filterable_fields.get(ns, [])
            fields: Dict[str, Any] = {}

            ns_field_defs = registry_fields.get(ns, {})
            for field_name in ns_filterable:
                field_def = ns_field_defs.get(field_name, {})
                sample_values = await self._get_sample_values(
                    session, org_id_str, ns, field_name,
                    ns_source_types, max_sample_values
                )
                fields[field_name] = {
                    "type": field_def.get("data_type", "string"),
                    "sample_values": sample_values,
                    "filterable": True,
                    "description": field_def.get("description"),
                }

            if ns_doc_count > 0 or ns_filterable:
                namespaces[ns] = {
                    "display_name": display_name,
                    "source_types": ns_source_types,
                    "doc_count": ns_doc_count,
                    "fields": fields,
                }

        # Query 3: Custom namespace field discovery (dynamic LLM-generated metadata)
        custom_fields = await self._discover_custom_fields(session, org_id_str, max_sample_values)
        if custom_fields:
            # Count assets with custom metadata
            custom_doc_count = 0
            if "asset" in source_type_counts:
                custom_doc_count = source_type_counts["asset"]["doc_count"]

            namespaces["custom"] = {
                "display_name": "Custom (LLM-generated)",
                "source_types": ["asset"],
                "doc_count": custom_doc_count,
                "fields": custom_fields,
            }

        cached_at = datetime.utcnow().isoformat()
        return {
            "namespaces": namespaces,
            "total_indexed_docs": total_docs,
            "cached_at": cached_at,
        }

    async def _get_sample_values(
        self,
        session: AsyncSession,
        org_id_str: str,
        namespace: str,
        field_name: str,
        source_types: List[str],
        max_samples: int,
    ) -> List[Any]:
        """Get sample distinct values for a specific metadata field."""
        try:
            sql = text(f"""
                SELECT DISTINCT sc.metadata->:namespace->>:field as val
                FROM search_chunks sc
                WHERE sc.organization_id = :org_id
                  AND sc.source_type = ANY(:source_types)
                  AND sc.metadata->:namespace->>:field IS NOT NULL
                LIMIT :max_sample
            """)
            result = await session.execute(sql, {
                "org_id": org_id_str,
                "namespace": namespace,
                "field": field_name,
                "source_types": source_types,
                "max_sample": max_samples,
            })
            return [row.val for row in result.fetchall() if row.val]
        except Exception as e:
            logger.debug(f"Failed to get sample values for {namespace}.{field_name}: {e}")
            return []

    async def _discover_custom_fields(
        self,
        session: AsyncSession,
        org_id_str: str,
        max_samples: int,
    ) -> Dict[str, Any]:
        """Discover fields in the dynamic 'custom' namespace."""
        try:
            sql = text("""
                SELECT DISTINCT f.key, jsonb_typeof(f.value) as value_type
                FROM search_chunks sc,
                     jsonb_each(sc.metadata->'custom') AS f
                WHERE sc.organization_id = :org_id
                  AND sc.metadata ? 'custom'
                LIMIT 50
            """)
            result = await session.execute(sql, {"org_id": org_id_str})
            rows = result.fetchall()

            if not rows:
                return {}

            fields: Dict[str, Any] = {}
            for row in rows:
                fields[row.key] = {
                    "type": row.value_type or "object",
                    "sample_values": [],
                    "filterable": True,
                }
            return fields
        except Exception as e:
            logger.debug(f"Failed to discover custom fields: {e}")
            return {}

    # =========================================================================
    # Health Check
    # =========================================================================

    async def health_check(self, session: AsyncSession) -> bool:
        """
        Check if search is healthy by verifying pgvector extension.

        Returns:
            True if search is available, False otherwise
        """
        try:
            result = await session.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
            row = result.fetchone()
            return row is not None
        except Exception as e:
            logger.error(f"Search health check failed: {e}")
            return False

    # =========================================================================
    # Main Search Method (Assets + All Types)
    # =========================================================================

    async def search(
        self,
        session: AsyncSession,
        organization_id: UUID,
        query: str,
        search_mode: str = "hybrid",
        semantic_weight: float = 0.5,
        source_types: Optional[List[str]] = None,
        content_types: Optional[List[str]] = None,
        collection_ids: Optional[List[UUID]] = None,
        sync_config_ids: Optional[List[UUID]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        folder_path: Optional[str] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        facet_filters: Optional[Dict[str, Any]] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResults:
        """
        Execute a search query with optional filters.

        Args:
            session: Database session
            organization_id: Organization UUID for scoping
            query: Search query string
            search_mode: Search mode (keyword, semantic, hybrid)
            semantic_weight: Weight for semantic scores in hybrid mode (0-1)
            source_types: Filter by source types
            content_types: Filter by content/MIME types
            collection_ids: Filter by collection IDs
            sync_config_ids: Filter by sync config IDs
            date_from: Filter by creation date >=
            date_to: Filter by creation date <=
            folder_path: Filter by storage folder path (prefix match on metadata storage_folder)
            metadata_filters: Raw namespaced JSONB containment filters (power-user).
                Example: {"sam": {"agency": "GSA"}, "custom": {"tags_llm_v1": {"tags": ["cyber"]}}}
            facet_filters: Cross-domain facet filters resolved via registry.
                Example: {"agency": ["GSA", "DOD"], "naics_code": "541512"}
            limit: Maximum results to return
            offset: Offset for pagination

        Returns:
            SearchResults with total count and matching hits
        """
        try:
            # Build filter conditions
            filters, params = self._build_base_filters(organization_id)

            # Map display names to source_type values for Salesforce
            salesforce_display_map = {
                "Accounts": "salesforce_account",
                "Contacts": "salesforce_contact",
                "Opportunities": "salesforce_opportunity",
                "salesforce": None,
            }

            # Map for forecast display names
            forecast_display_map = {
                "forecast": None,
                "ag_forecast": "ag_forecast",
                "apfs_forecast": "apfs_forecast",
                "state_forecast": "state_forecast",
            }

            # Handle source type filtering
            if source_types:
                sf_source_types = []
                forecast_source_types = []
                asset_source_types = []

                for st in source_types:
                    if st in salesforce_display_map:
                        if st == "salesforce":
                            sf_source_types = ["salesforce_account", "salesforce_contact", "salesforce_opportunity"]
                        else:
                            sf_source_types.append(salesforce_display_map[st])
                    elif st in forecast_display_map:
                        if st == "forecast":
                            forecast_source_types = ["ag_forecast", "apfs_forecast", "state_forecast"]
                        else:
                            forecast_source_types.append(forecast_display_map[st])
                    else:
                        asset_source_types.append(st)

                filter_clauses = []
                if sf_source_types:
                    filter_clauses.append("sc.source_type = ANY(:sf_source_types)")
                    params["sf_source_types"] = sf_source_types
                if forecast_source_types:
                    filter_clauses.append("sc.source_type = ANY(:forecast_source_types)")
                    params["forecast_source_types"] = forecast_source_types
                if asset_source_types:
                    filter_clauses.append("(sc.source_type = 'asset' AND sc.source_type_filter = ANY(:asset_source_types))")
                    params["asset_source_types"] = asset_source_types

                if filter_clauses:
                    filters.append("(" + " OR ".join(filter_clauses) + ")")
            else:
                filters.append("""(
                    sc.source_type = 'asset'
                    OR sc.source_type IN ('ag_forecast', 'apfs_forecast', 'state_forecast')
                    OR sc.source_type IN ('salesforce_account', 'salesforce_contact', 'salesforce_opportunity')
                    OR sc.source_type IN ('sam_solicitation', 'sam_notice')
                )""")

            if content_types:
                filters.append("sc.content_type = ANY(:content_types)")
                params["content_types"] = content_types

            if collection_ids:
                filters.append("sc.collection_id = ANY(:collection_ids)")
                params["collection_ids"] = [str(c) for c in collection_ids]

            if sync_config_ids:
                filters.append("sc.sync_config_id = ANY(:sync_config_ids)")
                params["sync_config_ids"] = [str(c) for c in sync_config_ids]

            if date_from:
                filters.append("sc.created_at >= :date_from")
                params["date_from"] = date_from

            if date_to:
                filters.append("sc.created_at <= :date_to")
                params["date_to"] = date_to

            if folder_path:
                from .storage_path_service import slugify
                clean = folder_path.strip("/")
                # Slugify each path component for normalization
                slugified = "/".join(slugify(p) for p in clean.split("/") if p)

                if any(slugified.startswith(prefix) for prefix in ("sharepoint/", "uploads/", "scrape/", "sam/")):
                    # Full storage path — prefix match
                    filters.append("sc.metadata->'source'->>'storage_folder' LIKE :folder_path_prefix")
                    params["folder_path_prefix"] = f"{slugified}%"
                else:
                    # Partial path (e.g., "shared-documents/opportunities") — match within folder hierarchy
                    filters.append("sc.metadata->'source'->>'storage_folder' LIKE :folder_path_prefix")
                    params["folder_path_prefix"] = f"%/{slugified}%"

            if metadata_filters:
                filters.append("sc.metadata @> CAST(:metadata_filter AS jsonb)")
                params["metadata_filter"] = json.dumps(metadata_filters)

            # Resolve facet_filters via registry service
            if facet_filters:
                from app.core.metadata.registry_service import metadata_registry_service

                facet_idx = 0
                for facet_name, facet_value in facet_filters.items():
                    mappings = metadata_registry_service.resolve_facet(facet_name)
                    if not mappings:
                        logger.warning(f"Unknown facet: {facet_name}, skipping")
                        continue

                    # Build OR clause across all content types for this facet
                    facet_clauses = []
                    for content_type, json_path in mappings.items():
                        # json_path is "namespace.field" e.g. "sam.agency"
                        parts = json_path.split(".", 1)
                        if len(parts) != 2:
                            continue
                        ns, field = parts

                        param_key = f"facet_{facet_idx}"
                        if isinstance(facet_value, list):
                            facet_clauses.append(
                                f"sc.metadata->'{ns}'->>'{ field}' = ANY(:{param_key})"
                            )
                            params[param_key] = facet_value
                        else:
                            facet_clauses.append(
                                f"sc.metadata->'{ns}'->>'{ field}' = :{param_key}"
                            )
                            params[param_key] = str(facet_value)
                        facet_idx += 1

                    if facet_clauses:
                        filters.append("(" + " OR ".join(facet_clauses) + ")")

            filter_clause = " AND ".join(filters)

            # Escape query for FTS
            fts_query = self._escape_fts_query(query)
            if not fts_query:
                return SearchResults(total=0, hits=[])

            params["fts_query"] = fts_query

            # Combined display type mapper for all types
            def combined_mapper(source_type: str) -> str:
                if source_type in SALESFORCE_DISPLAY_TYPES:
                    return SALESFORCE_DISPLAY_TYPES[source_type]
                if source_type in FORECAST_DISPLAY_TYPES:
                    return FORECAST_DISPLAY_TYPES[source_type]
                return source_type

            return await self._execute_typed_search(
                session, filter_clause, params, query, search_mode,
                semantic_weight, limit, offset, combined_mapper
            )

        except Exception as e:
            logger.error(f"Search failed: {e}")
            await session.rollback()
            return SearchResults(total=0, hits=[])

    # =========================================================================
    # SAM.gov Search
    # =========================================================================

    async def search_sam(
        self,
        session: AsyncSession,
        organization_id: UUID,
        query: str,
        search_mode: str = "hybrid",
        semantic_weight: float = 0.5,
        source_types: Optional[List[str]] = None,
        notice_types: Optional[List[str]] = None,
        agencies: Optional[List[str]] = None,
        naics_codes: Optional[List[str]] = None,
        set_asides: Optional[List[str]] = None,
        posted_within_days: Optional[int] = None,
        response_deadline_after: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        include_sam_assets: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResults:
        """
        Search SAM.gov notices and solicitations.

        Args:
            session: Database session
            organization_id: Organization UUID
            query: Search query
            search_mode: Search mode (keyword, semantic, hybrid)
            semantic_weight: Weight for semantic scores in hybrid mode (0-1)
            source_types: Filter by type (sam_notice, sam_solicitation)
            notice_types: Filter by notice types (ptype codes)
            agencies: Filter by agency names
            naics_codes: Filter by NAICS industry codes
            set_asides: Filter by set-aside types
            posted_within_days: Only include items posted within N days
            response_deadline_after: Filter by response deadline (YYYY-MM-DD or 'today')
            date_from: Filter by posted date >=
            date_to: Filter by posted date <=
            include_sam_assets: Also search document assets from SAM.gov (attachments)
            limit: Maximum results
            offset: Pagination offset

        Returns:
            SearchResults with SAM.gov content
        """
        from datetime import timedelta

        try:
            filters, params = self._build_base_filters(organization_id)

            # SAM-specific source types
            if source_types:
                if include_sam_assets:
                    # Include both specified SAM types AND sam_gov assets
                    filters.append("""(
                        sc.source_type = ANY(:source_types)
                        OR (sc.source_type = 'asset' AND sc.source_type_filter = 'sam_gov')
                    )""")
                else:
                    filters.append("sc.source_type = ANY(:source_types)")
                params["source_types"] = source_types
            else:
                if include_sam_assets:
                    filters.append("""(
                        sc.source_type IN ('sam_notice', 'sam_solicitation')
                        OR (sc.source_type = 'asset' AND sc.source_type_filter = 'sam_gov')
                    )""")
                else:
                    filters.append("sc.source_type IN ('sam_notice', 'sam_solicitation')")

            if notice_types:
                filters.append("sc.metadata->'sam'->>'notice_type' = ANY(:notice_types)")
                params["notice_types"] = notice_types

            if agencies:
                filters.append("sc.metadata->'sam'->>'agency' = ANY(:agencies)")
                params["agencies"] = agencies

            # NAICS code filter (check metadata field)
            if naics_codes:
                filters.append("sc.metadata->'sam'->>'naics_code' = ANY(:naics_codes)")
                params["naics_codes"] = naics_codes

            # Set-aside filter (partial match using ILIKE with ANY)
            if set_asides:
                set_aside_conditions = []
                for i, sa in enumerate(set_asides):
                    param_name = f"set_aside_{i}"
                    set_aside_conditions.append(f"sc.metadata->'sam'->>'set_aside' ILIKE :{param_name}")
                    params[param_name] = f"%{sa}%"
                if set_aside_conditions:
                    filters.append(f"({' OR '.join(set_aside_conditions)})")

            # Posted within days filter
            if posted_within_days:
                cutoff_date = (datetime.utcnow() - timedelta(days=posted_within_days)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                filters.append("(sc.metadata->'sam'->>'posted_date')::timestamp >= :posted_cutoff")
                params["posted_cutoff"] = cutoff_date

            # Response deadline filter
            if response_deadline_after:
                if response_deadline_after.lower() == "today":
                    deadline_date = datetime.utcnow().date()
                else:
                    deadline_date = datetime.strptime(response_deadline_after, "%Y-%m-%d").date()
                filters.append("(sc.metadata->'sam'->>'response_deadline')::date >= :deadline_date")
                params["deadline_date"] = deadline_date

            if date_from:
                filters.append("sc.created_at >= :date_from")
                params["date_from"] = date_from

            if date_to:
                filters.append("sc.created_at <= :date_to")
                params["date_to"] = date_to

            filter_clause = " AND ".join(filters)

            fts_query = self._escape_fts_query(query)
            if not fts_query:
                return SearchResults(total=0, hits=[])

            params["fts_query"] = fts_query

            return await self._execute_typed_search(
                session, filter_clause, params, query, search_mode,
                semantic_weight, limit, offset,
                display_type_mapper=lambda st: SAM_DISPLAY_TYPES.get(st, st)
            )

        except Exception as e:
            logger.error(f"SAM search failed: {e}")
            return SearchResults(total=0, hits=[])

    # =========================================================================
    # Salesforce Search
    # =========================================================================

    async def search_salesforce(
        self,
        session: AsyncSession,
        organization_id: UUID,
        query: str,
        search_mode: str = "hybrid",
        semantic_weight: float = 0.5,
        entity_types: Optional[List[str]] = None,
        account_types: Optional[List[str]] = None,
        stages: Optional[List[str]] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResults:
        """
        Search Salesforce accounts, contacts, and opportunities.

        Args:
            session: Database session
            organization_id: Organization UUID
            query: Search query
            search_mode: Search mode (keyword, semantic, hybrid)
            semantic_weight: Weight for semantic scores in hybrid mode (0-1)
            entity_types: Filter by type (account, contact, opportunity)
            account_types: Filter by account type
            stages: Filter by opportunity stage
            limit: Maximum results
            offset: Pagination offset

        Returns:
            SearchResults with Salesforce content
        """
        try:
            filters, params = self._build_base_filters(organization_id)

            # Salesforce-specific source types
            if entity_types:
                source_types = []
                for et in entity_types:
                    if et == "account":
                        source_types.append("salesforce_account")
                    elif et == "contact":
                        source_types.append("salesforce_contact")
                    elif et == "opportunity":
                        source_types.append("salesforce_opportunity")
                    else:
                        source_types.append(et)
                filters.append("sc.source_type = ANY(:source_types)")
                params["source_types"] = source_types
            else:
                filters.append("sc.source_type IN ('salesforce_account', 'salesforce_contact', 'salesforce_opportunity')")

            if account_types:
                filters.append("sc.metadata->'salesforce'->>'account_type' = ANY(:account_types)")
                params["account_types"] = account_types

            if stages:
                filters.append("sc.metadata->'salesforce'->>'stage_name' = ANY(:stages)")
                params["stages"] = stages

            filter_clause = " AND ".join(filters)

            fts_query = self._escape_fts_query(query)
            if not fts_query:
                return SearchResults(total=0, hits=[])

            params["fts_query"] = fts_query

            return await self._execute_typed_search(
                session, filter_clause, params, query, search_mode,
                semantic_weight, limit, offset,
                display_type_mapper=lambda st: SALESFORCE_DISPLAY_TYPES.get(st, st)
            )

        except Exception as e:
            logger.error(f"Salesforce search failed: {e}")
            return SearchResults(total=0, hits=[])

    # =========================================================================
    # Forecast Search
    # =========================================================================

    async def search_forecasts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        query: str,
        search_mode: str = "hybrid",
        semantic_weight: float = 0.5,
        source_types: Optional[List[str]] = None,
        fiscal_year: Optional[int] = None,
        agency_name: Optional[str] = None,
        naics_code: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SearchResults:
        """
        Search acquisition forecasts across all sources (AG, APFS, State).

        Args:
            session: Database session
            organization_id: Organization UUID
            query: Search query
            search_mode: Search mode (keyword, semantic, hybrid)
            semantic_weight: Weight for semantic scores in hybrid mode (0-1)
            source_types: Filter by forecast source (ag, apfs, state)
            fiscal_year: Filter by fiscal year
            agency_name: Filter by agency name (partial match)
            naics_code: Filter by NAICS code
            limit: Maximum results
            offset: Pagination offset

        Returns:
            SearchResults with forecast content
        """
        try:
            filters, params = self._build_base_filters(organization_id)

            # Map user-facing source types to internal source_type values
            forecast_type_map = {
                "ag": "ag_forecast",
                "apfs": "apfs_forecast",
                "state": "state_forecast",
            }

            if source_types:
                internal_types = [forecast_type_map.get(st, st) for st in source_types]
                filters.append("sc.source_type = ANY(:source_types)")
                params["source_types"] = internal_types
            else:
                filters.append("sc.source_type IN ('ag_forecast', 'apfs_forecast', 'state_forecast')")

            if fiscal_year:
                filters.append("(sc.metadata->'forecast'->>'fiscal_year')::int = :fiscal_year")
                params["fiscal_year"] = fiscal_year

            if agency_name:
                filters.append("sc.metadata->'forecast'->>'agency_name' ILIKE :agency_pattern")
                params["agency_pattern"] = f"%{agency_name}%"

            if naics_code:
                filters.append("""(
                    sc.metadata->'forecast'->>'naics_codes' LIKE :naics_pattern
                    OR sc.metadata->'forecast'->>'naics_code' = :naics_code
                )""")
                params["naics_pattern"] = f"%{naics_code}%"
                params["naics_code"] = naics_code

            filter_clause = " AND ".join(filters)

            fts_query = self._escape_fts_query(query)
            if not fts_query:
                return SearchResults(total=0, hits=[])

            params["fts_query"] = fts_query

            return await self._execute_typed_search(
                session, filter_clause, params, query, search_mode,
                semantic_weight, limit, offset,
                display_type_mapper=lambda st: FORECAST_DISPLAY_TYPES.get(st, st)
            )

        except Exception as e:
            logger.error(f"Forecast search failed: {e}")
            return SearchResults(total=0, hits=[])

    # =========================================================================
    # Faceted Search
    # =========================================================================

    async def search_with_facets(
        self,
        session: AsyncSession,
        organization_id: UUID,
        query: str,
        search_mode: str = "hybrid",
        semantic_weight: float = 0.5,
        source_types: Optional[List[str]] = None,
        content_types: Optional[List[str]] = None,
        collection_ids: Optional[List[UUID]] = None,
        sync_config_ids: Optional[List[UUID]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        facet_filters: Optional[Dict[str, Any]] = None,
        limit: int = 20,
        offset: int = 0,
        facet_size: int = 10,
    ) -> SearchResults:
        """
        Execute search with faceted aggregations.

        Returns search results plus facet counts for filtering.
        """
        # First, get search results
        results = await self.search(
            session=session,
            organization_id=organization_id,
            query=query,
            search_mode=search_mode,
            semantic_weight=semantic_weight,
            source_types=source_types,
            content_types=content_types,
            collection_ids=collection_ids,
            sync_config_ids=sync_config_ids,
            date_from=date_from,
            date_to=date_to,
            metadata_filters=metadata_filters,
            facet_filters=facet_filters,
            limit=limit,
            offset=offset,
        )

        # Build facets
        fts_query = self._escape_fts_query(query)
        if not fts_query:
            return results

        params: Dict[str, Any] = {
            "org_id": str(organization_id),
            "fts_query": fts_query,
            "facet_size": facet_size,
        }

        # Source type facet
        source_type_sql = """
            WITH asset_facets AS (
                SELECT sc.source_type_filter as value, COUNT(DISTINCT sc.source_id) as count
                FROM search_chunks sc
                WHERE sc.organization_id = :org_id
                AND sc.source_type = 'asset'
                AND sc.search_vector @@ to_tsquery('english', :fts_query)
                AND sc.source_type_filter IS NOT NULL
                GROUP BY sc.source_type_filter
            ),
            forecast_facets AS (
                SELECT 'forecast' as value, COUNT(DISTINCT sc.source_id) as count
                FROM search_chunks sc
                WHERE sc.organization_id = :org_id
                AND sc.source_type IN ('ag_forecast', 'apfs_forecast', 'state_forecast')
                AND sc.search_vector @@ to_tsquery('english', :fts_query)
            ),
            salesforce_facets AS (
                SELECT
                    CASE sc.source_type
                        WHEN 'salesforce_account' THEN 'Accounts'
                        WHEN 'salesforce_contact' THEN 'Contacts'
                        WHEN 'salesforce_opportunity' THEN 'Opportunities'
                    END as value,
                    COUNT(DISTINCT sc.source_id) as count
                FROM search_chunks sc
                WHERE sc.organization_id = :org_id
                AND sc.source_type IN ('salesforce_account', 'salesforce_contact', 'salesforce_opportunity')
                AND sc.search_vector @@ to_tsquery('english', :fts_query)
                GROUP BY sc.source_type
            )
            SELECT value, count FROM asset_facets WHERE count > 0
            UNION ALL
            SELECT value, count FROM forecast_facets WHERE count > 0
            UNION ALL
            SELECT value, count FROM salesforce_facets WHERE count > 0
            ORDER BY count DESC
            LIMIT :facet_size
        """
        source_result = await session.execute(text(source_type_sql), params)
        source_buckets = [
            FacetBucket(value=row.value, count=row.count)
            for row in source_result.fetchall()
        ]

        # Content type facet
        base_filter = """
            sc.organization_id = :org_id
            AND sc.source_type = 'asset'
            AND sc.search_vector @@ to_tsquery('english', :fts_query)
        """
        content_type_sql = f"""
            SELECT sc.content_type as value, COUNT(DISTINCT sc.source_id) as count
            FROM search_chunks sc
            WHERE {base_filter}
            AND sc.content_type IS NOT NULL
            GROUP BY sc.content_type
            ORDER BY count DESC
            LIMIT :facet_size
        """
        content_result = await session.execute(text(content_type_sql), params)
        content_buckets = [
            FacetBucket(value=row.value, count=row.count)
            for row in content_result.fetchall()
        ]

        results.facets = {
            "source_type": Facet(field="source_type", buckets=source_buckets),
            "content_type": Facet(field="content_type", buckets=content_buckets),
        }

        return results

    # =========================================================================
    # Index Statistics
    # =========================================================================

    async def get_index_stats(
        self, session: AsyncSession, organization_id: UUID
    ) -> Optional[IndexStats]:
        """
        Get statistics about the search index.

        Returns:
            IndexStats with document count, chunk count, and size
        """
        try:
            stats_sql = """
                SELECT
                    COUNT(DISTINCT source_id) as document_count,
                    COUNT(*) as chunk_count,
                    pg_total_relation_size('search_chunks') as size_bytes
                FROM search_chunks
                WHERE organization_id = :org_id
            """
            result = await session.execute(
                text(stats_sql), {"org_id": str(organization_id)}
            )
            row = result.fetchone()

            if not row:
                return None

            return IndexStats(
                index_name=f"search_chunks (org: {organization_id})",
                document_count=row.document_count or 0,
                chunk_count=row.chunk_count or 0,
                size_bytes=row.size_bytes or 0,
                status="healthy",
            )

        except Exception as e:
            logger.error(f"Failed to get index stats: {e}")
            return None


# Global service instance
pg_search_service = PgSearchService()


def get_pg_search_service() -> PgSearchService:
    """Get the global PostgreSQL search service instance."""
    return pg_search_service
