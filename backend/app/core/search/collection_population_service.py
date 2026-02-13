"""
Collection Population Service — orchestrates populating collection vector stores.

Provides two population strategies:
  - populate_from_index: Copies existing chunks from search_chunks (fast, reuses embeddings)
  - populate_fresh: Re-chunks from asset content + new embeddings (async via Celery)

Both strategies are store-agnostic — they resolve the appropriate
CollectionStoreAdapter (pgvector local or external) and delegate all
storage operations through the adapter interface.

Usage:
    from app.core.search.collection_population_service import collection_population_service

    result = await collection_population_service.populate_from_index(
        session, collection_id, org_id, asset_ids=["uuid1", "uuid2"]
    )
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.search.collection_service import collection_service
from app.core.search.collection_stores.base import ChunkData, CollectionStoreAdapter
from app.core.search.collection_stores.pgvector_store import PgVectorCollectionStore

logger = logging.getLogger("curatore.search.collection_population")


@dataclass
class PopulationResult:
    """Result of a collection population operation."""

    added: int = 0
    skipped: int = 0
    total: int = 0


class CollectionPopulationService:
    """Orchestrates collection population via store adapters."""

    # =====================================================================
    # Public API
    # =====================================================================

    async def populate_from_index(
        self,
        session: AsyncSession,
        collection_id: UUID,
        organization_id: UUID,
        asset_ids: List[UUID],
    ) -> PopulationResult:
        """
        Copy existing chunks from search_chunks (fast, reuses embeddings).

        Fetches chunks that already exist in the core index for the given
        assets and writes them to the collection's store. Metadata is
        flattened from the namespaced JSONB to a simple flat dict.
        """
        if not asset_ids:
            return PopulationResult()

        # Fetch matching chunks from the core index
        rows = await self._fetch_index_chunks(session, organization_id, asset_ids)

        if not rows:
            return PopulationResult(skipped=len(asset_ids))

        # Build ChunkData list
        chunks = []
        for row in rows:
            embedding_list = None
            if row.embedding_text:
                # Parse the vector text representation "[0.1,0.2,...]"
                embedding_list = [
                    float(x)
                    for x in row.embedding_text.strip("[]").split(",")
                    if x.strip()
                ]

            chunks.append(
                ChunkData(
                    chunk_index=row.chunk_index,
                    content=row.content,
                    embedding=embedding_list or [],
                    title=row.title,
                    source_asset_id=UUID(row.source_id) if row.source_id else None,
                    source_chunk_id=UUID(row.chunk_id) if row.chunk_id else None,
                    metadata=self._flatten_metadata(
                        dict(row.metadata) if row.metadata else {}
                    ),
                )
            )

        # Resolve store and write
        store = self._resolve_store(session, collection_id)
        written = await store.upsert_chunks(collection_id, chunks)

        # Update item count
        new_count = await store.count(collection_id)
        await self._update_item_count(session, collection_id, new_count)

        return PopulationResult(
            added=written,
            skipped=max(0, len(asset_ids) - len(set(r.source_id for r in rows))),
            total=new_count,
        )

    async def populate_fresh(
        self,
        session: AsyncSession,
        collection_id: UUID,
        organization_id: UUID,
        asset_ids: List[UUID],
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> str:
        """
        Re-chunk from asset content + new embeddings (async via Celery).

        Creates a Run record and dispatches a Celery task. Returns the run_id.
        """
        from app.core.shared.run_service import run_service

        # Create run
        run = await run_service.create_run(
            session=session,
            organization_id=organization_id,
            run_type="collection_populate",
            status="pending",
            metadata={
                "collection_id": str(collection_id),
                "asset_count": len(asset_ids),
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            },
        )
        await session.flush()
        run_id = str(run.id)

        # Dispatch Celery task
        from app.core.tasks.collections import populate_collection_fresh_task

        populate_collection_fresh_task.apply_async(
            kwargs={
                "collection_id": str(collection_id),
                "asset_ids": [str(a) for a in asset_ids],
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "run_id": run_id,
                "organization_id": str(organization_id),
            },
            queue="extraction",
        )

        return run_id

    async def remove_assets(
        self,
        session: AsyncSession,
        collection_id: UUID,
        organization_id: UUID,
        asset_ids: List[UUID],
    ) -> int:
        """Remove specific assets' chunks from the collection."""
        store = self._resolve_store(session, collection_id)
        removed = await store.delete_by_assets(collection_id, asset_ids)

        # Update item count
        new_count = await store.count(collection_id)
        await self._update_item_count(session, collection_id, new_count)

        return removed

    async def clear_collection(
        self,
        session: AsyncSession,
        collection_id: UUID,
        organization_id: UUID,
    ) -> int:
        """Remove all chunks from a collection."""
        store = self._resolve_store(session, collection_id)
        removed = await store.clear(collection_id)

        await self._update_item_count(session, collection_id, 0)

        return removed

    # =====================================================================
    # Store Resolution
    # =====================================================================

    def _resolve_store(
        self, session: AsyncSession, collection_id: UUID
    ) -> CollectionStoreAdapter:
        """
        Resolve the store adapter for a collection.

        If the collection has an active CollectionVectorSync, an external
        adapter would be returned (future). Otherwise the default local
        PgVectorCollectionStore is used.
        """
        # Future: check for CollectionVectorSync and return external adapter
        return PgVectorCollectionStore(session)

    # =====================================================================
    # Helpers
    # =====================================================================

    async def _fetch_index_chunks(
        self,
        session: AsyncSession,
        organization_id: UUID,
        asset_ids: List[UUID],
    ):
        """Fetch chunks from the core search_chunks table for given assets."""
        sql = """
            SELECT
                sc.id::text AS chunk_id,
                sc.source_id::text AS source_id,
                sc.chunk_index,
                sc.content,
                sc.title,
                sc.metadata,
                sc.embedding::text AS embedding_text
            FROM search_chunks sc
            WHERE sc.organization_id = :org_id
              AND sc.source_type = 'asset'
              AND sc.source_id = ANY(:asset_ids)
            ORDER BY sc.source_id, sc.chunk_index
        """
        result = await session.execute(
            text(sql),
            {
                "org_id": str(organization_id),
                "asset_ids": [str(a) for a in asset_ids],
            },
        )
        return result.fetchall()

    async def _update_item_count(
        self,
        session: AsyncSession,
        collection_id: UUID,
        count: int,
    ) -> None:
        """Update the denormalized item_count on the collection."""
        from app.core.database.models import SearchCollection

        collection = await session.get(SearchCollection, collection_id)
        if collection:
            collection.item_count = count
            await session.flush()

    @staticmethod
    def _flatten_metadata(namespaced: Dict[str, Any]) -> Dict[str, Any]:
        """
        Collapse namespaced JSONB to flat key/value dict.

        Example:
            {"source": {"filename": "a.pdf"}, "sam": {"agency": "GSA"}}
            → {"source_filename": "a.pdf", "sam_agency": "GSA"}
        """
        flat: Dict[str, Any] = {}
        for ns, fields in namespaced.items():
            if isinstance(fields, dict):
                for key, value in fields.items():
                    flat[f"{ns}_{key}"] = value
            else:
                flat[ns] = fields
        return flat


# Module-level singleton
collection_population_service = CollectionPopulationService()
