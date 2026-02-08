"""
Asset Metadata Service.

Provides CRUD operations for the AssetMetadata model. Uses a simple upsert
pattern -- metadata is canonical by default (is_canonical=True). When creating
canonical metadata of the same type for an asset, the existing record is
updated in place.

Usage:
    from app.core.shared.asset_metadata_service import asset_metadata_service

    metadata = await asset_metadata_service.create_metadata(
        session=session,
        asset_id=asset_id,
        metadata_type="summary.short.v1",
        metadata_content={"summary": "Document describes..."},
        producer_run_id=run_id,
    )

    canonical = await asset_metadata_service.get_canonical_metadata(
        session=session,
        asset_id=asset_id,
    )
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import UUID

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database.models import AssetMetadata, Asset

logger = logging.getLogger("curatore.asset_metadata_service")


class AssetMetadataService:
    """
    Service for managing AssetMetadata records.

    Uses a simple upsert pattern: metadata defaults to is_canonical=True.
    When creating canonical metadata of the same type, the existing record
    is updated in place rather than creating a new one.
    """

    # =========================================================================
    # CREATE / UPSERT OPERATIONS
    # =========================================================================

    async def create_metadata(
        self,
        session: AsyncSession,
        asset_id: UUID,
        metadata_type: str,
        metadata_content: Dict[str, Any],
        producer_run_id: Optional[UUID] = None,
        is_canonical: bool = True,
        schema_version: str = "1.0",
        metadata_object_ref: Optional[str] = None,
    ) -> AssetMetadata:
        """
        Create or update metadata for an asset.

        If is_canonical=True and canonical metadata of the same type already
        exists, the existing record is updated in place (upsert).

        Args:
            session: Database session
            asset_id: Asset UUID
            metadata_type: Type of metadata (e.g., "topics.v1", "summary.short.v1")
            metadata_content: The actual metadata payload (dict)
            producer_run_id: Run UUID that produced this metadata
            is_canonical: Whether this is canonical metadata (default True)
            schema_version: Schema version for this metadata type
            metadata_object_ref: Optional object store reference for large payloads

        Returns:
            Created or updated AssetMetadata instance

        Raises:
            ValueError: If asset not found
        """
        asset = await session.execute(
            select(Asset).where(Asset.id == asset_id)
        )
        if not asset.scalar_one_or_none():
            raise ValueError(f"Asset {asset_id} not found")

        # Upsert: if canonical and one already exists for this type, update it
        if is_canonical:
            existing = await self.get_canonical_metadata_by_type(
                session, asset_id, metadata_type
            )
            if existing:
                existing.metadata_content = metadata_content
                existing.schema_version = schema_version
                existing.producer_run_id = producer_run_id
                existing.metadata_object_ref = metadata_object_ref
                existing.updated_at = datetime.utcnow()

                await session.commit()
                await session.refresh(existing)

                logger.info(
                    f"Updated canonical metadata {existing.id} for asset "
                    f"{asset_id} (type: {metadata_type})"
                )
                return existing

        metadata = AssetMetadata(
            asset_id=asset_id,
            metadata_type=metadata_type,
            schema_version=schema_version,
            producer_run_id=producer_run_id,
            is_canonical=is_canonical,
            metadata_content=metadata_content,
            metadata_object_ref=metadata_object_ref,
        )

        session.add(metadata)
        await session.commit()
        await session.refresh(metadata)

        logger.info(
            f"Created metadata {metadata.id} for asset {asset_id} "
            f"(type: {metadata_type}, canonical: {is_canonical})"
        )

        return metadata

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    async def get_metadata(
        self,
        session: AsyncSession,
        metadata_id: UUID,
    ) -> Optional[AssetMetadata]:
        """Get metadata by ID."""
        result = await session.execute(
            select(AssetMetadata).where(AssetMetadata.id == metadata_id)
        )
        return result.scalar_one_or_none()

    async def get_metadata_by_asset(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> List[AssetMetadata]:
        """
        Get all metadata for an asset.

        Returns canonical metadata first, then by creation date descending.
        """
        query = (
            select(AssetMetadata)
            .where(AssetMetadata.asset_id == asset_id)
            .order_by(
                AssetMetadata.is_canonical.desc(),
                AssetMetadata.created_at.desc(),
            )
        )

        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_canonical_metadata(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> List[AssetMetadata]:
        """Get all canonical metadata for an asset (one per type)."""
        result = await session.execute(
            select(AssetMetadata)
            .where(
                and_(
                    AssetMetadata.asset_id == asset_id,
                    AssetMetadata.is_canonical == True,
                )
            )
            .order_by(AssetMetadata.metadata_type)
        )
        return list(result.scalars().all())

    async def get_canonical_metadata_by_type(
        self,
        session: AsyncSession,
        asset_id: UUID,
        metadata_type: str,
    ) -> Optional[AssetMetadata]:
        """Get the canonical metadata for a specific type."""
        result = await session.execute(
            select(AssetMetadata)
            .where(
                and_(
                    AssetMetadata.asset_id == asset_id,
                    AssetMetadata.metadata_type == metadata_type,
                    AssetMetadata.is_canonical == True,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_metadata_by_run(
        self,
        session: AsyncSession,
        run_id: UUID,
    ) -> List[AssetMetadata]:
        """Get all metadata produced by a specific run."""
        result = await session.execute(
            select(AssetMetadata)
            .where(AssetMetadata.producer_run_id == run_id)
            .order_by(AssetMetadata.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_metadata_by_type(
        self,
        session: AsyncSession,
        asset_id: UUID,
        metadata_type: str,
    ) -> List[AssetMetadata]:
        """
        Get all metadata of a specific type for an asset.

        Returns canonical first, then by creation date descending.
        """
        query = (
            select(AssetMetadata)
            .where(
                and_(
                    AssetMetadata.asset_id == asset_id,
                    AssetMetadata.metadata_type == metadata_type,
                )
            )
            .order_by(
                AssetMetadata.is_canonical.desc(),
                AssetMetadata.created_at.desc(),
            )
        )

        result = await session.execute(query)
        return list(result.scalars().all())

    async def count_metadata_by_asset(
        self,
        session: AsyncSession,
        asset_id: UUID,
        is_canonical: Optional[bool] = None,
    ) -> int:
        """Count metadata records for an asset."""
        query = select(func.count(AssetMetadata.id)).where(
            AssetMetadata.asset_id == asset_id
        )

        if is_canonical is not None:
            query = query.where(AssetMetadata.is_canonical == is_canonical)

        result = await session.execute(query)
        return result.scalar_one()

    # =========================================================================
    # UPDATE OPERATIONS
    # =========================================================================

    async def update_metadata_content(
        self,
        session: AsyncSession,
        metadata_id: UUID,
        metadata_content: Dict[str, Any],
    ) -> Optional[AssetMetadata]:
        """Update the content of a metadata record."""
        metadata = await self.get_metadata(session, metadata_id)
        if not metadata:
            return None

        metadata.metadata_content = metadata_content
        metadata.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(metadata)

        logger.info(f"Updated metadata content for {metadata_id}")

        return metadata

    # =========================================================================
    # DELETE OPERATIONS
    # =========================================================================

    async def delete_metadata(
        self,
        session: AsyncSession,
        metadata_id: UUID,
    ) -> bool:
        """
        Delete a metadata record.

        Returns:
            True if deleted, False if not found
        """
        metadata = await self.get_metadata(session, metadata_id)
        if not metadata:
            return False

        await session.delete(metadata)
        await session.commit()

        logger.info(f"Deleted metadata {metadata_id}")

        return True

    # =========================================================================
    # UTILITY OPERATIONS
    # =========================================================================

    async def get_metadata_types_for_asset(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> List[str]:
        """Get distinct metadata types available for an asset."""
        result = await session.execute(
            select(AssetMetadata.metadata_type)
            .where(AssetMetadata.asset_id == asset_id)
            .distinct()
            .order_by(AssetMetadata.metadata_type)
        )
        return [row[0] for row in result.all()]

    async def has_canonical_metadata(
        self,
        session: AsyncSession,
        asset_id: UUID,
        metadata_type: Optional[str] = None,
    ) -> bool:
        """Check if an asset has any canonical metadata."""
        query = select(func.count(AssetMetadata.id)).where(
            and_(
                AssetMetadata.asset_id == asset_id,
                AssetMetadata.is_canonical == True,
            )
        )

        if metadata_type:
            query = query.where(AssetMetadata.metadata_type == metadata_type)

        result = await session.execute(query)
        return result.scalar_one() > 0


# Singleton instance
asset_metadata_service = AssetMetadataService()
