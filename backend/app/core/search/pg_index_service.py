# ============================================================================
# backend/app/services/pg_index_service.py
# ============================================================================
"""
PostgreSQL Index Service for Curatore v2 - Asset Indexing with Embeddings

This module handles indexing assets to the PostgreSQL search_chunks table
after extraction completes. It creates document chunks with embeddings
for hybrid full-text + semantic search.

Key Features:
    - Index assets after extraction with chunking
    - Generate embeddings for semantic search
    - Support for multiple source types (assets, SAM notices, etc.)
    - Bulk reindex operations
    - Clean up old index entries on delete

Usage:
    from app.core.search.pg_index_service import pg_index_service

    # Index a single asset
    await pg_index_service.index_asset(session, asset_id)

    # Remove asset from index
    await pg_index_service.delete_asset_index(session, org_id, asset_id)

    # Reindex all assets for an organization
    stats = await pg_index_service.reindex_organization(session, org_id)

Author: Curatore v2 Development Team
Version: 2.0.0
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text, select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database.models import Asset, ExtractionResult
from app.core.shared.asset_service import asset_service
from .chunking_service import chunking_service, DocumentChunk
from .embedding_service import embedding_service
from .metadata_builders import metadata_builder_registry
from app.core.storage.minio_service import get_minio_service

logger = logging.getLogger("curatore.pg_index_service")


def _is_search_enabled() -> bool:
    """Check if PostgreSQL search is enabled via settings."""
    return getattr(settings, "search_enabled", True)


class PgIndexService:
    """
    Service for indexing assets to PostgreSQL search_chunks table.

    This service manages the lifecycle of search index entries:
    - Creating chunks with embeddings on asset extraction completion
    - Updating index entries when assets are re-extracted
    - Removing entries when assets are deleted
    - Bulk operations for migrations and recovery

    Indexing Pipeline:
        1. Fetch asset and completed extraction
        2. Download markdown content from MinIO
        3. Split content into chunks using ChunkingService
        4. Generate embeddings for each chunk using EmbeddingService
        5. Insert/update chunks in search_chunks table

    Thread Safety:
        The service uses async operations throughout. Embedding generation
        is offloaded to a thread pool to avoid blocking.
    """

    async def index_asset(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> bool:
        """
        Index an asset to the search_chunks table after extraction.

        Downloads the extracted markdown content, splits it into chunks,
        generates embeddings, and inserts into the search_chunks table.

        Args:
            session: Database session
            asset_id: Asset UUID to index

        Returns:
            True if indexed successfully, False otherwise
        """
        if not _is_search_enabled():
            logger.debug("Search disabled, skipping index")
            return False

        try:
            # Get asset with latest extraction
            result = await asset_service.get_asset_with_latest_extraction(
                session, asset_id
            )
            if not result:
                logger.warning(f"Asset {asset_id} not found for indexing")
                return False

            asset, extraction = result

            # Skip if no completed extraction
            if not extraction or extraction.status != "completed":
                logger.info(
                    f"Asset {asset_id} has no completed extraction, skipping index"
                )
                return False

            # Download markdown content from MinIO
            content = ""
            if extraction.extracted_bucket and extraction.extracted_object_key:
                minio = get_minio_service()
                if minio:
                    try:
                        content_bytes = minio.get_object(
                            extraction.extracted_bucket,
                            extraction.extracted_object_key,
                        )
                        content = content_bytes.getvalue().decode("utf-8")
                        logger.debug(
                            f"Downloaded {len(content)} chars of content for {asset_id}"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to fetch content for {asset_id}: {e}")

            # Build document metadata
            title, url, collection_id, sync_config_id, metadata = self._build_asset_metadata(
                asset
            )

            # Delete existing chunks for this asset
            await self._delete_chunks(session, "asset", asset_id)

            # Chunk the content
            chunks = chunking_service.chunk_document(content, title=title)

            if not chunks:
                # If no content to chunk, still create one entry for metadata search
                chunks = [DocumentChunk(
                    content=title or asset.original_filename or "",
                    chunk_index=0,
                    title=title,
                )]

            # Generate embeddings in batch for efficiency
            chunk_texts = [chunk.content for chunk in chunks]
            embeddings = await embedding_service.get_embeddings_batch(chunk_texts)

            # Insert chunks
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                await self._insert_chunk(
                    session=session,
                    source_type="asset",
                    source_id=asset_id,
                    organization_id=asset.organization_id,
                    chunk_index=i,
                    content=chunk.content,
                    title=title,
                    filename=asset.original_filename,
                    url=url,
                    embedding=embedding,
                    source_type_filter=asset.source_type,
                    content_type=asset.content_type,
                    collection_id=collection_id,
                    sync_config_id=sync_config_id,
                    metadata=metadata,
                )

            # Propagate canonical AssetMetadata into search_chunks.metadata.custom
            await self.propagate_asset_metadata(session, asset_id)

            # Update asset.indexed_at timestamp
            # Set both indexed_at and updated_at to the same value to prevent
            # onupdate=datetime.utcnow from making updated_at slightly later
            _now = datetime.utcnow()
            await session.execute(
                update(Asset)
                .where(Asset.id == asset_id)
                .values(indexed_at=_now, updated_at=_now)
            )

            await session.commit()

            # Invalidate metadata schema cache after indexing
            from .pg_search_service import pg_search_service
            pg_search_service.invalidate_metadata_cache(asset.organization_id)

            logger.info(f"Indexed asset {asset_id} with {len(chunks)} chunks")
            return True

        except Exception as e:
            logger.error(f"Error indexing asset {asset_id}: {e}")
            await session.rollback()
            return False

    async def prepare_asset_for_indexing(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """
        Prepare an asset for indexing without generating embeddings or writing to DB.

        Extracts the read-only preparation from index_asset() so that chunks
        from multiple assets can be embedded in a single batched API call.

        Args:
            session: Database session
            asset_id: Asset UUID to prepare

        Returns:
            Dict with all data needed for indexing, or None if asset can't be indexed.
            Keys: asset_id, organization_id, original_filename, source_type,
                  content_type, title, url, collection_id, sync_config_id,
                  metadata, chunks
        """
        if not _is_search_enabled():
            return None

        try:
            result = await asset_service.get_asset_with_latest_extraction(
                session, asset_id
            )
            if not result:
                logger.warning(f"Asset {asset_id} not found for indexing")
                return None

            asset, extraction = result

            if not extraction or extraction.status != "completed":
                logger.info(
                    f"Asset {asset_id} has no completed extraction, skipping index"
                )
                return None

            # Download markdown content from MinIO
            content = ""
            if extraction.extracted_bucket and extraction.extracted_object_key:
                minio = get_minio_service()
                if minio:
                    try:
                        content_bytes = minio.get_object(
                            extraction.extracted_bucket,
                            extraction.extracted_object_key,
                        )
                        content = content_bytes.getvalue().decode("utf-8")
                        # Remove null bytes - they're invalid in PostgreSQL TEXT columns
                        # but can appear in some PDF extractions
                        if "\x00" in content:
                            logger.debug(f"Removing null bytes from content for {asset_id}")
                            content = content.replace("\x00", "")
                    except Exception as e:
                        logger.warning(f"Failed to fetch content for {asset_id}: {e}")

            # Build document metadata
            title, url, collection_id, sync_config_id, metadata = self._build_asset_metadata(
                asset
            )

            # Chunk the content
            chunks = chunking_service.chunk_document(content, title=title)

            if not chunks:
                chunks = [DocumentChunk(
                    content=title or asset.original_filename or "",
                    chunk_index=0,
                    title=title,
                )]

            return {
                "asset_id": asset_id,
                "organization_id": asset.organization_id,
                "original_filename": asset.original_filename,
                "source_type": asset.source_type,
                "content_type": asset.content_type,
                "title": title,
                "url": url,
                "collection_id": collection_id,
                "sync_config_id": sync_config_id,
                "metadata": metadata,
                "chunks": chunks,
            }

        except Exception as e:
            logger.error(f"Error preparing asset {asset_id} for indexing: {e}")
            return None

    async def index_asset_prepared(
        self,
        session: AsyncSession,
        prepared: Dict[str, Any],
        embeddings: List[List[float]],
    ) -> bool:
        """
        Write a prepared asset to the search index with pre-computed embeddings.

        This is the write phase counterpart to prepare_asset_for_indexing().
        It deletes old chunks, inserts new ones, and updates the asset timestamp.

        Args:
            session: Database session
            prepared: Dict returned by prepare_asset_for_indexing()
            embeddings: Pre-computed embeddings, one per chunk

        Returns:
            True if indexed successfully, False otherwise
        """
        asset_id = prepared["asset_id"]
        try:
            # Delete existing chunks for this asset
            await self._delete_chunks(session, "asset", asset_id)

            # Insert chunks with pre-computed embeddings
            chunks = prepared["chunks"]
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                await self._insert_chunk(
                    session=session,
                    source_type="asset",
                    source_id=asset_id,
                    organization_id=prepared["organization_id"],
                    chunk_index=i,
                    content=chunk.content,
                    title=prepared["title"],
                    filename=prepared["original_filename"],
                    url=prepared["url"],
                    embedding=embedding,
                    source_type_filter=prepared["source_type"],
                    content_type=prepared["content_type"],
                    collection_id=prepared["collection_id"],
                    sync_config_id=prepared["sync_config_id"],
                    metadata=prepared["metadata"],
                )

            # Propagate canonical AssetMetadata into search_chunks.metadata.custom
            await self.propagate_asset_metadata(session, asset_id)

            # Update asset.indexed_at timestamp
            _now = datetime.utcnow()
            await session.execute(
                update(Asset)
                .where(Asset.id == asset_id)
                .values(indexed_at=_now, updated_at=_now)
            )

            await session.commit()

            # Invalidate metadata schema cache after indexing
            from .pg_search_service import pg_search_service
            pg_search_service.invalidate_metadata_cache(prepared["organization_id"])

            logger.info(f"Indexed asset {asset_id} with {len(chunks)} chunks")
            return True

        except Exception as e:
            logger.error(f"Error indexing prepared asset {asset_id}: {e}")
            await session.rollback()
            return False

    def _derive_storage_folder(self, raw_object_key: Optional[str]) -> str:
        """Derive storage_folder from raw_object_key.

        Strips org_id prefix (first segment) and filename (last segment).
        e.g. "{org_id}/sharepoint/site/docs/file.pdf" → "sharepoint/site/docs"
        """
        if not raw_object_key:
            return ""
        parts = raw_object_key.split("/")
        if len(parts) > 2:
            return "/".join(parts[1:-1])
        return ""

    def _build_asset_metadata(
        self, asset: Asset
    ) -> tuple[Optional[str], Optional[str], Optional[UUID], Optional[UUID], Optional[Dict]]:
        """
        Extract metadata from asset for indexing.

        Source_metadata is already namespaced by connectors, so the builder
        passes it through. This method also extracts title/url/collection_id/
        sync_config_id from the namespaced structure.

        Returns:
            Tuple of (title, url, collection_id, sync_config_id, metadata)
        """
        title = asset.original_filename
        url = None
        collection_id = None
        sync_config_id = None

        source_meta = asset.source_metadata or {}
        storage_folder = self._derive_storage_folder(asset.raw_object_key)

        # Use builder — pass-through for assets (source_metadata already namespaced)
        builder_key = f"asset_{asset.source_type}" if asset.source_type else "asset_default"
        builder = metadata_builder_registry.get(builder_key) or metadata_builder_registry.get("asset_default")
        metadata = builder.build_metadata(
            storage_folder=storage_folder,
            source_metadata=source_meta,
        )

        # Extract title/url/collection_id/sync_config_id from namespaced metadata
        if asset.source_type in ("web_scrape", "web_scrape_document"):
            scrape = source_meta.get("scrape", {})
            url = scrape.get("url") or scrape.get("source_url")
            if url:
                title = url
            col_id = scrape.get("collection_id")
            if col_id:
                collection_id = UUID(col_id) if isinstance(col_id, str) else col_id

        elif asset.source_type == "sharepoint":
            sp = source_meta.get("sharepoint", {})
            sc_id = source_meta.get("sync", {}).get("config_id")
            if sc_id:
                sync_config_id = UUID(sc_id) if isinstance(sc_id, str) else sc_id

            sp_path = sp.get("path")
            if sp_path:
                title = f"{sp_path}/{asset.original_filename}"

            url = sp.get("web_url")

        return title, url, collection_id, sync_config_id, metadata

    async def propagate_asset_metadata(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> bool:
        """
        Merge canonical AssetMetadata into search_chunks.metadata.custom.

        This bridges the AssetMetadata table (written by update_metadata /
        bulk_update_metadata functions) into the search index so that
        LLM-generated metadata becomes searchable and filterable.

        Args:
            session: Database session
            asset_id: Asset UUID whose metadata to propagate

        Returns:
            True if propagation succeeded or no metadata to propagate
        """
        import json
        from app.core.database.models import AssetMetadata

        try:
            from sqlalchemy import select as sa_select
            query = sa_select(AssetMetadata).where(
                AssetMetadata.asset_id == asset_id,
                AssetMetadata.is_canonical == True,
            )
            result = await session.execute(query)
            records = list(result.scalars().all())

            if not records:
                return True

            custom = {}
            for record in records:
                # Convert dotted type to underscore key: "tags.llm.v1" → "tags_llm_v1"
                type_key = record.metadata_type.replace(".", "_")
                custom[type_key] = record.metadata_content

            sql = text("""
                UPDATE search_chunks
                SET metadata = jsonb_set(
                    COALESCE(metadata, '{}'::jsonb),
                    '{custom}',
                    CAST(:custom AS jsonb),
                    true
                )
                WHERE source_type = 'asset' AND source_id = CAST(:aid AS UUID)
            """)
            await session.execute(sql, {
                "custom": json.dumps(custom),
                "aid": str(asset_id),
            })

            # Invalidate metadata schema cache (custom namespace changed)
            # Look up the organization_id from the asset
            from app.core.database.models import Asset as AssetModel
            asset_result = await session.execute(
                sa_select(AssetModel.organization_id).where(AssetModel.id == asset_id)
            )
            org_id = asset_result.scalar()
            if org_id:
                from .pg_search_service import pg_search_service
                pg_search_service.invalidate_metadata_cache(org_id)

            logger.debug(f"Propagated {len(records)} metadata records for asset {asset_id}")
            return True

        except Exception as e:
            logger.error(f"Error propagating metadata for asset {asset_id}: {e}")
            return False

    async def _insert_chunk(
        self,
        session: AsyncSession,
        source_type: str,
        source_id: UUID,
        organization_id: UUID,
        chunk_index: int,
        content: str,
        title: Optional[str],
        filename: Optional[str],
        url: Optional[str],
        embedding: List[float],
        source_type_filter: Optional[str] = None,
        content_type: Optional[str] = None,
        collection_id: Optional[UUID] = None,
        sync_config_id: Optional[UUID] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Insert a single chunk into search_chunks table."""
        import json

        # Format embedding as pgvector string: '[0.1, 0.2, ...]'
        embedding_str = "[" + ",".join(str(f) for f in embedding) + "]"
        metadata_json = json.dumps(metadata) if metadata else None

        # Use CAST() syntax instead of :: to avoid conflicts with SQLAlchemy named params
        sql = text("""
            INSERT INTO search_chunks (
                source_type, source_id, organization_id, chunk_index,
                content, title, filename, url, embedding,
                source_type_filter, content_type, collection_id, sync_config_id, metadata
            ) VALUES (
                :source_type, CAST(:source_id AS UUID), CAST(:organization_id AS UUID), :chunk_index,
                :content, :title, :filename, :url, CAST(:embedding AS vector),
                :source_type_filter, :content_type, CAST(:collection_id AS UUID), CAST(:sync_config_id AS UUID), CAST(:metadata AS jsonb)
            )
            ON CONFLICT (source_type, source_id, chunk_index)
            DO UPDATE SET
                content = EXCLUDED.content,
                title = EXCLUDED.title,
                filename = EXCLUDED.filename,
                url = EXCLUDED.url,
                embedding = EXCLUDED.embedding,
                source_type_filter = EXCLUDED.source_type_filter,
                content_type = EXCLUDED.content_type,
                collection_id = EXCLUDED.collection_id,
                sync_config_id = EXCLUDED.sync_config_id,
                metadata = COALESCE(search_chunks.metadata, '{}'::jsonb) || EXCLUDED.metadata
        """)

        await session.execute(sql, {
            "source_type": source_type,
            "source_id": str(source_id),
            "organization_id": str(organization_id),
            "chunk_index": chunk_index,
            "content": content,
            "title": title,
            "filename": filename,
            "url": url,
            "embedding": embedding_str,
            "source_type_filter": source_type_filter,
            "content_type": content_type,
            "collection_id": str(collection_id) if collection_id else None,
            "sync_config_id": str(sync_config_id) if sync_config_id else None,
            "metadata": metadata_json,
        })

    async def _delete_chunks(
        self,
        session: AsyncSession,
        source_type: str,
        source_id: UUID,
    ) -> None:
        """Delete all chunks for a source."""
        sql = text("""
            DELETE FROM search_chunks
            WHERE source_type = :source_type AND source_id = :source_id
        """)
        await session.execute(sql, {
            "source_type": source_type,
            "source_id": str(source_id),
        })

    async def delete_asset_index(
        self,
        session: AsyncSession,
        organization_id: UUID,
        asset_id: UUID,
    ) -> bool:
        """
        Remove an asset from the search index.

        Args:
            session: Database session
            organization_id: Organization UUID (for validation)
            asset_id: Asset UUID

        Returns:
            True if deleted successfully, False otherwise
        """
        if not _is_search_enabled():
            return True

        try:
            sql = text("""
                DELETE FROM search_chunks
                WHERE source_type = 'asset'
                AND source_id = :asset_id
                AND organization_id = :org_id
            """)
            await session.execute(sql, {
                "asset_id": str(asset_id),
                "org_id": str(organization_id),
            })
            await session.commit()
            logger.info(f"Deleted index for asset {asset_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete index for asset {asset_id}: {e}")
            return False

    async def index_sam_notice(
        self,
        session: AsyncSession,
        organization_id: UUID,
        notice_id: UUID,
        sam_notice_id: str,
        solicitation_id: Optional[UUID] = None,
        title: str = "",
        description: str = "",
        notice_type: str = "",
        agency: Optional[str] = None,
        posted_date: Optional[datetime] = None,
        response_deadline: Optional[datetime] = None,
        url: Optional[str] = None,
        embedding: Optional[List[float]] = None,
    ) -> bool:
        """Index a SAM.gov notice."""
        if not _is_search_enabled():
            return False
        try:
            builder = metadata_builder_registry.get("sam_notice")
            content = builder.build_content(title=title, description=description)
            metadata = builder.build_metadata(
                sam_notice_id=sam_notice_id,
                solicitation_id=str(solicitation_id) if solicitation_id else None,
                notice_type=notice_type, agency=agency,
                posted_date=posted_date.isoformat() if posted_date else None,
                response_deadline=response_deadline.isoformat() if response_deadline else None,
            )
            if embedding is None:
                embedding = await embedding_service.get_embedding(content)
            await self._delete_chunks(session, "sam_notice", notice_id)
            await self._insert_chunk(
                session=session, source_type="sam_notice", source_id=notice_id,
                organization_id=organization_id, chunk_index=0, content=content,
                title=title, filename=sam_notice_id, url=url, embedding=embedding,
                source_type_filter="sam_gov", content_type=notice_type, metadata=metadata,
            )
            from app.core.database.models import SamNotice as SamNoticeModel
            await session.execute(
                update(SamNoticeModel).where(SamNoticeModel.id == notice_id)
                .values(indexed_at=datetime.utcnow())
            )
            await session.commit()
            logger.debug(f"Indexed SAM notice {notice_id}")
            return True
        except Exception as e:
            logger.error(f"Error indexing SAM notice {notice_id}: {e}")
            await session.rollback()
            return False

    async def index_sam_solicitation(
        self, session: AsyncSession, organization_id: UUID, solicitation_id: UUID,
        solicitation_number: str, title: str, description: str,
        agency: Optional[str] = None, office: Optional[str] = None,
        naics_code: Optional[str] = None, set_aside: Optional[str] = None,
        posted_date: Optional[datetime] = None, response_deadline: Optional[datetime] = None,
        url: Optional[str] = None, embedding: Optional[List[float]] = None,
    ) -> bool:
        """Index a SAM.gov solicitation."""
        if not _is_search_enabled():
            return False
        try:
            builder = metadata_builder_registry.get("sam_solicitation")
            content = builder.build_content(title=title, description=description, agency=agency)
            metadata = builder.build_metadata(
                solicitation_number=solicitation_number, agency=agency, office=office,
                naics_code=naics_code, set_aside=set_aside,
                posted_date=posted_date.isoformat() if posted_date else None,
                response_deadline=response_deadline.isoformat() if response_deadline else None,
            )
            if embedding is None:
                embedding = await embedding_service.get_embedding(content)
            await self._delete_chunks(session, "sam_solicitation", solicitation_id)
            await self._insert_chunk(
                session=session, source_type="sam_solicitation", source_id=solicitation_id,
                organization_id=organization_id, chunk_index=0, content=content,
                title=title, filename=solicitation_number, url=url, embedding=embedding,
                source_type_filter="sam_gov", content_type="solicitation", metadata=metadata,
            )
            from app.core.database.models import SamSolicitation as SamSolicitationModel
            _now = datetime.utcnow()
            await session.execute(
                update(SamSolicitationModel).where(SamSolicitationModel.id == solicitation_id)
                .values(indexed_at=_now, updated_at=_now)
            )
            await session.commit()
            logger.debug(f"Indexed SAM solicitation {solicitation_id}")
            return True
        except Exception as e:
            logger.error(f"Error indexing SAM solicitation {solicitation_id}: {e}")
            await session.rollback()
            return False

    async def delete_sam_notice(self, session, organization_id, notice_id) -> bool:
        try:
            await self._delete_chunks(session, "sam_notice", notice_id)
            await session.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to delete SAM notice index {notice_id}: {e}")
            return False

    async def delete_sam_solicitation(self, session, organization_id, solicitation_id) -> bool:
        try:
            await self._delete_chunks(session, "sam_solicitation", solicitation_id)
            await session.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to delete SAM solicitation index {solicitation_id}: {e}")
            return False

    async def index_forecast(
        self,
        session: AsyncSession,
        organization_id: UUID,
        forecast_id: UUID,
        source_type: str = "",
        source_id: str = "",
        title: str = "",
        description: Optional[str] = None,
        agency_name: Optional[str] = None,
        naics_codes: Optional[list] = None,
        set_aside_type: Optional[str] = None,
        fiscal_year: Optional[int] = None,
        estimated_award_quarter: Optional[str] = None,
        url: Optional[str] = None,
        embedding: Optional[List[float]] = None,
    ) -> bool:
        """Index an acquisition forecast (AG, APFS, or State)."""
        if not _is_search_enabled():
            return False
        try:
            # Map source_type to internal source_type
            internal_source_type = f"{source_type}_forecast" if source_type else "forecast"

            builder = metadata_builder_registry.get("forecast")
            content = builder.build_content(
                title=title, description=description,
                agency_name=agency_name, naics_codes=naics_codes,
            )
            metadata = builder.build_metadata(
                source_type=source_type, source_id=source_id,
                agency_name=agency_name, naics_codes=naics_codes,
                set_aside_type=set_aside_type, fiscal_year=fiscal_year,
                estimated_award_quarter=estimated_award_quarter,
            )
            if embedding is None:
                embedding = await embedding_service.get_embedding(content)
            await self._delete_chunks(session, internal_source_type, forecast_id)
            await self._insert_chunk(
                session=session, source_type=internal_source_type, source_id=forecast_id,
                organization_id=organization_id, chunk_index=0, content=content,
                title=title, filename=source_id, url=url, embedding=embedding,
                source_type_filter=internal_source_type, content_type="forecast",
                metadata=metadata,
            )
            await session.commit()
            logger.debug(f"Indexed forecast {forecast_id} ({source_type})")
            return True
        except Exception as e:
            logger.error(f"Error indexing forecast {forecast_id}: {e}")
            await session.rollback()
            return False

    async def delete_forecast(self, session, organization_id, forecast_id, source_type: str = "") -> bool:
        """Delete a forecast from the search index."""
        try:
            internal_source_type = f"{source_type}_forecast" if source_type else "forecast"
            await self._delete_chunks(session, internal_source_type, forecast_id)
            await session.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to delete forecast index {forecast_id}: {e}")
            return False

    async def index_salesforce_account(
        self,
        session: AsyncSession,
        organization_id: UUID,
        account_id: UUID,
        salesforce_id: str = "",
        name: str = "",
        account_type: Optional[str] = None,
        industry: Optional[str] = None,
        description: Optional[str] = None,
        website: Optional[str] = None,
        embedding: Optional[List[float]] = None,
    ) -> bool:
        """Index a Salesforce account."""
        if not _is_search_enabled():
            return False
        try:
            builder = metadata_builder_registry.get("salesforce_account")
            content = builder.build_content(
                name=name, account_type=account_type,
                industry=industry, description=description,
            )
            metadata = builder.build_metadata(
                salesforce_id=salesforce_id, account_type=account_type,
                industry=industry, website=website,
            )
            if embedding is None:
                embedding = await embedding_service.get_embedding(content)
            await self._delete_chunks(session, "salesforce_account", account_id)
            await self._insert_chunk(
                session=session, source_type="salesforce_account", source_id=account_id,
                organization_id=organization_id, chunk_index=0, content=content,
                title=name, filename=salesforce_id, url=None, embedding=embedding,
                source_type_filter="salesforce_account", content_type="account",
                metadata=metadata,
            )
            await session.commit()
            logger.debug(f"Indexed Salesforce account {account_id}")
            return True
        except Exception as e:
            logger.error(f"Error indexing Salesforce account {account_id}: {e}")
            await session.rollback()
            return False

    async def index_salesforce_contact(
        self,
        session: AsyncSession,
        organization_id: UUID,
        contact_id: UUID,
        salesforce_id: str = "",
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        email: Optional[str] = None,
        title: Optional[str] = None,
        account_name: Optional[str] = None,
        department: Optional[str] = None,
        embedding: Optional[List[float]] = None,
    ) -> bool:
        """Index a Salesforce contact."""
        if not _is_search_enabled():
            return False
        try:
            builder = metadata_builder_registry.get("salesforce_contact")
            full_name = f"{first_name or ''} {last_name or ''}".strip() or "Unknown Contact"
            content = builder.build_content(
                first_name=first_name, last_name=last_name,
                title=title, account_name=account_name,
                department=department, email=email,
            )
            metadata = builder.build_metadata(
                salesforce_id=salesforce_id, first_name=first_name,
                last_name=last_name, email=email, title=title,
                account_name=account_name,
            )
            if embedding is None:
                embedding = await embedding_service.get_embedding(content)
            await self._delete_chunks(session, "salesforce_contact", contact_id)
            await self._insert_chunk(
                session=session, source_type="salesforce_contact", source_id=contact_id,
                organization_id=organization_id, chunk_index=0, content=content,
                title=full_name, filename=salesforce_id, url=None, embedding=embedding,
                source_type_filter="salesforce_contact", content_type="contact",
                metadata=metadata,
            )
            await session.commit()
            logger.debug(f"Indexed Salesforce contact {contact_id}")
            return True
        except Exception as e:
            logger.error(f"Error indexing Salesforce contact {contact_id}: {e}")
            await session.rollback()
            return False

    async def index_salesforce_opportunity(
        self,
        session: AsyncSession,
        organization_id: UUID,
        opportunity_id: UUID,
        salesforce_id: str = "",
        name: str = "",
        stage_name: Optional[str] = None,
        amount: Optional[float] = None,
        opportunity_type: Optional[str] = None,
        account_name: Optional[str] = None,
        description: Optional[str] = None,
        close_date: Optional[str] = None,
        embedding: Optional[List[float]] = None,
    ) -> bool:
        """Index a Salesforce opportunity."""
        if not _is_search_enabled():
            return False
        try:
            builder = metadata_builder_registry.get("salesforce_opportunity")
            content = builder.build_content(
                name=name, account_name=account_name,
                stage_name=stage_name, opportunity_type=opportunity_type,
                amount=amount, description=description,
            )
            metadata = builder.build_metadata(
                salesforce_id=salesforce_id, stage_name=stage_name,
                amount=amount, opportunity_type=opportunity_type,
                account_name=account_name, close_date=close_date,
            )
            if embedding is None:
                embedding = await embedding_service.get_embedding(content)
            await self._delete_chunks(session, "salesforce_opportunity", opportunity_id)
            await self._insert_chunk(
                session=session, source_type="salesforce_opportunity", source_id=opportunity_id,
                organization_id=organization_id, chunk_index=0, content=content,
                title=name, filename=salesforce_id, url=None, embedding=embedding,
                source_type_filter="salesforce_opportunity", content_type="opportunity",
                metadata=metadata,
            )
            await session.commit()
            logger.debug(f"Indexed Salesforce opportunity {opportunity_id}")
            return True
        except Exception as e:
            logger.error(f"Error indexing Salesforce opportunity {opportunity_id}: {e}")
            await session.rollback()
            return False

    async def reindex_organization(
        self,
        session: AsyncSession,
        organization_id: UUID,
        batch_size: int = 50,
    ) -> Dict[str, Any]:
        """
        Reindex all assets for an organization.

        Fetches all assets with completed extractions, clears existing index,
        and re-indexes everything. Uses batched embedding generation for efficiency.

        Args:
            session: Database session
            organization_id: Organization UUID
            batch_size: Number of assets to process per batch

        Returns:
            Dict with indexed, failed, skipped counts
        """
        if not _is_search_enabled():
            return {"indexed": 0, "failed": 0, "skipped": 0, "error": "Search disabled"}

        stats = {"indexed": 0, "failed": 0, "skipped": 0}

        try:
            # Get all assets for this organization
            result = await session.execute(
                select(Asset).where(Asset.organization_id == organization_id)
            )
            assets = result.scalars().all()

            logger.info(
                f"Reindexing {len(assets)} assets for org {organization_id} "
                f"(batch_size={batch_size})"
            )

            # Process in batches
            for i in range(0, len(assets), batch_size):
                batch = assets[i : i + batch_size]

                # Prepare all assets in the batch
                prepared_list = []
                for asset in batch:
                    prepared = await self.prepare_asset_for_indexing(session, asset.id)
                    if prepared:
                        prepared_list.append(prepared)
                    else:
                        stats["skipped"] += 1

                if not prepared_list:
                    continue

                # Gather all chunk texts for batch embedding
                all_chunk_texts = []
                chunk_counts = []
                for prepared in prepared_list:
                    chunks = prepared["chunks"]
                    chunk_texts = [c.content for c in chunks]
                    all_chunk_texts.extend(chunk_texts)
                    chunk_counts.append(len(chunk_texts))

                # Generate all embeddings in one batch
                try:
                    all_embeddings = await embedding_service.get_embeddings_batch(all_chunk_texts)
                except Exception as e:
                    logger.error(f"Batch embedding failed: {e}")
                    stats["failed"] += len(prepared_list)
                    continue

                # Distribute embeddings back to prepared assets and index
                embedding_offset = 0
                for prepared, count in zip(prepared_list, chunk_counts):
                    asset_embeddings = all_embeddings[embedding_offset : embedding_offset + count]
                    embedding_offset += count

                    try:
                        success = await self.index_asset_prepared(
                            session, prepared, asset_embeddings
                        )
                        if success:
                            stats["indexed"] += 1
                        else:
                            stats["failed"] += 1
                    except Exception as e:
                        logger.error(f"Failed to index asset {prepared['asset_id']}: {e}")
                        stats["failed"] += 1

            logger.info(f"Reindex complete for org {organization_id}: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Reindex failed for org {organization_id}: {e}")
            stats["error"] = str(e)
            return stats

    async def get_index_health(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> Dict[str, Any]:
        """
        Get the health status of the search index for an organization.

        Returns:
            Dict with enabled, status, index_name, document_count,
            chunk_count, size_bytes, message
        """
        if not _is_search_enabled():
            return {
                "enabled": False,
                "status": "disabled",
                "message": "Search is disabled",
            }

        try:
            stats = await self._get_org_index_stats(session, organization_id)
            return {
                "enabled": True,
                "status": "healthy",
                "index_name": f"search_chunks (org: {organization_id})",
                "document_count": stats.get("document_count", 0),
                "chunk_count": stats.get("chunk_count", 0),
                "size_bytes": stats.get("size_bytes", 0),
                "message": "Index is healthy",
            }
        except Exception as e:
            logger.error(f"Index health check failed: {e}")
            return {
                "enabled": True,
                "status": "error",
                "message": str(e),
            }

    async def _get_org_index_stats(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> Dict[str, Any]:
        """Get basic index statistics for an organization."""
        sql = text("""
            SELECT
                COUNT(DISTINCT source_id) as document_count,
                COUNT(*) as chunk_count,
                pg_total_relation_size('search_chunks') as size_bytes
            FROM search_chunks
            WHERE organization_id = :org_id
        """)
        result = await session.execute(sql, {"org_id": str(organization_id)})
        row = result.fetchone()
        if not row:
            return {"document_count": 0, "chunk_count": 0, "size_bytes": 0}
        return {
            "document_count": row.document_count or 0,
            "chunk_count": row.chunk_count or 0,
            "size_bytes": row.size_bytes or 0,
        }


# Global service instance
pg_index_service = PgIndexService()


def get_pg_index_service() -> PgIndexService:
    """Get the global PostgreSQL index service instance."""
    return pg_index_service
