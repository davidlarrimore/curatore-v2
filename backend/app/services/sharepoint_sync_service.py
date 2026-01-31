"""
SharePoint Sync Service for managing SharePoint folder synchronization.

Provides operations for:
- Sync config CRUD (create, read, update, archive)
- Sync execution (one-way pull from SharePoint)
- File sync (create/update assets from SharePoint files)
- Deleted file detection and cleanup

Usage:
    from app.services.sharepoint_sync_service import sharepoint_sync_service

    # Create sync config
    config = await sharepoint_sync_service.create_sync_config(
        session=session,
        organization_id=org_id,
        connection_id=conn_id,
        name="IT Documents",
        folder_url="https://mycompany.sharepoint.com/sites/IT/Shared%20Documents/Policies",
    )

    # Execute sync
    result = await sharepoint_sync_service.execute_sync(
        session=session,
        sync_config_id=config.id,
        organization_id=org_id,
    )
"""

import hashlib
import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database.models import (
    Asset,
    Connection,
    Run,
    RunLogEvent,
    SharePointSyncConfig,
    SharePointSyncedDocument,
)
from ..config import settings
from .storage_path_service import storage_paths

logger = logging.getLogger("curatore.sharepoint_sync")


def generate_slug(name: str) -> str:
    """Generate a URL-friendly slug from a name."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug or "sync"


class SharePointSyncService:
    """
    Service for managing SharePoint sync configurations and execution.

    Handles:
    - Sync config lifecycle (CRUD)
    - Sync execution (pull files from SharePoint)
    - Change detection (etag/hash comparison)
    - Deleted file tracking
    - Cleanup operations
    """

    # =========================================================================
    # SYNC CONFIG CRUD
    # =========================================================================

    async def create_sync_config(
        self,
        session: AsyncSession,
        organization_id: UUID,
        connection_id: Optional[UUID],
        name: str,
        folder_url: str,
        description: Optional[str] = None,
        sync_config: Optional[Dict[str, Any]] = None,
        sync_frequency: str = "manual",
        created_by: Optional[UUID] = None,
    ) -> SharePointSyncConfig:
        """
        Create a new SharePoint sync configuration.

        Args:
            session: Database session
            organization_id: Organization UUID
            connection_id: SharePoint connection UUID (nullable for env-based auth)
            name: Display name for the sync config
            folder_url: SharePoint folder URL to sync
            description: Optional description
            sync_config: Sync settings (recursive, include/exclude patterns)
            sync_frequency: How often to sync (manual, hourly, daily)
            created_by: User UUID who created this config

        Returns:
            Created SharePointSyncConfig instance

        Raises:
            ValueError: If a sync config with the same name or folder URL already exists
        """
        # Check for existing config with same name (case-insensitive)
        existing_name = await session.execute(
            select(SharePointSyncConfig).where(
                and_(
                    SharePointSyncConfig.organization_id == organization_id,
                    func.lower(SharePointSyncConfig.name) == func.lower(name),
                    SharePointSyncConfig.status != "archived",  # Allow reusing names from archived configs
                )
            )
        )
        if existing_name.scalar_one_or_none():
            raise ValueError(f"A sync configuration with the name '{name}' already exists")

        # Normalize folder URL for comparison (remove trailing slashes, query params variations)
        normalized_url = folder_url.rstrip("/").split("?")[0]

        # Check for existing config with same folder URL
        existing_url_result = await session.execute(
            select(SharePointSyncConfig).where(
                and_(
                    SharePointSyncConfig.organization_id == organization_id,
                    SharePointSyncConfig.status != "archived",  # Allow reusing URLs from archived configs
                )
            )
        )
        existing_configs = existing_url_result.scalars().all()
        for existing in existing_configs:
            existing_normalized = existing.folder_url.rstrip("/").split("?")[0]
            if existing_normalized == normalized_url:
                raise ValueError(
                    f"A sync configuration for this SharePoint folder already exists: '{existing.name}'"
                )

        # Generate unique slug
        base_slug = generate_slug(name)
        slug = base_slug
        counter = 1

        # Ensure slug uniqueness within org
        while True:
            existing = await session.execute(
                select(SharePointSyncConfig).where(
                    and_(
                        SharePointSyncConfig.organization_id == organization_id,
                        SharePointSyncConfig.slug == slug,
                    )
                )
            )
            if not existing.scalar_one_or_none():
                break
            slug = f"{base_slug}-{counter}"
            counter += 1

        config = SharePointSyncConfig(
            organization_id=organization_id,
            connection_id=connection_id,
            name=name,
            slug=slug,
            description=description,
            folder_url=folder_url,
            sync_config=sync_config or {"recursive": True},
            sync_frequency=sync_frequency,
            status="active",
            is_active=True,
            stats={},
            created_by=created_by,
        )

        session.add(config)
        await session.commit()
        await session.refresh(config)

        logger.info(
            f"Created SharePoint sync config {config.id} "
            f"(name: {name}, slug: {slug}, org: {organization_id})"
        )

        return config

    async def get_sync_config(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
    ) -> Optional[SharePointSyncConfig]:
        """
        Get sync config by ID.

        Args:
            session: Database session
            sync_config_id: Sync config UUID

        Returns:
            SharePointSyncConfig instance or None
        """
        result = await session.execute(
            select(SharePointSyncConfig).where(SharePointSyncConfig.id == sync_config_id)
        )
        return result.scalar_one_or_none()

    async def get_sync_config_by_slug(
        self,
        session: AsyncSession,
        organization_id: UUID,
        slug: str,
    ) -> Optional[SharePointSyncConfig]:
        """
        Get sync config by organization and slug.

        Args:
            session: Database session
            organization_id: Organization UUID
            slug: Sync config slug

        Returns:
            SharePointSyncConfig instance or None
        """
        result = await session.execute(
            select(SharePointSyncConfig).where(
                and_(
                    SharePointSyncConfig.organization_id == organization_id,
                    SharePointSyncConfig.slug == slug,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_sync_configs(
        self,
        session: AsyncSession,
        organization_id: UUID,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[SharePointSyncConfig], int]:
        """
        List sync configs for an organization.

        Args:
            session: Database session
            organization_id: Organization UUID
            status: Optional status filter (active, paused, archived)
            limit: Maximum results to return
            offset: Number of results to skip

        Returns:
            Tuple of (list of configs, total count)
        """
        # Build base query
        base_query = select(SharePointSyncConfig).where(
            SharePointSyncConfig.organization_id == organization_id
        )

        if status:
            base_query = base_query.where(SharePointSyncConfig.status == status)

        # Get total count
        count_query = select(func.count()).select_from(base_query.subquery())
        total = (await session.execute(count_query)).scalar() or 0

        # Get paginated results
        query = (
            base_query
            .order_by(SharePointSyncConfig.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        result = await session.execute(query)
        configs = list(result.scalars().all())

        return configs, total

    async def update_sync_config(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
        **updates: Any,
    ) -> Optional[SharePointSyncConfig]:
        """
        Update sync config fields.

        When is_active is set to False, this will also cancel any pending
        extraction jobs for assets belonging to this sync config.

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            **updates: Fields to update (name, description, sync_config, status, etc.)

        Returns:
            Updated SharePointSyncConfig or None if not found
        """
        config = await self.get_sync_config(session, sync_config_id)
        if not config:
            return None

        # Check if we're disabling the sync (is_active changing from True to False)
        is_disabling = (
            "is_active" in updates
            and updates["is_active"] is False
            and config.is_active is True
        )

        # Allowed update fields
        allowed_fields = {
            "name", "description", "sync_config", "status", "is_active",
            "sync_frequency", "folder_url", "folder_name", "folder_drive_id",
            "folder_item_id", "connection_id",
        }

        for field, value in updates.items():
            if field in allowed_fields and value is not None:
                setattr(config, field, value)

        config.updated_at = datetime.utcnow()

        # If disabling, cancel pending extractions for this sync config's assets
        if is_disabling:
            cancelled_count = await self._cancel_pending_extractions_for_sync_config(
                session, sync_config_id, config.organization_id
            )
            if cancelled_count > 0:
                logger.info(
                    f"Cancelled {cancelled_count} pending extraction(s) for disabled sync config {sync_config_id}"
                )

        await session.commit()
        await session.refresh(config)

        logger.info(f"Updated sync config {sync_config_id}: {list(updates.keys())}")

        return config

    async def _cancel_pending_extractions_for_sync_config(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
        organization_id: UUID,
    ) -> int:
        """
        Cancel all pending/submitted/running extraction jobs for assets in a sync config.

        This is called when a sync config is disabled to prevent wasted processing.

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            organization_id: Organization UUID

        Returns:
            Number of extraction runs cancelled
        """
        from ..celery_app import app as celery_app

        # Find all asset IDs linked to this sync config
        asset_query = select(SharePointSyncedDocument.asset_id).where(
            SharePointSyncedDocument.sync_config_id == sync_config_id
        )
        asset_result = await session.execute(asset_query)
        asset_ids = [str(row[0]) for row in asset_result.fetchall()]

        if not asset_ids:
            return 0

        # Find all pending/submitted/running extraction runs for these assets
        # Run.input_asset_ids is a JSON array, so we need to check if asset_id is in it
        runs_query = select(Run).where(
            and_(
                Run.organization_id == organization_id,
                Run.run_type == "extraction",
                Run.status.in_(["pending", "submitted", "running"]),
            )
        )
        runs_result = await session.execute(runs_query)
        runs = runs_result.scalars().all()

        cancelled_count = 0
        for run in runs:
            # Check if any of the run's input assets belong to this sync config
            run_asset_ids = run.input_asset_ids or []
            if any(asset_id in asset_ids for asset_id in run_asset_ids):
                # Revoke Celery task if submitted
                if run.celery_task_id and run.status in ("submitted", "running"):
                    try:
                        celery_app.control.revoke(run.celery_task_id, terminate=True)
                        logger.info(f"Revoked Celery task {run.celery_task_id} for run {run.id}")
                    except Exception as e:
                        logger.warning(f"Failed to revoke Celery task {run.celery_task_id}: {e}")

                # Update run status
                run.status = "cancelled"
                run.completed_at = datetime.utcnow()
                run.error_message = "Cancelled: SharePoint sync disabled"
                cancelled_count += 1

                logger.info(f"Cancelled extraction run {run.id} (sync config disabled)")

        return cancelled_count

    async def archive_sync_config_with_opensearch_cleanup(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
        organization_id: UUID,
    ) -> Dict[str, Any]:
        """
        Archive a sync config and remove documents from OpenSearch.

        This removes documents from search but keeps assets intact:
        1. Remove documents from OpenSearch index
        2. Set config status to "archived"

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            organization_id: Organization UUID for OpenSearch

        Returns:
            Dict with cleanup statistics
        """
        from .index_service import index_service

        config = await self.get_sync_config(session, sync_config_id)
        if not config:
            return {"error": "Sync config not found"}

        stats = {
            "opensearch_removed": 0,
            "extractions_cancelled": 0,
            "errors": [],
        }

        # Cancel any pending extraction jobs for this sync config's assets
        if config.is_active:
            cancelled_count = await self._cancel_pending_extractions_for_sync_config(
                session, sync_config_id, organization_id
            )
            stats["extractions_cancelled"] = cancelled_count

        # Get all synced documents
        docs_result = await session.execute(
            select(SharePointSyncedDocument).where(
                SharePointSyncedDocument.sync_config_id == sync_config_id
            )
        )
        synced_docs = list(docs_result.scalars().all())

        # Remove from OpenSearch only
        for doc in synced_docs:
            if doc.asset_id:
                try:
                    await index_service.delete_asset_index(organization_id, doc.asset_id)
                    stats["opensearch_removed"] += 1
                except Exception as e:
                    stats["errors"].append(f"OpenSearch removal failed for {doc.asset_id}: {e}")

        # Set config to archived status
        config.status = "archived"
        config.is_active = False
        config.updated_at = datetime.utcnow()

        await session.commit()

        logger.info(
            f"Archived sync config {sync_config_id}: "
            f"opensearch_removed={stats['opensearch_removed']}, "
            f"extractions_cancelled={stats['extractions_cancelled']}"
        )

        return stats

    async def delete_sync_config_with_cleanup(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
        organization_id: UUID,
    ) -> Dict[str, Any]:
        """
        Permanently delete a sync config with full cleanup.

        This performs a complete removal including:
        1. Delete files from MinIO storage (raw and extracted)
        2. Hard delete Asset records from database
        3. Remove documents from OpenSearch index
        4. Delete SharePointSyncedDocument records
        5. Delete related Run records
        6. Delete the sync config itself

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            organization_id: Organization UUID for OpenSearch

        Returns:
            Dict with cleanup statistics
        """
        from .asset_service import asset_service
        from .index_service import index_service
        from .minio_service import get_minio_service
        from sqlalchemy import delete as sql_delete, func
        from ..database.models import ExtractionResult, AssetVersion

        config = await self.get_sync_config(session, sync_config_id)
        if not config:
            return {"error": "Sync config not found"}

        minio = get_minio_service()

        stats = {
            "assets_deleted": 0,
            "files_deleted": 0,
            "documents_deleted": 0,
            "runs_deleted": 0,
            "extractions_cancelled": 0,
            "opensearch_removed": 0,
            "storage_freed_bytes": 0,
            "errors": [],
        }

        # 0. Cancel any pending extraction jobs before deleting
        cancelled_count = await self._cancel_pending_extractions_for_sync_config(
            session, sync_config_id, organization_id
        )
        stats["extractions_cancelled"] = cancelled_count

        # 1. Get all synced documents
        docs_result = await session.execute(
            select(SharePointSyncedDocument).where(
                SharePointSyncedDocument.sync_config_id == sync_config_id
            )
        )
        synced_docs = list(docs_result.scalars().all())

        # 2. Delete assets, files from MinIO, and remove from OpenSearch
        for doc in synced_docs:
            if doc.asset_id:
                try:
                    # Remove from OpenSearch
                    await index_service.delete_asset_index(organization_id, doc.asset_id)
                    stats["opensearch_removed"] += 1
                except Exception as e:
                    stats["errors"].append(f"OpenSearch removal failed for {doc.asset_id}: {e}")

                try:
                    # Get asset to find file locations
                    asset = await asset_service.get_asset(session, doc.asset_id)
                    if asset:
                        # Track storage freed
                        if asset.file_size:
                            stats["storage_freed_bytes"] += asset.file_size

                        # Delete raw file from MinIO
                        if minio and asset.raw_bucket and asset.raw_object_key:
                            try:
                                minio.delete_object(asset.raw_bucket, asset.raw_object_key)
                                stats["files_deleted"] += 1
                            except Exception as e:
                                stats["errors"].append(f"Failed to delete raw file for {doc.asset_id}: {e}")

                        # Delete extracted files from MinIO (via extraction results)
                        extraction_result = await session.execute(
                            select(ExtractionResult).where(ExtractionResult.asset_id == asset.id)
                        )
                        extractions = list(extraction_result.scalars().all())
                        for extraction in extractions:
                            if minio and extraction.extracted_bucket and extraction.extracted_object_key:
                                try:
                                    minio.delete_object(extraction.extracted_bucket, extraction.extracted_object_key)
                                    stats["files_deleted"] += 1
                                except Exception as e:
                                    pass  # Don't fail on extraction cleanup

                        # Delete extraction results
                        await session.execute(
                            sql_delete(ExtractionResult).where(ExtractionResult.asset_id == asset.id)
                        )

                        # Delete asset versions if any
                        await session.execute(
                            sql_delete(AssetVersion).where(AssetVersion.asset_id == asset.id)
                        )

                        # Hard delete the asset record
                        await session.execute(
                            sql_delete(Asset).where(Asset.id == asset.id)
                        )
                        stats["assets_deleted"] += 1
                except Exception as e:
                    stats["errors"].append(f"Asset deletion failed for {doc.asset_id}: {e}")

        # 3. Delete SharePointSyncedDocument records
        await session.execute(
            sql_delete(SharePointSyncedDocument).where(
                SharePointSyncedDocument.sync_config_id == sync_config_id
            )
        )
        stats["documents_deleted"] = len(synced_docs)

        # 4. Delete related Runs (using json_extract for SQLite compatibility)
        runs_result = await session.execute(
            select(Run).where(
                func.json_extract(Run.config, "$.sync_config_id") == str(sync_config_id)
            )
        )
        runs = list(runs_result.scalars().all())

        for run in runs:
            # Delete run log events first
            await session.execute(
                sql_delete(RunLogEvent).where(RunLogEvent.run_id == run.id)
            )
            await session.execute(
                sql_delete(Run).where(Run.id == run.id)
            )
            stats["runs_deleted"] += 1

        # 5. Delete the sync config itself
        await session.execute(
            sql_delete(SharePointSyncConfig).where(
                SharePointSyncConfig.id == sync_config_id
            )
        )

        await session.commit()

        logger.info(
            f"Deleted sync config {sync_config_id} with cleanup: "
            f"assets={stats['assets_deleted']}, docs={stats['documents_deleted']}, "
            f"runs={stats['runs_deleted']}, opensearch={stats['opensearch_removed']}"
        )

        return stats

    # =========================================================================
    # SYNCED DOCUMENT OPERATIONS
    # =========================================================================

    async def get_synced_document(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
        sharepoint_item_id: str,
    ) -> Optional[SharePointSyncedDocument]:
        """
        Get synced document by SharePoint item ID.

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            sharepoint_item_id: Microsoft Graph item ID

        Returns:
            SharePointSyncedDocument or None
        """
        result = await session.execute(
            select(SharePointSyncedDocument).where(
                and_(
                    SharePointSyncedDocument.sync_config_id == sync_config_id,
                    SharePointSyncedDocument.sharepoint_item_id == sharepoint_item_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_synced_documents(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
        sync_status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[SharePointSyncedDocument], int]:
        """
        List synced documents for a sync config.

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            sync_status: Optional status filter (synced, deleted_in_source, orphaned)
            limit: Maximum results to return
            offset: Number of results to skip

        Returns:
            Tuple of (list of documents, total count)
        """
        base_query = select(SharePointSyncedDocument).where(
            SharePointSyncedDocument.sync_config_id == sync_config_id
        )

        if sync_status:
            base_query = base_query.where(SharePointSyncedDocument.sync_status == sync_status)

        # Get total count
        count_query = select(func.count()).select_from(base_query.subquery())
        total = (await session.execute(count_query)).scalar() or 0

        # Get paginated results
        query = (
            base_query
            .order_by(SharePointSyncedDocument.sharepoint_path)
            .limit(limit)
            .offset(offset)
        )

        result = await session.execute(query)
        documents = list(result.scalars().all())

        return documents, total

    async def create_synced_document(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
        asset_id: UUID,
        sharepoint_item_id: str,
        sharepoint_drive_id: str,
        sharepoint_path: Optional[str] = None,
        sharepoint_web_url: Optional[str] = None,
        sharepoint_etag: Optional[str] = None,
        content_hash: Optional[str] = None,
        sharepoint_created_at: Optional[datetime] = None,
        sharepoint_modified_at: Optional[datetime] = None,
        sharepoint_created_by: Optional[str] = None,
        sharepoint_modified_by: Optional[str] = None,
        file_size: Optional[int] = None,
        run_id: Optional[UUID] = None,
        sync_metadata: Optional[Dict[str, Any]] = None,
    ) -> SharePointSyncedDocument:
        """
        Create a synced document record.

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            asset_id: Asset UUID
            sharepoint_item_id: Microsoft Graph item ID
            sharepoint_drive_id: Microsoft Graph drive ID
            sharepoint_path: Relative path in synced folder
            sharepoint_web_url: Direct link to file in SharePoint
            sharepoint_etag: ETag for change detection
            content_hash: SHA-256 hash of file content
            sharepoint_created_at: Creation date in SharePoint
            sharepoint_modified_at: Last modified date in SharePoint
            sharepoint_created_by: Creator email/name
            sharepoint_modified_by: Last modifier email/name
            file_size: File size in bytes
            run_id: Run that created this record
            sync_metadata: Additional sync metadata (hashes, IDs, etc.)

        Returns:
            Created SharePointSyncedDocument
        """
        doc = SharePointSyncedDocument(
            sync_config_id=sync_config_id,
            asset_id=asset_id,
            sharepoint_item_id=sharepoint_item_id,
            sharepoint_drive_id=sharepoint_drive_id,
            sharepoint_path=sharepoint_path,
            sharepoint_web_url=sharepoint_web_url,
            sharepoint_etag=sharepoint_etag,
            content_hash=content_hash,
            sharepoint_created_at=sharepoint_created_at,
            sharepoint_modified_at=sharepoint_modified_at,
            sharepoint_created_by=sharepoint_created_by,
            sharepoint_modified_by=sharepoint_modified_by,
            file_size=file_size,
            sync_status="synced",
            last_synced_at=datetime.utcnow(),
            last_sync_run_id=run_id,
            sync_metadata=sync_metadata or {},
        )

        session.add(doc)
        await session.flush()

        return doc

    async def update_synced_document(
        self,
        session: AsyncSession,
        doc: SharePointSyncedDocument,
        **updates: Any,
    ) -> SharePointSyncedDocument:
        """
        Update a synced document record.

        Args:
            session: Database session
            doc: Document to update
            **updates: Fields to update

        Returns:
            Updated SharePointSyncedDocument
        """
        allowed_fields = {
            "sharepoint_etag", "content_hash", "sharepoint_modified_at",
            "sharepoint_modified_by", "file_size", "sync_status",
            "last_synced_at", "last_sync_run_id", "deleted_detected_at",
            "sync_metadata",
        }

        for field, value in updates.items():
            if field in allowed_fields:
                setattr(doc, field, value)

        doc.updated_at = datetime.utcnow()
        await session.flush()

        return doc

    # =========================================================================
    # SYNC EXECUTION
    # =========================================================================

    async def execute_sync(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
        organization_id: UUID,
        run_id: UUID,
        full_sync: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute synchronization for a sync config.

        This is the main sync entry point, typically called from a Celery task.
        It:
        1. Gets the folder inventory from SharePoint
        2. Compares with existing synced documents
        3. Downloads new/updated files and creates Assets
        4. Detects deleted files and marks them

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            organization_id: Organization UUID
            run_id: Run UUID for tracking
            full_sync: If True, re-download all files regardless of etag

        Returns:
            Sync result dict with statistics
        """
        from .sharepoint_service import sharepoint_inventory_stream
        from .run_service import run_service
        from .run_log_service import run_log_service

        # =================================================================
        # PHASE 1: INITIALIZATION
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 1: Initializing sync configuration",
            context={"phase": "init", "sync_config_id": str(sync_config_id)},
        )
        await session.commit()

        # Get sync config
        config = await self.get_sync_config(session, sync_config_id)
        if not config:
            raise ValueError(f"Sync config {sync_config_id} not found")

        if config.status != "active" or not config.is_active:
            raise ValueError(f"Sync config {sync_config_id} is not active")

        sync_settings = config.sync_config or {}
        recursive = sync_settings.get("recursive", True)
        include_patterns = sync_settings.get("include_patterns", [])
        exclude_patterns = sync_settings.get("exclude_patterns", [])
        max_file_size_mb = sync_settings.get("max_file_size_mb", 100)

        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="progress",
            message=f"Loaded sync config: {config.name}",
            context={
                "folder_url": config.folder_url,
                "recursive": recursive,
                "exclude_patterns": exclude_patterns,
            },
        )
        await session.commit()

        # Get connection for auth
        connection = None
        if config.connection_id:
            conn_result = await session.execute(
                select(Connection).where(Connection.id == config.connection_id)
            )
            connection = conn_result.scalar_one_or_none()

        # =================================================================
        # PHASE 2: CONNECTING & STREAMING SYNC
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 2: Connecting to SharePoint and starting streaming sync",
            context={"phase": "connecting", "connection_id": str(config.connection_id) if config.connection_id else None},
        )
        await session.commit()

        logger.info(f"Starting streaming sync for {config.folder_url}")

        # Results tracking
        results = {
            "total_files": 0,
            "new_files": 0,
            "updated_files": 0,
            "unchanged_files": 0,
            "skipped_files": 0,
            "failed_files": 0,
            "deleted_detected": 0,
            "errors": [],
        }

        # Track all seen item IDs for deletion detection
        current_item_ids = set()

        # Progress tracking
        processed_files = 0
        folders_scanned = 0
        last_log_time = datetime.utcnow()
        log_interval_seconds = 5  # Log progress every 5 seconds

        # Initialize config stats
        config.stats = {
            "total_files": 0,
            "synced_files": 0,
            "processed_files": 0,
            "new_files": 0,
            "updated_files": 0,
            "unchanged_files": 0,
            "failed_files": 0,
            "deleted_count": 0,
            "current_file": None,
            "folders_scanned": 0,
            "phase": "scanning_and_syncing",
        }
        await session.commit()

        folder_info = None

        # Callback for folder scanning progress
        async def on_folder_scanned(folder_path: str, files_found: int, folders_pending: int):
            nonlocal folders_scanned, last_log_time
            folders_scanned += 1

            # Log progress periodically (not on every folder to avoid spam)
            now = datetime.utcnow()
            if (now - last_log_time).total_seconds() >= log_interval_seconds:
                last_log_time = now

                # Update Run.progress with current state
                await run_service.update_run_progress(
                    session=session,
                    run_id=run_id,
                    current=processed_files,
                    total=None,  # Unknown total until scan completes
                    unit="files",
                    phase="scanning_and_syncing",
                    details={
                        "folders_scanned": folders_scanned,
                        "folders_pending": folders_pending,
                        "new_files": results["new_files"],
                        "updated_files": results["updated_files"],
                        "unchanged_files": results["unchanged_files"],
                        "skipped_files": results["skipped_files"],
                        "failed_files": results["failed_files"],
                    },
                )

                await run_log_service.log_event(
                    session=session,
                    run_id=run_id,
                    level="INFO",
                    event_type="progress",
                    message=f"Scanning: {folders_scanned} folders scanned, {processed_files} files synced, {folders_pending} folders remaining",
                    context={
                        "phase": "scanning_and_syncing",
                        "folders_scanned": folders_scanned,
                        "files_synced": processed_files,
                        "folders_pending": folders_pending,
                    },
                )
                await session.commit()

        try:
            # Stream items and process them as they're discovered
            async for folder_data, item in sharepoint_inventory_stream(
                folder_url=config.folder_url,
                recursive=recursive,
                include_folders=False,  # Only files
                page_size=100,
                max_items=None,
                organization_id=organization_id,
                session=session,
                on_folder_scanned=on_folder_scanned,
            ):
                # First yield is folder info
                if folder_data is not None:
                    folder_info = folder_data
                    config.folder_name = folder_info.get("name")
                    config.folder_drive_id = folder_info.get("drive_id")
                    config.folder_item_id = folder_info.get("id")
                    await run_log_service.log_event(
                        session=session,
                        run_id=run_id,
                        level="INFO",
                        event_type="progress",
                        message=f"Connected to folder: {folder_info.get('name')}",
                        context={"phase": "scanning_and_syncing", "folder_name": folder_info.get("name")},
                    )
                    await session.commit()
                    continue

                if item is None:
                    continue

                # Skip if item doesn't pass filters
                if not self._item_passes_filter(item, include_patterns, exclude_patterns, max_file_size_mb):
                    results["skipped_files"] += 1
                    continue

                results["total_files"] += 1
                current_item_ids.add(item.get("id"))

                # Process this file immediately
                current_file = item.get("name", "unknown")
                try:
                    result = await self._sync_single_file(
                        session=session,
                        config=config,
                        item=item,
                        run_id=run_id,
                        full_sync=full_sync,
                    )
                    results[result] += 1
                    processed_files += 1

                    # Log new/updated files
                    if result == "new_files":
                        await run_log_service.log_event(
                            session=session,
                            run_id=run_id,
                            level="INFO",
                            event_type="file_download",
                            message=f"Downloaded: {current_file}",
                            context={"phase": "scanning_and_syncing", "file": current_file, "action": "new"},
                        )
                    elif result == "updated_files":
                        await run_log_service.log_event(
                            session=session,
                            run_id=run_id,
                            level="INFO",
                            event_type="file_download",
                            message=f"Updated: {current_file}",
                            context={"phase": "scanning_and_syncing", "file": current_file, "action": "updated"},
                        )

                except Exception as e:
                    logger.error(f"Failed to sync file {current_file}: {e}")
                    results["failed_files"] += 1
                    results["errors"].append({"file": current_file, "error": str(e)})
                    processed_files += 1
                    await run_log_service.log_event(
                        session=session,
                        run_id=run_id,
                        level="ERROR",
                        event_type="file_error",
                        message=f"Failed: {current_file}",
                        context={"phase": "scanning_and_syncing", "file": current_file, "error": str(e)},
                    )

                # Update config stats periodically
                config.stats = {
                    "total_files": results["total_files"],
                    "synced_files": results["new_files"] + results["updated_files"] + results["unchanged_files"],
                    "processed_files": processed_files,
                    "new_files": results["new_files"],
                    "updated_files": results["updated_files"],
                    "unchanged_files": results["unchanged_files"],
                    "failed_files": results["failed_files"],
                    "deleted_count": 0,
                    "current_file": current_file,
                    "folders_scanned": folders_scanned,
                    "phase": "scanning_and_syncing",
                }
                await session.commit()

        except Exception as e:
            logger.error(f"Streaming sync failed: {e}")
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="ERROR",
                event_type="error",
                message=f"Streaming sync failed: {e}",
                context={"phase": "scanning_and_syncing", "error": str(e)},
            )
            await session.commit()
            raise

        # Log completion of scanning phase
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="progress",
            message=f"Scanning complete: {folders_scanned} folders, {results['total_files']} files found, {processed_files} processed",
            context={
                "phase": "scanning_and_syncing",
                "folders_scanned": folders_scanned,
                "total_files": results["total_files"],
                "processed": processed_files,
                "new": results["new_files"],
                "updated": results["updated_files"],
                "unchanged": results["unchanged_files"],
                "failed": results["failed_files"],
            },
        )

        # Update Run.progress with scan completion
        await run_service.update_run_progress(
            session=session,
            run_id=run_id,
            current=processed_files,
            total=results["total_files"],
            unit="files",
            phase="scan_complete",
            details={
                "folders_scanned": folders_scanned,
                "new_files": results["new_files"],
                "updated_files": results["updated_files"],
                "unchanged_files": results["unchanged_files"],
                "skipped_files": results["skipped_files"],
                "failed_files": results["failed_files"],
            },
        )
        await session.commit()

        # =================================================================
        # PHASE 3: DETECTING DELETIONS
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 3: Detecting deleted files",
            context={"phase": "detecting_deletions"},
        )

        # Update Run.progress for deletion detection phase
        await run_service.update_run_progress(
            session=session,
            run_id=run_id,
            current=processed_files,
            total=results["total_files"],
            unit="files",
            phase="detecting_deletions",
            details={
                "folders_scanned": folders_scanned,
                "new_files": results["new_files"],
                "updated_files": results["updated_files"],
                "unchanged_files": results["unchanged_files"],
                "failed_files": results["failed_files"],
            },
        )
        await session.commit()

        # Detect deleted files
        config.stats["phase"] = "detecting_deletions"
        config.stats["current_file"] = None
        await session.commit()

        deleted_count = await self._detect_deleted_files(
            session=session,
            sync_config_id=sync_config_id,
            current_item_ids=current_item_ids,
            run_id=run_id,
        )
        results["deleted_detected"] = deleted_count

        if deleted_count > 0:
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="WARNING",
                event_type="progress",
                message=f"Detected {deleted_count} files deleted from SharePoint",
                context={"phase": "detecting_deletions", "deleted_count": deleted_count},
            )
        else:
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="progress",
                message="No deleted files detected",
                context={"phase": "detecting_deletions", "deleted_count": 0},
            )
        await session.commit()

        # =================================================================
        # PHASE 4: COMPLETING SYNC
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 4: Finalizing sync",
            context={"phase": "completing"},
        )

        # Update Run.progress with final state
        await run_service.update_run_progress(
            session=session,
            run_id=run_id,
            current=processed_files,
            total=results["total_files"],
            unit="files",
            phase="completing",
            details={
                "folders_scanned": folders_scanned,
                "new_files": results["new_files"],
                "updated_files": results["updated_files"],
                "unchanged_files": results["unchanged_files"],
                "skipped_files": results["skipped_files"],
                "failed_files": results["failed_files"],
                "deleted_detected": deleted_count,
            },
        )
        await session.commit()

        # Update final sync config stats and tracking
        config.last_sync_at = datetime.utcnow()
        config.last_sync_status = "success" if results["failed_files"] == 0 else "partial"
        config.last_sync_run_id = run_id
        config.stats = {
            "total_files": results["total_files"],
            "synced_files": results["new_files"] + results["updated_files"] + results["unchanged_files"],
            "processed_files": processed_files,
            "new_files": results["new_files"],
            "updated_files": results["updated_files"],
            "unchanged_files": results["unchanged_files"],
            "failed_files": results["failed_files"],
            "deleted_count": deleted_count,
            "folders_scanned": folders_scanned,
            "current_file": None,
            "phase": "completed",
            "last_sync_results": results,
        }

        await session.commit()

        # Complete the run with results summary
        results_summary = {
            "total_files": results["total_files"],
            "new_files": results["new_files"],
            "updated_files": results["updated_files"],
            "unchanged_files": results["unchanged_files"],
            "skipped_files": results["skipped_files"],
            "failed_files": results["failed_files"],
            "deleted_detected": deleted_count,
            "folders_scanned": folders_scanned,
            "sync_status": "success" if results["failed_files"] == 0 else "partial",
            "errors": results.get("errors", []),
        }
        await run_service.complete_run(
            session=session,
            run_id=run_id,
            results_summary=results_summary,
        )

        # Log final summary
        status_msg = "completed successfully" if results["failed_files"] == 0 else "completed with errors"
        await run_log_service.log_summary(
            session=session,
            run_id=run_id,
            message=f"SharePoint sync {status_msg}: {results['new_files']} new, {results['updated_files']} updated, {results['unchanged_files']} unchanged, {results['failed_files']} failed, {deleted_count} deleted in source",
            context={
                "new_files": results["new_files"],
                "updated_files": results["updated_files"],
                "unchanged_files": results["unchanged_files"],
                "failed_files": results["failed_files"],
                "deleted_detected": deleted_count,
                "status": "success" if results["failed_files"] == 0 else "partial",
            },
        )
        await session.commit()

        logger.info(
            f"Sync completed for {config.name}: "
            f"new={results['new_files']}, updated={results['updated_files']}, "
            f"unchanged={results['unchanged_files']}, deleted={deleted_count}"
        )

        return results

    def _filter_items(
        self,
        items: List[Dict[str, Any]],
        include_patterns: List[str],
        exclude_patterns: List[str],
        max_file_size_mb: int,
    ) -> List[Dict[str, Any]]:
        """Filter items based on patterns and size."""
        import fnmatch

        filtered = []
        max_size_bytes = max_file_size_mb * 1024 * 1024

        for item in items:
            # Skip folders
            if item.get("type") == "folder":
                continue

            name = item.get("name", "")
            size = item.get("size") or 0

            # Check size
            if size > max_size_bytes:
                continue

            # Check exclude patterns
            if exclude_patterns:
                excluded = any(fnmatch.fnmatch(name, p) for p in exclude_patterns)
                if excluded:
                    continue

            # Check include patterns (if specified, must match)
            if include_patterns:
                included = any(fnmatch.fnmatch(name, p) for p in include_patterns)
                if not included:
                    continue

            filtered.append(item)

        return filtered

    def _item_passes_filter(
        self,
        item: Dict[str, Any],
        include_patterns: List[str],
        exclude_patterns: List[str],
        max_file_size_mb: int,
    ) -> bool:
        """Check if a single item passes the filter criteria."""
        import fnmatch

        # Skip folders
        if item.get("type") == "folder":
            return False

        name = item.get("name", "")
        size = item.get("size") or 0
        max_size_bytes = max_file_size_mb * 1024 * 1024

        # Check size
        if size > max_size_bytes:
            return False

        # Check exclude patterns
        if exclude_patterns:
            excluded = any(fnmatch.fnmatch(name, p) for p in exclude_patterns)
            if excluded:
                return False

        # Check include patterns (if specified, must match)
        if include_patterns:
            included = any(fnmatch.fnmatch(name, p) for p in include_patterns)
            if not included:
                return False

        return True

    async def _sync_single_file(
        self,
        session: AsyncSession,
        config: SharePointSyncConfig,
        item: Dict[str, Any],
        run_id: UUID,
        full_sync: bool,
    ) -> str:
        """
        Sync a single file from SharePoint.

        Returns:
            Result type: "new_files", "updated_files", "unchanged_files", "skipped_files"
        """
        item_id = item.get("id")
        name = item.get("name", "unknown")
        etag = item.get("etag") or item.get("eTag")
        size = item.get("size")
        web_url = item.get("web_url")
        folder_path = item.get("folder", "").strip("/")
        created = item.get("created")
        modified = item.get("modified")
        created_by = item.get("created_by")
        modified_by = item.get("last_modified_by")

        # Check if we already have this file via SharePointSyncedDocument
        existing_doc = await self.get_synced_document(
            session, config.id, item_id
        )

        if existing_doc:
            # Check if file has changed
            if not full_sync and existing_doc.sharepoint_etag == etag:
                # Update last_synced_at even if unchanged
                await self.update_synced_document(
                    session, existing_doc,
                    last_synced_at=datetime.utcnow(),
                    last_sync_run_id=run_id,
                    sync_status="synced",  # Reset if was marked deleted
                )
                return "unchanged_files"

            # File has changed - need to re-download and update asset
            return await self._update_existing_file(
                session=session,
                config=config,
                item=item,
                existing_doc=existing_doc,
                run_id=run_id,
            )

        # No SharePointSyncedDocument found - check for orphan asset by sharepoint_item_id
        # This handles cases where asset was created but sync tracking record wasn't
        orphan_asset = await self._find_asset_by_sharepoint_item_id(
            session=session,
            organization_id=config.organization_id,
            sharepoint_item_id=item_id,
        )

        if orphan_asset:
            # Found orphan asset - create missing sync tracking record
            logger.info(
                f"Found orphan asset {orphan_asset.id} for SharePoint item {item_id}, "
                f"creating sync tracking record"
            )
            drive_id = item.get("drive_id") or config.folder_drive_id
            await self.create_synced_document(
                session=session,
                sync_config_id=config.id,
                asset_id=orphan_asset.id,
                sharepoint_item_id=item_id,
                sharepoint_drive_id=drive_id,
                sharepoint_path=folder_path,
                sharepoint_web_url=web_url,
                sharepoint_etag=etag,
                content_hash=orphan_asset.file_hash,
                run_id=run_id,
            )
            await session.flush()
            return "unchanged_files"

        # Truly new file - download and create asset
        return await self._download_and_create_asset(
            session=session,
            config=config,
            item=item,
            run_id=run_id,
        )

    async def _find_asset_by_sharepoint_item_id(
        self,
        session: AsyncSession,
        organization_id: UUID,
        sharepoint_item_id: str,
    ) -> Optional[Asset]:
        """
        Find an existing asset by SharePoint item ID in source_metadata.

        This is a fallback lookup for cases where the SharePointSyncedDocument
        record is missing but an asset with this SharePoint item exists.

        Args:
            session: Database session
            organization_id: Organization UUID
            sharepoint_item_id: Microsoft Graph item ID

        Returns:
            Asset if found, None otherwise
        """
        # Query assets by source_metadata JSON field
        # Use json_extract for SQLite compatibility
        result = await session.execute(
            select(Asset).where(
                and_(
                    Asset.organization_id == organization_id,
                    Asset.source_type == "sharepoint",
                    func.json_extract(Asset.source_metadata, "$.sharepoint_item_id") == sharepoint_item_id,
                )
            ).limit(1)
        )
        return result.scalar_one_or_none()

    async def _find_asset_by_storage_key(
        self,
        session: AsyncSession,
        raw_bucket: str,
        raw_object_key: str,
    ) -> Optional[Asset]:
        """
        Find an existing asset by its storage key (bucket + object key).

        This is a fallback lookup that catches cases where an asset exists
        but the SharePointSyncedDocument record was lost (e.g., during a
        failed deletion or cleanup). Prevents UNIQUE constraint violations.

        Args:
            session: Database session
            raw_bucket: MinIO bucket name
            raw_object_key: Object key (path) in the bucket

        Returns:
            Asset if found, None otherwise
        """
        result = await session.execute(
            select(Asset).where(
                and_(
                    Asset.raw_bucket == raw_bucket,
                    Asset.raw_object_key == raw_object_key,
                )
            ).limit(1)
        )
        return result.scalar_one_or_none()

    async def _download_and_create_asset(
        self,
        session: AsyncSession,
        config: SharePointSyncConfig,
        item: Dict[str, Any],
        run_id: UUID,
    ) -> str:
        """Download a new file and create an asset with comprehensive metadata."""
        from .asset_service import asset_service
        from .minio_service import get_minio_service
        from .sharepoint_service import sharepoint_download

        minio_service = get_minio_service()
        if not minio_service:
            raise RuntimeError("MinIO service is not available")

        # Basic identification
        item_id = item.get("id")
        name = item.get("name", "unknown")
        folder_path = item.get("folder", "").strip("/")
        extension = item.get("extension", "")

        # Size and URLs
        size = item.get("size")
        web_url = item.get("web_url")
        mime_type = item.get("mime") or item.get("file_type")

        # Change detection
        etag = item.get("etag") or item.get("eTag")
        ctag = item.get("ctag")

        # SharePoint timestamps
        created = item.get("created")
        modified = item.get("modified")

        # File system timestamps (original file dates)
        fs_created = item.get("fs_created")
        fs_modified = item.get("fs_modified")

        # Creator info (enhanced)
        created_by = item.get("created_by")
        created_by_email = item.get("created_by_email")
        created_by_id = item.get("created_by_id")

        # Modifier info (enhanced)
        modified_by = item.get("last_modified_by")
        modified_by_email = item.get("last_modified_by_email")
        modified_by_id = item.get("last_modified_by_id")

        # Content hashes
        quick_xor_hash = item.get("quick_xor_hash")
        sha1_hash = item.get("sha1_hash")
        sha256_hash = item.get("sha256_hash")

        # Additional metadata
        description = item.get("description")
        parent_path = item.get("parent_path")
        drive_id_from_item = item.get("drive_id")

        # Helper to parse ISO dates safely
        def parse_date(date_str):
            if not date_str:
                return None
            try:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except:
                return None

        # Parse all dates
        created_at = parse_date(created)
        modified_at = parse_date(modified)
        fs_created_at = parse_date(fs_created)
        fs_modified_at = parse_date(fs_modified)

        # Generate storage path
        org_id_str = str(config.organization_id)
        storage_key = storage_paths.sharepoint_sync(
            org_id=org_id_str,
            sync_slug=config.slug,
            relative_path=folder_path,
            filename=name,
            extracted=False,
        )

        # Check for existing asset with this storage key (handles orphaned assets)
        # This prevents UNIQUE constraint violations when sync tracking record was lost
        uploads_bucket = minio_service.bucket_uploads
        existing_asset = await self._find_asset_by_storage_key(
            session=session,
            raw_bucket=uploads_bucket,
            raw_object_key=storage_key,
        )
        if existing_asset:
            logger.info(
                f"Found existing asset {existing_asset.id} with storage key {storage_key}, "
                f"creating sync tracking record instead of duplicate"
            )
            drive_id = item.get("drive_id") or config.folder_drive_id
            await self.create_synced_document(
                session=session,
                sync_config_id=config.id,
                asset_id=existing_asset.id,
                sharepoint_item_id=item_id,
                sharepoint_drive_id=drive_id,
                sharepoint_path=folder_path,
                sharepoint_web_url=web_url,
                sharepoint_etag=etag,
                content_hash=existing_asset.file_hash,
                run_id=run_id,
            )
            await session.flush()
            return "unchanged_files"

        # Download file to temp location, then upload to MinIO
        # For now, use SharePoint download and then upload to MinIO
        # In the future, this could stream directly

        import tempfile
        import httpx

        # Get the download URL and fetch the file
        from .sharepoint_service import _get_sharepoint_credentials, _graph_base_url, _encode_share_url

        credentials = await _get_sharepoint_credentials(config.organization_id, session)
        tenant_id = credentials["tenant_id"]
        client_id = credentials["client_id"]
        client_secret = credentials["client_secret"]

        token_payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        }

        graph_base = _graph_base_url()
        drive_id = config.folder_drive_id

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            # Get token
            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            token_resp = await client.post(token_url, data=token_payload)
            token_resp.raise_for_status()
            token = token_resp.json().get("access_token")

            headers = {"Authorization": f"Bearer {token}"}

            # Download file content
            download_url = f"{graph_base}/drives/{drive_id}/items/{item_id}/content"

            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                async with client.stream("GET", download_url, headers=headers) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        tmp_file.write(chunk)
                tmp_path = tmp_file.name

        # Read file content and calculate hash
        content_hash = None
        file_content = None
        try:
            with open(tmp_path, "rb") as f:
                file_content = f.read()
                content_hash = hashlib.sha256(file_content).hexdigest()
        except Exception as e:
            logger.error(f"Failed to read temp file {tmp_path}: {e}")
            raise
        finally:
            # Clean up temp file
            try:
                Path(tmp_path).unlink()
            except:
                pass

        # Upload to MinIO
        from io import BytesIO
        minio_service.put_object(
            bucket=uploads_bucket,
            key=storage_key,
            data=BytesIO(file_content),
            length=len(file_content),
            content_type=mime_type or "application/octet-stream",
        )

        # Create asset with comprehensive source metadata
        actual_size = len(file_content)
        source_metadata = {
            # Sync identification
            "sync_config_id": str(config.id),
            "sync_config_name": config.name,
            "folder_url": config.folder_url,
            # SharePoint identification
            "sharepoint_item_id": item_id,
            "sharepoint_drive_id": drive_id,
            "sharepoint_path": folder_path,
            "sharepoint_folder": folder_path.rsplit("/", 1)[0] if "/" in folder_path else "",
            "sharepoint_web_url": web_url,
            "sharepoint_parent_path": parent_path,
            # File metadata
            "file_extension": extension,
            "description": description,
            # Timestamps (ISO format strings for JSON serialization)
            "sharepoint_created_at": created_at.isoformat() if created_at else None,
            "sharepoint_modified_at": modified_at.isoformat() if modified_at else None,
            "file_created_at": fs_created_at.isoformat() if fs_created_at else None,
            "file_modified_at": fs_modified_at.isoformat() if fs_modified_at else None,
            # Creator info
            "created_by": created_by,
            "created_by_email": created_by_email,
            "created_by_id": created_by_id,
            # Modifier info
            "modified_by": modified_by,
            "modified_by_email": modified_by_email,
            "modified_by_id": modified_by_id,
            # Content hashes from SharePoint
            "sharepoint_quick_xor_hash": quick_xor_hash,
            "sharepoint_sha1_hash": sha1_hash,
            "sharepoint_sha256_hash": sha256_hash,
            # Change detection
            "sharepoint_etag": etag,
            "sharepoint_ctag": ctag,
        }
        # Remove None values for cleaner storage
        source_metadata = {k: v for k, v in source_metadata.items() if v is not None}

        asset = await asset_service.create_asset(
            session=session,
            organization_id=config.organization_id,
            source_type="sharepoint",
            source_metadata=source_metadata,
            original_filename=name,
            raw_bucket=uploads_bucket,
            raw_object_key=storage_key,
            content_type=mime_type or "application/octet-stream",
            file_size=actual_size,
            file_hash=content_hash,
            status="pending",  # Will trigger extraction
        )

        # Create synced document record with extended metadata
        sync_metadata = {
            # Content hashes for deduplication/verification
            "quick_xor_hash": quick_xor_hash,
            "sha1_hash": sha1_hash,
            "sha256_hash": sha256_hash,
            # Creator IDs for auditing
            "created_by_id": created_by_id,
            "modified_by_id": modified_by_id,
            # File system dates (original file dates before upload)
            "fs_created_at": fs_created_at.isoformat() if fs_created_at else None,
            "fs_modified_at": fs_modified_at.isoformat() if fs_modified_at else None,
            # SharePoint-specific
            "ctag": ctag,
            "description": description,
            "parent_path": parent_path,
            "extension": extension,
        }
        # Remove None values
        sync_metadata = {k: v for k, v in sync_metadata.items() if v is not None}

        await self.create_synced_document(
            session=session,
            sync_config_id=config.id,
            asset_id=asset.id,
            sharepoint_item_id=item_id,
            sharepoint_drive_id=drive_id,
            sharepoint_path=folder_path,
            sharepoint_web_url=web_url,
            sharepoint_etag=etag,
            content_hash=content_hash,
            sharepoint_created_at=created_at,
            sharepoint_modified_at=modified_at,
            sharepoint_created_by=created_by,
            sharepoint_modified_by=modified_by,
            file_size=actual_size,
            run_id=run_id,
            sync_metadata=sync_metadata,
        )

        await session.flush()

        logger.info(f"Created asset {asset.id} from SharePoint file: {name}")

        # Note: Extraction is automatically queued by asset_service.create_asset()

        return "new_files"

    async def _update_existing_file(
        self,
        session: AsyncSession,
        config: SharePointSyncConfig,
        item: Dict[str, Any],
        existing_doc: SharePointSyncedDocument,
        run_id: UUID,
    ) -> str:
        """Update an existing synced file that has changed in SharePoint."""
        from .asset_service import asset_service
        from .minio_service import get_minio_service

        minio_service = get_minio_service()
        if not minio_service:
            raise RuntimeError("MinIO service is not available")

        # Basic identification
        item_id = item.get("id")
        name = item.get("name", "unknown")
        folder_path = item.get("folder", "").strip("/")
        extension = item.get("extension", "")

        # Size and type
        size = item.get("size")
        mime_type = item.get("mime") or item.get("file_type")

        # Change detection
        etag = item.get("etag") or item.get("eTag")
        ctag = item.get("ctag")

        # Timestamps
        modified = item.get("modified")
        fs_modified = item.get("fs_modified")

        # Modifier info (enhanced)
        modified_by = item.get("last_modified_by")
        modified_by_email = item.get("last_modified_by_email")
        modified_by_id = item.get("last_modified_by_id")

        # Content hashes
        quick_xor_hash = item.get("quick_xor_hash")
        sha1_hash = item.get("sha1_hash")
        sha256_hash = item.get("sha256_hash")

        # Additional metadata
        description = item.get("description")

        # Helper to parse dates
        def parse_date(date_str):
            if not date_str:
                return None
            try:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except:
                return None

        modified_at = parse_date(modified)
        fs_modified_at = parse_date(fs_modified)

        # Get asset
        asset = await asset_service.get_asset(session, existing_doc.asset_id)
        if not asset:
            logger.warning(f"Asset {existing_doc.asset_id} not found, creating new")
            return await self._download_and_create_asset(
                session=session,
                config=config,
                item=item,
                run_id=run_id,
            )

        # Download updated content
        import tempfile
        import httpx

        from .sharepoint_service import _get_sharepoint_credentials, _graph_base_url

        credentials = await _get_sharepoint_credentials(config.organization_id, session)
        tenant_id = credentials["tenant_id"]
        client_id = credentials["client_id"]
        client_secret = credentials["client_secret"]

        token_payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        }

        graph_base = _graph_base_url()
        drive_id = config.folder_drive_id

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            token_resp = await client.post(token_url, data=token_payload)
            token_resp.raise_for_status()
            token = token_resp.json().get("access_token")

            headers = {"Authorization": f"Bearer {token}"}
            download_url = f"{graph_base}/drives/{drive_id}/items/{item_id}/content"

            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                async with client.stream("GET", download_url, headers=headers) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        tmp_file.write(chunk)
                tmp_path = tmp_file.name

        # Read file content and calculate hash
        content_hash = None
        file_content = None
        try:
            with open(tmp_path, "rb") as f:
                file_content = f.read()
                content_hash = hashlib.sha256(file_content).hexdigest()
        except Exception as e:
            logger.error(f"Failed to read temp file {tmp_path}: {e}")
            raise
        finally:
            # Clean up temp file
            try:
                Path(tmp_path).unlink()
            except:
                pass

        # Upload to same location (overwrite)
        from io import BytesIO
        uploads_bucket = minio_service.bucket_uploads
        minio_service.put_object(
            bucket=uploads_bucket,
            key=asset.raw_object_key,
            data=BytesIO(file_content),
            length=len(file_content),
            content_type=mime_type or "application/octet-stream",
        )

        # Update asset metadata
        actual_size = len(file_content)
        asset.file_size = actual_size
        asset.file_hash = content_hash
        asset.content_type = mime_type or "application/octet-stream"
        asset.status = "pending"  # Re-trigger extraction
        asset.updated_at = datetime.utcnow()

        # Update source_metadata with latest info
        source_meta = asset.source_metadata or {}
        source_meta.update({
            "sharepoint_modified_at": modified_at.isoformat() if modified_at else None,
            "file_modified_at": fs_modified_at.isoformat() if fs_modified_at else None,
            "modified_by": modified_by,
            "modified_by_email": modified_by_email,
            "modified_by_id": modified_by_id,
            "sharepoint_etag": etag,
            "sharepoint_ctag": ctag,
            "description": description,
            "sharepoint_quick_xor_hash": quick_xor_hash,
            "sharepoint_sha1_hash": sha1_hash,
            "sharepoint_sha256_hash": sha256_hash,
        })
        # Remove None values
        asset.source_metadata = {k: v for k, v in source_meta.items() if v is not None}

        # Build updated sync_metadata
        sync_metadata = existing_doc.sync_metadata or {}
        sync_metadata.update({
            "quick_xor_hash": quick_xor_hash,
            "sha1_hash": sha1_hash,
            "sha256_hash": sha256_hash,
            "modified_by_id": modified_by_id,
            "fs_modified_at": fs_modified_at.isoformat() if fs_modified_at else None,
            "ctag": ctag,
            "description": description,
            "extension": extension,
        })
        # Remove None values
        sync_metadata = {k: v for k, v in sync_metadata.items() if v is not None}

        # Update synced document record
        await self.update_synced_document(
            session, existing_doc,
            sharepoint_etag=etag,
            content_hash=content_hash,
            sharepoint_modified_at=modified_at,
            sharepoint_modified_by=modified_by,
            file_size=actual_size,
            sync_status="synced",
            last_synced_at=datetime.utcnow(),
            last_sync_run_id=run_id,
            sync_metadata=sync_metadata,
        )

        await session.flush()

        logger.info(f"Updated asset {asset.id} from SharePoint file: {name}")

        # Queue extraction for the updated asset (centralized via extraction_queue_service)
        try:
            from .extraction_queue_service import extraction_queue_service
            await extraction_queue_service.queue_extraction_for_asset(
                session=session,
                asset_id=asset.id,
            )
            logger.debug(f"Queued extraction for updated asset {asset.id}")
        except Exception as e:
            # Safety net task will catch this if queueing fails
            logger.warning(f"Failed to queue extraction for updated asset {asset.id}: {e}")

        return "updated_files"

    async def _detect_deleted_files(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
        current_item_ids: set,
        run_id: UUID,
    ) -> int:
        """Detect files that have been deleted in SharePoint."""
        # Get all synced documents that are currently marked as "synced"
        result = await session.execute(
            select(SharePointSyncedDocument).where(
                and_(
                    SharePointSyncedDocument.sync_config_id == sync_config_id,
                    SharePointSyncedDocument.sync_status == "synced",
                )
            )
        )
        synced_docs = list(result.scalars().all())

        deleted_count = 0
        now = datetime.utcnow()

        for doc in synced_docs:
            if doc.sharepoint_item_id not in current_item_ids:
                # File was deleted in SharePoint
                doc.sync_status = "deleted_in_source"
                doc.deleted_detected_at = now
                doc.last_sync_run_id = run_id
                doc.updated_at = now
                deleted_count += 1
                logger.info(
                    f"Detected deleted file: {doc.sharepoint_path} (item_id: {doc.sharepoint_item_id})"
                )

        if deleted_count > 0:
            await session.flush()

        return deleted_count

    # =========================================================================
    # CLEANUP OPERATIONS
    # =========================================================================

    async def get_deleted_documents(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
    ) -> List[SharePointSyncedDocument]:
        """Get all documents marked as deleted_in_source."""
        docs, _ = await self.list_synced_documents(
            session=session,
            sync_config_id=sync_config_id,
            sync_status="deleted_in_source",
            limit=1000,  # Get all
        )
        return docs

    async def cleanup_deleted_documents(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
        delete_assets: bool = False,
    ) -> Dict[str, int]:
        """
        Cleanup documents marked as deleted_in_source.

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            delete_assets: If True, also delete Asset records and files from storage

        Returns:
            Cleanup result with counts
        """
        from .asset_service import asset_service
        from .minio_service import get_minio_service
        from .index_service import index_service
        from sqlalchemy import delete as sql_delete
        from ..database.models import ExtractionResult, AssetVersion

        deleted_docs = await self.get_deleted_documents(session, sync_config_id)
        minio = get_minio_service()

        # Get organization_id from first doc's asset or config
        organization_id = None
        config = await self.get_sync_config(session, sync_config_id)
        if config:
            organization_id = config.organization_id

        results = {
            "documents_removed": 0,
            "assets_deleted": 0,
            "files_deleted": 0,
            "storage_freed_bytes": 0,
        }

        for doc in deleted_docs:
            if delete_assets and doc.asset_id:
                asset = await asset_service.get_asset(session, doc.asset_id)
                if asset:
                    # Track storage freed
                    if asset.file_size:
                        results["storage_freed_bytes"] += asset.file_size

                    # Remove from OpenSearch
                    if organization_id:
                        try:
                            await index_service.delete_asset_index(organization_id, doc.asset_id)
                        except:
                            pass

                    # Delete raw file from MinIO
                    if minio and asset.raw_bucket and asset.raw_object_key:
                        try:
                            minio.delete_object(asset.raw_bucket, asset.raw_object_key)
                            results["files_deleted"] += 1
                        except:
                            pass

                    # Delete extracted files
                    extraction_result = await session.execute(
                        select(ExtractionResult).where(ExtractionResult.asset_id == asset.id)
                    )
                    extractions = list(extraction_result.scalars().all())
                    for extraction in extractions:
                        if minio and extraction.extracted_bucket and extraction.extracted_object_key:
                            try:
                                minio.delete_object(extraction.extracted_bucket, extraction.extracted_object_key)
                                results["files_deleted"] += 1
                            except:
                                pass

                    # Delete extraction results
                    await session.execute(
                        sql_delete(ExtractionResult).where(ExtractionResult.asset_id == asset.id)
                    )

                    # Delete asset versions
                    await session.execute(
                        sql_delete(AssetVersion).where(AssetVersion.asset_id == asset.id)
                    )

                    # Hard delete the asset
                    await session.execute(
                        sql_delete(Asset).where(Asset.id == asset.id)
                    )
                    results["assets_deleted"] += 1

            # Remove the synced document record
            await session.delete(doc)
            results["documents_removed"] += 1

        if results["documents_removed"] > 0:
            await session.commit()

        logger.info(
            f"Cleanup completed for sync config {sync_config_id}: "
            f"docs={results['documents_removed']}, assets={results['assets_deleted']}, "
            f"files={results['files_deleted']}, freed={results['storage_freed_bytes']} bytes"
        )

        return results

    async def reset_all_synced_assets(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
    ) -> Dict[str, int]:
        """
        Delete ALL synced assets and documents for a sync config.

        Used when making breaking changes (folder_url, connection_id, or recursive: true->false)
        that would invalidate existing synced data.

        Args:
            session: Database session
            sync_config_id: Sync config UUID

        Returns:
            Reset result with counts:
            {
                "documents_removed": int,
                "assets_deleted": int,
                "files_deleted": int,
                "storage_freed_bytes": int,
            }
        """
        from .asset_service import asset_service
        from .minio_service import get_minio_service
        from .index_service import index_service
        from sqlalchemy import delete as sql_delete
        from ..database.models import ExtractionResult, AssetVersion

        # Get all synced documents (not just deleted ones)
        docs_result = await session.execute(
            select(SharePointSyncedDocument).where(
                SharePointSyncedDocument.sync_config_id == sync_config_id
            )
        )
        all_docs = list(docs_result.scalars().all())

        minio = get_minio_service()

        # Get organization_id from config
        organization_id = None
        config = await self.get_sync_config(session, sync_config_id)
        if config:
            organization_id = config.organization_id

        results = {
            "documents_removed": 0,
            "assets_deleted": 0,
            "files_deleted": 0,
            "storage_freed_bytes": 0,
        }

        for doc in all_docs:
            if doc.asset_id:
                asset = await asset_service.get_asset(session, doc.asset_id)
                if asset:
                    # Track storage freed
                    if asset.file_size:
                        results["storage_freed_bytes"] += asset.file_size

                    # Remove from OpenSearch
                    if organization_id:
                        try:
                            await index_service.delete_asset_index(organization_id, doc.asset_id)
                        except:
                            pass

                    # Delete raw file from MinIO
                    if minio and asset.raw_bucket and asset.raw_object_key:
                        try:
                            minio.delete_object(asset.raw_bucket, asset.raw_object_key)
                            results["files_deleted"] += 1
                        except:
                            pass

                    # Delete extracted files
                    extraction_result = await session.execute(
                        select(ExtractionResult).where(ExtractionResult.asset_id == asset.id)
                    )
                    extractions = list(extraction_result.scalars().all())
                    for extraction in extractions:
                        if minio and extraction.extracted_bucket and extraction.extracted_object_key:
                            try:
                                minio.delete_object(extraction.extracted_bucket, extraction.extracted_object_key)
                                results["files_deleted"] += 1
                            except:
                                pass

                    # Delete extraction results
                    await session.execute(
                        sql_delete(ExtractionResult).where(ExtractionResult.asset_id == asset.id)
                    )

                    # Delete asset versions
                    await session.execute(
                        sql_delete(AssetVersion).where(AssetVersion.asset_id == asset.id)
                    )

                    # Hard delete the asset
                    await session.execute(
                        sql_delete(Asset).where(Asset.id == asset.id)
                    )
                    results["assets_deleted"] += 1

            # Remove the synced document record
            await session.delete(doc)
            results["documents_removed"] += 1

        # Reset sync config stats
        if config:
            config.stats = {
                "total_files": 0,
                "synced_files": 0,
                "deleted_count": 0,
            }
            config.last_sync_at = None
            config.last_sync_status = None
            config.last_sync_run_id = None

        if results["documents_removed"] > 0:
            await session.flush()

        logger.info(
            f"Reset completed for sync config {sync_config_id}: "
            f"docs={results['documents_removed']}, assets={results['assets_deleted']}, "
            f"files={results['files_deleted']}, freed={results['storage_freed_bytes']} bytes"
        )

        return results

    async def remove_synced_items(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
        sharepoint_item_ids: List[str],
        delete_assets: bool = True,
    ) -> Dict[str, int]:
        """
        Remove specific synced items from a sync config.

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            sharepoint_item_ids: List of SharePoint item IDs to remove
            delete_assets: If True, also delete Asset records and storage files

        Returns:
            Dict with counts:
            {
                "documents_removed": int,
                "assets_deleted": int,
                "files_deleted": int,
            }
        """
        from .asset_service import asset_service
        from .minio_service import get_minio_service
        from .index_service import index_service
        from sqlalchemy import delete as sql_delete
        from ..database.models import ExtractionResult, AssetVersion

        # Get documents matching the item IDs
        docs_result = await session.execute(
            select(SharePointSyncedDocument).where(
                SharePointSyncedDocument.sync_config_id == sync_config_id,
                SharePointSyncedDocument.sharepoint_item_id.in_(sharepoint_item_ids),
            )
        )
        docs_to_remove = list(docs_result.scalars().all())

        if not docs_to_remove:
            return {
                "documents_removed": 0,
                "assets_deleted": 0,
                "files_deleted": 0,
            }

        minio = get_minio_service()

        # Get organization_id from config
        config = await self.get_sync_config(session, sync_config_id)
        organization_id = config.organization_id if config else None

        results = {
            "documents_removed": 0,
            "assets_deleted": 0,
            "files_deleted": 0,
        }

        for doc in docs_to_remove:
            if delete_assets and doc.asset_id:
                asset = await asset_service.get_asset(session, doc.asset_id)
                if asset:
                    # Remove from OpenSearch
                    if organization_id:
                        try:
                            await index_service.delete_asset_index(organization_id, doc.asset_id)
                        except:
                            pass

                    # Delete raw file from MinIO
                    if minio and asset.raw_bucket and asset.raw_object_key:
                        try:
                            minio.delete_object(asset.raw_bucket, asset.raw_object_key)
                            results["files_deleted"] += 1
                        except:
                            pass

                    # Delete extracted files
                    extraction_result = await session.execute(
                        select(ExtractionResult).where(ExtractionResult.asset_id == asset.id)
                    )
                    extractions = list(extraction_result.scalars().all())
                    for extraction in extractions:
                        if minio and extraction.extracted_bucket and extraction.extracted_object_key:
                            try:
                                minio.delete_object(extraction.extracted_bucket, extraction.extracted_object_key)
                                results["files_deleted"] += 1
                            except:
                                pass

                    # Delete extraction results
                    await session.execute(
                        sql_delete(ExtractionResult).where(ExtractionResult.asset_id == asset.id)
                    )

                    # Delete asset versions
                    await session.execute(
                        sql_delete(AssetVersion).where(AssetVersion.asset_id == asset.id)
                    )

                    # Hard delete the asset
                    await session.execute(
                        sql_delete(Asset).where(Asset.id == asset.id)
                    )
                    results["assets_deleted"] += 1

            # Remove the synced document record
            await session.delete(doc)
            results["documents_removed"] += 1

        if results["documents_removed"] > 0:
            await session.commit()

        logger.info(
            f"Removed {results['documents_removed']} items from sync config {sync_config_id}: "
            f"assets={results['assets_deleted']}, files={results['files_deleted']}"
        )

        return results

    async def cleanup_orphan_sharepoint_assets(
        self,
        session: AsyncSession,
        organization_id: UUID,
        delete_files: bool = True,
    ) -> Dict[str, Any]:
        """
        Clean up orphan SharePoint assets.

        Finds and deletes SharePoint assets that:
        - Have source_type='sharepoint'
        - Have a sync_config_id that no longer exists or is archived
        - OR have no sync_config_id at all

        Args:
            session: Database session
            organization_id: Organization UUID
            delete_files: If True, delete files from MinIO (default True)

        Returns:
            Dict with cleanup statistics
        """
        from .asset_service import asset_service
        from .minio_service import get_minio_service
        from .index_service import index_service
        from sqlalchemy import delete as sql_delete
        from sqlalchemy.orm import load_only
        from ..database.models import Asset, ExtractionResult, AssetVersion

        minio = get_minio_service() if delete_files else None

        results = {
            "orphan_assets_found": 0,
            "assets_deleted": 0,
            "files_deleted": 0,
            "storage_freed_bytes": 0,
            "opensearch_removed": 0,
            "errors": [],
        }

        # Get all SharePoint assets for this organization
        assets_result = await session.execute(
            select(Asset).where(
                and_(
                    Asset.organization_id == organization_id,
                    Asset.source_type == "sharepoint",
                    Asset.status != "deleted",
                )
            )
        )
        sharepoint_assets = list(assets_result.scalars().all())

        # Get all active (non-archived) sync config IDs
        configs_result = await session.execute(
            select(SharePointSyncConfig.id).where(
                and_(
                    SharePointSyncConfig.organization_id == organization_id,
                    SharePointSyncConfig.status != "archived",
                )
            )
        )
        active_config_ids = {str(c) for c in configs_result.scalars().all()}

        # Find orphan assets
        orphan_assets = []
        for asset in sharepoint_assets:
            source_meta = asset.source_metadata or {}
            sync_config_id = source_meta.get("sync_config_id")

            # Asset is orphan if:
            # 1. No sync_config_id at all
            # 2. sync_config_id doesn't exist in active configs
            if not sync_config_id or sync_config_id not in active_config_ids:
                orphan_assets.append(asset)

        results["orphan_assets_found"] = len(orphan_assets)

        if not orphan_assets:
            logger.info(f"No orphan SharePoint assets found for org {organization_id}")
            return results

        logger.info(f"Found {len(orphan_assets)} orphan SharePoint assets for org {organization_id}")

        # Delete orphan assets
        for asset in orphan_assets:
            try:
                # Track storage freed
                if asset.file_size:
                    results["storage_freed_bytes"] += asset.file_size

                # Remove from OpenSearch
                try:
                    await index_service.delete_asset_index(organization_id, asset.id)
                    results["opensearch_removed"] += 1
                except Exception as e:
                    results["errors"].append(f"OpenSearch removal failed for {asset.id}: {e}")

                # Delete raw file from MinIO
                if minio and asset.raw_bucket and asset.raw_object_key:
                    try:
                        minio.delete_object(asset.raw_bucket, asset.raw_object_key)
                        results["files_deleted"] += 1
                    except Exception as e:
                        results["errors"].append(f"Raw file deletion failed for {asset.id}: {e}")

                # Delete extracted files
                extraction_result = await session.execute(
                    select(ExtractionResult).where(ExtractionResult.asset_id == asset.id)
                )
                extractions = list(extraction_result.scalars().all())
                for extraction in extractions:
                    if minio and extraction.extracted_bucket and extraction.extracted_object_key:
                        try:
                            minio.delete_object(extraction.extracted_bucket, extraction.extracted_object_key)
                            results["files_deleted"] += 1
                        except:
                            pass

                # Delete extraction results
                await session.execute(
                    sql_delete(ExtractionResult).where(ExtractionResult.asset_id == asset.id)
                )

                # Delete asset versions
                await session.execute(
                    sql_delete(AssetVersion).where(AssetVersion.asset_id == asset.id)
                )

                # Delete any orphan synced document records
                await session.execute(
                    sql_delete(SharePointSyncedDocument).where(
                        SharePointSyncedDocument.asset_id == asset.id
                    )
                )

                # Hard delete the asset
                await session.execute(
                    sql_delete(Asset).where(Asset.id == asset.id)
                )
                results["assets_deleted"] += 1

            except Exception as e:
                results["errors"].append(f"Failed to delete asset {asset.id}: {e}")

        await session.commit()

        logger.info(
            f"Orphan SharePoint asset cleanup for org {organization_id}: "
            f"found={results['orphan_assets_found']}, deleted={results['assets_deleted']}, "
            f"files={results['files_deleted']}, freed={results['storage_freed_bytes']} bytes"
        )

        return results


# Singleton instance
sharepoint_sync_service = SharePointSyncService()
