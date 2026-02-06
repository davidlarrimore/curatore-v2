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
    from app.services.pg_index_service import pg_index_service

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

from ..config import settings
from ..database.models import Asset, ExtractionResult
from .asset_service import asset_service
from .chunking_service import chunking_service, DocumentChunk
from .embedding_service import embedding_service
from .minio_service import get_minio_service

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

            # Update asset.indexed_at timestamp
            await session.execute(
                update(Asset)
                .where(Asset.id == asset_id)
                .values(indexed_at=datetime.utcnow())
            )

            await session.commit()
            logger.info(f"Indexed asset {asset_id} with {len(chunks)} chunks")
            return True

        except Exception as e:
            logger.error(f"Error indexing asset {asset_id}: {e}")
            await session.rollback()
            return False

    def _build_asset_metadata(
        self, asset: Asset
    ) -> tuple[Optional[str], Optional[str], Optional[UUID], Optional[UUID], Optional[Dict]]:
        """
        Extract metadata from asset for indexing.

        Returns:
            Tuple of (title, url, collection_id, sync_config_id, metadata)
        """
        title = asset.original_filename
        url = None
        collection_id = None
        sync_config_id = None
        metadata = {}

        source_meta = asset.source_metadata or {}

        if asset.source_type == "web_scrape":
            url = source_meta.get("url")
            if url:
                title = source_meta.get("title") or url
            col_id = source_meta.get("collection_id")
            if col_id:
                collection_id = UUID(col_id) if isinstance(col_id, str) else col_id

        elif asset.source_type == "sharepoint":
            sc_id = source_meta.get("sync_config_id")
            if sc_id:
                sync_config_id = UUID(sc_id) if isinstance(sc_id, str) else sc_id

            sp_path = source_meta.get("sharepoint_path")
            if sp_path:
                title = f"{sp_path}/{asset.original_filename}"

            # Get SharePoint web URL for direct access
            url = source_meta.get("sharepoint_web_url")

            # Store enhanced metadata
            metadata = {
                "sharepoint_path": sp_path,
                "sharepoint_folder": source_meta.get("sharepoint_folder"),
                "sharepoint_web_url": url,
                "created_by": source_meta.get("created_by"),
                "modified_by": source_meta.get("modified_by"),
            }

        elif asset.source_type == "upload":
            metadata = {
                "uploaded_by": source_meta.get("uploaded_by"),
            }

        return title, url, collection_id, sync_config_id, metadata

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
                metadata = EXCLUDED.metadata
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
    ) -> bool:
        """
        Index a SAM.gov notice.

        Args:
            session: Database session
            organization_id: Organization UUID
            notice_id: Internal notice UUID
            sam_notice_id: SAM.gov notice identifier
            solicitation_id: Parent solicitation UUID (None for standalone notices)
            title: Notice title
            description: Notice description/content
            notice_type: Type of notice
            agency: Agency name
            posted_date: When notice was posted
            response_deadline: Submission deadline
            url: SAM.gov URL

        Returns:
            True if indexed successfully
        """
        if not _is_search_enabled():
            return False

        try:
            # Build content for indexing
            content = f"{title}\n\n{description}"

            # Generate embedding
            embedding = await embedding_service.get_embedding(content)

            # Build metadata
            metadata = {
                "sam_notice_id": sam_notice_id,
                "solicitation_id": str(solicitation_id) if solicitation_id else None,
                "notice_type": notice_type,
                "agency": agency,
                "posted_date": posted_date.isoformat() if posted_date else None,
                "response_deadline": response_deadline.isoformat() if response_deadline else None,
            }

            # Delete existing and insert new
            await self._delete_chunks(session, "sam_notice", notice_id)

            await self._insert_chunk(
                session=session,
                source_type="sam_notice",
                source_id=notice_id,
                organization_id=organization_id,
                chunk_index=0,
                content=content,
                title=title,
                filename=sam_notice_id,
                url=url,
                embedding=embedding,
                source_type_filter="sam_gov",
                content_type=notice_type,
                metadata=metadata,
            )

            await session.commit()
            logger.debug(f"Indexed SAM notice {notice_id}")
            return True

        except Exception as e:
            logger.error(f"Error indexing SAM notice {notice_id}: {e}")
            await session.rollback()
            return False

    async def index_sam_solicitation(
        self,
        session: AsyncSession,
        organization_id: UUID,
        solicitation_id: UUID,
        solicitation_number: str,
        title: str,
        description: str,
        agency: Optional[str] = None,
        office: Optional[str] = None,
        naics_code: Optional[str] = None,
        set_aside: Optional[str] = None,
        posted_date: Optional[datetime] = None,
        response_deadline: Optional[datetime] = None,
        url: Optional[str] = None,
    ) -> bool:
        """
        Index a SAM.gov solicitation.

        Args:
            session: Database session
            organization_id: Organization UUID
            solicitation_id: Internal solicitation UUID
            solicitation_number: SAM.gov solicitation number
            title: Solicitation title
            description: Full description
            agency: Agency name
            office: Office name
            naics_code: NAICS classification code
            set_aside: Set-aside type
            posted_date: When posted
            response_deadline: Submission deadline
            url: SAM.gov URL

        Returns:
            True if indexed successfully
        """
        if not _is_search_enabled():
            return False

        try:
            # Build content for indexing
            content = f"{title}\n\n{description}"
            if agency:
                content = f"{agency}\n{content}"

            # Generate embedding
            embedding = await embedding_service.get_embedding(content)

            # Build metadata
            metadata = {
                "solicitation_number": solicitation_number,
                "agency": agency,
                "office": office,
                "naics_code": naics_code,
                "set_aside": set_aside,
                "posted_date": posted_date.isoformat() if posted_date else None,
                "response_deadline": response_deadline.isoformat() if response_deadline else None,
            }

            # Delete existing and insert new
            await self._delete_chunks(session, "sam_solicitation", solicitation_id)

            await self._insert_chunk(
                session=session,
                source_type="sam_solicitation",
                source_id=solicitation_id,
                organization_id=organization_id,
                chunk_index=0,
                content=content,
                title=title,
                filename=solicitation_number,
                url=url,
                embedding=embedding,
                source_type_filter="sam_gov",
                content_type="solicitation",
                metadata=metadata,
            )

            await session.commit()
            logger.debug(f"Indexed SAM solicitation {solicitation_id}")
            return True

        except Exception as e:
            logger.error(f"Error indexing SAM solicitation {solicitation_id}: {e}")
            await session.rollback()
            return False

    async def delete_sam_notice(
        self,
        session: AsyncSession,
        organization_id: UUID,
        notice_id: UUID,
    ) -> bool:
        """Delete a SAM notice from the index."""
        try:
            await self._delete_chunks(session, "sam_notice", notice_id)
            await session.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to delete SAM notice index {notice_id}: {e}")
            return False

    async def delete_sam_solicitation(
        self,
        session: AsyncSession,
        organization_id: UUID,
        solicitation_id: UUID,
    ) -> bool:
        """Delete a SAM solicitation from the index."""
        try:
            await self._delete_chunks(session, "sam_solicitation", solicitation_id)
            await session.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to delete SAM solicitation index {solicitation_id}: {e}")
            return False

    # =========================================================================
    # FORECAST INDEXING
    # =========================================================================

    async def index_forecast(
        self,
        session: AsyncSession,
        organization_id: UUID,
        forecast_id: UUID,
        source_type: str,
        source_id: str,
        title: str,
        description: Optional[str] = None,
        agency_name: Optional[str] = None,
        naics_codes: Optional[list] = None,
        set_aside_type: Optional[str] = None,
        fiscal_year: Optional[int] = None,
        estimated_award_quarter: Optional[str] = None,
        url: Optional[str] = None,
    ) -> bool:
        """
        Index an acquisition forecast.

        Args:
            session: Database session
            organization_id: Organization UUID
            forecast_id: Internal forecast UUID
            source_type: Source (ag, apfs, state)
            source_id: Source-specific identifier (nid, apfs_number, row_hash)
            title: Forecast title
            description: Forecast description
            agency_name: Agency name
            naics_codes: List of NAICS code dicts
            set_aside_type: Set-aside type
            fiscal_year: Fiscal year
            estimated_award_quarter: Estimated award quarter
            url: Source URL (if available)

        Returns:
            True if indexed successfully
        """
        if not _is_search_enabled():
            return False

        try:
            # Build content for indexing
            content_parts = [title]
            if description:
                content_parts.append(description)
            if agency_name:
                content_parts.append(agency_name)
            if naics_codes:
                for nc in naics_codes:
                    if isinstance(nc, dict):
                        code = nc.get("code", "")
                        desc = nc.get("description", "")
                        if code:
                            content_parts.append(code)
                        if desc:
                            content_parts.append(desc)

            content = "\n\n".join(content_parts)

            # Generate embedding
            embedding = await embedding_service.get_embedding(content)

            # Build metadata
            metadata = {
                "source_type": source_type,
                "source_id": source_id,
                "agency_name": agency_name,
                "set_aside_type": set_aside_type,
                "fiscal_year": fiscal_year,
                "estimated_award_quarter": estimated_award_quarter,
            }

            # Delete existing chunk for this forecast
            await self._delete_chunks(session, f"{source_type}_forecast", forecast_id)

            # Insert single chunk (forecasts are typically short)
            await self._insert_chunk(
                session=session,
                source_type=f"{source_type}_forecast",
                source_id=forecast_id,
                organization_id=organization_id,
                chunk_index=0,
                content=content,
                title=title,
                filename=source_id,
                url=url,
                embedding=embedding,
                source_type_filter="forecast",
                content_type=source_type,
                metadata=metadata,
            )

            # Update indexed_at timestamp on the forecast record
            if source_type == "ag":
                from ..database.models import AgForecast
                await session.execute(
                    update(AgForecast)
                    .where(AgForecast.id == forecast_id)
                    .values(indexed_at=datetime.utcnow())
                )
            elif source_type == "apfs":
                from ..database.models import ApfsForecast
                await session.execute(
                    update(ApfsForecast)
                    .where(ApfsForecast.id == forecast_id)
                    .values(indexed_at=datetime.utcnow())
                )
            elif source_type == "state":
                from ..database.models import StateForecast
                await session.execute(
                    update(StateForecast)
                    .where(StateForecast.id == forecast_id)
                    .values(indexed_at=datetime.utcnow())
                )

            await session.commit()
            logger.debug(f"Indexed {source_type} forecast {forecast_id}")
            return True

        except Exception as e:
            logger.error(f"Error indexing forecast {forecast_id}: {e}")
            await session.rollback()
            return False

    async def delete_forecast(
        self,
        session: AsyncSession,
        organization_id: UUID,
        forecast_id: UUID,
        source_type: str,
    ) -> bool:
        """Delete a forecast from the index."""
        try:
            await self._delete_chunks(session, f"{source_type}_forecast", forecast_id)
            await session.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to delete forecast index {forecast_id}: {e}")
            return False

    async def reindex_organization(
        self,
        session: AsyncSession,
        organization_id: UUID,
        batch_size: int = 50,
    ) -> Dict[str, Any]:
        """
        Reindex all assets for an organization.

        Fetches all assets with completed extractions and indexes them
        in batches.

        Args:
            session: Database session
            organization_id: Organization UUID
            batch_size: Number of assets to process per batch

        Returns:
            Dict with reindex statistics
        """
        if not _is_search_enabled():
            return {
                "status": "disabled",
                "message": "Search is not enabled",
                "total": 0,
                "indexed": 0,
                "failed": 0,
            }

        # Get all assets with completed extractions
        query = (
            select(Asset)
            .where(Asset.organization_id == organization_id)
            .where(Asset.status == "ready")
            .order_by(Asset.created_at)
        )
        result = await session.execute(query)
        assets = list(result.scalars().all())

        total = len(assets)
        indexed = 0
        failed = 0
        errors: List[str] = []

        logger.info(f"Starting reindex of {total} assets for org {organization_id}")

        for i, asset in enumerate(assets):
            try:
                success = await self.index_asset(session, asset.id)
                if success:
                    indexed += 1
                else:
                    failed += 1

                if (i + 1) % batch_size == 0:
                    logger.info(f"Processed {i + 1}/{total} assets")

            except Exception as e:
                logger.error(f"Error reindexing asset {asset.id}: {e}")
                failed += 1
                errors.append(f"Asset {asset.id}: {str(e)}")

        logger.info(
            f"Reindex complete for org {organization_id}: "
            f"{indexed}/{total} indexed, {failed} failed"
        )

        return {
            "status": "completed",
            "total": total,
            "indexed": indexed,
            "failed": failed,
            "errors": errors[:20],  # Limit error list
        }

    async def get_index_health(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> Dict[str, Any]:
        """
        Get health status of the search index for an organization.

        Args:
            session: Database session
            organization_id: Organization UUID

        Returns:
            Dict with index health information
        """
        if not _is_search_enabled():
            return {
                "enabled": False,
                "status": "disabled",
                "message": "Search is not enabled",
            }

        try:
            # Check pgvector extension
            ext_result = await session.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
            has_pgvector = ext_result.fetchone() is not None

            if not has_pgvector:
                return {
                    "enabled": True,
                    "status": "unavailable",
                    "message": "pgvector extension not installed",
                }

            # Get stats
            stats_sql = text("""
                SELECT
                    COUNT(DISTINCT source_id) as document_count,
                    COUNT(*) as chunk_count
                FROM search_chunks
                WHERE organization_id = :org_id
            """)
            stats_result = await session.execute(
                stats_sql, {"org_id": str(organization_id)}
            )
            stats = stats_result.fetchone()

            return {
                "enabled": True,
                "status": "healthy",
                "index_name": f"search_chunks (PostgreSQL + pgvector)",
                "document_count": stats.document_count if stats else 0,
                "chunk_count": stats.chunk_count if stats else 0,
            }

        except Exception as e:
            logger.error(f"Failed to get index health: {e}")
            return {
                "enabled": True,
                "status": "error",
                "message": str(e),
            }

    # =========================================================================
    # SALESFORCE INDEXING
    # =========================================================================

    async def index_salesforce_account(
        self,
        session: AsyncSession,
        organization_id: UUID,
        account_id: UUID,
        salesforce_id: str,
        name: str,
        account_type: Optional[str] = None,
        industry: Optional[str] = None,
        description: Optional[str] = None,
        website: Optional[str] = None,
    ) -> bool:
        """
        Index a Salesforce account for search.

        Args:
            session: Database session
            organization_id: Organization UUID
            account_id: Internal account UUID
            salesforce_id: Salesforce 18-character ID
            name: Account name
            account_type: Account type classification
            industry: Industry classification
            description: Account description
            website: Company website

        Returns:
            True if indexed successfully
        """
        if not _is_search_enabled():
            return False

        try:
            # Build content for indexing
            content_parts = [name]
            if account_type:
                content_parts.append(f"Type: {account_type}")
            if industry:
                content_parts.append(f"Industry: {industry}")
            if description:
                content_parts.append(description)

            content = "\n\n".join(content_parts)

            # Generate embedding
            embedding = await embedding_service.get_embedding(content)

            # Build metadata
            metadata = {
                "salesforce_id": salesforce_id,
                "account_type": account_type,
                "industry": industry,
                "website": website,
            }

            # Delete existing and insert new
            await self._delete_chunks(session, "salesforce_account", account_id)

            await self._insert_chunk(
                session=session,
                source_type="salesforce_account",
                source_id=account_id,
                organization_id=organization_id,
                chunk_index=0,
                content=content,
                title=name,
                filename=salesforce_id,
                url=website,
                embedding=embedding,
                source_type_filter="salesforce",
                content_type=account_type or "Account",
                metadata=metadata,
            )

            await session.commit()
            logger.debug(f"Indexed Salesforce account {account_id}")
            return True

        except Exception as e:
            logger.error(f"Error indexing Salesforce account {account_id}: {e}")
            await session.rollback()
            return False

    async def index_salesforce_opportunity(
        self,
        session: AsyncSession,
        organization_id: UUID,
        opportunity_id: UUID,
        salesforce_id: str,
        name: str,
        stage_name: Optional[str] = None,
        amount: Optional[float] = None,
        opportunity_type: Optional[str] = None,
        account_name: Optional[str] = None,
        description: Optional[str] = None,
        close_date: Optional[datetime] = None,
    ) -> bool:
        """
        Index a Salesforce opportunity for search.

        Args:
            session: Database session
            organization_id: Organization UUID
            opportunity_id: Internal opportunity UUID
            salesforce_id: Salesforce 18-character ID
            name: Opportunity name
            stage_name: Pipeline stage
            amount: Deal amount
            opportunity_type: Opportunity type
            account_name: Associated account name
            description: Opportunity description
            close_date: Expected close date

        Returns:
            True if indexed successfully
        """
        if not _is_search_enabled():
            return False

        try:
            # Build content for indexing
            content_parts = [name]
            if account_name:
                content_parts.append(f"Account: {account_name}")
            if stage_name:
                content_parts.append(f"Stage: {stage_name}")
            if opportunity_type:
                content_parts.append(f"Type: {opportunity_type}")
            if amount:
                content_parts.append(f"Amount: ${amount:,.2f}")
            if description:
                content_parts.append(description)

            content = "\n\n".join(content_parts)

            # Generate embedding
            embedding = await embedding_service.get_embedding(content)

            # Build metadata
            metadata = {
                "salesforce_id": salesforce_id,
                "stage_name": stage_name,
                "amount": amount,
                "opportunity_type": opportunity_type,
                "account_name": account_name,
                "close_date": close_date.isoformat() if close_date else None,
            }

            # Delete existing and insert new
            await self._delete_chunks(session, "salesforce_opportunity", opportunity_id)

            await self._insert_chunk(
                session=session,
                source_type="salesforce_opportunity",
                source_id=opportunity_id,
                organization_id=organization_id,
                chunk_index=0,
                content=content,
                title=name,
                filename=salesforce_id,
                url=None,
                embedding=embedding,
                source_type_filter="salesforce",
                content_type=opportunity_type or "Opportunity",
                metadata=metadata,
            )

            await session.commit()
            logger.debug(f"Indexed Salesforce opportunity {opportunity_id}")
            return True

        except Exception as e:
            logger.error(f"Error indexing Salesforce opportunity {opportunity_id}: {e}")
            await session.rollback()
            return False

    async def delete_salesforce_account_index(
        self,
        session: AsyncSession,
        account_id: UUID,
    ) -> bool:
        """Remove Salesforce account from search index."""
        try:
            await self._delete_chunks(session, "salesforce_account", account_id)
            await session.commit()
            logger.debug(f"Removed Salesforce account {account_id} from index")
            return True
        except Exception as e:
            logger.error(f"Failed to delete index for Salesforce account {account_id}: {e}")
            return False

    async def delete_salesforce_opportunity_index(
        self,
        session: AsyncSession,
        opportunity_id: UUID,
    ) -> bool:
        """Remove Salesforce opportunity from search index."""
        try:
            await self._delete_chunks(session, "salesforce_opportunity", opportunity_id)
            await session.commit()
            logger.debug(f"Removed Salesforce opportunity {opportunity_id} from index")
            return True
        except Exception as e:
            logger.error(f"Failed to delete index for Salesforce opportunity {opportunity_id}: {e}")
            return False

    async def index_salesforce_contact(
        self,
        session: AsyncSession,
        organization_id: UUID,
        contact_id: UUID,
        salesforce_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        email: Optional[str] = None,
        title: Optional[str] = None,
        account_name: Optional[str] = None,
        department: Optional[str] = None,
    ) -> bool:
        """
        Index a Salesforce contact for search.

        Args:
            session: Database session
            organization_id: Organization UUID
            contact_id: Internal contact UUID
            salesforce_id: Salesforce 18-character ID
            first_name: Contact first name
            last_name: Contact last name
            email: Contact email
            title: Contact job title
            account_name: Associated account name
            department: Contact department

        Returns:
            True if indexed successfully
        """
        if not _is_search_enabled():
            return False

        try:
            # Build full name
            full_name = f"{first_name or ''} {last_name or ''}".strip() or "Unknown Contact"

            # Build content for indexing
            content_parts = [full_name]
            if title:
                content_parts.append(f"Title: {title}")
            if account_name:
                content_parts.append(f"Account: {account_name}")
            if department:
                content_parts.append(f"Department: {department}")
            if email:
                content_parts.append(f"Email: {email}")

            content = "\n\n".join(content_parts)

            # Generate embedding
            embedding = await embedding_service.get_embedding(content)

            # Build metadata
            metadata = {
                "salesforce_id": salesforce_id,
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "title": title,
                "account_name": account_name,
            }

            # Delete existing and insert new
            await self._delete_chunks(session, "salesforce_contact", contact_id)

            await self._insert_chunk(
                session=session,
                source_type="salesforce_contact",
                source_id=contact_id,
                organization_id=organization_id,
                chunk_index=0,
                content=content,
                title=full_name,
                filename=salesforce_id,
                url=None,
                embedding=embedding,
                source_type_filter="salesforce",
                content_type=title or "Contact",
                metadata=metadata,
            )

            await session.commit()
            logger.debug(f"Indexed Salesforce contact {contact_id}")
            return True

        except Exception as e:
            logger.error(f"Error indexing Salesforce contact {contact_id}: {e}")
            await session.rollback()
            return False

    async def delete_salesforce_contact_index(
        self,
        session: AsyncSession,
        contact_id: UUID,
    ) -> bool:
        """Remove Salesforce contact from search index."""
        try:
            await self._delete_chunks(session, "salesforce_contact", contact_id)
            await session.commit()
            logger.debug(f"Removed Salesforce contact {contact_id} from index")
            return True
        except Exception as e:
            logger.error(f"Failed to delete index for Salesforce contact {contact_id}: {e}")
            return False


# Global service instance
pg_index_service = PgIndexService()


def get_pg_index_service() -> PgIndexService:
    """Get the global PostgreSQL index service instance."""
    return pg_index_service
