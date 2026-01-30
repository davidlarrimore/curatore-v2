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
        """
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

        await session.commit()
        await session.refresh(config)

        logger.info(f"Updated sync config {sync_config_id}: {list(updates.keys())}")

        return config

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
            "errors": [],
        }

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
            f"opensearch_removed={stats['opensearch_removed']}"
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
        1. Delete all associated assets (soft delete)
        2. Remove documents from OpenSearch index
        3. Delete SharePointSyncedDocument records
        4. Delete related Run records
        5. Delete the sync config itself

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            organization_id: Organization UUID for OpenSearch

        Returns:
            Dict with cleanup statistics
        """
        from .asset_service import asset_service
        from .index_service import index_service
        from sqlalchemy import delete as sql_delete, func

        config = await self.get_sync_config(session, sync_config_id)
        if not config:
            return {"error": "Sync config not found"}

        stats = {
            "assets_deleted": 0,
            "documents_deleted": 0,
            "runs_deleted": 0,
            "opensearch_removed": 0,
            "errors": [],
        }

        # 1. Get all synced documents
        docs_result = await session.execute(
            select(SharePointSyncedDocument).where(
                SharePointSyncedDocument.sync_config_id == sync_config_id
            )
        )
        synced_docs = list(docs_result.scalars().all())

        # 2. Delete assets and remove from OpenSearch
        for doc in synced_docs:
            if doc.asset_id:
                try:
                    # Remove from OpenSearch
                    await index_service.delete_asset_index(organization_id, doc.asset_id)
                    stats["opensearch_removed"] += 1
                except Exception as e:
                    stats["errors"].append(f"OpenSearch removal failed for {doc.asset_id}: {e}")

                try:
                    # Soft delete the asset
                    asset = await asset_service.get_asset(session, doc.asset_id)
                    if asset:
                        asset.status = "deleted"
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
        from .sharepoint_service import sharepoint_inventory
        from .run_service import run_service

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

        # Get connection for auth
        connection = None
        if config.connection_id:
            conn_result = await session.execute(
                select(Connection).where(Connection.id == config.connection_id)
            )
            connection = conn_result.scalar_one_or_none()

        # Get folder inventory from SharePoint
        logger.info(f"Getting SharePoint inventory for {config.folder_url}")

        try:
            inventory = await sharepoint_inventory(
                folder_url=config.folder_url,
                recursive=recursive,
                include_folders=False,  # Only files
                page_size=100,
                max_items=None,  # Get all
                organization_id=organization_id,
                session=session,
            )
        except Exception as e:
            logger.error(f"Failed to get SharePoint inventory: {e}")
            raise

        # Cache folder info
        folder_info = inventory.get("folder", {})
        if folder_info:
            config.folder_name = folder_info.get("name")
            config.folder_drive_id = folder_info.get("drive_id")
            config.folder_item_id = folder_info.get("id")

        items = inventory.get("items", [])
        logger.info(f"Found {len(items)} files in SharePoint folder")

        # Filter items
        filtered_items = self._filter_items(
            items, include_patterns, exclude_patterns, max_file_size_mb
        )
        logger.info(f"After filtering: {len(filtered_items)} files to sync")

        # Track current item IDs for deletion detection
        current_item_ids = {item.get("id") for item in filtered_items if item.get("id")}

        # Process each item
        total_files = len(filtered_items)
        results = {
            "total_files": total_files,
            "new_files": 0,
            "updated_files": 0,
            "unchanged_files": 0,
            "skipped_files": 0,
            "failed_files": 0,
            "deleted_detected": 0,
            "errors": [],
        }

        # Initialize config stats for progress tracking
        config.stats = {
            "total_files": total_files,
            "synced_files": 0,
            "processed_files": 0,
            "new_files": 0,
            "updated_files": 0,
            "unchanged_files": 0,
            "failed_files": 0,
            "deleted_count": 0,
            "current_file": None,
            "phase": "syncing",
        }
        await session.commit()

        # Update run progress with total
        await run_service.update_run_progress(
            session=session,
            run_id=run_id,
            current=0,
            total=total_files,
            unit="files",
        )

        for idx, item in enumerate(filtered_items):
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
            except Exception as e:
                logger.error(f"Failed to sync file {item.get('name')}: {e}")
                results["failed_files"] += 1
                results["errors"].append({
                    "file": item.get("name"),
                    "error": str(e),
                })

            # Update incremental stats after each file
            processed = idx + 1
            config.stats = {
                "total_files": total_files,
                "synced_files": results["new_files"] + results["updated_files"] + results["unchanged_files"],
                "processed_files": processed,
                "new_files": results["new_files"],
                "updated_files": results["updated_files"],
                "unchanged_files": results["unchanged_files"],
                "failed_files": results["failed_files"],
                "deleted_count": 0,
                "current_file": current_file,
                "phase": "syncing",
            }

            # Update run progress
            await run_service.update_run_progress(
                session=session,
                run_id=run_id,
                current=processed,
                total=total_files,
                unit="files",
            )

            # Commit after each file to make progress visible
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

        # Update final sync config stats and tracking
        config.last_sync_at = datetime.utcnow()
        config.last_sync_status = "success" if results["failed_files"] == 0 else "partial"
        config.last_sync_run_id = run_id
        config.stats = {
            "total_files": results["total_files"],
            "synced_files": results["new_files"] + results["updated_files"] + results["unchanged_files"],
            "processed_files": total_files,
            "new_files": results["new_files"],
            "updated_files": results["updated_files"],
            "unchanged_files": results["unchanged_files"],
            "failed_files": results["failed_files"],
            "deleted_count": deleted_count,
            "current_file": None,
            "phase": "completed",
            "last_sync_results": results,
        }

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

        # Check if we already have this file
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
        else:
            # New file - download and create asset
            return await self._download_and_create_asset(
                session=session,
                config=config,
                item=item,
                run_id=run_id,
            )

    async def _download_and_create_asset(
        self,
        session: AsyncSession,
        config: SharePointSyncConfig,
        item: Dict[str, Any],
        run_id: UUID,
    ) -> str:
        """Download a new file and create an asset."""
        from .asset_service import asset_service
        from .minio_service import get_minio_service
        from .sharepoint_service import sharepoint_download

        minio_service = get_minio_service()
        if not minio_service:
            raise RuntimeError("MinIO service is not available")

        item_id = item.get("id")
        name = item.get("name", "unknown")
        folder_path = item.get("folder", "").strip("/")
        size = item.get("size")
        web_url = item.get("web_url")
        etag = item.get("etag") or item.get("eTag")
        created = item.get("created")
        modified = item.get("modified")
        created_by = item.get("created_by")
        modified_by = item.get("last_modified_by")
        mime_type = item.get("mime") or item.get("file_type")

        # Parse dates
        created_at = None
        modified_at = None
        if created:
            try:
                created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except:
                pass
        if modified:
            try:
                modified_at = datetime.fromisoformat(modified.replace("Z", "+00:00"))
            except:
                pass

        # Generate storage path
        org_id_str = str(config.organization_id)
        storage_key = storage_paths.sharepoint_sync(
            org_id=org_id_str,
            sync_slug=config.slug,
            relative_path=folder_path,
            filename=name,
            extracted=False,
        )

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
        uploads_bucket = minio_service.bucket_uploads
        minio_service.put_object(
            bucket=uploads_bucket,
            key=storage_key,
            data=BytesIO(file_content),
            length=len(file_content),
            content_type=mime_type or "application/octet-stream",
        )

        # Create asset
        actual_size = len(file_content)
        asset = await asset_service.create_asset(
            session=session,
            organization_id=config.organization_id,
            source_type="sharepoint",
            source_metadata={
                "sync_config_id": str(config.id),
                "sync_config_name": config.name,
                "sharepoint_item_id": item_id,
                "sharepoint_drive_id": drive_id,
                "sharepoint_path": folder_path,
                "sharepoint_web_url": web_url,
                "folder_url": config.folder_url,
            },
            original_filename=name,
            raw_bucket=uploads_bucket,
            raw_object_key=storage_key,
            content_type=mime_type or "application/octet-stream",
            file_size=actual_size,
            file_hash=content_hash,
            status="pending",  # Will trigger extraction
        )

        # Create synced document record
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
        )

        await session.flush()

        logger.info(f"Created asset {asset.id} from SharePoint file: {name}")

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

        item_id = item.get("id")
        name = item.get("name", "unknown")
        folder_path = item.get("folder", "").strip("/")
        size = item.get("size")
        etag = item.get("etag") or item.get("eTag")
        modified = item.get("modified")
        modified_by = item.get("last_modified_by")
        mime_type = item.get("mime") or item.get("file_type")

        modified_at = None
        if modified:
            try:
                modified_at = datetime.fromisoformat(modified.replace("Z", "+00:00"))
            except:
                pass

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
        asset.file_size = len(file_content)  # Use actual downloaded size
        asset.file_hash = content_hash
        asset.content_type = mime_type or "application/octet-stream"
        asset.status = "pending"  # Re-trigger extraction
        asset.updated_at = datetime.utcnow()

        # Update synced document record
        await self.update_synced_document(
            session, existing_doc,
            sharepoint_etag=etag,
            content_hash=content_hash,
            sharepoint_modified_at=modified_at,
            sharepoint_modified_by=modified_by,
            file_size=len(file_content),  # Use actual downloaded size
            sync_status="synced",
            last_synced_at=datetime.utcnow(),
            last_sync_run_id=run_id,
        )

        await session.flush()

        logger.info(f"Updated asset {asset.id} from SharePoint file: {name}")

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
            delete_assets: If True, also soft-delete the Asset records

        Returns:
            Cleanup result with counts
        """
        from .asset_service import asset_service

        deleted_docs = await self.get_deleted_documents(session, sync_config_id)

        results = {
            "documents_removed": 0,
            "assets_deleted": 0,
        }

        for doc in deleted_docs:
            if delete_assets:
                # Soft-delete the asset
                asset = await asset_service.get_asset(session, doc.asset_id)
                if asset:
                    asset.status = "deleted"
                    asset.updated_at = datetime.utcnow()
                    results["assets_deleted"] += 1

            # Remove the synced document record
            await session.delete(doc)
            results["documents_removed"] += 1

        if results["documents_removed"] > 0:
            await session.commit()

        logger.info(
            f"Cleanup completed for sync config {sync_config_id}: "
            f"docs={results['documents_removed']}, assets={results['assets_deleted']}"
        )

        return results


# Singleton instance
sharepoint_sync_service = SharePointSyncService()
