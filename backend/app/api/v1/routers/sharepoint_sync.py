# backend/app/api/v1/routers/sharepoint_sync.py
"""
SharePoint Sync API endpoints for Curatore v2 API (v1).

Provides endpoints for managing SharePoint folder synchronization:
- Sync config CRUD (create, read, update, archive)
- Trigger sync operations
- List synced documents
- Browse SharePoint folders (wizard support)
- Import selected files
- Cleanup deleted files

Security:
    - All endpoints require authentication
    - Sync configs are organization-scoped
    - Only org_admin can create/delete configs
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select, desc, func

from app.database.models import Run, SharePointSyncConfig, SharePointSyncedDocument, Asset, User, Connection
from app.dependencies import get_current_user, require_org_admin
from app.services.database_service import database_service
from app.services.sharepoint_sync_service import sharepoint_sync_service
from app.services.run_service import run_service
from app.tasks import sharepoint_sync_task, sharepoint_import_task
from ..models import (
    SharePointSyncConfigResponse,
    SharePointSyncConfigCreateRequest,
    SharePointSyncConfigUpdateRequest,
    SharePointSyncConfigListResponse,
    SharePointSyncedDocumentResponse,
    SharePointSyncedDocumentListResponse,
    SharePointSyncTriggerRequest,
    SharePointSyncTriggerResponse,
    SharePointSyncHistoryResponse,
    SharePointBrowseFolderRequest,
    SharePointBrowseFolderResponse,
    SharePointImportRequest,
    SharePointImportResponse,
    SharePointCleanupRequest,
    SharePointCleanupResponse,
    SharePointRemoveItemsRequest,
    SharePointRemoveItemsResponse,
    RunResponse,
)

# Initialize router
router = APIRouter(prefix="/sharepoint-sync", tags=["SharePoint Sync"])

# Initialize logger
logger = logging.getLogger("curatore.api.sharepoint_sync")


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================

def _config_to_response(
    config: SharePointSyncConfig,
    is_syncing: bool = False,
    current_sync_status: Optional[str] = None,
    storage_stats: Optional[Dict[str, Any]] = None,
    connection_name: Optional[str] = None,
) -> SharePointSyncConfigResponse:
    """Convert SharePointSyncConfig model to response."""
    # Merge storage_stats into stats if provided
    stats = dict(config.stats or {})
    if storage_stats:
        stats["storage"] = storage_stats

    return SharePointSyncConfigResponse(
        id=str(config.id),
        organization_id=str(config.organization_id),
        connection_id=str(config.connection_id) if config.connection_id else None,
        connection_name=connection_name,
        name=config.name,
        slug=config.slug,
        description=config.description,
        folder_url=config.folder_url,
        folder_name=config.folder_name,
        folder_drive_id=config.folder_drive_id,
        folder_item_id=config.folder_item_id,
        sync_config=config.sync_config or {},
        status=config.status,
        is_active=config.is_active,
        last_sync_at=config.last_sync_at,
        last_sync_status=config.last_sync_status,
        last_sync_run_id=str(config.last_sync_run_id) if config.last_sync_run_id else None,
        sync_frequency=config.sync_frequency,
        stats=stats,
        created_at=config.created_at,
        updated_at=config.updated_at,
        created_by=str(config.created_by) if config.created_by else None,
        is_syncing=is_syncing,
        current_sync_status=current_sync_status,
    )


async def _get_storage_stats(session, config_id: UUID) -> Dict[str, Any]:
    """Calculate storage stats for a sync config."""
    # Get total file size and count from synced documents
    result = await session.execute(
        select(
            func.count(SharePointSyncedDocument.id).label("total_documents"),
            func.sum(SharePointSyncedDocument.file_size).label("total_bytes"),
        ).where(
            SharePointSyncedDocument.sync_config_id == config_id,
            SharePointSyncedDocument.sync_status == "synced",
        )
    )
    row = result.one()

    total_documents = row.total_documents or 0
    total_bytes = row.total_bytes or 0

    # Get count by status
    status_result = await session.execute(
        select(
            SharePointSyncedDocument.sync_status,
            func.count(SharePointSyncedDocument.id).label("count"),
        ).where(
            SharePointSyncedDocument.sync_config_id == config_id,
        ).group_by(SharePointSyncedDocument.sync_status)
    )
    status_counts = {row.sync_status: row.count for row in status_result.all()}

    return {
        "total_documents": total_documents,
        "total_bytes": total_bytes,
        "synced_count": status_counts.get("synced", 0),
        "deleted_count": status_counts.get("deleted_in_source", 0),
        "orphaned_count": status_counts.get("orphaned", 0),
    }


async def _get_connection_name(session, connection_id: Optional[UUID]) -> Optional[str]:
    """Get connection name by ID."""
    if not connection_id:
        return None
    result = await session.execute(
        select(Connection.name).where(Connection.id == connection_id)
    )
    row = result.scalar_one_or_none()
    return row


def _doc_to_response(
    doc: SharePointSyncedDocument,
    asset: Optional[Asset] = None,
) -> SharePointSyncedDocumentResponse:
    """Convert SharePointSyncedDocument model to response."""
    return SharePointSyncedDocumentResponse(
        id=str(doc.id),
        asset_id=str(doc.asset_id),
        sync_config_id=str(doc.sync_config_id),
        sharepoint_item_id=doc.sharepoint_item_id,
        sharepoint_drive_id=doc.sharepoint_drive_id,
        sharepoint_path=doc.sharepoint_path,
        sharepoint_web_url=doc.sharepoint_web_url,
        sharepoint_etag=doc.sharepoint_etag,
        content_hash=doc.content_hash,
        sharepoint_created_at=doc.sharepoint_created_at,
        sharepoint_modified_at=doc.sharepoint_modified_at,
        sharepoint_created_by=doc.sharepoint_created_by,
        sharepoint_modified_by=doc.sharepoint_modified_by,
        file_size=doc.file_size,
        sync_status=doc.sync_status,
        last_synced_at=doc.last_synced_at,
        last_sync_run_id=str(doc.last_sync_run_id) if doc.last_sync_run_id else None,
        deleted_detected_at=doc.deleted_detected_at,
        sync_metadata=doc.sync_metadata or {},
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        original_filename=asset.original_filename if asset else None,
        asset_status=asset.status if asset else None,
    )


async def _check_active_sync(session, config_id: UUID) -> tuple[bool, Optional[str]]:
    """Check if a sync or import is currently running for this config."""
    # Use json_extract for SQLite compatibility
    # Check both sharepoint_sync and sharepoint_import run types
    result = await session.execute(
        select(Run).where(
            func.json_extract(Run.config, "$.sync_config_id") == str(config_id),
            Run.run_type.in_(["sharepoint_sync", "sharepoint_import"]),
            Run.status.in_(["pending", "running"]),
        ).order_by(desc(Run.created_at)).limit(1)
    )
    run = result.scalar_one_or_none()
    if run:
        return True, run.status
    return False, None


# =========================================================================
# SYNC CONFIG ENDPOINTS
# =========================================================================

@router.get("/configs", response_model=SharePointSyncConfigListResponse)
async def list_sync_configs(
    status: Optional[str] = Query(None, description="Filter by status (active, paused, archived)"),
    limit: int = Query(50, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Offset"),
    current_user: User = Depends(get_current_user),
):
    """List SharePoint sync configs for the organization."""
    async with database_service.get_session() as session:
        configs, total = await sharepoint_sync_service.list_sync_configs(
            session=session,
            organization_id=current_user.organization_id,
            status=status,
            limit=limit,
            offset=offset,
        )

        # Check for active syncs
        config_responses = []
        for config in configs:
            is_syncing, sync_status = await _check_active_sync(session, config.id)
            config_responses.append(_config_to_response(config, is_syncing, sync_status))

        return SharePointSyncConfigListResponse(
            configs=config_responses,
            total=total,
            limit=limit,
            offset=offset,
        )


@router.post("/configs", response_model=SharePointSyncConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_sync_config(
    request: SharePointSyncConfigCreateRequest,
    current_user: User = Depends(require_org_admin),
):
    """Create a new SharePoint sync config."""
    async with database_service.get_session() as session:
        try:
            config = await sharepoint_sync_service.create_sync_config(
                session=session,
                organization_id=current_user.organization_id,
                connection_id=UUID(request.connection_id) if request.connection_id else None,
                name=request.name,
                folder_url=request.folder_url,
                description=request.description,
                sync_config=request.sync_config,
                sync_frequency=request.sync_frequency,
                created_by=current_user.id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        logger.info(f"Created SharePoint sync config {config.id} by user {current_user.id}")

        return _config_to_response(config)


@router.get("/configs/{config_id}", response_model=SharePointSyncConfigResponse)
async def get_sync_config(
    config_id: UUID,
    current_user: User = Depends(get_current_user),
):
    """Get a SharePoint sync config by ID."""
    async with database_service.get_session() as session:
        config = await sharepoint_sync_service.get_sync_config(session, config_id)

        if not config:
            raise HTTPException(status_code=404, detail="Sync config not found")

        if config.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        is_syncing, sync_status = await _check_active_sync(session, config.id)
        storage_stats = await _get_storage_stats(session, config.id)
        connection_name = await _get_connection_name(session, config.connection_id)

        return _config_to_response(config, is_syncing, sync_status, storage_stats, connection_name)


@router.patch("/configs/{config_id}", response_model=SharePointSyncConfigResponse)
async def update_sync_config(
    config_id: UUID,
    request: SharePointSyncConfigUpdateRequest,
    current_user: User = Depends(require_org_admin),
):
    """
    Update a SharePoint sync config.

    Safe changes (no asset impact):
    - name, description, sync_frequency, is_active, status
    - sync_config.include_patterns, sync_config.exclude_patterns (affects future syncs only)
    - sync_config.recursive: false -> true (only adds more files)

    Breaking changes (require reset_existing_assets=True):
    - folder_url (different folder = different files)
    - connection_id (could be different SharePoint tenant)
    - sync_config.recursive: true -> false (would orphan subfolder assets)

    When reset_existing_assets=True is provided with breaking changes,
    all existing synced assets will be deleted before applying the update.
    """
    async with database_service.get_session() as session:
        config = await sharepoint_sync_service.get_sync_config(session, config_id)

        if not config:
            raise HTTPException(status_code=404, detail="Sync config not found")

        if config.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Check if sync is currently running
        is_syncing, _ = await _check_active_sync(session, config.id)
        if is_syncing:
            raise HTTPException(
                status_code=409,
                detail="Cannot update while sync is in progress. Cancel the sync first."
            )

        # Reject folder_url changes - user must create a new sync config for a different folder
        if request.folder_url is not None and request.folder_url != config.folder_url:
            raise HTTPException(
                status_code=400,
                detail="Cannot change folder URL. To sync a different folder, create a new sync configuration."
            )

        # Reject connection_id changes - fundamental to the sync config
        if request.connection_id is not None:
            current_conn_id = str(config.connection_id) if config.connection_id else None
            if request.connection_id != current_conn_id:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot change connection. To use a different connection, create a new sync configuration."
                )

        # Detect breaking changes (only recursive: true -> false now)
        breaking_changes = []

        if request.sync_config is not None:
            current_recursive = (config.sync_config or {}).get("recursive", True)
            new_recursive = request.sync_config.get("recursive", current_recursive)
            if current_recursive and not new_recursive:
                breaking_changes.append("recursive: true -> false (would orphan subfolder assets)")

        # Check if breaking changes require reset
        if breaking_changes:
            # Check if there are existing synced documents
            docs_result = await session.execute(
                select(func.count(SharePointSyncedDocument.id)).where(
                    SharePointSyncedDocument.sync_config_id == config_id
                )
            )
            doc_count = docs_result.scalar() or 0

            if doc_count > 0 and not request.reset_existing_assets:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "Breaking changes detected",
                        "message": f"This update would invalidate {doc_count} existing synced assets. "
                                   f"Set reset_existing_assets=true to delete all existing assets and proceed.",
                        "breaking_changes": breaking_changes,
                        "existing_assets": doc_count,
                    }
                )

            # If reset is requested or no existing docs, proceed
            if doc_count > 0 and request.reset_existing_assets:
                logger.info(
                    f"Resetting {doc_count} assets for sync config {config_id} due to breaking changes: "
                    f"{breaking_changes}"
                )
                reset_result = await sharepoint_sync_service.reset_all_synced_assets(
                    session=session,
                    sync_config_id=config_id,
                )
                logger.info(f"Reset result: {reset_result}")

        # Build update dict from non-None fields
        # Note: folder_url and connection_id cannot be changed (rejected above)
        updates = {}
        if request.name is not None:
            updates["name"] = request.name
        if request.description is not None:
            updates["description"] = request.description
        if request.sync_config is not None:
            # Merge with existing sync_config to preserve other settings
            merged_sync_config = {**(config.sync_config or {}), **request.sync_config}
            updates["sync_config"] = merged_sync_config
        if request.status is not None:
            updates["status"] = request.status
        if request.is_active is not None:
            updates["is_active"] = request.is_active
        if request.sync_frequency is not None:
            updates["sync_frequency"] = request.sync_frequency

        updated = await sharepoint_sync_service.update_sync_config(
            session=session,
            sync_config_id=config_id,
            **updates,
        )

        logger.info(f"Updated SharePoint sync config {config_id} by user {current_user.id}")

        is_syncing, sync_status = await _check_active_sync(session, config.id)
        storage_stats = await _get_storage_stats(session, config.id)
        return _config_to_response(updated, is_syncing, sync_status, storage_stats)


@router.post("/configs/{config_id}/archive")
async def archive_sync_config(
    config_id: UUID,
    current_user: User = Depends(require_org_admin),
):
    """
    Archive a SharePoint sync config and remove documents from OpenSearch.

    This removes documents from search but keeps assets intact:
    - Removes documents from OpenSearch index
    - Sets config status to "archived"
    - Disables syncing (is_active = False)

    The sync config must be disabled (is_active = False) before archiving.
    After archiving, you can permanently delete using DELETE endpoint.

    Returns:
        Archive statistics including count of documents removed from OpenSearch
    """
    async with database_service.get_session() as session:
        config = await sharepoint_sync_service.get_sync_config(session, config_id)

        if not config:
            raise HTTPException(status_code=404, detail="Sync config not found")

        if config.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Must be disabled before archiving
        if config.is_active:
            raise HTTPException(
                status_code=400,
                detail="Sync must be disabled before archiving. Toggle off sync first."
            )

        # Check if sync is currently running
        is_syncing, _ = await _check_active_sync(session, config_id)
        if is_syncing:
            raise HTTPException(
                status_code=400,
                detail="Cannot archive while sync is in progress. Wait for sync to complete."
            )

        # Already archived
        if config.status == "archived":
            raise HTTPException(
                status_code=400,
                detail="Sync config is already archived."
            )

        stats = await sharepoint_sync_service.archive_sync_config_with_opensearch_cleanup(
            session=session,
            sync_config_id=config_id,
            organization_id=current_user.organization_id,
        )

        logger.info(
            f"Archived SharePoint sync config {config_id} by user {current_user.id}: "
            f"opensearch_removed={stats.get('opensearch_removed', 0)}"
        )

        return {
            "message": "Sync configuration archived and removed from search",
            "archive_stats": stats,
        }


@router.delete("/configs/{config_id}")
async def delete_sync_config(
    config_id: UUID,
    current_user: User = Depends(require_org_admin),
):
    """
    Permanently delete a SharePoint sync config with full cleanup.

    This performs a complete removal including:
    - Soft deletes all associated assets
    - Removes documents from OpenSearch index
    - Deletes synced document records
    - Deletes related worker runs
    - Deletes the sync config itself

    The sync config must be archived before it can be deleted.
    Use POST /configs/{id}/archive first.

    Returns:
        Cleanup statistics including counts of deleted items
    """
    async with database_service.get_session() as session:
        config = await sharepoint_sync_service.get_sync_config(session, config_id)

        if not config:
            raise HTTPException(status_code=404, detail="Sync config not found")

        if config.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Must be archived before deleting
        if config.status != "archived":
            raise HTTPException(
                status_code=400,
                detail="Sync config must be archived before deletion. Use the archive endpoint first."
            )

        # Check if sync is currently running (shouldn't happen if archived, but just in case)
        is_syncing, _ = await _check_active_sync(session, config_id)
        if is_syncing:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete while sync is in progress. Wait for sync to complete."
            )

        stats = await sharepoint_sync_service.delete_sync_config_with_cleanup(
            session=session,
            sync_config_id=config_id,
            organization_id=current_user.organization_id,
        )

        logger.info(
            f"Deleted SharePoint sync config {config_id} by user {current_user.id}: "
            f"assets={stats.get('assets_deleted', 0)}, docs={stats.get('documents_deleted', 0)}"
        )

        return {
            "message": "Sync configuration deleted successfully",
            "cleanup_stats": stats,
        }


# =========================================================================
# SYNC EXECUTION ENDPOINTS
# =========================================================================

@router.post("/configs/{config_id}/sync", response_model=SharePointSyncTriggerResponse)
async def trigger_sync(
    config_id: UUID,
    request: SharePointSyncTriggerRequest = SharePointSyncTriggerRequest(),
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
):
    """Trigger a manual sync for a config."""
    async with database_service.get_session() as session:
        config = await sharepoint_sync_service.get_sync_config(session, config_id)

        if not config:
            raise HTTPException(status_code=404, detail="Sync config not found")

        if config.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        if config.status != "active" or not config.is_active:
            raise HTTPException(
                status_code=400,
                detail="Sync config is not active"
            )

        # Check if already syncing
        is_syncing, _ = await _check_active_sync(session, config.id)
        if is_syncing:
            raise HTTPException(
                status_code=409,
                detail="A sync is already running for this config"
            )

        # Create run for tracking
        run = await run_service.create_run(
            session=session,
            organization_id=current_user.organization_id,
            run_type="sharepoint_sync",
            origin="user",
            config={
                "sync_config_id": str(config_id),
                "sync_config_name": config.name,
                "full_sync": request.full_sync,
            },
            created_by=current_user.id,
        )

        # Queue Celery task
        sharepoint_sync_task.delay(
            sync_config_id=str(config_id),
            organization_id=str(current_user.organization_id),
            run_id=str(run.id),
            full_sync=request.full_sync,
        )

        logger.info(f"Queued SharePoint sync for config {config_id}, run {run.id}")

        return SharePointSyncTriggerResponse(
            sync_config_id=str(config_id),
            run_id=str(run.id),
            status="pending",
            message="Sync queued for execution",
        )


@router.post("/configs/{config_id}/cancel-stuck")
async def cancel_stuck_runs(
    config_id: UUID,
    current_user: User = Depends(require_org_admin),
):
    """
    Cancel any stuck pending/running runs for this sync config.

    Use this endpoint when a sync appears stuck and you want to reset the state
    to allow a new sync to be triggered.
    """
    async with database_service.get_session() as session:
        config = await sharepoint_sync_service.get_sync_config(session, config_id)

        if not config:
            raise HTTPException(status_code=404, detail="Sync config not found")

        if config.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Find and cancel stuck runs
        result = await session.execute(
            select(Run).where(
                func.json_extract(Run.config, "$.sync_config_id") == str(config_id),
                Run.run_type.in_(["sharepoint_sync", "sharepoint_import"]),
                Run.status.in_(["pending", "running"]),
            )
        )
        stuck_runs = list(result.scalars().all())

        cancelled_count = 0
        for run in stuck_runs:
            run.status = "cancelled"
            run.error_message = "Manually cancelled by admin - run was stuck"
            cancelled_count += 1

        await session.commit()

        logger.info(
            f"Cancelled {cancelled_count} stuck runs for config {config_id} by user {current_user.id}"
        )

        return {
            "message": f"Cancelled {cancelled_count} stuck runs",
            "cancelled_count": cancelled_count,
            "run_ids": [str(r.id) for r in stuck_runs],
        }


@router.get("/configs/{config_id}/history", response_model=SharePointSyncHistoryResponse)
async def get_sync_history(
    config_id: UUID,
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Offset"),
    current_user: User = Depends(get_current_user),
):
    """Get sync run history for a config."""
    async with database_service.get_session() as session:
        config = await sharepoint_sync_service.get_sync_config(session, config_id)

        if not config:
            raise HTTPException(status_code=404, detail="Sync config not found")

        if config.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Get runs for this config (use json_extract for SQLite compatibility)
        # Include both sharepoint_sync and sharepoint_import runs
        result = await session.execute(
            select(Run).where(
                Run.run_type.in_(["sharepoint_sync", "sharepoint_import"]),
                func.json_extract(Run.config, "$.sync_config_id") == str(config_id),
            ).order_by(desc(Run.created_at)).limit(limit).offset(offset)
        )
        runs = list(result.scalars().all())

        # Get total count
        count_result = await session.execute(
            select(func.count(Run.id)).where(
                Run.run_type.in_(["sharepoint_sync", "sharepoint_import"]),
                func.json_extract(Run.config, "$.sync_config_id") == str(config_id),
            )
        )
        total = count_result.scalar() or 0

        return SharePointSyncHistoryResponse(
            runs=[
                RunResponse(
                    id=run.id,
                    organization_id=run.organization_id,
                    run_type=run.run_type,
                    origin=run.origin,
                    status=run.status,
                    input_asset_ids=run.input_asset_ids or [],
                    config=run.config or {},
                    progress=run.progress,
                    results_summary=run.results_summary,
                    error_message=run.error_message,
                    created_at=run.created_at,
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    created_by=run.created_by,
                )
                for run in runs
            ],
            total=total,
        )


# =========================================================================
# SYNCED DOCUMENT ENDPOINTS
# =========================================================================

@router.get("/configs/{config_id}/documents", response_model=SharePointSyncedDocumentListResponse)
async def list_synced_documents(
    config_id: UUID,
    sync_status: Optional[str] = Query(None, description="Filter by status (synced, deleted_in_source, orphaned)"),
    limit: int = Query(100, ge=1, le=500, description="Page size"),
    offset: int = Query(0, ge=0, description="Offset"),
    current_user: User = Depends(get_current_user),
):
    """List synced documents for a config."""
    async with database_service.get_session() as session:
        config = await sharepoint_sync_service.get_sync_config(session, config_id)

        if not config:
            raise HTTPException(status_code=404, detail="Sync config not found")

        if config.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        docs, total = await sharepoint_sync_service.list_synced_documents(
            session=session,
            sync_config_id=config_id,
            sync_status=sync_status,
            limit=limit,
            offset=offset,
        )

        # Get asset info for each doc
        doc_responses = []
        for doc in docs:
            asset_result = await session.execute(
                select(Asset).where(Asset.id == doc.asset_id)
            )
            asset = asset_result.scalar_one_or_none()
            doc_responses.append(_doc_to_response(doc, asset))

        return SharePointSyncedDocumentListResponse(
            documents=doc_responses,
            total=total,
            limit=limit,
            offset=offset,
        )


@router.post("/configs/{config_id}/cleanup", response_model=SharePointCleanupResponse)
async def cleanup_deleted_documents(
    config_id: UUID,
    request: SharePointCleanupRequest = SharePointCleanupRequest(),
    current_user: User = Depends(require_org_admin),
):
    """Cleanup documents marked as deleted in source."""
    async with database_service.get_session() as session:
        config = await sharepoint_sync_service.get_sync_config(session, config_id)

        if not config:
            raise HTTPException(status_code=404, detail="Sync config not found")

        if config.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        result = await sharepoint_sync_service.cleanup_deleted_documents(
            session=session,
            sync_config_id=config_id,
            delete_assets=request.delete_assets,
        )

        logger.info(
            f"Cleaned up {result['documents_removed']} documents for config {config_id} "
            f"(assets_deleted={result['assets_deleted']})"
        )

        return SharePointCleanupResponse(
            sync_config_id=str(config_id),
            documents_removed=result["documents_removed"],
            assets_deleted=result["assets_deleted"],
            message=f"Cleaned up {result['documents_removed']} deleted documents",
        )


@router.post(
    "/configs/{config_id}/remove-items",
    response_model=SharePointRemoveItemsResponse
)
async def remove_synced_items(
    config_id: UUID,
    request: SharePointRemoveItemsRequest,
    current_user: User = Depends(require_org_admin),
):
    """
    Remove specific synced items from a sync config.

    This will:
    - Delete the SharePointSyncedDocument records
    - Optionally delete the associated Asset records and files

    Args:
        config_id: Sync config UUID
        request: Request containing item_ids and delete_assets flag
    """
    async with database_service.get_session() as session:
        config = await sharepoint_sync_service.get_sync_config(session, config_id)

        if not config:
            raise HTTPException(status_code=404, detail="Sync config not found")

        if config.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        if not request.item_ids:
            return SharePointRemoveItemsResponse(
                sync_config_id=str(config_id),
                documents_removed=0,
                assets_deleted=0,
                message="No items specified for removal",
            )

        result = await sharepoint_sync_service.remove_synced_items(
            session=session,
            sync_config_id=config_id,
            sharepoint_item_ids=request.item_ids,
            delete_assets=request.delete_assets,
        )

        logger.info(
            f"Removed {result['documents_removed']} items from config {config_id} "
            f"(assets_deleted={result['assets_deleted']})"
        )

        return SharePointRemoveItemsResponse(
            sync_config_id=str(config_id),
            documents_removed=result["documents_removed"],
            assets_deleted=result["assets_deleted"],
            message=f"Removed {result['documents_removed']} items",
        )


# =========================================================================
# BROWSE AND IMPORT ENDPOINTS (Wizard Support)
# =========================================================================

@router.post("/browse", response_model=SharePointBrowseFolderResponse)
async def browse_sharepoint_folder(
    request: SharePointBrowseFolderRequest,
    current_user: User = Depends(get_current_user),
):
    """Browse a SharePoint folder for the import wizard."""
    from app.services.sharepoint_service import sharepoint_inventory

    async with database_service.get_session() as session:
        try:
            inventory = await sharepoint_inventory(
                folder_url=request.folder_url,
                recursive=request.recursive,
                include_folders=request.include_folders,
                page_size=100,
                max_items=500,  # Limit for browsing
                organization_id=current_user.organization_id,
                session=session,
            )
        except Exception as e:
            logger.error(f"Failed to browse SharePoint folder: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to browse SharePoint folder: {str(e)}"
            )

        folder_info = inventory.get("folder", {})
        items = inventory.get("items", [])

        return SharePointBrowseFolderResponse(
            folder_name=folder_info.get("name", ""),
            folder_id=folder_info.get("id", ""),
            folder_url=folder_info.get("web_url", request.folder_url),
            drive_id=folder_info.get("drive_id", ""),
            items=items,
            total_items=len(items),
        )


@router.post("/import", response_model=SharePointImportResponse)
async def import_sharepoint_files(
    request: SharePointImportRequest,
    current_user: User = Depends(get_current_user),
):
    """Import selected files from SharePoint.

    Can either:
    - Create a new sync config (create_sync_config=True with sync_config_name)
    - Add to an existing sync config (sync_config_id provided)
    - Import without any sync config (create_sync_config=False and no sync_config_id)
    """
    async with database_service.get_session() as session:
        sync_config_id = None

        # Use existing sync config if provided
        if request.sync_config_id:
            config = await sharepoint_sync_service.get_sync_config(
                session, UUID(request.sync_config_id)
            )
            if not config:
                raise HTTPException(status_code=404, detail="Sync config not found")
            if config.organization_id != current_user.organization_id:
                raise HTTPException(status_code=403, detail="Access denied")
            sync_config_id = request.sync_config_id

        # Create new sync config if requested (and no existing config specified)
        elif request.create_sync_config and request.sync_config_name:
            # Default to recursive=True for future syncs, with standard exclude patterns
            default_sync_config = {
                "recursive": True,
                "exclude_patterns": ["~$*", "*.tmp"],
            }
            try:
                config = await sharepoint_sync_service.create_sync_config(
                    session=session,
                    organization_id=current_user.organization_id,
                    connection_id=UUID(request.connection_id) if request.connection_id else None,
                    name=request.sync_config_name,
                    folder_url=request.folder_url,
                    description=request.sync_config_description,
                    sync_config=default_sync_config,
                    sync_frequency=request.sync_frequency,
                    created_by=current_user.id,
                )
                sync_config_id = str(config.id)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        # Create run for tracking
        run = await run_service.create_run(
            session=session,
            organization_id=current_user.organization_id,
            run_type="sharepoint_import",
            origin="user",
            config={
                "sync_config_id": sync_config_id,
                "folder_url": request.folder_url,
                "selected_count": len(request.selected_items),
                "connection_id": request.connection_id,
            },
            created_by=current_user.id,
        )

        # Queue Celery task
        sharepoint_import_task.delay(
            connection_id=request.connection_id,
            organization_id=str(current_user.organization_id),
            folder_url=request.folder_url,
            selected_items=request.selected_items,
            sync_config_id=sync_config_id,
            run_id=str(run.id),
        )

        logger.info(
            f"Queued SharePoint import for {len(request.selected_items)} files, "
            f"run {run.id}, config {sync_config_id}"
        )

        return SharePointImportResponse(
            run_id=str(run.id),
            sync_config_id=sync_config_id,
            status="pending",
            message=f"Import queued for {len(request.selected_items)} files",
            selected_count=len(request.selected_items),
        )
