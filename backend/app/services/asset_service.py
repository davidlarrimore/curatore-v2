"""
Asset Service for Asset Lifecycle Management.

Provides CRUD operations for the Asset model, which represents documents
with full provenance tracking. Assets are the canonical document representation
in Curatore's Phase 0 architecture.

Usage:
    from app.services.asset_service import asset_service

    # Create asset from upload
    asset = await asset_service.create_asset(
        session=session,
        organization_id=org_id,
        source_type="upload",
        source_metadata={"uploader": "user@example.com"},
        original_filename="document.pdf",
        raw_bucket="curatore-uploads",
        raw_object_key="org/asset/raw/file.pdf",
    )

    # Get asset with latest extraction
    asset_with_extraction = await asset_service.get_asset_with_latest_extraction(
        session=session,
        asset_id=asset_id,
    )
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from uuid import UUID

from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database.models import Asset, AssetVersion, ExtractionResult, Run
from ..config import settings

logger = logging.getLogger("curatore.asset_service")


class AssetService:
    """
    Service for managing Asset records in the database.

    Handles CRUD operations, provenance tracking, and status management
    for assets (documents) in Curatore's asset-centric architecture.
    """

    # =========================================================================
    # CREATE OPERATIONS
    # =========================================================================

    async def create_asset(
        self,
        session: AsyncSession,
        organization_id: UUID,
        source_type: str,
        source_metadata: Dict[str, Any],
        original_filename: str,
        raw_bucket: str,
        raw_object_key: str,
        content_type: Optional[str] = None,
        file_size: Optional[int] = None,
        file_hash: Optional[str] = None,
        status: str = "pending",
        created_by: Optional[UUID] = None,
        auto_extract: bool = True,
    ) -> Asset:
        """
        Create a new asset record with initial version (Phase 1).

        Creates both an Asset and an AssetVersion record. The AssetVersion
        tracks the immutable raw content, enabling version history and
        non-destructive updates.

        Args:
            session: Database session
            organization_id: Organization UUID
            source_type: Source type (upload, sharepoint, web_scrape, sam_gov)
            source_metadata: Source-specific metadata dict (URL, timestamp, etc.)
            original_filename: Original filename
            raw_bucket: Object storage bucket for raw content
            raw_object_key: Object storage key for raw content
            content_type: MIME type
            file_size: Size in bytes
            file_hash: SHA-256 hash for deduplication
            status: Initial status (default: pending)
            created_by: User UUID who created the asset
            auto_extract: Automatically queue extraction (default: True)

        Returns:
            Created Asset instance (with initial version created)
        """
        # Create Asset record
        asset = Asset(
            organization_id=organization_id,
            source_type=source_type,
            source_metadata=source_metadata or {},
            original_filename=original_filename,
            content_type=content_type,
            file_size=file_size,
            file_hash=file_hash,
            raw_bucket=raw_bucket,
            raw_object_key=raw_object_key,
            status=status,
            created_by=created_by,
            current_version_number=1,  # Phase 1: Initialize version tracking
        )

        session.add(asset)
        await session.flush()  # Flush to get asset.id for version

        # Create initial AssetVersion (Phase 1)
        version = AssetVersion(
            asset_id=asset.id,
            version_number=1,
            raw_bucket=raw_bucket,
            raw_object_key=raw_object_key,
            file_size=file_size,
            file_hash=file_hash,
            content_type=content_type,
            is_current=True,
            created_by=created_by,
        )

        session.add(version)
        await session.commit()
        await session.refresh(asset)

        logger.info(
            f"Created asset {asset.id} with version 1 (org: {organization_id}, "
            f"source: {source_type}, file: {original_filename})"
        )

        # Auto-queue extraction if requested and asset needs it
        if auto_extract and status == "pending":
            try:
                from .extraction_queue_service import extraction_queue_service
                run, extraction, extract_status = await extraction_queue_service.queue_extraction_for_asset(
                    session=session,
                    asset_id=asset.id,
                    user_id=created_by,
                )
                if extract_status == "queued":
                    logger.debug(f"Auto-queued extraction for asset {asset.id}")
                elif extract_status == "skipped_content_type":
                    logger.debug(f"Skipped extraction for asset {asset.id} (content type)")
                elif extract_status == "already_pending":
                    logger.debug(f"Extraction already pending for asset {asset.id}")
            except Exception as e:
                # Log but don't fail asset creation - safety net will catch it
                logger.warning(f"Failed to auto-queue extraction for asset {asset.id}: {e}")

        return asset

    async def create_asset_version(
        self,
        session: AsyncSession,
        asset_id: UUID,
        raw_bucket: str,
        raw_object_key: str,
        file_size: Optional[int] = None,
        file_hash: Optional[str] = None,
        content_type: Optional[str] = None,
        created_by: Optional[UUID] = None,
        trigger_extraction: bool = True,
    ) -> AssetVersion:
        """
        Create a new version for an existing asset (Phase 1).

        Used when a user re-uploads a document or content changes. Creates
        a new immutable AssetVersion and updates the Asset's current version.
        Old versions remain accessible for history.

        Optionally triggers automatic extraction of the new version (default: True).

        Args:
            session: Database session
            asset_id: Existing Asset UUID
            raw_bucket: Object storage bucket for new version's raw content
            raw_object_key: Object storage key for new version's raw content
            file_size: File size in bytes
            file_hash: SHA-256 hash
            content_type: MIME type
            created_by: User UUID who created this version
            trigger_extraction: Whether to automatically trigger extraction (default: True)

        Returns:
            Created AssetVersion instance

        Raises:
            ValueError: If asset not found
        """
        # Get existing asset
        asset = await self.get_asset(session, asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")

        # Calculate next version number
        next_version = (asset.current_version_number or 0) + 1

        # Mark all existing versions as not current
        await session.execute(
            select(AssetVersion)
            .where(AssetVersion.asset_id == asset_id)
        )
        # Update via query for efficiency
        result = await session.execute(
            select(AssetVersion).where(
                and_(
                    AssetVersion.asset_id == asset_id,
                    AssetVersion.is_current == True
                )
            )
        )
        current_versions = result.scalars().all()
        for v in current_versions:
            v.is_current = False

        # Create new version
        version = AssetVersion(
            asset_id=asset_id,
            version_number=next_version,
            raw_bucket=raw_bucket,
            raw_object_key=raw_object_key,
            file_size=file_size,
            file_hash=file_hash,
            content_type=content_type,
            is_current=True,
            created_by=created_by,
        )

        session.add(version)

        # Update asset's current version number and metadata
        asset.current_version_number = next_version
        asset.file_size = file_size
        asset.file_hash = file_hash
        asset.content_type = content_type
        asset.raw_bucket = raw_bucket
        asset.raw_object_key = raw_object_key
        asset.updated_at = datetime.utcnow()
        asset.status = "pending"  # Reset to pending for re-extraction

        await session.commit()
        await session.refresh(version)

        logger.info(
            f"Created version {next_version} for asset {asset_id} "
            f"(file: {asset.original_filename}, trigger_extraction={trigger_extraction})"
        )

        # Auto-queue extraction if requested
        if trigger_extraction:
            try:
                from .extraction_queue_service import extraction_queue_service
                run, extraction, extract_status = await extraction_queue_service.queue_extraction_for_asset(
                    session=session,
                    asset_id=asset_id,
                    user_id=created_by,
                )
                if extract_status == "queued":
                    logger.debug(f"Auto-queued extraction for asset {asset_id} version {next_version}")
                elif extract_status == "skipped_content_type":
                    logger.debug(f"Skipped extraction for asset {asset_id} (content type)")
            except Exception as e:
                # Log but don't fail version creation - safety net will catch it
                logger.warning(f"Failed to auto-queue extraction for asset {asset_id}: {e}")

        return version

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    async def get_asset(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> Optional[Asset]:
        """
        Get asset by ID.

        Args:
            session: Database session
            asset_id: Asset UUID

        Returns:
            Asset instance or None
        """
        result = await session.execute(
            select(Asset).where(Asset.id == asset_id)
        )
        return result.scalar_one_or_none()

    async def get_asset_with_latest_extraction(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> Optional[Tuple[Asset, Optional[ExtractionResult]]]:
        """
        Get asset with its latest extraction result.

        Args:
            session: Database session
            asset_id: Asset UUID

        Returns:
            Tuple of (Asset, ExtractionResult) or None if asset not found
            ExtractionResult may be None if no extraction exists
        """
        # Get asset
        asset = await self.get_asset(session, asset_id)
        if not asset:
            return None

        # Get latest extraction result
        extraction_result = await session.execute(
            select(ExtractionResult)
            .where(ExtractionResult.asset_id == asset_id)
            .order_by(ExtractionResult.created_at.desc())
            .limit(1)
        )
        extraction = extraction_result.scalar_one_or_none()

        return (asset, extraction)

    async def get_assets_by_organization(
        self,
        session: AsyncSession,
        organization_id: UUID,
        source_type: Optional[str] = None,
        status: Optional[str] = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Asset]:
        """
        Get assets for an organization with optional filters.

        Args:
            session: Database session
            organization_id: Organization UUID
            source_type: Filter by source type (upload, sharepoint, etc.)
            status: Filter by status (pending, ready, failed, deleted)
            include_deleted: If False (default), exclude assets with status='deleted'
            limit: Maximum results to return
            offset: Number of results to skip

        Returns:
            List of Asset instances
        """
        query = select(Asset).where(Asset.organization_id == organization_id)

        if source_type:
            query = query.where(Asset.source_type == source_type)

        if status:
            # If explicit status filter, use it
            query = query.where(Asset.status == status)
        elif not include_deleted:
            # Exclude deleted assets by default unless explicitly requested
            query = query.where(Asset.status != "deleted")

        query = query.order_by(Asset.created_at.desc()).limit(limit).offset(offset)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_asset_by_hash(
        self,
        session: AsyncSession,
        organization_id: UUID,
        file_hash: str,
    ) -> Optional[Asset]:
        """
        Find existing asset by file hash (for deduplication).

        Args:
            session: Database session
            organization_id: Organization UUID
            file_hash: SHA-256 file hash

        Returns:
            Existing Asset instance or None
        """
        result = await session.execute(
            select(Asset)
            .where(
                and_(
                    Asset.organization_id == organization_id,
                    Asset.file_hash == file_hash,
                    Asset.status != "deleted",
                )
            )
            .order_by(Asset.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_asset_by_object_key(
        self,
        session: AsyncSession,
        raw_bucket: str,
        raw_object_key: str,
    ) -> Optional[Asset]:
        """
        Find existing asset by storage path (bucket + object key).

        Used to check for path collisions when using human-readable paths.

        Args:
            session: Database session
            raw_bucket: Object storage bucket
            raw_object_key: Object storage key

        Returns:
            Existing Asset instance or None
        """
        result = await session.execute(
            select(Asset)
            .where(
                and_(
                    Asset.raw_bucket == raw_bucket,
                    Asset.raw_object_key == raw_object_key,
                    Asset.status != "deleted",
                )
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_assets_by_organization(
        self,
        session: AsyncSession,
        organization_id: UUID,
        source_type: Optional[str] = None,
        status: Optional[str] = None,
        include_deleted: bool = False,
    ) -> int:
        """
        Count assets for an organization with optional filters.

        Args:
            session: Database session
            organization_id: Organization UUID
            source_type: Filter by source type
            status: Filter by status
            include_deleted: If False (default), exclude assets with status='deleted'

        Returns:
            Count of matching assets
        """
        query = select(func.count(Asset.id)).where(
            Asset.organization_id == organization_id
        )

        if source_type:
            query = query.where(Asset.source_type == source_type)

        if status:
            query = query.where(Asset.status == status)
        elif not include_deleted:
            # Exclude deleted assets by default
            query = query.where(Asset.status != "deleted")

        result = await session.execute(query)
        return result.scalar_one()

    async def get_asset_versions(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> List[AssetVersion]:
        """
        Get all versions for an asset, ordered by version number (Phase 1).

        Args:
            session: Database session
            asset_id: Asset UUID

        Returns:
            List of AssetVersion instances, newest first
        """
        result = await session.execute(
            select(AssetVersion)
            .where(AssetVersion.asset_id == asset_id)
            .order_by(AssetVersion.version_number.desc())
        )
        return list(result.scalars().all())

    async def get_asset_version(
        self,
        session: AsyncSession,
        asset_id: UUID,
        version_number: int,
    ) -> Optional[AssetVersion]:
        """
        Get a specific version of an asset (Phase 1).

        Args:
            session: Database session
            asset_id: Asset UUID
            version_number: Version number to retrieve

        Returns:
            AssetVersion instance or None if not found
        """
        result = await session.execute(
            select(AssetVersion).where(
                and_(
                    AssetVersion.asset_id == asset_id,
                    AssetVersion.version_number == version_number
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_current_asset_version(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> Optional[AssetVersion]:
        """
        Get the current version of an asset (Phase 1).

        Args:
            session: Database session
            asset_id: Asset UUID

        Returns:
            AssetVersion instance marked as current, or None if not found
        """
        result = await session.execute(
            select(AssetVersion).where(
                and_(
                    AssetVersion.asset_id == asset_id,
                    AssetVersion.is_current == True
                )
            )
        )
        return result.scalar_one_or_none()

    # =========================================================================
    # UPDATE OPERATIONS
    # =========================================================================

    async def update_asset_status(
        self,
        session: AsyncSession,
        asset_id: UUID,
        status: str,
    ) -> Optional[Asset]:
        """
        Update asset status.

        Status transitions:
        - pending → ready (extraction successful)
        - pending → failed (extraction failed)
        - ready → deleted (soft delete)

        Args:
            session: Database session
            asset_id: Asset UUID
            status: New status (pending, ready, failed, deleted)

        Returns:
            Updated Asset instance or None if not found
        """
        asset = await self.get_asset(session, asset_id)
        if not asset:
            return None

        old_status = asset.status
        asset.status = status
        asset.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(asset)

        logger.info(
            f"Updated asset {asset_id} status: {old_status} → {status}"
        )

        return asset

    async def update_asset_metadata(
        self,
        session: AsyncSession,
        asset_id: UUID,
        source_metadata: Dict[str, Any],
    ) -> Optional[Asset]:
        """
        Update asset source metadata (merge with existing).

        Args:
            session: Database session
            asset_id: Asset UUID
            source_metadata: Metadata to merge

        Returns:
            Updated Asset instance or None if not found
        """
        asset = await self.get_asset(session, asset_id)
        if not asset:
            return None

        # Merge metadata
        asset.source_metadata = {**asset.source_metadata, **source_metadata}
        asset.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(asset)

        logger.info(f"Updated asset {asset_id} metadata")

        return asset

    # =========================================================================
    # DELETE OPERATIONS
    # =========================================================================

    async def soft_delete_asset(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> bool:
        """
        Soft delete an asset (set status to 'deleted').

        Note: Physical deletion of object storage files should be handled
        by lifecycle policies or separate cleanup jobs.

        Args:
            session: Database session
            asset_id: Asset UUID

        Returns:
            True if asset was deleted, False if not found
        """
        asset = await self.update_asset_status(session, asset_id, "deleted")
        return asset is not None


# Singleton instance
asset_service = AssetService()
