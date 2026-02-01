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

Usage:
    from app.services.pg_search_service import pg_search_service

    # Hybrid search (default)
    results = await pg_search_service.search(
        session=db_session,
        organization_id=org_id,
        query="cybersecurity requirements",
        search_mode="hybrid",
        semantic_weight=0.5,
    )

Author: Curatore v2 Development Team
Version: 2.0.0
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import text, func, select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from .embedding_service import embedding_service

logger = logging.getLogger("curatore.pg_search_service")


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

    Attributes:
        _embedding_dim: Dimension of embeddings (768 for all-mpnet-base-v2)
    """

    def __init__(self):
        """Initialize the PostgreSQL search service."""
        self._embedding_dim = 768  # Must match embedding model

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

    def _build_highlight_query(self, column: str, query: str) -> str:
        """
        Build ts_headline() query for highlighting matches.

        Args:
            column: Column name to highlight
            query: Search query

        Returns:
            SQL snippet for ts_headline
        """
        escaped_query = self._escape_fts_query(query)
        if not escaped_query:
            return f"{column}"
        return f"""
            ts_headline(
                'english',
                {column},
                to_tsquery('english', '{escaped_query}'),
                'StartSel=<mark>, StopSel=</mark>, MaxWords=50, MinWords=25, MaxFragments=3'
            )
        """

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
            limit: Maximum results to return
            offset: Offset for pagination

        Returns:
            SearchResults with total count and matching hits
        """
        try:
            # Build filter conditions
            filters = ["sc.organization_id = :org_id"]
            params: Dict[str, Any] = {"org_id": str(organization_id)}

            # Only search asset-type chunks for the main search endpoint
            filters.append("sc.source_type = 'asset'")

            if source_types:
                filters.append("sc.source_type_filter = ANY(:source_types)")
                params["source_types"] = source_types

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

            filter_clause = " AND ".join(filters)

            # Escape query for FTS
            fts_query = self._escape_fts_query(query)
            if not fts_query:
                return SearchResults(total=0, hits=[])

            params["fts_query"] = fts_query

            # Build query based on search mode
            if search_mode == "keyword":
                return await self._keyword_search(
                    session, filter_clause, params, query, limit, offset
                )
            elif search_mode == "semantic":
                return await self._semantic_search(
                    session, filter_clause, params, query, limit, offset
                )
            else:  # hybrid
                return await self._hybrid_search(
                    session, filter_clause, params, query, semantic_weight, limit, offset
                )

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return SearchResults(total=0, hits=[])

    async def _keyword_search(
        self,
        session: AsyncSession,
        filter_clause: str,
        params: Dict[str, Any],
        query: str,
        limit: int,
        offset: int,
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
                source_type_filter as source_type,
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
            hits.append(SearchHit(
                asset_id=str(row.source_id),
                score=float(row.score) * 100,  # Normalize to 0-100
                title=row.title,
                filename=row.filename,
                source_type=row.source_type,
                content_type=row.content_type,
                url=row.url,
                created_at=row.created_at,
                highlights={"content": [row.highlight]} if row.highlight else {},
                keyword_score=float(row.score),
            ))

        return SearchResults(total=total, hits=hits)

    async def _semantic_search(
        self,
        session: AsyncSession,
        filter_clause: str,
        params: Dict[str, Any],
        query: str,
        limit: int,
        offset: int,
    ) -> SearchResults:
        """Execute semantic-only search using vector similarity."""
        # Generate query embedding
        query_embedding = await embedding_service.get_embedding(query)

        # Count total (approximate for semantic - use a threshold)
        # For semantic search, we consider anything with similarity > 0.3 as relevant
        # Format embedding as pgvector string: '[0.1, 0.2, ...]'
        params["embedding"] = "[" + ",".join(str(f) for f in query_embedding) + "]"
        params["similarity_threshold"] = 0.3

        # Note: For true total, we'd need to scan all vectors, which is expensive.
        # Instead, we return top K and estimate total
        search_sql = f"""
            WITH ranked_chunks AS (
                SELECT
                    sc.source_id,
                    sc.title,
                    sc.filename,
                    sc.source_type_filter,
                    sc.content_type,
                    sc.url,
                    sc.created_at,
                    sc.content,
                    1 - (sc.embedding <=> CAST(:embedding AS vector)) as semantic_score,
                    ROW_NUMBER() OVER (
                        PARTITION BY sc.source_id
                        ORDER BY sc.embedding <=> CAST(:embedding AS vector) ASC
                    ) as rn
                FROM search_chunks sc
                WHERE {filter_clause}
                AND sc.embedding IS NOT NULL
            )
            SELECT
                source_id,
                title,
                filename,
                source_type_filter as source_type,
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
            hits.append(SearchHit(
                asset_id=str(row.source_id),
                score=float(row.score) * 100,
                title=row.title,
                filename=row.filename,
                source_type=row.source_type,
                content_type=row.content_type,
                url=row.url,
                created_at=row.created_at,
                highlights={"content": [row.snippet + "..."]} if row.snippet else {},
                semantic_score=float(row.score),
            ))

        # Estimate total as slightly more than returned if we hit limit
        total = len(hits) if len(hits) < limit else limit + 10

        return SearchResults(total=total, hits=hits)

    async def _hybrid_search(
        self,
        session: AsyncSession,
        filter_clause: str,
        params: Dict[str, Any],
        query: str,
        semantic_weight: float,
        limit: int,
        offset: int,
    ) -> SearchResults:
        """
        Execute hybrid search combining keyword and semantic results.

        Uses Reciprocal Rank Fusion (RRF) style combination:
        - Get top K results from keyword search
        - Get top K results from semantic search
        - Combine scores with configurable weighting
        """
        # Generate query embedding
        query_embedding = await embedding_service.get_embedding(query)
        # Format embedding as pgvector string: '[0.1, 0.2, ...]'
        params["embedding"] = "[" + ",".join(str(f) for f in query_embedding) + "]"
        params["keyword_weight"] = 1 - semantic_weight
        params["semantic_weight"] = semantic_weight

        # Hybrid search query
        # This query:
        # 1. Gets keyword matches with ts_rank
        # 2. Gets semantic matches with vector similarity
        # 3. Combines them with weighted scoring
        search_sql = f"""
            WITH keyword_results AS (
                SELECT
                    sc.source_id,
                    sc.title,
                    sc.filename,
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
            semantic_results AS (
                SELECT
                    sc.source_id,
                    sc.title,
                    sc.filename,
                    sc.source_type_filter,
                    sc.content_type,
                    sc.url,
                    sc.created_at,
                    sc.content,
                    1 - (sc.embedding <=> CAST(:embedding AS vector)) as semantic_score,
                    ROW_NUMBER() OVER (
                        PARTITION BY sc.source_id
                        ORDER BY sc.embedding <=> CAST(:embedding AS vector) ASC
                    ) as rn
                FROM search_chunks sc
                WHERE {filter_clause}
                AND sc.embedding IS NOT NULL
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
                    COALESCE(k.source_type_filter, s.source_type_filter) as source_type,
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
            hits.append(SearchHit(
                asset_id=str(row.source_id),
                score=float(row.score) * 100,
                title=row.title,
                filename=row.filename,
                source_type=row.source_type,
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

        # Base filter - matching documents
        base_filter = """
            sc.organization_id = :org_id
            AND sc.source_type = 'asset'
            AND sc.search_vector @@ to_tsquery('english', :fts_query)
        """

        # Source type facet
        source_type_sql = f"""
            SELECT sc.source_type_filter as value, COUNT(DISTINCT sc.source_id) as count
            FROM search_chunks sc
            WHERE {base_filter}
            AND sc.source_type_filter IS NOT NULL
            GROUP BY sc.source_type_filter
            ORDER BY count DESC
            LIMIT :facet_size
        """
        source_result = await session.execute(text(source_type_sql), params)
        source_buckets = [
            FacetBucket(value=row.value, count=row.count)
            for row in source_result.fetchall()
        ]

        # Content type facet
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

    async def search_sam(
        self,
        session: AsyncSession,
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
        Search SAM.gov notices and solicitations.

        Args:
            session: Database session
            organization_id: Organization UUID
            query: Search query
            source_types: Filter by type (sam_notice, sam_solicitation)
            notice_types: Filter by notice types
            agencies: Filter by agency names
            date_from: Filter by posted date >=
            date_to: Filter by posted date <=
            limit: Maximum results
            offset: Pagination offset

        Returns:
            SearchResults with SAM.gov content
        """
        try:
            filters = ["sc.organization_id = :org_id"]
            params: Dict[str, Any] = {"org_id": str(organization_id)}

            # SAM-specific source types
            if source_types:
                filters.append("sc.source_type = ANY(:source_types)")
                params["source_types"] = source_types
            else:
                filters.append("sc.source_type IN ('sam_notice', 'sam_solicitation')")

            if notice_types:
                filters.append("sc.metadata->>'notice_type' = ANY(:notice_types)")
                params["notice_types"] = notice_types

            if agencies:
                filters.append("sc.metadata->>'agency' = ANY(:agencies)")
                params["agencies"] = agencies

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

            # Count
            count_sql = f"""
                SELECT COUNT(DISTINCT sc.source_id)
                FROM search_chunks sc
                WHERE {filter_clause}
                AND sc.search_vector @@ to_tsquery('english', :fts_query)
            """
            count_result = await session.execute(text(count_sql), params)
            total = count_result.scalar() or 0

            # Search
            search_sql = f"""
                WITH ranked AS (
                    SELECT
                        sc.source_id,
                        sc.source_type,
                        sc.title,
                        sc.filename,
                        sc.content_type,
                        sc.url,
                        sc.created_at,
                        sc.metadata,
                        sc.content,
                        ts_rank(sc.search_vector, to_tsquery('english', :fts_query)) as score,
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
                    source_type,
                    title,
                    filename,
                    content_type,
                    url,
                    created_at::text,
                    metadata,
                    score,
                    ts_headline(
                        'english',
                        content,
                        to_tsquery('english', :fts_query),
                        'StartSel=<mark>, StopSel=</mark>, MaxWords=50, MinWords=25, MaxFragments=3'
                    ) as highlight
                FROM ranked
                WHERE rn = 1
                ORDER BY score DESC
                LIMIT :limit OFFSET :offset
            """
            params["limit"] = limit
            params["offset"] = offset

            result = await session.execute(text(search_sql), params)
            rows = result.fetchall()

            hits = []
            for row in rows:
                hits.append(SearchHit(
                    asset_id=str(row.source_id),
                    score=float(row.score) * 100,
                    title=row.title,
                    filename=row.filename,
                    source_type=row.source_type,
                    content_type=row.content_type,
                    url=row.url,
                    created_at=row.created_at,
                    highlights={"content": [row.highlight]} if row.highlight else {},
                    keyword_score=float(row.score),
                ))

            return SearchResults(total=total, hits=hits)

        except Exception as e:
            logger.error(f"SAM search failed: {e}")
            return SearchResults(total=0, hits=[])

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
