"""
PgVector collection store — local pgvector-backed implementation.

Stores collection chunks in the ``collection_chunks`` table with
tsvector full-text search and pgvector semantic search, providing
hybrid search capabilities identical to the core search_chunks table
but fully isolated per-collection.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .base import ChunkData, ChunkResult, CollectionStoreAdapter

logger = logging.getLogger("curatore.search.collection_stores.pgvector")


class PgVectorCollectionStore(CollectionStoreAdapter):
    """
    Local pgvector-backed collection store.

    All operations target the ``collection_chunks`` table. Requires an
    ``AsyncSession`` passed per-call (via the ``session`` constructor param
    or overridden on individual methods).
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    # =====================================================================
    # Upsert
    # =====================================================================

    async def upsert_chunks(
        self, collection_id: UUID, chunks: List[ChunkData]
    ) -> int:
        """
        Batch upsert chunks using INSERT ... ON CONFLICT DO UPDATE.

        Dedup key: (collection_id, source_asset_id, chunk_index).
        """
        if not chunks:
            return 0

        written = 0
        batch_size = 100

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]

            values_parts = []
            params: Dict[str, Any] = {"coll_id": str(collection_id)}

            for j, chunk in enumerate(batch):
                prefix = f"c{j}"
                embedding_str = (
                    "[" + ",".join(str(f) for f in chunk.embedding) + "]"
                    if chunk.embedding
                    else None
                )
                values_parts.append(
                    f"(:{prefix}_coll_id::uuid, :{prefix}_idx, :{prefix}_content, "
                    f":{prefix}_title, :{prefix}_asset_id::uuid, "
                    f":{prefix}_chunk_id::uuid, "
                    f"CAST(:{prefix}_embedding AS vector), "
                    f"CAST(:{prefix}_metadata AS jsonb))"
                )
                params[f"{prefix}_coll_id"] = str(collection_id)
                params[f"{prefix}_idx"] = chunk.chunk_index
                params[f"{prefix}_content"] = chunk.content
                params[f"{prefix}_title"] = chunk.title
                params[f"{prefix}_asset_id"] = (
                    str(chunk.source_asset_id) if chunk.source_asset_id else None
                )
                params[f"{prefix}_chunk_id"] = (
                    str(chunk.source_chunk_id) if chunk.source_chunk_id else None
                )
                params[f"{prefix}_embedding"] = embedding_str
                params[f"{prefix}_metadata"] = (
                    json.dumps(chunk.metadata) if chunk.metadata else None
                )

            values_sql = ",\n".join(values_parts)

            upsert_sql = f"""
                INSERT INTO collection_chunks
                    (collection_id, chunk_index, content, title,
                     source_asset_id, source_chunk_id, embedding, metadata)
                VALUES {values_sql}
                ON CONFLICT (collection_id, source_asset_id, chunk_index)
                DO UPDATE SET
                    content = EXCLUDED.content,
                    title = EXCLUDED.title,
                    source_chunk_id = EXCLUDED.source_chunk_id,
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata
            """

            result = await self._session.execute(text(upsert_sql), params)
            written += result.rowcount

        return written

    # =====================================================================
    # Search
    # =====================================================================

    async def search(
        self,
        collection_id: UUID,
        query: str,
        query_embedding: List[float],
        search_mode: str = "hybrid",
        limit: int = 20,
        semantic_weight: float = 0.5,
    ) -> List[ChunkResult]:
        """Hybrid search within a collection."""
        if search_mode == "keyword":
            return await self._keyword_search(collection_id, query, limit)
        elif search_mode == "semantic":
            return await self._semantic_search(
                collection_id, query_embedding, limit
            )
        else:
            return await self._hybrid_search(
                collection_id, query, query_embedding, limit, semantic_weight
            )

    async def _keyword_search(
        self, collection_id: UUID, query: str, limit: int
    ) -> List[ChunkResult]:
        """Full-text keyword search using tsvector."""
        fts_query = self._escape_fts_query(query)
        if not fts_query:
            return []

        sql = """
            SELECT
                cc.id::text,
                cc.content,
                cc.title,
                cc.source_asset_id::text,
                cc.metadata,
                ts_rank(cc.search_vector, to_tsquery('english', :fts_query)) AS score,
                ts_headline(
                    'english', cc.content,
                    to_tsquery('english', :fts_query),
                    'StartSel=<mark>, StopSel=</mark>, MaxWords=50, MinWords=25, MaxFragments=3'
                ) AS highlight
            FROM collection_chunks cc
            WHERE cc.collection_id = :coll_id
              AND cc.search_vector @@ to_tsquery('english', :fts_query)
            ORDER BY score DESC
            LIMIT :limit
        """
        result = await self._session.execute(
            text(sql),
            {
                "coll_id": str(collection_id),
                "fts_query": fts_query,
                "limit": limit,
            },
        )
        return [
            ChunkResult(
                id=row.id,
                content=row.content,
                title=row.title,
                source_asset_id=row.source_asset_id,
                score=float(row.score) * 100,
                metadata=dict(row.metadata) if row.metadata else None,
                keyword_score=float(row.score),
                highlight=row.highlight,
            )
            for row in result.fetchall()
        ]

    async def _semantic_search(
        self,
        collection_id: UUID,
        query_embedding: List[float],
        limit: int,
    ) -> List[ChunkResult]:
        """Semantic search using pgvector cosine similarity."""
        embedding_str = "[" + ",".join(str(f) for f in query_embedding) + "]"

        sql = """
            SELECT
                cc.id::text,
                cc.content,
                cc.title,
                cc.source_asset_id::text,
                cc.metadata,
                1 - (cc.embedding <=> CAST(:embedding AS vector)) AS score
            FROM collection_chunks cc
            WHERE cc.collection_id = :coll_id
              AND cc.embedding IS NOT NULL
            ORDER BY cc.embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """
        result = await self._session.execute(
            text(sql),
            {
                "coll_id": str(collection_id),
                "embedding": embedding_str,
                "limit": limit,
            },
        )
        return [
            ChunkResult(
                id=row.id,
                content=row.content,
                title=row.title,
                source_asset_id=row.source_asset_id,
                score=float(row.score) * 100,
                metadata=dict(row.metadata) if row.metadata else None,
                semantic_score=float(row.score),
            )
            for row in result.fetchall()
        ]

    async def _hybrid_search(
        self,
        collection_id: UUID,
        query: str,
        query_embedding: List[float],
        limit: int,
        semantic_weight: float,
    ) -> List[ChunkResult]:
        """Hybrid search combining keyword and semantic scores."""
        fts_query = self._escape_fts_query(query)
        embedding_str = "[" + ",".join(str(f) for f in query_embedding) + "]"
        keyword_weight = 1.0 - semantic_weight

        # If there's no valid FTS query, fall back to semantic only
        if not fts_query:
            return await self._semantic_search(
                collection_id, query_embedding, limit
            )

        # Two-CTE approach: compute keyword and semantic scores separately,
        # then merge on chunk id with a weighted combination.
        sql = """
            WITH keyword_scores AS (
                SELECT
                    cc.id,
                    ts_rank(cc.search_vector, to_tsquery('english', :fts_query)) AS kw_score
                FROM collection_chunks cc
                WHERE cc.collection_id = :coll_id
                  AND cc.search_vector @@ to_tsquery('english', :fts_query)
            ),
            semantic_scores AS (
                SELECT
                    cc.id,
                    1 - (cc.embedding <=> CAST(:embedding AS vector)) AS sem_score
                FROM collection_chunks cc
                WHERE cc.collection_id = :coll_id
                  AND cc.embedding IS NOT NULL
                ORDER BY cc.embedding <=> CAST(:embedding AS vector)
                LIMIT :sem_limit
            ),
            merged AS (
                SELECT id FROM keyword_scores
                UNION
                SELECT id FROM semantic_scores
            )
            SELECT
                m.id::text,
                cc.content,
                cc.title,
                cc.source_asset_id::text,
                cc.metadata,
                COALESCE(k.kw_score, 0) AS keyword_score,
                COALESCE(s.sem_score, 0) AS semantic_score,
                (
                    :kw_weight * COALESCE(k.kw_score, 0) +
                    :sem_weight * COALESCE(s.sem_score, 0)
                ) AS score,
                CASE WHEN k.kw_score IS NOT NULL THEN
                    ts_headline(
                        'english', cc.content,
                        to_tsquery('english', :fts_query),
                        'StartSel=<mark>, StopSel=</mark>, MaxWords=50, MinWords=25, MaxFragments=3'
                    )
                ELSE NULL END AS highlight
            FROM merged m
            JOIN collection_chunks cc ON cc.id = m.id
            LEFT JOIN keyword_scores k ON k.id = m.id
            LEFT JOIN semantic_scores s ON s.id = m.id
            ORDER BY score DESC
            LIMIT :limit
        """
        result = await self._session.execute(
            text(sql),
            {
                "coll_id": str(collection_id),
                "fts_query": fts_query,
                "embedding": embedding_str,
                "kw_weight": keyword_weight,
                "sem_weight": semantic_weight,
                "sem_limit": limit * 3,  # oversample for better merge
                "limit": limit,
            },
        )
        return [
            ChunkResult(
                id=row.id,
                content=row.content,
                title=row.title,
                source_asset_id=row.source_asset_id,
                score=float(row.score) * 100,
                metadata=dict(row.metadata) if row.metadata else None,
                keyword_score=float(row.keyword_score) if row.keyword_score else None,
                semantic_score=float(row.semantic_score) if row.semantic_score else None,
                highlight=row.highlight,
            )
            for row in result.fetchall()
        ]

    # =====================================================================
    # Delete / Clear / Count
    # =====================================================================

    async def delete_by_assets(
        self, collection_id: UUID, asset_ids: List[UUID]
    ) -> int:
        """Delete chunks for specific assets."""
        if not asset_ids:
            return 0

        result = await self._session.execute(
            text(
                "DELETE FROM collection_chunks "
                "WHERE collection_id = :coll_id "
                "AND source_asset_id = ANY(:asset_ids)"
            ),
            {
                "coll_id": str(collection_id),
                "asset_ids": [str(a) for a in asset_ids],
            },
        )
        return result.rowcount

    async def clear(self, collection_id: UUID) -> int:
        """Delete all chunks in a collection."""
        result = await self._session.execute(
            text("DELETE FROM collection_chunks WHERE collection_id = :coll_id"),
            {"coll_id": str(collection_id)},
        )
        return result.rowcount

    async def count(self, collection_id: UUID) -> int:
        """Count chunks in a collection."""
        result = await self._session.execute(
            text(
                "SELECT COUNT(*) FROM collection_chunks WHERE collection_id = :coll_id"
            ),
            {"coll_id": str(collection_id)},
        )
        return result.scalar() or 0

    # =====================================================================
    # Helpers
    # =====================================================================

    @staticmethod
    def _escape_fts_query(query: str) -> str:
        """Escape query for PostgreSQL full-text search (same logic as pg_search_service)."""
        query = re.sub(r"[^\w\s]", " ", query)
        words = [w for w in query.split() if w]
        if not words:
            return ""
        joiner = " & " if len(words) <= 3 else " | "
        return joiner.join(f"{word}:*" for word in words)
