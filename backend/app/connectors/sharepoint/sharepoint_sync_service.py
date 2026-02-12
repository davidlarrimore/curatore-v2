"""
SharePoint Sync Service for managing SharePoint folder synchronization.

Provides operations for:
- Sync config CRUD (create, read, update, archive)
- Sync execution (one-way pull from SharePoint)
- File sync (create/update assets from SharePoint files)
- Deleted file detection and cleanup

Usage:
    from app.connectors.sharepoint.sharepoint_sync_service import sharepoint_sync_service

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

import asyncio
import hashlib
import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import httpx


def _to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert a datetime to naive UTC (strip timezone info).

    PostgreSQL TIMESTAMP WITHOUT TIME ZONE columns expect naive datetimes.
    This ensures SharePoint's timezone-aware datetimes are stored correctly.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        # Convert to UTC then strip timezone
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database.models import (
    Asset,
    Connection,
    Run,
    RunLogEvent,
    SharePointSyncConfig,
    SharePointSyncedDocument,
)
from app.core.storage.storage_path_service import storage_paths

logger = logging.getLogger("curatore.sharepoint_sync")


# =============================================================================
# BATCH COMMIT CONFIGURATION
# =============================================================================

# Commit database changes every N files to reduce PostgreSQL checkpoint pressure.
# Large syncs (4000+ files) with per-file commits cause massive WAL writes and
# checkpoint overload. Batching commits reduces I/O and prevents worker stalls.
BATCH_COMMIT_SIZE = 50


# =============================================================================
# FILE DOWNLOAD WITH RETRY LOGIC
# =============================================================================

# Transient errors that should trigger a retry
TRANSIENT_ERROR_PATTERNS = (
    "Server disconnected",
    "Connection reset",
    "Connection refused",
    "RemoteProtocolError",
    "ReadTimeout",
    "WriteTimeout",
    "ConnectTimeout",
)


async def _download_file_with_retry(
    organization_id: UUID,
    session: AsyncSession,
    drive_id: str,
    item_id: str,
    file_name: str,
    max_retries: int = 3,
    retry_delay_seconds: int = 30,
) -> bytes:
    """
    Download a file from SharePoint with retry logic for transient errors.

    Features:
    - Retries on network errors (server disconnected, connection reset, etc.)
    - Retries on 401 with token refresh
    - Retries on 429 (rate limiting) with Retry-After header support
    - 30 second wait between retries by default

    Args:
        organization_id: Organization UUID for credentials lookup
        session: Database session for credentials lookup
        drive_id: SharePoint drive ID
        item_id: SharePoint item ID
        file_name: File name for logging
        max_retries: Maximum retry attempts (default: 3)
        retry_delay_seconds: Seconds to wait between retries (default: 30)

    Returns:
        File content as bytes

    Raises:
        Exception if all retries fail
    """
    from .sharepoint_service import (
        TokenManager,
        _get_sharepoint_credentials,
        _graph_base_url,
    )

    credentials = await _get_sharepoint_credentials(organization_id, session)
    tenant_id = credentials["tenant_id"]
    client_id = credentials["client_id"]
    client_secret = credentials["client_secret"]

    graph_base = _graph_base_url()
    download_url = f"{graph_base}/drives/{drive_id}/items/{item_id}/content"

    # Create token manager for automatic refresh
    token_manager = TokenManager(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )

    last_error = None

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        # Get initial token
        await token_manager.get_valid_token(client)

        for attempt in range(max_retries + 1):
            try:
                headers = token_manager.get_headers()

                with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                    async with client.stream("GET", download_url, headers=headers) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes():
                            tmp_file.write(chunk)
                    tmp_path = tmp_file.name

                # Read file content
                try:
                    with open(tmp_path, "rb") as f:
                        file_content = f.read()
                    return file_content
                finally:
                    # Clean up temp file
                    try:
                        Path(tmp_path).unlink()
                    except Exception:
                        pass

            except httpx.HTTPStatusError as e:
                last_error = e
                status_code = e.response.status_code

                if status_code == 401:
                    # Token expired - refresh and retry
                    if attempt < max_retries:
                        logger.warning(
                            f"Download {file_name}: 401 Unauthorized (attempt {attempt + 1}/{max_retries + 1}). "
                            f"Refreshing token and retrying..."
                        )
                        await token_manager.refresh_token(client)
                        continue
                elif status_code == 429:
                    # Rate limited - wait and retry
                    retry_after = int(e.response.headers.get("Retry-After", retry_delay_seconds))
                    if attempt < max_retries:
                        logger.warning(
                            f"Download {file_name}: Rate limited (429). "
                            f"Waiting {retry_after}s before retry..."
                        )
                        await asyncio.sleep(retry_after)
                        continue
                elif status_code >= 500:
                    # Server error - retry with delay
                    if attempt < max_retries:
                        logger.warning(
                            f"Download {file_name}: Server error {status_code} "
                            f"(attempt {attempt + 1}/{max_retries + 1}). "
                            f"Waiting {retry_delay_seconds}s..."
                        )
                        await asyncio.sleep(retry_delay_seconds)
                        continue
                # 4xx errors (except 401, 429) - don't retry
                raise

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout,
                    httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(
                        f"Download {file_name}: Network error (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Waiting {retry_delay_seconds}s..."
                    )
                    await asyncio.sleep(retry_delay_seconds)
                    # Refresh token in case it expired during the wait
                    await token_manager.get_valid_token(client)
                    continue
                raise

            except Exception as e:
                last_error = e
                error_str = str(e)
                is_transient = any(
                    pattern.lower() in error_str.lower()
                    for pattern in TRANSIENT_ERROR_PATTERNS
                )

                if is_transient and attempt < max_retries:
                    logger.warning(
                        f"Download {file_name}: Transient error (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Waiting {retry_delay_seconds}s..."
                    )
                    await asyncio.sleep(retry_delay_seconds)
                    await token_manager.get_valid_token(client)
                    continue
                raise

    # All retries exhausted
    if last_error:
        raise last_error
    raise RuntimeError(f"Download failed for {file_name} after {max_retries + 1} attempts")


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
        site_name: Optional[str] = None,
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
            site_name=site_name,
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

        # If disabling, cancel all pending jobs for this sync config
        if is_disabling:
            cancelled_count = await self._cancel_pending_jobs_for_sync_config(
                session, sync_config_id, config.organization_id
            )
            if cancelled_count > 0:
                logger.info(
                    f"Cancelled {cancelled_count} pending job(s) for disabled sync config {sync_config_id}"
                )

        await session.commit()
        await session.refresh(config)

        logger.info(f"Updated sync config {sync_config_id}: {list(updates.keys())}")

        return config

    async def _cancel_pending_jobs_for_sync_config(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
        organization_id: UUID,
    ) -> int:
        """
        Cancel all pending jobs for assets in a sync config by storage path.

        Uses the sync config's slug to find ALL assets with matching storage paths,
        regardless of whether they have SharePointSyncedDocument tracking records.
        Cancels both extraction and extraction_enhancement jobs.

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            organization_id: Organization UUID

        Returns:
            Number of runs cancelled
        """
        from app.celery_app import app as celery_app

        # Get sync config to find slug
        config = await self.get_sync_config(session, sync_config_id)
        if not config or not config.slug:
            return 0

        # Build storage path prefix: {org_id}/sharepoint/{slug}/
        path_prefix = f"{organization_id}/sharepoint/{config.slug}/"

        # Find all assets with this storage path prefix
        asset_query = select(Asset.id).where(
            and_(
                Asset.organization_id == organization_id,
                Asset.raw_object_key.like(f"{path_prefix}%"),
            )
        )
        asset_result = await session.execute(asset_query)
        asset_ids = {str(row[0]) for row in asset_result.fetchall()}

        if not asset_ids:
            logger.info(f"No assets found with path prefix {path_prefix}")
            return 0

        logger.info(f"Found {len(asset_ids)} assets with path prefix {path_prefix}")

        # Find all pending jobs (extraction and extraction_enhancement)
        runs_query = select(Run).where(
            and_(
                Run.organization_id == organization_id,
                Run.run_type.in_(["extraction", "extraction_enhancement"]),
                Run.status.in_(["pending", "submitted", "running"]),
            )
        )
        runs_result = await session.execute(runs_query)
        runs = runs_result.scalars().all()

        cancelled_count = 0
        for run in runs:
            run_asset_ids = run.input_asset_ids or []
            if any(asset_id in asset_ids for asset_id in run_asset_ids):
                # Revoke Celery task if submitted
                if run.celery_task_id and run.status in ("submitted", "running"):
                    try:
                        celery_app.control.revoke(run.celery_task_id, terminate=True)
                    except Exception as e:
                        logger.warning(f"Failed to revoke task {run.celery_task_id}: {e}")

                run.status = "cancelled"
                run.completed_at = datetime.utcnow()
                run.error_message = "Cancelled: SharePoint sync archived"
                cancelled_count += 1

        logger.info(f"Cancelled {cancelled_count} jobs for sync config {sync_config_id}")
        return cancelled_count

    async def archive_sync_config_with_search_cleanup(
        self,
        session: AsyncSession,
        sync_config_id: UUID,
        organization_id: UUID,
    ) -> Dict[str, Any]:
        """
        Archive a sync config and remove documents from search index.

        This removes documents from search but keeps assets intact:
        1. Remove documents from search index
        2. Set config status to "archived"

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            organization_id: Organization UUID for search index

        Returns:
            Dict with cleanup statistics
        """
        from app.core.search.pg_index_service import pg_index_service

        config = await self.get_sync_config(session, sync_config_id)
        if not config:
            return {"error": "Sync config not found"}

        stats = {
            "search_removed": 0,
            "jobs_cancelled": 0,
            "errors": [],
        }

        # Cancel all pending jobs (extraction + enhancement) by storage path
        cancelled_count = await self._cancel_pending_jobs_for_sync_config(
            session, sync_config_id, organization_id
        )
        stats["jobs_cancelled"] = cancelled_count

        # Get all synced documents
        docs_result = await session.execute(
            select(SharePointSyncedDocument).where(
                SharePointSyncedDocument.sync_config_id == sync_config_id
            )
        )
        synced_docs = list(docs_result.scalars().all())

        # Remove from search index only
        for doc in synced_docs:
            if doc.asset_id:
                try:
                    await pg_index_service.delete_asset_index(session, organization_id, doc.asset_id)
                    stats["search_removed"] += 1
                except Exception as e:
                    stats["errors"].append(f"Search index removal failed for {doc.asset_id}: {e}")

        # Set config to archived status
        config.status = "archived"
        config.is_active = False
        config.updated_at = datetime.utcnow()

        await session.commit()

        logger.info(
            f"Archived sync config {sync_config_id}: "
            f"search_removed={stats['search_removed']}, "
            f"jobs_cancelled={stats['jobs_cancelled']}"
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
        3. Remove documents from search index
        4. Delete SharePointSyncedDocument records
        5. Delete related Run records
        6. Delete the sync config itself

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            organization_id: Organization UUID for search index

        Returns:
            Dict with cleanup statistics
        """
        from sqlalchemy import delete as sql_delete
        from sqlalchemy import func

        from app.core.database.models import AssetVersion, ExtractionResult
        from app.core.search.pg_index_service import pg_index_service
        from app.core.storage.minio_service import get_minio_service

        config = await self.get_sync_config(session, sync_config_id)
        if not config:
            return {"error": "Sync config not found"}

        minio = get_minio_service()

        stats = {
            "assets_deleted": 0,
            "files_deleted": 0,
            "documents_deleted": 0,
            "runs_deleted": 0,
            "jobs_cancelled": 0,
            "search_removed": 0,
            "storage_freed_bytes": 0,
            "errors": [],
        }

        # 0. Cancel all pending jobs (extraction + enhancement) by storage path
        cancelled_count = await self._cancel_pending_jobs_for_sync_config(
            session, sync_config_id, organization_id
        )
        stats["jobs_cancelled"] = cancelled_count

        # 1. Find ALL assets by storage path (not just tracked ones)
        # This catches orphaned assets from failed syncs
        path_prefix = f"{organization_id}/sharepoint/{config.slug}/"
        assets_result = await session.execute(
            select(Asset).where(
                and_(
                    Asset.organization_id == organization_id,
                    Asset.raw_object_key.like(f"{path_prefix}%"),
                )
            )
        )
        assets = list(assets_result.scalars().all())
        logger.info(f"Found {len(assets)} assets with path prefix {path_prefix}")

        # 2. Delete assets, files from MinIO, and remove from search index
        for asset in assets:
            try:
                # Remove from search index
                await pg_index_service.delete_asset_index(session, organization_id, asset.id)
                stats["search_removed"] += 1
            except Exception as e:
                stats["errors"].append(f"Search index removal failed for {asset.id}: {e}")

            try:
                # Track storage freed
                if asset.file_size:
                    stats["storage_freed_bytes"] += asset.file_size

                # Delete raw file from MinIO
                if minio and asset.raw_bucket and asset.raw_object_key:
                    try:
                        minio.delete_object(asset.raw_bucket, asset.raw_object_key)
                        stats["files_deleted"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Failed to delete raw file for {asset.id}: {e}")

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
                        except Exception:
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
                stats["errors"].append(f"Asset deletion failed for {asset.id}: {e}")

        # 3. Delete SharePointSyncedDocument records
        docs_result = await session.execute(
            select(func.count()).select_from(SharePointSyncedDocument).where(
                SharePointSyncedDocument.sync_config_id == sync_config_id
            )
        )
        docs_count = docs_result.scalar() or 0
        await session.execute(
            sql_delete(SharePointSyncedDocument).where(
                SharePointSyncedDocument.sync_config_id == sync_config_id
            )
        )
        stats["documents_deleted"] = docs_count

        # 4. Delete related Runs (PostgreSQL JSON: column["key"].astext)
        runs_result = await session.execute(
            select(Run).where(
                Run.config["sync_config_id"].astext == str(sync_config_id)
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
            f"assets={stats['assets_deleted']}, files={stats['files_deleted']}, "
            f"docs={stats['documents_deleted']}, runs={stats['runs_deleted']}, "
            f"jobs_cancelled={stats['jobs_cancelled']}, search={stats['search_removed']}"
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
        organization_id: UUID,
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
            organization_id: Organization UUID for multi-tenant isolation
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
            organization_id=organization_id,
            sync_config_id=sync_config_id,
            asset_id=asset_id,
            sharepoint_item_id=sharepoint_item_id,
            sharepoint_drive_id=sharepoint_drive_id,
            sharepoint_path=sharepoint_path,
            sharepoint_web_url=sharepoint_web_url,
            sharepoint_etag=sharepoint_etag,
            content_hash=content_hash,
            sharepoint_created_at=_to_naive_utc(sharepoint_created_at),
            sharepoint_modified_at=_to_naive_utc(sharepoint_modified_at),
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

        # Fields that need timezone conversion
        datetime_fields = {"sharepoint_modified_at", "last_synced_at", "deleted_detected_at"}

        for field, value in updates.items():
            if field in allowed_fields:
                # Convert timezone-aware datetimes to naive UTC
                if field in datetime_fields and value is not None:
                    value = _to_naive_utc(value)
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
        use_delta: Optional[bool] = None,
        group_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Execute synchronization for a sync config.

        This is the main sync entry point, typically called from a Celery task.
        It supports two sync modes:

        1. Full Sync (default or when delta not available):
           - Enumerates all files via folder traversal
           - Compares etags to detect changes
           - Downloads new/updated files
           - Detects deleted files by missing items

        2. Delta Sync (when delta_enabled and token available):
           - Queries Microsoft Graph Delta API
           - Only returns changed/deleted items since last sync
           - Much faster for large sites with few changes

        Args:
            session: Database session
            sync_config_id: Sync config UUID
            organization_id: Organization UUID
            run_id: Run UUID for tracking
            full_sync: If True, re-download all files regardless of etag
            use_delta: Override delta_enabled setting (None = use config setting)

        Returns:
            Sync result dict with statistics
        """
        from app.core.shared.run_log_service import run_log_service
        from app.core.shared.run_service import run_service

        from .sharepoint_service import DeltaTokenExpiredError, sharepoint_inventory_stream

        # =================================================================
        # PHASE 1: INITIALIZATION
        # =================================================================
        await run_service.update_run_progress(
            session=session,
            run_id=run_id,
            current=0,
            total=None,
            unit="files",
            phase="initializing",
        )
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

        # Safety net: resolve site_name if not yet set (e.g., config created via API without browse)
        if not config.site_name:
            try:
                from .sharepoint_service import get_site_metadata
                site_meta = await get_site_metadata(
                    folder_url=config.folder_url,
                    organization_id=organization_id,
                    session=session,
                )
                if site_meta:
                    config.site_name = site_meta.get("display_name") or site_meta.get("name")
                    await session.flush()
            except Exception:
                logger.warning(f"Could not resolve site_name for config {sync_config_id}")

        sync_settings = config.sync_config or {}
        recursive = sync_settings.get("recursive", True)
        include_patterns = sync_settings.get("include_patterns", [])
        exclude_patterns = sync_settings.get("exclude_patterns", [])
        folder_exclude_patterns = sync_settings.get("folder_exclude_patterns", [])
        max_file_size_mb = sync_settings.get("max_file_size_mb", 100)

        # Parse min_modified_date filter (skip files older than this date)
        min_modified_date: Optional[datetime] = None
        min_modified_date_str = sync_settings.get("min_modified_date")
        if min_modified_date_str:
            try:
                from dateutil.parser import parse as parse_date
                min_modified_date = parse_date(min_modified_date_str)
                # Convert to naive UTC for consistent comparison
                if min_modified_date.tzinfo is not None:
                    min_modified_date = min_modified_date.astimezone(timezone.utc).replace(tzinfo=None)
            except (ValueError, TypeError) as e:
                logger.warning(f"Could not parse min_modified_date '{min_modified_date_str}': {e}")

        # Selection mode: 'all' syncs everything, 'selected' uses folder/file selection
        selection_mode = sync_settings.get("selection_mode", "all")

        # Folder/file selection filters (only used when selection_mode is 'selected')
        # selected_folders: List of folder paths - sync all contents recursively
        # selected_files: List of {item_id, path, name} - sync only these specific files
        selected_folders = sync_settings.get("selected_folders", [])
        selected_files = sync_settings.get("selected_files", [])
        selected_file_ids = {f.get("item_id") for f in selected_files if f.get("item_id")}
        # Only apply selection filter if mode is 'selected' AND there are selections
        has_selection_filter = (
            selection_mode == "selected" and bool(selected_folders or selected_files)
        )

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
                "folder_exclude_patterns": folder_exclude_patterns,
                "selection_mode": selection_mode,
                "selected_folders": len(selected_folders),
                "selected_files": len(selected_files),
                "min_modified_date": min_modified_date.isoformat() if min_modified_date else None,
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
        # DELTA SYNC DECISION
        # =================================================================
        # Incremental syncs (full_sync=False) should always use delta when possible:
        # 1. use_delta parameter takes precedence if explicitly specified
        # 2. Otherwise, incremental syncs default to delta (if token available)
        # 3. full_sync=True always does full enumeration
        # 4. Must have a valid delta token to actually use delta
        #
        # The config.delta_enabled setting controls whether to CAPTURE new delta
        # tokens during full syncs, not whether to USE them for incremental syncs.
        if use_delta is not None:
            # Explicit override
            should_use_delta = use_delta
        elif full_sync:
            # Full sync = full enumeration
            should_use_delta = False
        else:
            # Incremental sync = use delta if we have a token
            should_use_delta = True

        if should_use_delta and config.delta_token:
            # Use delta sync path for incremental sync
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="progress",
                message="Using delta sync for incremental changes",
                context={"phase": "init", "sync_method": "delta"},
            )
            await session.commit()

            try:
                return await self._execute_delta_sync(
                    session=session,
                    config=config,
                    organization_id=organization_id,
                    run_id=run_id,
                    include_patterns=include_patterns,
                    exclude_patterns=exclude_patterns,
                    max_file_size_mb=max_file_size_mb,
                    min_modified_date=min_modified_date,
                    has_selection_filter=has_selection_filter,
                    selected_folders=selected_folders,
                    selected_file_ids=selected_file_ids,
                    group_id=group_id,
                )
            except DeltaTokenExpiredError:
                # Delta token expired - fall through to full sync
                logger.warning(f"Delta token expired for {config.name}, falling back to full sync")
                await run_log_service.log_event(
                    session=session,
                    run_id=run_id,
                    level="WARNING",
                    event_type="progress",
                    message="Delta token expired, performing full sync to refresh",
                    context={"phase": "init", "reason": "delta_token_expired"},
                )
                # Clear expired token
                config.delta_token = None
                config.delta_token_acquired_at = None
                await session.commit()
        elif should_use_delta and not config.delta_token:
            # Wanted to use delta but no token available
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="progress",
                message="No delta token available - performing full enumeration to establish baseline",
                context={"phase": "init", "sync_method": "full_enumeration", "reason": "no_delta_token"},
            )
            await session.commit()

        # =================================================================
        # PHASE 2: CONNECTING & STREAMING SYNC (FULL ENUMERATION)
        # =================================================================
        await run_service.update_run_progress(
            session=session,
            run_id=run_id,
            current=0,
            total=None,
            unit="files",
            phase="connecting",
        )
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
            "skipped_folders": 0,
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
            "skipped_folders": 0,
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
                        "skipped_folders": results["skipped_folders"],
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

        # Callback for skipped folders (due to folder_exclude_patterns)
        async def on_folder_skipped(folder_name: str, folder_path: str):
            results["skipped_folders"] += 1
            logger.debug(f"Skipped excluded folder: {folder_path}")

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
                on_folder_skipped=on_folder_skipped,
                folder_exclude_patterns=folder_exclude_patterns,
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
                if not self._item_passes_filter(item, include_patterns, exclude_patterns, max_file_size_mb, min_modified_date):
                    results["skipped_files"] += 1
                    continue

                # Skip if we've already processed this item (deduplication)
                item_id = item.get("id")
                if item_id in current_item_ids:
                    logger.debug(f"Skipping duplicate item: {item.get('name')} (id: {item_id})")
                    continue

                # Skip if item doesn't match folder/file selection (if any)
                if has_selection_filter:
                    if not self._item_matches_selection(
                        item, selected_folders, selected_file_ids
                    ):
                        results["skipped_files"] += 1
                        continue

                results["total_files"] += 1
                current_item_ids.add(item_id)

                # Process this file immediately
                current_file = item.get("name", "unknown")
                try:
                    result = await self._sync_single_file(
                        session=session,
                        config=config,
                        item=item,
                        run_id=run_id,
                        full_sync=full_sync,
                        group_id=group_id,
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
                            context={"phase": "scanning_and_syncing", "file": current_file, "action": "new", "folder": item.get("folder", "")},
                        )
                    elif result == "updated_files":
                        await run_log_service.log_event(
                            session=session,
                            run_id=run_id,
                            level="INFO",
                            event_type="file_download",
                            message=f"Updated: {current_file}",
                            context={"phase": "scanning_and_syncing", "file": current_file, "action": "updated", "folder": item.get("folder", "")},
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
                        context={"phase": "scanning_and_syncing", "file": current_file, "error": str(e), "folder": item.get("folder", "")},
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

                # Batch commit every N files to reduce PostgreSQL checkpoint pressure
                # (per-file commits with 4000+ files cause massive WAL writes)
                if processed_files % BATCH_COMMIT_SIZE == 0:
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
                "skipped_folders": results["skipped_folders"],
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
                "skipped_folders": results["skipped_folders"],
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
            "skipped_folders": results["skipped_folders"],
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
            "skipped_folders": results["skipped_folders"],
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

        # =================================================================
        # CAPTURE DELTA TOKEN (auto-enable on successful full sync)
        # =================================================================
        # After a successful full sync with no failures, automatically enable delta
        # and capture the token for future incremental syncs
        if results["failed_files"] == 0:
            try:
                # Auto-enable delta on first successful full sync
                if not config.delta_enabled:
                    config.delta_enabled = True
                    logger.info(f"Auto-enabled delta for config {config.id} after successful full sync")

                await self._capture_initial_delta_token(
                    session=session,
                    config=config,
                    organization_id=organization_id,
                    run_id=run_id,
                )
            except Exception as e:
                logger.warning(f"Failed to capture delta token after full sync: {e}")
                # Don't fail the sync, just log the warning

        return results

    async def _execute_delta_sync(
        self,
        session: AsyncSession,
        config: SharePointSyncConfig,
        organization_id: UUID,
        run_id: UUID,
        include_patterns: List[str],
        exclude_patterns: List[str],
        max_file_size_mb: int,
        min_modified_date: Optional[datetime],
        has_selection_filter: bool,
        selected_folders: List[str],
        selected_file_ids: set,
        group_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Execute sync using Microsoft Graph Delta API for incremental changes.

        This method is much faster than full enumeration for large sites with
        few changes, as it only queries for items that changed since the last sync.

        Args:
            session: Database session
            config: SharePointSyncConfig with delta_token
            organization_id: Organization UUID
            run_id: Run UUID for tracking
            include_patterns: File patterns to include
            exclude_patterns: File patterns to exclude
            max_file_size_mb: Maximum file size in MB
            min_modified_date: Skip files older than this date
            has_selection_filter: Whether folder/file selection is active
            selected_folders: Selected folder paths
            selected_file_ids: Set of selected file IDs

        Returns:
            Sync result dict with statistics
        """
        from app.core.shared.run_log_service import run_log_service
        from app.core.shared.run_service import run_service

        from .sharepoint_service import sharepoint_delta_query

        # Log delta sync start
        await run_service.update_run_progress(
            session=session,
            run_id=run_id,
            current=0,
            total=None,
            unit="files",
            phase="delta_sync",
        )
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 2: Using delta query for incremental sync",
            context={
                "phase": "delta_sync",
                "delta_enabled": True,
                "has_token": bool(config.delta_token),
            },
        )
        await session.commit()

        logger.info(f"Starting delta sync for {config.folder_url}")

        # Results tracking
        results = {
            "total_files": 0,
            "new_files": 0,
            "updated_files": 0,
            "unchanged_files": 0,
            "skipped_files": 0,
            "skipped_folders": 0,
            "failed_files": 0,
            "deleted_detected": 0,
            "errors": [],
            "sync_mode": "delta",
        }

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
            "skipped_folders": 0,
            "current_file": None,
            "phase": "delta_sync",
        }
        await session.commit()

        # Query delta API
        processed_files = 0
        try:
            changed_items, new_delta_token = await sharepoint_delta_query(
                drive_id=config.folder_drive_id,
                item_id=config.folder_item_id,
                delta_token=config.delta_token,
                organization_id=organization_id,
                session=session,
            )

            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="progress",
                message=f"Delta query returned {len(changed_items)} changed items",
                context={
                    "phase": "delta_sync",
                    "changed_items": len(changed_items),
                },
            )
            await session.commit()

            # Process changed items
            for item in changed_items:
                change_type = item.get("_change_type")
                item_type = item.get("type")

                # Skip folders for now (only process files)
                if item_type == "folder":
                    if change_type == "deleted":
                        # Folder deleted - we'll catch file deletions individually
                        pass
                    continue

                # Apply filters
                if not self._item_passes_filter(item, include_patterns, exclude_patterns, max_file_size_mb, min_modified_date):
                    results["skipped_files"] += 1
                    continue

                # Apply selection filter if active
                if has_selection_filter:
                    if not self._item_matches_selection(item, selected_folders, selected_file_ids):
                        results["skipped_files"] += 1
                        continue

                results["total_files"] += 1
                current_file = item.get("name", "unknown")

                try:
                    if change_type == "deleted":
                        # Handle deleted file
                        await self._handle_deleted_item(
                            session=session,
                            config=config,
                            item=item,
                            run_id=run_id,
                        )
                        results["deleted_detected"] += 1

                        await run_log_service.log_event(
                            session=session,
                            run_id=run_id,
                            level="INFO",
                            event_type="file_delete",
                            message=f"Marked as deleted: {current_file}",
                            context={"phase": "delta_sync", "file": current_file, "action": "deleted", "folder": item.get("folder", "")},
                        )
                    else:
                        # Download/update file
                        result = await self._sync_single_file(
                            session=session,
                            config=config,
                            item=item,
                            run_id=run_id,
                            full_sync=False,
                            group_id=group_id,
                        )
                        results[result] += 1
                        processed_files += 1

                        if result == "new_files":
                            await run_log_service.log_event(
                                session=session,
                                run_id=run_id,
                                level="INFO",
                                event_type="file_download",
                                message=f"Downloaded: {current_file}",
                                context={"phase": "delta_sync", "file": current_file, "action": "new", "folder": item.get("folder", "")},
                            )
                        elif result == "updated_files":
                            await run_log_service.log_event(
                                session=session,
                                run_id=run_id,
                                level="INFO",
                                event_type="file_download",
                                message=f"Updated: {current_file}",
                                context={"phase": "delta_sync", "file": current_file, "action": "updated", "folder": item.get("folder", "")},
                            )

                except Exception as e:
                    logger.error(f"Failed to process delta item {current_file}: {e}")
                    results["failed_files"] += 1
                    results["errors"].append({"file": current_file, "error": str(e)})

                    await run_log_service.log_event(
                        session=session,
                        run_id=run_id,
                        level="ERROR",
                        event_type="file_error",
                        message=f"Failed: {current_file}",
                        context={"phase": "delta_sync", "file": current_file, "error": str(e), "folder": item.get("folder", "")},
                    )

                # Update config stats
                config.stats = {
                    "total_files": results["total_files"],
                    "synced_files": results["new_files"] + results["updated_files"] + results["unchanged_files"],
                    "processed_files": processed_files,
                    "new_files": results["new_files"],
                    "updated_files": results["updated_files"],
                    "unchanged_files": results["unchanged_files"],
                    "failed_files": results["failed_files"],
                    "deleted_count": results["deleted_detected"],
                    "current_file": current_file,
                    "phase": "delta_sync",
                }
                await session.commit()

            # Update delta token only if there were no failures
            # If files failed, keep the old token so the next sync retries them
            if results["failed_files"] == 0:
                config.delta_token = new_delta_token
                config.last_delta_sync_at = datetime.utcnow()
            else:
                logger.warning(
                    f"Delta token NOT advanced for {config.name}: "
                    f"{results['failed_files']} files failed, will retry on next sync"
                )

        except Exception as e:
            logger.error(f"Delta sync failed: {e}")
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="ERROR",
                event_type="error",
                message=f"Delta sync failed: {e}",
                context={"phase": "delta_sync", "error": str(e)},
            )
            await session.commit()
            raise

        # =================================================================
        # COMPLETE DELTA SYNC
        # =================================================================
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
            "deleted_count": results["deleted_detected"],
            "current_file": None,
            "phase": "completed",
            "sync_mode": "delta",
            "last_sync_results": results,
        }
        await session.commit()

        # Complete the run
        results_summary = {
            "total_files": results["total_files"],
            "new_files": results["new_files"],
            "updated_files": results["updated_files"],
            "unchanged_files": results["unchanged_files"],
            "skipped_files": results["skipped_files"],
            "skipped_folders": results["skipped_folders"],
            "failed_files": results["failed_files"],
            "deleted_detected": results["deleted_detected"],
            "sync_mode": "delta",
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
            message=f"SharePoint delta sync {status_msg}: {results['new_files']} new, {results['updated_files']} updated, {results['unchanged_files']} unchanged, {results['failed_files']} failed, {results['deleted_detected']} deleted",
            context={
                "new_files": results["new_files"],
                "updated_files": results["updated_files"],
                "unchanged_files": results["unchanged_files"],
                "failed_files": results["failed_files"],
                "deleted_detected": results["deleted_detected"],
                "sync_mode": "delta",
                "status": "success" if results["failed_files"] == 0 else "partial",
            },
        )
        await session.commit()

        logger.info(
            f"Delta sync completed for {config.name}: "
            f"new={results['new_files']}, updated={results['updated_files']}, "
            f"unchanged={results['unchanged_files']}, deleted={results['deleted_detected']}"
        )

        return results

    async def _capture_initial_delta_token(
        self,
        session: AsyncSession,
        config: SharePointSyncConfig,
        organization_id: UUID,
        run_id: UUID,
    ) -> None:
        """
        Capture initial delta token after a full sync.

        This establishes the baseline for future delta syncs by making
        an initial delta query and storing the returned delta link.
        """
        from app.core.shared.run_log_service import run_log_service

        from .sharepoint_service import sharepoint_delta_query

        if not config.folder_drive_id or not config.folder_item_id:
            logger.warning(f"Cannot capture delta token: missing drive_id or item_id for {config.name}")
            return

        try:
            # Make initial delta query to get token
            # We don't need to process items since we just did a full sync
            _, new_delta_token = await sharepoint_delta_query(
                drive_id=config.folder_drive_id,
                item_id=config.folder_item_id,
                delta_token=None,  # Initial query
                organization_id=organization_id,
                session=session,
            )

            if new_delta_token:
                config.delta_token = new_delta_token
                config.delta_token_acquired_at = datetime.utcnow()
                await session.commit()

                logger.info(f"Captured delta token for {config.name}")
                await run_log_service.log_event(
                    session=session,
                    run_id=run_id,
                    level="INFO",
                    event_type="progress",
                    message="Captured delta token for future incremental syncs",
                    context={"phase": "completing", "delta_enabled": True},
                )
                await session.commit()

        except Exception as e:
            logger.warning(f"Failed to capture delta token for {config.name}: {e}")
            # Don't raise - this is a non-critical operation

    async def _handle_deleted_item(
        self,
        session: AsyncSession,
        config: SharePointSyncConfig,
        item: Dict[str, Any],
        run_id: UUID,
    ) -> None:
        """
        Mark a synced document as deleted based on delta query result.

        Args:
            session: Database session
            config: SharePointSyncConfig
            item: Delta item with _change_type='deleted'
            run_id: Run UUID for tracking
        """
        item_id = item.get("id")
        if not item_id:
            return

        # Find the synced document by SharePoint item ID
        result = await session.execute(
            select(SharePointSyncedDocument).where(
                and_(
                    SharePointSyncedDocument.sync_config_id == config.id,
                    SharePointSyncedDocument.sharepoint_item_id == item_id,
                    SharePointSyncedDocument.status != "deleted_in_source",
                )
            )
        )
        doc = result.scalar_one_or_none()

        if doc:
            doc.status = "deleted_in_source"
            doc.deleted_at = datetime.utcnow()
            doc.last_sync_run_id = run_id
            await session.commit()

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

    # File extensions that cannot be extracted to markdown - skip downloading
    NON_EXTRACTABLE_EXTENSIONS = {
        # Video
        ".mp4", ".avi", ".mov", ".wmv", ".flv", ".mkv", ".webm", ".m4v", ".mpeg", ".mpg",
        ".3gp", ".3g2", ".ogv", ".ts", ".mts", ".m2ts", ".vob", ".asf",
        # Audio
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".aiff", ".aif",
        ".opus", ".mid", ".midi", ".ac3", ".amr",
        # Images (not useful for text extraction)
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
        ".heic", ".heif",  # Apple image formats
        ".tiff", ".tif", ".raw", ".cr2", ".nef", ".arw",  # RAW/professional formats
        # Archives (TODO: Support zip extraction for direct uploads, not SharePoint sync)
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".cab", ".lzh", ".lz4",
        # Large binary formats
        ".iso", ".dmg", ".exe", ".msi", ".dll", ".bin", ".dat",
        # Font files
        ".ttf", ".otf", ".woff", ".woff2", ".eot",
        # Design/CAD files
        ".psd", ".ai", ".sketch", ".fig", ".xd",
        ".dwg", ".dxf", ".stl", ".obj", ".fbx",
        # OneNote (proprietary binary, requires MS Graph API to extract)
        ".one", ".onetoc2", ".onepkg",
    }

    def _item_passes_filter(
        self,
        item: Dict[str, Any],
        include_patterns: List[str],
        exclude_patterns: List[str],
        max_file_size_mb: int,
        min_modified_date: Optional[datetime] = None,
    ) -> bool:
        """
        Check if a single item passes the filter criteria.

        Filters applied:
        1. Skip folders
        2. Skip files exceeding max size
        3. Skip files matching exclude patterns
        4. Skip files not matching include patterns (if specified)
        5. Skip non-extractable file types (video, audio, etc.)
        6. Skip files older than min_modified_date (if specified)
        """
        import fnmatch
        from pathlib import Path

        from dateutil.parser import parse as parse_date

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

        # Skip non-extractable file types (video, audio, etc.)
        ext = Path(name).suffix.lower()
        if ext in self.NON_EXTRACTABLE_EXTENSIONS:
            return False

        # Check min_modified_date filter
        if min_modified_date:
            item_modified = item.get("modified")
            if item_modified:
                try:
                    # Parse the modified date string
                    if isinstance(item_modified, str):
                        item_modified_dt = parse_date(item_modified)
                    else:
                        item_modified_dt = item_modified

                    # Convert both to naive UTC for comparison
                    if item_modified_dt.tzinfo is not None:
                        item_modified_dt = item_modified_dt.astimezone(timezone.utc).replace(tzinfo=None)
                    min_date_naive = min_modified_date
                    if min_date_naive.tzinfo is not None:
                        min_date_naive = min_date_naive.astimezone(timezone.utc).replace(tzinfo=None)

                    if item_modified_dt < min_date_naive:
                        return False
                except (ValueError, TypeError) as e:
                    # If we can't parse the date, log and include the file
                    logger.warning(f"Could not parse modified date for {name}: {e}")

        return True

    def _item_matches_selection(
        self,
        item: Dict[str, Any],
        selected_folders: List[str],
        selected_file_ids: set,
    ) -> bool:
        """
        Check if an item matches the folder/file selection criteria.

        An item matches if:
        1. Its item_id is in selected_file_ids (explicitly selected file), OR
        2. Its full path starts with any of the selected_folders (within a selected folder)

        If no selections are provided, all items match (no filtering).

        Args:
            item: File item with 'id', 'name', 'folder' fields
            selected_folders: List of folder paths to sync (all contents recursively)
            selected_file_ids: Set of item IDs for individually selected files

        Returns:
            True if item should be synced, False otherwise
        """
        # Check if this specific file was selected
        item_id = item.get("id")
        if item_id and item_id in selected_file_ids:
            return True

        # Check if item is within any selected folder
        if selected_folders:
            item_folder = item.get("folder", "").strip("/")
            item_name = item.get("name", "")
            item_full_path = f"{item_folder}/{item_name}".strip("/") if item_folder else item_name

            for folder in selected_folders:
                folder = folder.strip("/")
                # Item is within the folder if its path starts with the folder path
                # e.g., folder="Documents/HR" matches "Documents/HR/file.pdf" and "Documents/HR/Subfolder/file.pdf"
                if item_folder == folder or item_folder.startswith(f"{folder}/"):
                    return True
                # Also check if the folder itself matches (for items directly in the folder)
                if item_full_path.startswith(f"{folder}/"):
                    return True

        return False

    async def _sync_single_file(
        self,
        session: AsyncSession,
        config: SharePointSyncConfig,
        item: Dict[str, Any],
        run_id: UUID,
        full_sync: bool,
        group_id: Optional[UUID] = None,
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
            # Determine if we need to download this file
            etag_matches = existing_doc.sharepoint_etag == etag
            is_successfully_synced = existing_doc.sync_status == "synced"

            # Skip download if:
            # - Etag matches (file unchanged in SharePoint)
            # - AND file was successfully synced previously
            # This applies to BOTH regular sync AND full_sync (gap-filling behavior)
            # full_sync will still re-download files that:
            #   - Have different etag (changed in SharePoint)
            #   - Have sync_status != "synced" (previously failed)
            if etag_matches and is_successfully_synced:
                # Update last_synced_at even if unchanged
                await self.update_synced_document(
                    session, existing_doc,
                    last_synced_at=datetime.utcnow(),
                    last_sync_run_id=run_id,
                    sync_status="synced",  # Confirm still synced
                )
                return "unchanged_files"

            # File needs re-download because:
            # - etag changed (file modified in SharePoint), OR
            # - sync_status != "synced" (previous sync failed)
            return await self._update_existing_file(
                session=session,
                config=config,
                item=item,
                existing_doc=existing_doc,
                run_id=run_id,
                group_id=group_id,
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
                organization_id=config.organization_id,
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
            group_id=group_id,
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
        # Query assets by source_metadata JSON field (namespaced format)
        # Old flat-format assets were already migrated to namespaced by the migration
        from sqlalchemy import or_
        result = await session.execute(
            select(Asset).where(
                and_(
                    Asset.organization_id == organization_id,
                    Asset.source_type == "sharepoint",
                    or_(
                        Asset.source_metadata["sharepoint"]["item_id"].astext == sharepoint_item_id,
                        Asset.source_metadata["sharepoint_item_id"].astext == sharepoint_item_id,
                    ),
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
        group_id: Optional[UUID] = None,
    ) -> str:
        """Download a new file and create an asset with comprehensive metadata."""
        from app.core.shared.asset_service import asset_service
        from app.core.storage.minio_service import get_minio_service


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
                organization_id=config.organization_id,
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

        # Download file with retry logic for transient errors
        drive_id = config.folder_drive_id
        file_content = await _download_file_with_retry(
            organization_id=config.organization_id,
            session=session,
            drive_id=drive_id,
            item_id=item_id,
            file_name=name,
            max_retries=3,
            retry_delay_seconds=30,
        )

        # Calculate content hash
        content_hash = hashlib.sha256(file_content).hexdigest()

        # Upload to MinIO
        from io import BytesIO
        minio_service.put_object(
            bucket=uploads_bucket,
            key=storage_key,
            data=BytesIO(file_content),
            length=len(file_content),
            content_type=mime_type or "application/octet-stream",
        )

        # Create asset with comprehensive namespaced source metadata
        actual_size = len(file_content)
        source_metadata = {
            "source": {
                "storage_folder": storage_key.rsplit("/", 1)[0] if "/" in storage_key else "",
            },
            "sharepoint": {
                "item_id": item_id,
                "drive_id": drive_id,
                "path": folder_path,
                "folder": folder_path.rsplit("/", 1)[0] if "/" in folder_path else "",
                "web_url": web_url,
                "parent_path": parent_path,
                "site_name": config.site_name,
                "created_by": created_by,
                "created_by_email": created_by_email,
                "created_by_id": created_by_id,
                "modified_by": modified_by,
                "modified_by_email": modified_by_email,
                "modified_by_id": modified_by_id,
                "created_at": created_at.isoformat() if created_at else None,
                "modified_at": modified_at.isoformat() if modified_at else None,
                "file_created_at": fs_created_at.isoformat() if fs_created_at else None,
                "file_modified_at": fs_modified_at.isoformat() if fs_modified_at else None,
                "quick_xor_hash": quick_xor_hash,
                "sha1_hash": sha1_hash,
                "sha256_hash": sha256_hash,
                "etag": etag,
                "ctag": ctag,
            },
            "sync": {
                "config_id": str(config.id),
                "config_name": config.name,
                "folder_url": config.folder_url,
            },
            "file": {
                "extension": extension,
                "description": description,
            },
        }
        # Strip None values within each namespace
        source_metadata = {
            ns: {k: v for k, v in fields.items() if v is not None}
            for ns, fields in source_metadata.items()
        }

        try:
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
                group_id=group_id,  # Link child extraction to parent job's run group
            )
        except Exception as e:
            # Handle duplicate asset (UNIQUE constraint on storage key)
            if "UNIQUE constraint" in str(e) or "IntegrityError" in str(type(e).__name__):
                await session.rollback()
                logger.warning(
                    f"Asset already exists for {name} at {storage_key}, recovering..."
                )
                # Find the existing asset and create sync document for it
                existing_asset = await self._find_asset_by_storage_key(
                    session=session,
                    raw_bucket=uploads_bucket,
                    raw_object_key=storage_key,
                )
                if existing_asset:
                    await self.create_synced_document(
                        session=session,
                        organization_id=config.organization_id,
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
                else:
                    # Couldn't find existing asset, re-raise
                    raise
            else:
                raise

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
            organization_id=config.organization_id,
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
        group_id: Optional[UUID] = None,
    ) -> str:
        """Update an existing synced file that has changed in SharePoint."""
        from app.core.shared.asset_service import asset_service
        from app.core.storage.minio_service import get_minio_service

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
                group_id=group_id,
            )

        # Download updated content with retry logic for transient errors
        drive_id = config.folder_drive_id
        file_content = await _download_file_with_retry(
            organization_id=config.organization_id,
            session=session,
            drive_id=drive_id,
            item_id=item_id,
            file_name=name,
            max_retries=3,
            retry_delay_seconds=30,
        )

        # Calculate content hash
        content_hash = hashlib.sha256(file_content).hexdigest()

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

        # Update source_metadata with latest info (namespaced format)
        source_meta = asset.source_metadata or {}
        sp_updates = {
            "site_name": config.site_name,
            "modified_at": modified_at.isoformat() if modified_at else None,
            "file_modified_at": fs_modified_at.isoformat() if fs_modified_at else None,
            "modified_by": modified_by,
            "modified_by_email": modified_by_email,
            "modified_by_id": modified_by_id,
            "etag": etag,
            "ctag": ctag,
            "quick_xor_hash": quick_xor_hash,
            "sha1_hash": sha1_hash,
            "sha256_hash": sha256_hash,
        }
        sp = source_meta.get("sharepoint", {})
        sp.update({k: v for k, v in sp_updates.items() if v is not None})
        source_meta["sharepoint"] = sp
        if description:
            file_ns = source_meta.get("file", {})
            file_ns["description"] = description
            source_meta["file"] = file_ns
        asset.source_metadata = source_meta

        # Build updated sync_metadata
        sync_metadata = existing_doc.sync_metadata or {}
        sync_updates = {
            "quick_xor_hash": quick_xor_hash,
            "sha1_hash": sha1_hash,
            "sha256_hash": sha256_hash,
            "modified_by_id": modified_by_id,
            "fs_modified_at": fs_modified_at.isoformat() if fs_modified_at else None,
            "ctag": ctag,
            "description": description,
            "extension": extension,
        }
        # Only merge non-None values — preserves existing keys
        sync_metadata.update({k: v for k, v in sync_updates.items() if v is not None})

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
            from app.core.ingestion.extraction_queue_service import extraction_queue_service
            await extraction_queue_service.queue_extraction_for_asset(
                session=session,
                asset_id=asset.id,
                group_id=group_id,  # Link child extraction to parent job's run group
            )
            logger.debug(f"Queued extraction for updated asset {asset.id}" + (f" (group: {group_id})" if group_id else ""))
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
        from sqlalchemy import delete as sql_delete

        from app.core.database.models import AssetVersion, ExtractionResult
        from app.core.search.pg_index_service import pg_index_service
        from app.core.shared.asset_service import asset_service
        from app.core.storage.minio_service import get_minio_service

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

                    # Remove from search index
                    if organization_id:
                        try:
                            await pg_index_service.delete_asset_index(session, organization_id, doc.asset_id)
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
        from sqlalchemy import delete as sql_delete

        from app.core.database.models import AssetVersion, ExtractionResult
        from app.core.search.pg_index_service import pg_index_service
        from app.core.shared.asset_service import asset_service
        from app.core.storage.minio_service import get_minio_service

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

                    # Remove from search index
                    if organization_id:
                        try:
                            await pg_index_service.delete_asset_index(session, organization_id, doc.asset_id)
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
        from sqlalchemy import delete as sql_delete

        from app.core.database.models import AssetVersion, ExtractionResult
        from app.core.search.pg_index_service import pg_index_service
        from app.core.shared.asset_service import asset_service
        from app.core.storage.minio_service import get_minio_service

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
                    # Remove from search index
                    if organization_id:
                        try:
                            await pg_index_service.delete_asset_index(session, organization_id, doc.asset_id)
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
        from sqlalchemy import delete as sql_delete

        from app.core.database.models import Asset, AssetVersion, ExtractionResult
        from app.core.search.pg_index_service import pg_index_service
        from app.core.storage.minio_service import get_minio_service

        minio = get_minio_service() if delete_files else None

        results = {
            "orphan_assets_found": 0,
            "assets_deleted": 0,
            "files_deleted": 0,
            "storage_freed_bytes": 0,
            "search_removed": 0,
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

                # Remove from search index
                try:
                    await pg_index_service.delete_asset_index(session, organization_id, asset.id)
                    results["search_removed"] += 1
                except Exception as e:
                    results["errors"].append(f"Search index removal failed for {asset.id}: {e}")

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
