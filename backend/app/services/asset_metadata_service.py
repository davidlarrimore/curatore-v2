"""
Asset Metadata Service for Flexible Metadata Management.

Provides CRUD operations and promotion mechanics for the AssetMetadata model,
enabling LLM-driven metadata iteration without schema churn. This is the core
service for Phase 3: Flexible Metadata & Experimentation.

Key Features:
- Create canonical or experimental metadata
- Promote experimental metadata to canonical
- Query canonical vs experimental metadata
- Support for multiple metadata types per asset
- Run attribution for all metadata-producing activity

Usage:
    from app.services.asset_metadata_service import asset_metadata_service

    # Create experimental metadata from a run
    metadata = await asset_metadata_service.create_metadata(
        session=session,
        asset_id=asset_id,
        metadata_type="summary.short.v1",
        metadata_content={"summary": "Document describes..."},
        producer_run_id=run_id,
        is_canonical=False,
    )

    # Promote to canonical
    promoted = await asset_metadata_service.promote_to_canonical(
        session=session,
        metadata_id=metadata.id,
    )

    # Get all canonical metadata for an asset
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

from ..database.models import AssetMetadata, Asset, Run

logger = logging.getLogger("curatore.asset_metadata_service")


class AssetMetadataService:
    """
    Service for managing AssetMetadata records in the database.

    Handles CRUD operations, promotion/demotion mechanics, and queries
    for canonical vs experimental metadata in Curatore's Phase 3 architecture.
    """

    # =========================================================================
    # CREATE OPERATIONS
    # =========================================================================

    async def create_metadata(
        self,
        session: AsyncSession,
        asset_id: UUID,
        metadata_type: str,
        metadata_content: Dict[str, Any],
        producer_run_id: Optional[UUID] = None,
        is_canonical: bool = False,
        schema_version: str = "1.0",
        metadata_object_ref: Optional[str] = None,
    ) -> AssetMetadata:
        """
        Create a new metadata record for an asset.

        If is_canonical=True and another canonical metadata of the same type
        exists, the old canonical is automatically superseded.

        Args:
            session: Database session
            asset_id: Asset UUID
            metadata_type: Type of metadata (e.g., "topics.v1", "summary.short.v1")
            metadata_content: The actual metadata payload (dict)
            producer_run_id: Run UUID that produced this metadata (for attribution)
            is_canonical: Whether this is canonical (production) metadata
            schema_version: Schema version for this metadata type
            metadata_object_ref: Optional object store reference for large payloads

        Returns:
            Created AssetMetadata instance

        Raises:
            ValueError: If asset not found
        """
        # Verify asset exists
        asset = await session.execute(
            select(Asset).where(Asset.id == asset_id)
        )
        if not asset.scalar_one_or_none():
            raise ValueError(f"Asset {asset_id} not found")

        # If creating canonical, supersede any existing canonical of same type
        if is_canonical:
            existing_canonical = await self.get_canonical_metadata_by_type(
                session, asset_id, metadata_type
            )
            if existing_canonical:
                # Supersede the old canonical
                existing_canonical.status = "superseded"
                existing_canonical.superseded_at = datetime.utcnow()

        # Create new metadata record
        metadata = AssetMetadata(
            asset_id=asset_id,
            metadata_type=metadata_type,
            schema_version=schema_version,
            producer_run_id=producer_run_id,
            is_canonical=is_canonical,
            status="active",
            metadata_content=metadata_content,
            metadata_object_ref=metadata_object_ref,
            promoted_at=datetime.utcnow() if is_canonical else None,
        )

        session.add(metadata)

        # If superseding, update the pointer
        if is_canonical and existing_canonical:
            await session.flush()
            existing_canonical.superseded_by_id = metadata.id

        await session.commit()
        await session.refresh(metadata)

        logger.info(
            f"Created {'canonical' if is_canonical else 'experimental'} metadata "
            f"{metadata.id} for asset {asset_id} (type: {metadata_type})"
        )

        return metadata

    async def create_experimental_from_run(
        self,
        session: AsyncSession,
        asset_id: UUID,
        run_id: UUID,
        metadata_type: str,
        metadata_content: Dict[str, Any],
        schema_version: str = "1.0",
    ) -> AssetMetadata:
        """
        Convenience method to create experimental metadata from a run.

        Args:
            session: Database session
            asset_id: Asset UUID
            run_id: Run UUID that produced this metadata
            metadata_type: Type of metadata
            metadata_content: The metadata payload

        Returns:
            Created AssetMetadata instance
        """
        return await self.create_metadata(
            session=session,
            asset_id=asset_id,
            metadata_type=metadata_type,
            metadata_content=metadata_content,
            producer_run_id=run_id,
            is_canonical=False,
            schema_version=schema_version,
        )

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    async def get_metadata(
        self,
        session: AsyncSession,
        metadata_id: UUID,
    ) -> Optional[AssetMetadata]:
        """
        Get metadata by ID.

        Args:
            session: Database session
            metadata_id: Metadata UUID

        Returns:
            AssetMetadata instance or None
        """
        result = await session.execute(
            select(AssetMetadata).where(AssetMetadata.id == metadata_id)
        )
        return result.scalar_one_or_none()

    async def get_metadata_by_asset(
        self,
        session: AsyncSession,
        asset_id: UUID,
        include_superseded: bool = False,
    ) -> List[AssetMetadata]:
        """
        Get all metadata for an asset.

        Args:
            session: Database session
            asset_id: Asset UUID
            include_superseded: Whether to include superseded metadata

        Returns:
            List of AssetMetadata instances
        """
        query = select(AssetMetadata).where(AssetMetadata.asset_id == asset_id)

        if not include_superseded:
            query = query.where(AssetMetadata.status == "active")

        query = query.order_by(
            AssetMetadata.is_canonical.desc(),  # Canonical first
            AssetMetadata.created_at.desc(),
        )

        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_canonical_metadata(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> List[AssetMetadata]:
        """
        Get all canonical (production) metadata for an asset.

        Args:
            session: Database session
            asset_id: Asset UUID

        Returns:
            List of canonical AssetMetadata instances (one per type)
        """
        result = await session.execute(
            select(AssetMetadata)
            .where(
                and_(
                    AssetMetadata.asset_id == asset_id,
                    AssetMetadata.is_canonical == True,
                    AssetMetadata.status == "active",
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
        """
        Get the canonical metadata for a specific type.

        Args:
            session: Database session
            asset_id: Asset UUID
            metadata_type: Metadata type to retrieve

        Returns:
            AssetMetadata instance or None
        """
        result = await session.execute(
            select(AssetMetadata)
            .where(
                and_(
                    AssetMetadata.asset_id == asset_id,
                    AssetMetadata.metadata_type == metadata_type,
                    AssetMetadata.is_canonical == True,
                    AssetMetadata.status == "active",
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_experimental_metadata(
        self,
        session: AsyncSession,
        asset_id: UUID,
        metadata_type: Optional[str] = None,
    ) -> List[AssetMetadata]:
        """
        Get experimental (non-canonical) metadata for an asset.

        Args:
            session: Database session
            asset_id: Asset UUID
            metadata_type: Optional filter by metadata type

        Returns:
            List of experimental AssetMetadata instances
        """
        query = select(AssetMetadata).where(
            and_(
                AssetMetadata.asset_id == asset_id,
                AssetMetadata.is_canonical == False,
                AssetMetadata.status == "active",
            )
        )

        if metadata_type:
            query = query.where(AssetMetadata.metadata_type == metadata_type)

        query = query.order_by(AssetMetadata.created_at.desc())

        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_metadata_by_run(
        self,
        session: AsyncSession,
        run_id: UUID,
    ) -> List[AssetMetadata]:
        """
        Get all metadata produced by a specific run.

        Args:
            session: Database session
            run_id: Run UUID

        Returns:
            List of AssetMetadata instances
        """
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
        include_superseded: bool = False,
    ) -> List[AssetMetadata]:
        """
        Get all metadata of a specific type for an asset.

        Useful for comparing different versions/variants of the same metadata type.

        Args:
            session: Database session
            asset_id: Asset UUID
            metadata_type: Metadata type to retrieve
            include_superseded: Whether to include superseded metadata

        Returns:
            List of AssetMetadata instances (canonical first, then by date)
        """
        query = select(AssetMetadata).where(
            and_(
                AssetMetadata.asset_id == asset_id,
                AssetMetadata.metadata_type == metadata_type,
            )
        )

        if not include_superseded:
            query = query.where(AssetMetadata.status == "active")

        query = query.order_by(
            AssetMetadata.is_canonical.desc(),
            AssetMetadata.created_at.desc(),
        )

        result = await session.execute(query)
        return list(result.scalars().all())

    async def count_metadata_by_asset(
        self,
        session: AsyncSession,
        asset_id: UUID,
        is_canonical: Optional[bool] = None,
    ) -> int:
        """
        Count metadata records for an asset.

        Args:
            session: Database session
            asset_id: Asset UUID
            is_canonical: Optional filter by canonical status

        Returns:
            Count of metadata records
        """
        query = select(func.count(AssetMetadata.id)).where(
            and_(
                AssetMetadata.asset_id == asset_id,
                AssetMetadata.status == "active",
            )
        )

        if is_canonical is not None:
            query = query.where(AssetMetadata.is_canonical == is_canonical)

        result = await session.execute(query)
        return result.scalar_one()

    # =========================================================================
    # PROMOTION OPERATIONS
    # =========================================================================

    async def promote_to_canonical(
        self,
        session: AsyncSession,
        metadata_id: UUID,
    ) -> AssetMetadata:
        """
        Promote experimental metadata to canonical status.

        This is a pointer update operation - no recomputation is performed.
        If canonical metadata of the same type already exists, it is superseded.

        Args:
            session: Database session
            metadata_id: Metadata UUID to promote

        Returns:
            Promoted AssetMetadata instance

        Raises:
            ValueError: If metadata not found or already canonical
        """
        # Get the metadata to promote
        metadata = await self.get_metadata(session, metadata_id)
        if not metadata:
            raise ValueError(f"Metadata {metadata_id} not found")

        if metadata.is_canonical:
            raise ValueError(f"Metadata {metadata_id} is already canonical")

        if metadata.status != "active":
            raise ValueError(f"Cannot promote metadata with status '{metadata.status}'")

        # Find and supersede existing canonical of same type
        existing_canonical = await self.get_canonical_metadata_by_type(
            session, metadata.asset_id, metadata.metadata_type
        )

        if existing_canonical:
            existing_canonical.status = "superseded"
            existing_canonical.superseded_at = datetime.utcnow()
            existing_canonical.superseded_by_id = metadata_id

        # Promote the metadata
        metadata.is_canonical = True
        metadata.promoted_at = datetime.utcnow()
        metadata.promoted_from_id = metadata.id  # Self-reference for tracking

        await session.commit()
        await session.refresh(metadata)

        logger.info(
            f"Promoted metadata {metadata_id} to canonical for asset {metadata.asset_id} "
            f"(type: {metadata.metadata_type})"
        )

        return metadata

    async def demote_to_experimental(
        self,
        session: AsyncSession,
        metadata_id: UUID,
    ) -> AssetMetadata:
        """
        Demote canonical metadata back to experimental.

        Useful when canonical metadata needs to be reconsidered.
        Does not restore previously superseded metadata.

        Args:
            session: Database session
            metadata_id: Metadata UUID to demote

        Returns:
            Demoted AssetMetadata instance

        Raises:
            ValueError: If metadata not found or not canonical
        """
        metadata = await self.get_metadata(session, metadata_id)
        if not metadata:
            raise ValueError(f"Metadata {metadata_id} not found")

        if not metadata.is_canonical:
            raise ValueError(f"Metadata {metadata_id} is not canonical")

        metadata.is_canonical = False

        await session.commit()
        await session.refresh(metadata)

        logger.info(
            f"Demoted metadata {metadata_id} to experimental for asset {metadata.asset_id}"
        )

        return metadata

    # =========================================================================
    # UPDATE OPERATIONS
    # =========================================================================

    async def update_metadata_content(
        self,
        session: AsyncSession,
        metadata_id: UUID,
        metadata_content: Dict[str, Any],
    ) -> Optional[AssetMetadata]:
        """
        Update the content of a metadata record.

        Note: For canonical metadata, consider creating a new version instead
        to preserve history.

        Args:
            session: Database session
            metadata_id: Metadata UUID
            metadata_content: New metadata content

        Returns:
            Updated AssetMetadata instance or None if not found
        """
        metadata = await self.get_metadata(session, metadata_id)
        if not metadata:
            return None

        metadata.metadata_content = metadata_content

        await session.commit()
        await session.refresh(metadata)

        logger.info(f"Updated metadata content for {metadata_id}")

        return metadata

    async def deprecate_metadata(
        self,
        session: AsyncSession,
        metadata_id: UUID,
    ) -> Optional[AssetMetadata]:
        """
        Mark metadata as deprecated (manually invalidated).

        Deprecated metadata remains in the system but is excluded from
        normal queries.

        Args:
            session: Database session
            metadata_id: Metadata UUID

        Returns:
            Deprecated AssetMetadata instance or None if not found
        """
        metadata = await self.get_metadata(session, metadata_id)
        if not metadata:
            return None

        if metadata.is_canonical:
            # Demote first to remove canonical status
            metadata.is_canonical = False

        metadata.status = "deprecated"

        await session.commit()
        await session.refresh(metadata)

        logger.info(f"Deprecated metadata {metadata_id}")

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
        Hard delete a metadata record.

        Note: Prefer deprecate_metadata for soft deletion with history preservation.

        Args:
            session: Database session
            metadata_id: Metadata UUID

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
        """
        Get distinct metadata types available for an asset.

        Args:
            session: Database session
            asset_id: Asset UUID

        Returns:
            List of metadata type strings
        """
        result = await session.execute(
            select(AssetMetadata.metadata_type)
            .where(
                and_(
                    AssetMetadata.asset_id == asset_id,
                    AssetMetadata.status == "active",
                )
            )
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
        """
        Check if an asset has any canonical metadata.

        Args:
            session: Database session
            asset_id: Asset UUID
            metadata_type: Optional specific type to check

        Returns:
            True if canonical metadata exists
        """
        query = select(func.count(AssetMetadata.id)).where(
            and_(
                AssetMetadata.asset_id == asset_id,
                AssetMetadata.is_canonical == True,
                AssetMetadata.status == "active",
            )
        )

        if metadata_type:
            query = query.where(AssetMetadata.metadata_type == metadata_type)

        result = await session.execute(query)
        return result.scalar_one() > 0


# Singleton instance
asset_metadata_service = AssetMetadataService()
