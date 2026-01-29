# ============================================================================
# backend/app/services/index_service.py
# ============================================================================
"""
Index Service for Curatore v2 - Asset Indexing to OpenSearch

This module handles the indexing of assets to OpenSearch after extraction
completes. It bridges the asset/extraction system with the search system.

Key Features:
    - Index assets after successful extraction
    - Download markdown content from MinIO for indexing
    - Handle asset deletions (remove from index)
    - Bulk reindex all assets for an organization

Usage:
    from app.services.index_service import index_service

    # Index a single asset after extraction
    await index_service.index_asset(session, asset_id)

    # Remove asset from index
    await index_service.delete_asset_index(organization_id, asset_id)

    # Reindex all assets for an organization
    stats = await index_service.reindex_organization(session, organization_id)

Author: Curatore v2 Development Team
Version: 2.0.0
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database.models import Asset, ExtractionResult
from .asset_service import asset_service
from .config_loader import config_loader
from .minio_service import get_minio_service
from .opensearch_service import opensearch_service

logger = logging.getLogger("curatore.index_service")


def _is_opensearch_enabled() -> bool:
    """Check if OpenSearch is enabled via config.yml or environment variables."""
    # Try config.yml first
    opensearch_config = config_loader.get_opensearch_config()
    if opensearch_config:
        return opensearch_config.enabled
    # Fall back to environment variable
    return settings.opensearch_enabled


class IndexService:
    """
    Service for indexing assets to OpenSearch.

    This service is responsible for building searchable documents from assets
    and their extracted content, then indexing them to OpenSearch.

    Document Building:
        - Title: From source_metadata.title, URL path, or filename
        - Content: Extracted markdown from MinIO
        - Metadata: Source type, content type, URL, collection, etc.

    Indexing Triggers:
        - After successful extraction (via index_asset_task)
        - Manual reindex via API endpoint
        - Bulk reindex for migrations

    Error Handling:
        - Indexing failures are logged but don't block other operations
        - Missing content is handled gracefully (index with metadata only)
    """

    async def index_asset(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> bool:
        """
        Index an asset to OpenSearch after extraction.

        Downloads the extracted markdown content from MinIO and indexes
        it to OpenSearch with metadata for full-text search.

        Args:
            session: Database session
            asset_id: Asset UUID to index

        Returns:
            True if indexed successfully, False otherwise
        """
        if not _is_opensearch_enabled():
            logger.debug("OpenSearch disabled, skipping index")
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
                        # Continue with empty content - still index metadata

            # Build title from filename or URL
            title = asset.original_filename
            url = None
            collection_id = None

            if asset.source_type == "web_scrape":
                source_meta = asset.source_metadata or {}
                url = source_meta.get("url")
                if url:
                    # Prefer page title from metadata, fallback to URL
                    title = source_meta.get("title") or url
                collection_id = source_meta.get("collection_id")
                if collection_id:
                    collection_id = UUID(collection_id)

            # Index to OpenSearch
            success = await opensearch_service.index_document(
                organization_id=asset.organization_id,
                asset_id=asset.id,
                title=title,
                content=content,
                filename=asset.original_filename,
                source_type=asset.source_type,
                content_type=asset.content_type,
                url=url,
                collection_id=collection_id,
                metadata=asset.source_metadata,
                created_at=asset.created_at,
            )

            if success:
                logger.info(f"Indexed asset {asset_id} to OpenSearch")
            else:
                logger.warning(f"Failed to index asset {asset_id}")

            return success

        except Exception as e:
            logger.error(f"Error indexing asset {asset_id}: {e}")
            return False

    async def delete_asset_index(
        self,
        organization_id: UUID,
        asset_id: UUID,
    ) -> bool:
        """
        Remove an asset from the OpenSearch index.

        Args:
            organization_id: Organization UUID
            asset_id: Asset UUID

        Returns:
            True if deleted successfully, False otherwise
        """
        if not _is_opensearch_enabled():
            return True

        return await opensearch_service.delete_document(organization_id, asset_id)

    async def reindex_organization(
        self,
        session: AsyncSession,
        organization_id: UUID,
        batch_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Reindex all assets for an organization.

        Fetches all assets with completed extractions and indexes them
        in batches. Useful for migrations and recovery.

        Args:
            session: Database session
            organization_id: Organization UUID
            batch_size: Number of assets to process per batch

        Returns:
            Dict with reindex statistics
        """
        if not _is_opensearch_enabled():
            return {
                "status": "disabled",
                "message": "OpenSearch is not enabled",
                "total": 0,
                "indexed": 0,
                "failed": 0,
            }

        if batch_size is None:
            opensearch_config = config_loader.get_opensearch_config()
            if opensearch_config:
                batch_size = opensearch_config.batch_size
            else:
                batch_size = settings.opensearch_batch_size

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

        # Process in batches
        for i in range(0, total, batch_size):
            batch = assets[i : i + batch_size]
            batch_docs = []

            for asset in batch:
                try:
                    # Get latest extraction
                    extraction_query = (
                        select(ExtractionResult)
                        .where(ExtractionResult.asset_id == asset.id)
                        .where(ExtractionResult.status == "completed")
                        .order_by(ExtractionResult.created_at.desc())
                        .limit(1)
                    )
                    extraction_result = await session.execute(extraction_query)
                    extraction = extraction_result.scalar_one_or_none()

                    if not extraction:
                        failed += 1
                        continue

                    # Download content
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
                            except Exception as e:
                                logger.warning(
                                    f"Failed to fetch content for {asset.id}: {e}"
                                )

                    # Build document
                    title = asset.original_filename
                    url = None
                    collection_id = None

                    if asset.source_type == "web_scrape":
                        source_meta = asset.source_metadata or {}
                        url = source_meta.get("url")
                        if url:
                            title = source_meta.get("title") or url
                        collection_id = source_meta.get("collection_id")

                    batch_docs.append(
                        {
                            "asset_id": str(asset.id),
                            "title": title,
                            "content": content,
                            "filename": asset.original_filename,
                            "source_type": asset.source_type,
                            "content_type": asset.content_type,
                            "url": url,
                            "collection_id": collection_id,
                            "metadata": asset.source_metadata,
                            "created_at": asset.created_at.isoformat(),
                        }
                    )

                except Exception as e:
                    logger.error(f"Error preparing asset {asset.id}: {e}")
                    failed += 1
                    errors.append(f"Asset {asset.id}: {str(e)}")

            # Bulk index batch
            if batch_docs:
                bulk_result = await opensearch_service.bulk_index(
                    organization_id=organization_id,
                    documents=batch_docs,
                )
                indexed += bulk_result["success"]
                failed += bulk_result["failed"]
                errors.extend(bulk_result.get("errors", []))

            logger.debug(
                f"Processed batch {i // batch_size + 1}: "
                f"{indexed} indexed, {failed} failed"
            )

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
        organization_id: UUID,
    ) -> Dict[str, Any]:
        """
        Get health status of the search index for an organization.

        Args:
            organization_id: Organization UUID

        Returns:
            Dict with index health information
        """
        if not _is_opensearch_enabled():
            return {
                "enabled": False,
                "status": "disabled",
                "message": "OpenSearch is not enabled",
            }

        # Check OpenSearch connectivity
        is_healthy = await opensearch_service.health_check()

        if not is_healthy:
            return {
                "enabled": True,
                "status": "unavailable",
                "message": "OpenSearch is not reachable",
            }

        # Get index stats
        stats = await opensearch_service.get_index_stats(organization_id)

        if not stats:
            return {
                "enabled": True,
                "status": "error",
                "message": "Failed to get index stats",
            }

        return {
            "enabled": True,
            "status": stats.status,
            "index_name": stats.index_name,
            "document_count": stats.document_count,
            "size_bytes": stats.size_bytes,
        }


# Global service instance
index_service = IndexService()
