"""
Celery tasks for SharePoint synchronization, import, and deletion.

Handles SharePoint folder sync, wizard import, and async config deletion.
"""
import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from celery import shared_task
from sqlalchemy import select

from app.config import settings
from app.core.shared.database_service import database_service

# Logger for tasks
logger = logging.getLogger("curatore.tasks")


# ============================================================================
# PHASE 8: SHAREPOINT SYNC TASKS
# ============================================================================

@shared_task(bind=True, soft_time_limit=3600, time_limit=3900, name="app.tasks.sharepoint_sync_task")  # 60 minute soft limit, 65 minute hard limit
def sharepoint_sync_task(
    self,
    sync_config_id: str,
    organization_id: str,
    run_id: str,
    full_sync: bool = False,
    use_delta: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Execute SharePoint folder synchronization.

    This task supports two sync modes:
    1. Full enumeration: Scans all files, compares etags
    2. Delta query: Uses Microsoft Graph Delta API for incremental changes

    Phases:
    1. Initialization - Load config, validate state
    2. Connection - Authenticate with SharePoint
    3. Sync - Either delta query or full streaming enumeration
    4. Detection - Mark deleted files (full sync only)
    5. Completion - Update stats, capture delta token

    Args:
        sync_config_id: SharePointSyncConfig UUID string
        organization_id: Organization UUID string
        run_id: Run UUID string
        full_sync: If True, re-download all files regardless of etag
        use_delta: Override delta_enabled setting (None = use config)

    Returns:
        Dict with sync results including sync_mode ('delta' or 'full')
    """
    logger = logging.getLogger("curatore.tasks.sharepoint_sync")
    sync_mode = "delta" if use_delta else "full (default)"
    logger.info(f"Starting SharePoint sync for config {sync_config_id} (mode: {sync_mode})")

    try:
        result = asyncio.run(
            _sharepoint_sync_async(
                sync_config_id=uuid.UUID(sync_config_id),
                organization_id=uuid.UUID(organization_id),
                run_id=uuid.UUID(run_id),
                full_sync=full_sync,
                use_delta=use_delta,
            )
        )

        actual_mode = result.get("sync_mode", "full")
        logger.info(f"SharePoint sync completed for config {sync_config_id} (mode: {actual_mode}): {result}")
        return result

    except Exception as e:
        logger.error(f"SharePoint sync failed for config {sync_config_id}: {e}", exc_info=True)
        # Mark run as failed
        asyncio.run(_fail_sharepoint_sync_run(uuid.UUID(run_id), str(e)))
        raise


async def _sharepoint_sync_async(
    sync_config_id,
    organization_id,
    run_id,
    full_sync: bool,
    use_delta: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Async implementation of SharePoint sync.

    Creates a RunGroup to track child extraction jobs and supports:
    - Priority-based extraction queueing (SharePoint = lowest priority)
    - Parent-child job tracking for timeout and cancellation
    - Post-sync procedure triggers via group completion events
    """
    from app.connectors.sharepoint.sharepoint_sync_service import sharepoint_sync_service
    from app.core.database.models import Asset, SharePointSyncConfig, SharePointSyncedDocument
    from app.core.ingestion.extraction_queue_service import extraction_queue_service
    from app.core.ops.heartbeat_service import heartbeat_service
    from app.core.ops.queue_registry import QueuePriority
    from app.core.shared.run_group_service import run_group_service
    from app.core.shared.run_log_service import run_log_service
    from app.core.shared.run_service import run_service

    logger = logging.getLogger("curatore.tasks.sharepoint_sync")

    async with database_service.get_session() as session:
        # Start the run and send initial heartbeat with progress
        await run_service.start_run(session, run_id)
        await run_service.update_run_progress(
            session=session,
            run_id=run_id,
            current=0,
            total=None,
            unit="files",
            phase="starting",
        )
        await heartbeat_service.beat(session, run_id)

        # Get sync config for automation settings
        config = await session.get(SharePointSyncConfig, sync_config_id)
        automation_config = getattr(config, 'automation_config', {}) or {} if config else {}

        # Create RunGroup for tracking child extractions
        group = await run_group_service.create_group(
            session=session,
            organization_id=organization_id,
            group_type="sharepoint_sync",
            parent_run_id=run_id,
            config={
                "config_id": str(sync_config_id),
                "config_name": config.name if config else "Unknown",
                "after_procedure_slug": automation_config.get("after_procedure_slug"),
                "after_procedure_params": automation_config.get("after_procedure_params", {}),
            },
        )
        group_id = group.id

        # Determine sync mode for logging
        if full_sync:
            sync_mode = "full (re-download all files)"
        elif use_delta is False:
            sync_mode = "incremental (full enumeration, delta disabled)"
        else:
            sync_mode = "incremental (will use delta if token available)"

        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="start",
            message=f"Starting SharePoint sync: {sync_mode}",
            context={
                "full_sync": full_sync,
                "use_delta": use_delta,
                "sync_mode": sync_mode,
                "group_id": str(group_id),
            },
        )
        await session.commit()

        try:
            # Execute sync (group_id passed to link child extractions to this run's group)
            result = await sharepoint_sync_service.execute_sync(
                session=session,
                sync_config_id=sync_config_id,
                organization_id=organization_id,
                run_id=run_id,
                full_sync=full_sync,
                use_delta=use_delta,
                group_id=group_id,
            )

            # Heartbeat after sync execution
            await heartbeat_service.beat(session, run_id, progress={
                "phase": "sync_complete",
                "files_synced": result.get("files_synced", 0),
            })

            # Get newly created assets for extraction
            new_docs_result = await session.execute(
                select(SharePointSyncedDocument).where(
                    SharePointSyncedDocument.sync_config_id == sync_config_id,
                    SharePointSyncedDocument.last_sync_run_id == run_id,
                )
            )
            new_docs = list(new_docs_result.scalars().all())

            # Check if we should still spawn children (group not cancelled/failed)
            should_spawn = await run_group_service.should_spawn_children(session, group_id)

            # Trigger extraction for new/updated assets with SharePoint priority (lowest)
            extraction_count = 0
            for doc in new_docs:
                if not should_spawn:
                    logger.info(f"Skipping extraction for asset {doc.asset_id} - group cancelled/failed")
                    break

                asset_result = await session.execute(
                    select(Asset).where(Asset.id == doc.asset_id)
                )
                asset = asset_result.scalar_one_or_none()
                if asset and asset.status == "pending":
                    try:
                        # Queue extraction with SharePoint priority (0 = lowest)
                        # and link to group for parent-child tracking
                        await extraction_queue_service.queue_extraction(
                            session=session,
                            asset_id=asset.id,
                            organization_id=organization_id,
                            origin="sharepoint_sync",
                            priority=QueuePriority.SHAREPOINT_SYNC,  # 0 = lowest
                            group_id=group_id,
                        )
                        extraction_count += 1

                        # Heartbeat every 20 extractions queued
                        if extraction_count % 20 == 0:
                            await heartbeat_service.beat(session, run_id, progress={
                                "phase": "queueing_extractions",
                                "queued": extraction_count,
                                "total": len(new_docs),
                            })
                    except Exception as e:
                        logger.warning(f"Failed to queue extraction for asset {asset.id}: {e}")

            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="progress",
                message=f"Queued extraction for {extraction_count} assets (priority: SharePoint sync)",
                context={"extraction_count": extraction_count, "group_id": str(group_id)},
            )

            # Finalize the group (handles case where children complete before parent finishes)
            await run_group_service.finalize_group(session, group_id)

            # Note: run is already completed by sharepoint_sync_service.execute_sync()
            await session.commit()

            # Emit event for completed SharePoint sync
            from app.core.shared.event_service import event_service
            try:
                await event_service.emit(
                    session=session,
                    event_name="sharepoint_sync.completed",
                    organization_id=organization_id,
                    payload={
                        "sync_config_id": str(sync_config_id),
                        "run_id": str(run_id),
                        "sync_mode": result.get("sync_mode", "full"),
                        "files_synced": result.get("files_synced", 0),
                        "files_added": result.get("files_added", 0),
                        "files_updated": result.get("files_updated", 0),
                        "files_deleted": result.get("files_deleted", 0),
                        "extractions_triggered": extraction_count,
                    },
                    source_run_id=run_id,
                )
            except Exception as event_error:
                logger.warning(f"Failed to emit sharepoint_sync.completed event: {event_error}")

            return result

        except Exception as e:
            logger.error(f"SharePoint sync error: {e}")
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="ERROR",
                event_type="error",
                message=str(e),
            )
            await run_service.fail_run(session, run_id, str(e))

            # Mark the group as failed (prevents post-job triggers)
            await run_group_service.mark_group_failed(session, group_id, str(e))

            await session.commit()
            raise


async def _fail_sharepoint_sync_run(run_id, error_message: str):
    """Mark a sync run as failed."""
    from app.core.shared.run_service import run_service

    async with database_service.get_session() as session:
        await run_service.fail_run(session, run_id, error_message)
        await session.commit()


@shared_task(bind=True, soft_time_limit=3600, time_limit=3900, name="app.tasks.sharepoint_import_task")  # 60 minute soft limit, 65 minute hard limit
def sharepoint_import_task(
    self,
    connection_id: Optional[str],
    organization_id: str,
    folder_url: str,
    selected_items: list,
    sync_config_id: Optional[str],
    run_id: str,
) -> Dict[str, Any]:
    """
    Import selected files from SharePoint (wizard import).

    This task:
    1. Downloads each selected file from SharePoint
    2. Creates Assets with source_type='sharepoint'
    3. Creates SharePointSyncedDocument records if sync_config_id provided
    4. Triggers extraction for each asset

    Args:
        connection_id: SharePoint connection UUID string (optional)
        organization_id: Organization UUID string
        folder_url: SharePoint folder URL
        selected_items: List of items to import with their metadata
        sync_config_id: Optional sync config UUID to link documents to
        run_id: Run UUID string

    Returns:
        Dict with import results
    """
    logger = logging.getLogger("curatore.tasks.sharepoint_import")
    logger.info(f"Starting SharePoint import for {len(selected_items)} files")

    try:
        result = asyncio.run(
            _sharepoint_import_async(
                connection_id=uuid.UUID(connection_id) if connection_id else None,
                organization_id=uuid.UUID(organization_id),
                folder_url=folder_url,
                selected_items=selected_items,
                sync_config_id=uuid.UUID(sync_config_id) if sync_config_id else None,
                run_id=uuid.UUID(run_id),
            )
        )

        logger.info(f"SharePoint import completed: {result}")
        return result

    except Exception as e:
        logger.error(f"SharePoint import failed: {e}", exc_info=True)
        asyncio.run(_fail_sharepoint_sync_run(uuid.UUID(run_id), str(e)))
        raise


async def _expand_folders_to_files(
    client: "httpx.AsyncClient",
    headers: Dict[str, str],
    graph_base: str,
    items: list,
    logger: "logging.Logger",
) -> list:
    """
    Recursively expand folders into their file contents.

    Takes a list of items that may contain folders and returns a flat list
    of only files, recursively fetching folder contents.
    """
    expanded_files = []

    async def list_folder_children(drive_id: str, folder_id: str, parent_path: str) -> list:
        """Recursively list all files in a folder."""
        files = []
        url = f"{graph_base}/drives/{drive_id}/items/{folder_id}/children"
        params = {"$top": "200"}  # Fetch in batches

        while url:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            for child in data.get("value", []):
                child_name = child.get("name", "")
                child_path = f"{parent_path}/{child_name}".strip("/") if parent_path else child_name

                if "folder" in child:
                    # Recursively process subfolder
                    child_id = child.get("id")
                    if child_id:
                        subfolder_files = await list_folder_children(drive_id, child_id, child_path)
                        files.extend(subfolder_files)
                else:
                    # It's a file - extract metadata
                    file_info = child.get("file", {})
                    parent_ref = child.get("parentReference", {})
                    created_by_info = child.get("createdBy", {}).get("user", {})
                    modified_by_info = child.get("lastModifiedBy", {}).get("user", {})

                    files.append({
                        "id": child.get("id"),
                        "name": child_name,
                        "type": "file",
                        "folder": parent_path,  # Relative path within the selected folder
                        "size": child.get("size"),
                        "mime": file_info.get("mimeType"),
                        "file_type": file_info.get("mimeType"),
                        "web_url": child.get("webUrl"),
                        "drive_id": parent_ref.get("driveId"),
                        "etag": child.get("eTag"),
                        "created": child.get("createdDateTime"),
                        "modified": child.get("lastModifiedDateTime"),
                        "created_by": created_by_info.get("displayName"),
                        "created_by_email": created_by_info.get("email"),
                        "last_modified_by": modified_by_info.get("displayName"),
                        "last_modified_by_email": modified_by_info.get("email"),
                    })

            url = data.get("@odata.nextLink")
            params = None  # nextLink includes params

        return files

    for item in items:
        item_type = item.get("type", "file")

        if item_type == "folder":
            # Expand folder contents
            folder_name = item.get("name", "")
            folder_id = item.get("id")
            drive_id = item.get("drive_id")

            if not folder_id or not drive_id:
                logger.warning(f"Skipping folder '{folder_name}': missing id or drive_id")
                continue

            logger.info(f"Expanding folder '{folder_name}' to get files...")
            try:
                folder_files = await list_folder_children(drive_id, folder_id, folder_name)
                logger.info(f"Found {len(folder_files)} files in folder '{folder_name}'")
                expanded_files.extend(folder_files)
            except Exception as e:
                logger.error(f"Failed to expand folder '{folder_name}': {e}")
        else:
            # It's already a file, add as-is
            expanded_files.append(item)

    return expanded_files


def _build_file_entry_from_graph(
    child: Dict[str, Any],
    parent_path: str,
    drive_id: str,
) -> Dict[str, Any]:
    """
    Build standardized file entry from Microsoft Graph API child item.

    Args:
        child: Graph API item response
        parent_path: Relative folder path from sync root
        drive_id: SharePoint drive ID

    Returns:
        Standardized file entry dict for import/sync processing
    """
    file_info = child.get("file", {})
    parent_ref = child.get("parentReference", {})
    created_by = child.get("createdBy", {}).get("user", {})
    modified_by = child.get("lastModifiedBy", {}).get("user", {})

    return {
        "id": child.get("id"),
        "name": child.get("name", ""),
        "type": "file",
        "folder": parent_path,
        "size": child.get("size"),
        "mime": file_info.get("mimeType"),
        "file_type": file_info.get("mimeType"),
        "web_url": child.get("webUrl"),
        "drive_id": parent_ref.get("driveId") or drive_id,
        "etag": child.get("eTag"),
        "created": child.get("createdDateTime"),
        "modified": child.get("lastModifiedDateTime"),
        "created_by": created_by.get("displayName"),
        "created_by_email": created_by.get("email"),
        "last_modified_by": modified_by.get("displayName"),
        "last_modified_by_email": modified_by.get("email"),
    }


async def _expand_folders_to_files_stream(
    client: "httpx.AsyncClient",
    headers: Dict[str, str],
    graph_base: str,
    items: list,
    logger: "logging.Logger",
    run_id: uuid.UUID,
    session: "AsyncSession",
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream files from folder expansion using BFS traversal.

    Yields files as discovered with periodic activity updates to prevent timeout.
    This is the streaming replacement for _expand_folders_to_files() that prevents
    the 300-second activity timeout by touching last_activity_at periodically.

    Args:
        client: httpx AsyncClient with SharePoint token
        headers: HTTP headers with Authorization
        graph_base: Microsoft Graph API base URL
        items: List of selected items (files and/or folders)
        logger: Logger instance
        run_id: Run UUID for activity tracking
        session: Database session

    Yields:
        File entry dicts as they are discovered during BFS traversal
    """
    from app.core.shared.run_log_service import run_log_service
    from app.core.shared.run_service import run_service

    # BFS queue: (drive_id, folder_id, parent_path)
    folder_queue: List[Tuple[str, str, str]] = []

    # First pass: yield direct files, queue folders
    for item in items:
        item_type = item.get("type", "file")
        if item_type == "folder":
            folder_id = item.get("id")
            drive_id = item.get("drive_id")
            folder_name = item.get("name", "")
            if folder_id and drive_id:
                folder_queue.append((drive_id, folder_id, folder_name))
        else:
            yield item

    # Tracking
    folders_scanned = 0
    files_discovered = 0
    last_activity = datetime.utcnow()
    activity_interval = 30  # seconds between activity updates

    # BFS folder traversal
    while folder_queue:
        drive_id, folder_id, parent_path = folder_queue.pop(0)

        # List folder contents with pagination
        url = f"{graph_base}/drives/{drive_id}/items/{folder_id}/children"
        params = {"$top": "200"}

        while url:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            for child in data.get("value", []):
                child_name = child.get("name", "")
                child_path = f"{parent_path}/{child_name}".strip("/") if parent_path else child_name

                if "folder" in child:
                    # Queue subfolder for BFS
                    child_id = child.get("id")
                    if child_id:
                        folder_queue.append((drive_id, child_id, child_path))
                else:
                    # It's a file - yield immediately
                    files_discovered += 1
                    yield _build_file_entry_from_graph(child, parent_path, drive_id)

            url = data.get("@odata.nextLink")
            params = None  # nextLink includes params

        folders_scanned += 1

        # Periodic activity update to prevent timeout
        now = datetime.utcnow()
        if (now - last_activity).total_seconds() >= activity_interval:
            last_activity = now

            # Touch run activity
            await run_service.touch_activity(session, run_id)

            # Log progress
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="progress",
                message=f"Scanning: {folders_scanned} folders, {files_discovered} files, {len(folder_queue)} remaining",
                context={
                    "phase": "expanding",
                    "folders_scanned": folders_scanned,
                    "files_discovered": files_discovered,
                    "folders_remaining": len(folder_queue),
                },
            )
            await session.commit()


async def _sharepoint_import_async(
    connection_id: Optional[uuid.UUID],
    organization_id: uuid.UUID,
    folder_url: str,
    selected_items: list,
    sync_config_id: Optional[uuid.UUID],
    run_id: uuid.UUID,
) -> Dict[str, Any]:
    """
    Async implementation of SharePoint import.

    Handles both files and folders. When a folder is selected, recursively
    fetches all files within that folder and imports them.
    """
    import hashlib
    import tempfile

    import httpx

    from app.connectors.sharepoint.sharepoint_service import _get_sharepoint_credentials, _graph_base_url
    from app.connectors.sharepoint.sharepoint_sync_service import sharepoint_sync_service
    from app.core.ingestion.upload_integration_service import upload_integration_service
    from app.core.shared.asset_service import asset_service
    from app.core.shared.run_log_service import run_log_service
    from app.core.shared.run_service import run_service
    from app.core.storage.minio_service import get_minio_service
    from app.core.storage.storage_path_service import storage_paths

    logger = logging.getLogger("curatore.tasks.sharepoint_import")

    async with database_service.get_session() as session:
        # =================================================================
        # PHASE 1: INITIALIZATION
        # =================================================================
        await run_service.start_run(session, run_id)
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 1: Initializing import",
            context={"phase": "init", "selected_items": len(selected_items)},
        )
        await session.commit()

        # Get sync config if provided
        sync_config = None
        sync_slug = "import"
        if sync_config_id:
            sync_config = await sharepoint_sync_service.get_sync_config(session, sync_config_id)
            if sync_config:
                sync_slug = sync_config.slug
                await run_log_service.log_event(
                    session=session,
                    run_id=run_id,
                    level="INFO",
                    event_type="progress",
                    message=f"Loaded sync config: {sync_config.name}",
                    context={"sync_config_name": sync_config.name, "sync_slug": sync_slug},
                )
                await session.commit()

        # =================================================================
        # PHASE 2: CONNECTING TO SHAREPOINT
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 2: Connecting to SharePoint",
            context={"phase": "connecting"},
        )
        await session.commit()

        # Get SharePoint credentials
        credentials = await _get_sharepoint_credentials(organization_id, session)
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

        results = {
            "imported": 0,
            "failed": 0,
            "skipped_non_extractable": 0,
            "errors": [],
        }

        # Get MinIO service
        minio = get_minio_service()
        if not minio:
            raise RuntimeError("MinIO service is not available")

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            # Get token
            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            token_resp = await client.post(token_url, data=token_payload)
            token_resp.raise_for_status()
            token = token_resp.json().get("access_token")
            headers = {"Authorization": f"Bearer {token}"}

            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="progress",
                message="Successfully authenticated with SharePoint",
                context={"phase": "connecting"},
            )
            await session.commit()

            # =================================================================
            # PHASE 3+4: STREAMING DISCOVERY AND DOWNLOAD
            # =================================================================
            # Count folders vs files in selection
            folder_count = sum(1 for item in selected_items if item.get("type") == "folder")
            file_count = len(selected_items) - folder_count

            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="phase",
                message=f"Phase 3: Streaming discovery and download from {folder_count} folders and {file_count} direct files",
                context={"phase": "streaming", "folders": folder_count, "direct_files": file_count},
            )
            await session.commit()

            # Track processed count (total unknown during streaming)
            processed = 0
            last_progress_log = datetime.utcnow()
            progress_log_interval = 30  # Log progress every 30 seconds

            # Stream files as they're discovered and process immediately
            async for item in _expand_folders_to_files_stream(
                client=client,
                headers=headers,
                graph_base=graph_base,
                items=selected_items,
                logger=logger,
                run_id=run_id,
                session=session,
            ):
                item_id = item.get("id")
                name = item.get("name", "unknown")
                folder_path = item.get("folder", "").strip("/")
                drive_id = item.get("drive_id")
                size = item.get("size")
                web_url = item.get("web_url")
                mime_type = item.get("mime") or item.get("file_type")

                # Skip non-extractable file types (video, audio, images, etc.)
                ext = Path(name).suffix.lower()
                non_extractable = {
                    # Video
                    ".mp4", ".avi", ".mov", ".wmv", ".flv", ".mkv", ".webm", ".m4v",
                    ".mpeg", ".mpg", ".3gp", ".3g2", ".ogv", ".ts", ".mts", ".m2ts",
                    ".vob", ".asf",
                    # Audio
                    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".aiff",
                    ".aif", ".opus", ".mid", ".midi", ".ac3", ".amr",
                    # Images (not useful for text extraction)
                    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
                    ".heic", ".heif",  # Apple image formats
                    ".tiff", ".tif", ".raw", ".cr2", ".nef", ".arw",  # RAW/professional
                    # Archives (skip for SharePoint sync - TODO: support for direct uploads)
                    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".cab", ".lzh", ".lz4",
                    # Large binary formats
                    ".iso", ".dmg", ".exe", ".msi", ".dll", ".bin", ".dat",
                    # Fonts
                    ".ttf", ".otf", ".woff", ".woff2", ".eot",
                    # Design/CAD files
                    ".psd", ".ai", ".sketch", ".fig", ".xd",
                    ".dwg", ".dxf", ".stl", ".obj", ".fbx",
                    # OneNote (proprietary binary, requires MS Graph API)
                    ".one", ".onetoc2", ".onepkg",
                }
                if ext in non_extractable:
                    logger.debug(f"Skipping non-extractable file: {name}")
                    results["skipped_non_extractable"] += 1
                    continue

                try:
                    # Download file
                    if not drive_id:
                        # Try to get drive_id from sync config or folder inventory
                        if sync_config and sync_config.folder_drive_id:
                            drive_id = sync_config.folder_drive_id
                        else:
                            raise ValueError("drive_id is required for import")

                    download_url = f"{graph_base}/drives/{drive_id}/items/{item_id}/content"

                    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                        async with client.stream("GET", download_url, headers=headers) as response:
                            response.raise_for_status()
                            async for chunk in response.aiter_bytes():
                                tmp_file.write(chunk)
                        tmp_path = tmp_file.name

                    # Calculate content hash
                    content_hash = None
                    try:
                        with open(tmp_path, "rb") as f:
                            content_hash = hashlib.sha256(f.read()).hexdigest()
                    except:
                        pass

                    # Generate storage path
                    org_id_str = str(organization_id)
                    storage_key = storage_paths.sharepoint_sync(
                        org_id=org_id_str,
                        sync_slug=sync_slug,
                        relative_path=folder_path,
                        filename=name,
                        extracted=False,
                    )

                    # Upload to MinIO
                    uploads_bucket = minio.bucket_uploads
                    file_size = Path(tmp_path).stat().st_size
                    with open(tmp_path, "rb") as f:
                        minio.put_object(
                            bucket=uploads_bucket,
                            key=storage_key,
                            data=f,
                            length=file_size,
                            content_type=mime_type or "application/octet-stream",
                        )

                    # Cleanup temp file
                    try:
                        Path(tmp_path).unlink()
                    except:
                        pass

                    # Create asset
                    asset = await asset_service.create_asset(
                        session=session,
                        organization_id=organization_id,
                        source_type="sharepoint",
                        source_metadata={
                            "sync_config_id": str(sync_config_id) if sync_config_id else None,
                            "sharepoint_item_id": item_id,
                            "sharepoint_drive_id": drive_id,
                            "sharepoint_path": folder_path,
                            "sharepoint_web_url": web_url,
                            "folder_url": folder_url,
                            "import_run_id": str(run_id),
                        },
                        original_filename=name,
                        raw_bucket=uploads_bucket,
                        raw_object_key=storage_key,
                        content_type=mime_type,
                        file_size=size,
                        file_hash=content_hash,
                        status="pending",
                    )

                    # Create synced document record if sync config exists
                    if sync_config_id:
                        await sharepoint_sync_service.create_synced_document(
                            session=session,
                            organization_id=organization_id,
                            sync_config_id=sync_config_id,
                            asset_id=asset.id,
                            sharepoint_item_id=item_id,
                            sharepoint_drive_id=drive_id,
                            sharepoint_path=folder_path,
                            sharepoint_web_url=web_url,
                            file_size=size,
                            content_hash=content_hash,
                            run_id=run_id,
                        )

                    # Trigger extraction
                    try:
                        await upload_integration_service.trigger_extraction(
                            session=session,
                            asset_id=asset.id,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to trigger extraction for {name}: {e}")

                    results["imported"] += 1

                except Exception as e:
                    logger.error(f"Failed to import {name}: {e}")
                    results["failed"] += 1
                    results["errors"].append({"file": name, "error": str(e)})

                    await run_log_service.log_event(
                        session=session,
                        run_id=run_id,
                        level="ERROR",
                        event_type="file_error",
                        message=f"Failed to import: {name}",
                        context={"phase": "streaming", "file": name, "error": str(e)},
                    )

                # Update progress count
                processed += 1

                # Update run progress (total is unknown during streaming)
                await run_service.update_run_progress(
                    session=session,
                    run_id=run_id,
                    current=processed,
                    total=None,
                    unit="files",
                    phase="streaming",
                )

                # Log progress at time intervals (since total is unknown)
                now = datetime.utcnow()
                if (now - last_progress_log).total_seconds() >= progress_log_interval:
                    last_progress_log = now
                    await run_log_service.log_event(
                        session=session,
                        run_id=run_id,
                        level="INFO",
                        event_type="progress",
                        message=f"Import progress: {processed} files processed ({results['imported']} imported, {results['failed']} failed)",
                        context={
                            "phase": "streaming",
                            "processed": processed,
                            "imported": results["imported"],
                            "failed": results["failed"],
                        },
                    )

                await session.commit()

            # =================================================================
            # PHASE 4: COMPLETING IMPORT
            # =================================================================
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="phase",
                message=f"Phase 4: Finalizing import ({processed} files processed)",
                context={"phase": "completing", "total_processed": processed},
            )
            await session.commit()

        # Complete the run
        status_msg = "completed successfully" if results["failed"] == 0 else "completed with errors"
        await run_service.complete_run(
            session=session,
            run_id=run_id,
            results_summary=results,
        )

        skipped = results.get("skipped_non_extractable", 0)
        await run_log_service.log_summary(
            session=session,
            run_id=run_id,
            message=f"SharePoint import {status_msg}: {results['imported']} imported, {results['failed']} failed, {skipped} skipped (non-extractable)",
            context={
                "imported": results["imported"],
                "failed": results["failed"],
                "skipped_non_extractable": skipped,
                "errors": results["errors"][:5] if results["errors"] else [],  # Limit errors in summary
                "status": "success" if results["failed"] == 0 else "partial",
            },
        )

        await session.commit()

        return results


# ============================================================================
# SHAREPOINT ASYNC DELETION TASK
# ============================================================================

@shared_task(bind=True, soft_time_limit=1800, time_limit=1900, name="app.tasks.async_delete_sync_config_task")  # 30 minute soft limit, 32 minute hard limit
def async_delete_sync_config_task(
    self,
    sync_config_id: str,
    organization_id: str,
    run_id: str,
    config_name: str,
) -> Dict[str, Any]:
    """
    Asynchronously delete a SharePoint sync config with full cleanup.

    This task performs a complete removal including:
    1. Cancel pending extraction jobs
    2. Delete files from MinIO storage (raw and extracted)
    3. Hard delete Asset records from database
    4. Remove documents from search index
    5. Delete SharePointSyncedDocument records
    6. Delete related Run records (except the deletion tracking run)
    7. Delete the sync config itself
    8. Complete the tracking run with results summary

    Args:
        sync_config_id: SharePointSyncConfig UUID string
        organization_id: Organization UUID string
        run_id: Run UUID string (for tracking this deletion)
        config_name: Name of the config being deleted (for logging)

    Returns:
        Dict with deletion results
    """
    logger = logging.getLogger("curatore.tasks.sharepoint_delete")
    logger.info(f"Starting async deletion for SharePoint sync config {sync_config_id} ({config_name})")

    try:
        result = asyncio.run(
            _async_delete_sync_config(
                sync_config_id=uuid.UUID(sync_config_id),
                organization_id=uuid.UUID(organization_id),
                run_id=uuid.UUID(run_id),
                config_name=config_name,
            )
        )

        logger.info(f"Async deletion completed for config {sync_config_id}: {result}")
        return result

    except Exception as e:
        logger.error(f"Async deletion failed for config {sync_config_id}: {e}", exc_info=True)
        # Mark run as failed
        asyncio.run(_fail_deletion_run(uuid.UUID(run_id), str(e)))
        raise


async def _async_delete_sync_config(
    sync_config_id,
    organization_id,
    run_id,
    config_name: str,
) -> Dict[str, Any]:
    """
    Async implementation of SharePoint sync config deletion.
    """
    from sqlalchemy import delete as sql_delete

    from app.connectors.sharepoint.sharepoint_sync_service import sharepoint_sync_service
    from app.core.database.models import (
        Asset,
        AssetVersion,
        ExtractionResult,
        Run,
        RunLogEvent,
        SharePointSyncConfig,
        SharePointSyncedDocument,
    )
    from app.core.search.pg_index_service import pg_index_service
    from app.core.shared.asset_service import asset_service
    from app.core.shared.run_log_service import run_log_service
    from app.core.shared.run_service import run_service
    from app.core.storage.minio_service import get_minio_service

    logger = logging.getLogger("curatore.tasks.sharepoint_delete")

    async with database_service.get_session() as session:
        # Start the run
        await run_service.start_run(session, run_id)
        await session.commit()

        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message=f"Starting deletion of SharePoint sync config: {config_name}",
            context={"phase": "starting", "config_id": str(sync_config_id)},
        )
        await session.commit()

        # Get the sync config
        config = await sharepoint_sync_service.get_sync_config(session, sync_config_id)
        if not config:
            await run_service.fail_run(session, run_id, "Sync config not found")
            await session.commit()
            return {"error": "Sync config not found"}

        minio = get_minio_service()

        stats = {
            "config_name": config_name,
            "assets_deleted": 0,
            "files_deleted": 0,
            "documents_deleted": 0,
            "runs_deleted": 0,
            "extractions_cancelled": 0,
            "search_removed": 0,
            "storage_freed_bytes": 0,
            "errors": [],
        }

        # =================================================================
        # PHASE 1: CANCEL PENDING EXTRACTIONS
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 1: Cancelling pending extraction jobs",
            context={"phase": "cancel_extractions"},
        )
        await session.commit()

        try:
            cancelled_count = await sharepoint_sync_service._cancel_pending_jobs_for_sync_config(
                session, sync_config_id, organization_id
            )
            stats["extractions_cancelled"] = cancelled_count
            logger.info(f"Cancelled {cancelled_count} pending jobs")
        except Exception as e:
            stats["errors"].append(f"Failed to cancel extractions: {e}")
            logger.warning(f"Failed to cancel extractions: {e}")

        # =================================================================
        # PHASE 2: GET SYNCED DOCUMENTS
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 2: Gathering synced documents",
            context={"phase": "gather_documents"},
        )
        await session.commit()

        docs_result = await session.execute(
            select(SharePointSyncedDocument).where(
                SharePointSyncedDocument.sync_config_id == sync_config_id
            )
        )
        synced_docs = list(docs_result.scalars().all())
        total_docs = len(synced_docs)

        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="info",
            message=f"Found {total_docs} synced documents to delete",
            context={"total_documents": total_docs},
        )
        await session.commit()

        # =================================================================
        # PHASE 3: DELETE ASSETS AND FILES
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 3: Deleting assets and files",
            context={"phase": "delete_assets", "total": total_docs},
        )
        await session.commit()

        processed = 0
        last_progress = 0

        for doc in synced_docs:
            if doc.asset_id:
                try:
                    # Remove from search index
                    try:
                        await pg_index_service.delete_asset_index(session, organization_id, doc.asset_id)
                        stats["search_removed"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Search index removal failed for {doc.asset_id}: {e}")

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
                    stats["errors"].append(f"Asset deletion failed for {doc.asset_id}: {e}")

            processed += 1

            # Update progress every 10%
            if total_docs > 0:
                current_percent = int((processed / total_docs) * 100)
                if current_percent >= last_progress + 10:
                    last_progress = current_percent
                    run = await session.get(Run, run_id)
                    if run:
                        run.progress = {"percent": current_percent}
                    await run_log_service.log_event(
                        session=session,
                        run_id=run_id,
                        level="INFO",
                        event_type="progress",
                        message=f"Deletion progress: {processed}/{total_docs} assets ({current_percent}%)",
                        context={
                            "phase": "delete_assets",
                            "processed": processed,
                            "total": total_docs,
                            "percent": current_percent,
                        },
                    )
                    await session.commit()

        # =================================================================
        # PHASE 3.5: CLEANUP FILES BY STORAGE PATH PREFIX
        # =================================================================
        # This ensures all files are deleted even if extraction results
        # didn't track them properly
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 3.5: Cleaning up files by storage path",
            context={"phase": "cleanup_storage_paths"},
        )
        await session.commit()

        if minio and config and config.slug:
            path_prefix = f"{organization_id}/sharepoint/{config.slug}/"
            buckets_to_clean = [
                settings.minio_bucket_uploads,
                settings.minio_bucket_processed,
            ]
            for bucket in buckets_to_clean:
                try:
                    objects = list(minio.list_objects(bucket, prefix=path_prefix, recursive=True))
                    for obj in objects:
                        try:
                            minio.delete_object(bucket, obj.object_name)
                            stats["files_deleted"] += 1
                        except Exception:
                            pass
                    if objects:
                        logger.info(f"Cleaned up {len(objects)} files from {bucket}/{path_prefix}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup {bucket}/{path_prefix}: {e}")

        # =================================================================
        # PHASE 4: DELETE SYNCED DOCUMENT RECORDS
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 4: Deleting synced document records",
            context={"phase": "delete_documents"},
        )
        await session.commit()

        await session.execute(
            sql_delete(SharePointSyncedDocument).where(
                SharePointSyncedDocument.sync_config_id == sync_config_id
            )
        )
        stats["documents_deleted"] = total_docs

        # =================================================================
        # PHASE 5: DELETE RELATED RUNS (EXCEPT THIS ONE)
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 5: Deleting related sync runs",
            context={"phase": "delete_runs"},
        )
        await session.commit()

        # Find all runs related to this config (sync and import runs)
        runs_result = await session.execute(
            select(Run).where(
                Run.config["sync_config_id"].astext == str(sync_config_id),
                Run.id != run_id,  # Don't delete this deletion tracking run yet
            )
        )
        runs = list(runs_result.scalars().all())

        for related_run in runs:
            # Delete run log events first
            await session.execute(
                sql_delete(RunLogEvent).where(RunLogEvent.run_id == related_run.id)
            )
            await session.execute(
                sql_delete(Run).where(Run.id == related_run.id)
            )
            stats["runs_deleted"] += 1

        # =================================================================
        # PHASE 6: DELETE SYNC CONFIG
        # =================================================================
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="phase",
            message="Phase 6: Deleting sync configuration",
            context={"phase": "delete_config"},
        )
        await session.commit()

        await session.execute(
            sql_delete(SharePointSyncConfig).where(
                SharePointSyncConfig.id == sync_config_id
            )
        )

        await session.commit()

        # =================================================================
        # PHASE 7: COMPLETE THE RUN
        # =================================================================
        status_msg = "completed successfully" if len(stats["errors"]) == 0 else "completed with errors"

        await run_service.complete_run(
            session=session,
            run_id=run_id,
            results_summary=stats,
        )

        await run_log_service.log_summary(
            session=session,
            run_id=run_id,
            message=f"SharePoint sync config deletion {status_msg}: {config_name}",
            context={
                "assets_deleted": stats["assets_deleted"],
                "files_deleted": stats["files_deleted"],
                "documents_deleted": stats["documents_deleted"],
                "runs_deleted": stats["runs_deleted"],
                "search_removed": stats["search_removed"],
                "storage_freed_mb": round(stats["storage_freed_bytes"] / (1024 * 1024), 2),
                "errors": stats["errors"][:5] if stats["errors"] else [],
                "status": "success" if len(stats["errors"]) == 0 else "partial",
            },
        )

        await session.commit()

        logger.info(
            f"Deleted sync config {sync_config_id} ({config_name}) with cleanup: "
            f"assets={stats['assets_deleted']}, docs={stats['documents_deleted']}, "
            f"runs={stats['runs_deleted']}, search={stats['search_removed']}"
        )

        return stats


async def _fail_deletion_run(run_id, error_message: str):
    """Mark a deletion run as failed."""
    from app.core.shared.run_service import run_service

    async with database_service.get_session() as session:
        await run_service.fail_run(session, run_id, error_message)
        await session.commit()
