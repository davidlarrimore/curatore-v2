"""
Celery tasks for search collection population.

Provides async collection population that re-chunks from asset content
and generates fresh embeddings, writing results through the store adapter.
"""

import asyncio
import logging
from typing import List, Optional

from app.celery_app import app as celery_app

logger = logging.getLogger("curatore.tasks.collections")


@celery_app.task(
    name="app.tasks.populate_collection_fresh_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def populate_collection_fresh_task(
    self,
    collection_id: str,
    asset_ids: List[str],
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    run_id: Optional[str] = None,
    organization_id: Optional[str] = None,
):
    """
    Celery task: re-chunk assets from content + fresh embeddings.

    Steps:
      1. For each asset: fetch extraction markdown from storage
      2. Chunk with custom or default settings
      3. Batch embed all chunks
      4. Write via store adapter
      5. Update Run status
    """
    logger.info(
        "Starting fresh population: collection=%s, assets=%d, run=%s",
        collection_id, len(asset_ids), run_id,
    )
    try:
        asyncio.run(
            _populate_fresh_async(
                collection_id=collection_id,
                asset_ids=asset_ids,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                run_id=run_id,
                organization_id=organization_id,
            )
        )
    except Exception as exc:
        logger.exception("Fresh population failed: %s", exc)
        # Mark run as failed
        if run_id and organization_id:
            try:
                asyncio.run(_fail_run(run_id, organization_id, str(exc)))
            except Exception:
                pass
        raise


async def _populate_fresh_async(
    collection_id: str,
    asset_ids: List[str],
    chunk_size: Optional[int],
    chunk_overlap: Optional[int],
    run_id: Optional[str],
    organization_id: Optional[str],
):
    """Async implementation of fresh population."""
    from uuid import UUID

    from app.core.search.chunking_service import ChunkingService
    from app.core.search.collection_stores.base import ChunkData
    from app.core.search.collection_stores.pgvector_store import PgVectorCollectionStore
    from app.core.search.embedding_service import embedding_service
    from app.core.shared.database_service import database_service
    from app.core.shared.run_service import run_service

    coll_uuid = UUID(collection_id)
    org_uuid = UUID(organization_id) if organization_id else None
    run_uuid = UUID(run_id) if run_id else None

    async with database_service.get_session() as session:
        # Mark run as running
        if run_uuid:
            await run_service.update_run_status(session, run_uuid, "running")
            await session.commit()

        try:
            # Initialize chunker with custom or default settings
            chunker = ChunkingService(
                max_chunk_size=chunk_size,
                overlap_size=chunk_overlap,
            )

            all_chunks: List[ChunkData] = []
            assets_processed = 0

            for asset_id_str in asset_ids:
                asset_uuid = UUID(asset_id_str)

                # Fetch asset and its extraction content
                content = await _get_asset_content(session, org_uuid, asset_uuid)
                if not content:
                    logger.warning(
                        "No content for asset %s, skipping", asset_id_str
                    )
                    continue

                # Get asset title
                title = await _get_asset_title(session, asset_uuid)

                # Chunk the content
                doc_chunks = chunker.chunk_document(content, title=title)

                for dc in doc_chunks:
                    all_chunks.append(
                        ChunkData(
                            chunk_index=dc.chunk_index,
                            content=dc.content,
                            embedding=[],  # will be filled below
                            title=dc.title or title,
                            source_asset_id=asset_uuid,
                            metadata={"source": "fresh_population"},
                        )
                    )
                assets_processed += 1

            if not all_chunks:
                if run_uuid:
                    await run_service.complete_run(
                        session, run_uuid,
                        result={"added": 0, "assets_processed": 0, "total": 0},
                    )
                    await session.commit()
                return

            # Batch embed all chunks
            texts = [c.content for c in all_chunks]
            embeddings = await embedding_service.get_embeddings_batch_concurrent(
                texts, max_concurrent=10, batch_size=50
            )
            for chunk, emb in zip(all_chunks, embeddings):
                chunk.embedding = emb

            # Write to store
            store = PgVectorCollectionStore(session)
            written = await store.upsert_chunks(coll_uuid, all_chunks)

            # Update item count
            new_count = await store.count(coll_uuid)
            from app.core.database.models import SearchCollection

            collection = await session.get(SearchCollection, coll_uuid)
            if collection:
                collection.item_count = new_count

            # Complete run
            if run_uuid:
                await run_service.complete_run(
                    session, run_uuid,
                    result={
                        "added": written,
                        "assets_processed": assets_processed,
                        "total": new_count,
                    },
                )

            await session.commit()
            logger.info(
                "Fresh population complete: collection=%s, written=%d, total=%d",
                collection_id, written, new_count,
            )

        except Exception as exc:
            await session.rollback()
            if run_uuid:
                try:
                    await run_service.fail_run(session, run_uuid, error=str(exc))
                    await session.commit()
                except Exception:
                    pass
            raise


async def _get_asset_content(session, organization_id, asset_id) -> Optional[str]:
    """Fetch extraction markdown for an asset."""
    from sqlalchemy import text

    result = await session.execute(
        text("""
            SELECT er.markdown_content
            FROM extraction_results er
            JOIN asset_versions av ON er.asset_version_id = av.id
            JOIN assets a ON av.asset_id = a.id
            WHERE a.id = :asset_id
              AND a.organization_id = :org_id
            ORDER BY av.version_number DESC
            LIMIT 1
        """),
        {"asset_id": str(asset_id), "org_id": str(organization_id)},
    )
    row = result.fetchone()
    return row.markdown_content if row else None


async def _get_asset_title(session, asset_id) -> Optional[str]:
    """Get asset title or filename."""
    from sqlalchemy import text

    result = await session.execute(
        text("SELECT title, original_filename FROM assets WHERE id = :id"),
        {"id": str(asset_id)},
    )
    row = result.fetchone()
    if not row:
        return None
    return row.title or row.original_filename


async def _fail_run(run_id: str, organization_id: str, error: str):
    """Mark a run as failed (standalone, for use in except handler)."""
    from uuid import UUID

    from app.core.shared.database_service import database_service
    from app.core.shared.run_service import run_service

    async with database_service.get_session() as session:
        await run_service.fail_run(session, UUID(run_id), error=error)
        await session.commit()
