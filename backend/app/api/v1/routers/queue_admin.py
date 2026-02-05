"""
Queue Admin API Router for Curatore v2.

Provides administrative endpoints for monitoring and managing all job queues:
- Queue statistics (pending, submitted, running counts)
- Active job listing (extractions, SAM pulls, scrapes, SharePoint syncs, maintenance)
- Individual job cancellation (where supported by queue type)
- Queue registry configuration

These endpoints power the unified Job Manager UI and provide visibility
into all background processing activities.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, and_, func, or_

from ....database.models import Run, Asset, ExtractionResult, User
from ....services.database_service import database_service
from ....services.extraction_queue_service import extraction_queue_service
from ....services.queue_registry import queue_registry
from ....api.v1.routers.auth import get_current_user
from ..models import (
    UnifiedQueueStatsResponse,
    ExtractionQueueInfo,
    CeleryQueuesInfo,
    ThroughputInfo,
    Recent5mInfo,
    Recent24hInfo,
    WorkersInfo,
)

logger = logging.getLogger("curatore.api.queue_admin")

router = APIRouter(prefix="/queue", tags=["Queue Admin"])


# All known run_types that should be shown in Job Manager
ALL_RUN_TYPES = [
    "extraction",
    "extraction_enhancement",
    "sam_pull",
    "scrape",
    "sharepoint_sync",
    "sharepoint_import",
    "sharepoint_delete",
    "system_maintenance",
    "procedure",
    "procedure_run",
    "pipeline",
    "pipeline_run",
]


# ============================================================================
# Response Models
# ============================================================================


class QueueStatsResponse(BaseModel):
    """Queue statistics response."""
    pending_count: int
    submitted_count: int
    running_count: int
    completed_count: int
    failed_count: int
    timed_out_count: int
    max_concurrent: int
    avg_extraction_time_seconds: Optional[float]
    throughput_per_minute: float
    recent_24h: Dict[str, int]


class ActiveExtractionItem(BaseModel):
    """Individual active extraction item (legacy model for backwards compatibility)."""
    run_id: str
    asset_id: str
    filename: str
    source_type: str
    status: str
    queue_position: Optional[int]
    queue_priority: int
    created_at: str
    submitted_at: Optional[str]
    timeout_at: Optional[str]
    extractor_version: Optional[str]


class ActiveExtractionsResponse(BaseModel):
    """Active extractions list response (legacy model for backwards compatibility)."""
    items: List[ActiveExtractionItem]
    total: int


class ChildJobStats(BaseModel):
    """Statistics about child jobs for a parent job."""
    total: int = 0
    pending: int = 0
    submitted: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    timed_out: int = 0


class ActiveJobItem(BaseModel):
    """Individual active job item for unified Job Manager."""
    run_id: str
    run_type: str
    status: str
    queue_priority: int
    created_at: str
    started_at: Optional[str]
    submitted_at: Optional[str]
    completed_at: Optional[str]
    timeout_at: Optional[str]
    last_activity_at: Optional[str]  # For activity-based timeout tracking

    # Display fields
    display_name: str  # Computed from run_type + config
    display_context: Optional[str]  # Additional context (e.g., "markitdown", "10 pages")

    # For extractions
    asset_id: Optional[str]
    filename: Optional[str]
    source_type: Optional[str]
    extractor_version: Optional[str]
    queue_position: Optional[int]

    # For other job types
    config: Optional[Dict[str, Any]]  # Original config for detailed display
    progress: Optional[Dict[str, Any]]  # Progress info if available

    # Capabilities (from queue_registry)
    can_cancel: bool
    can_retry: bool

    # Parent-child relationship info
    is_parent_job: bool = False
    group_id: Optional[str] = None
    parent_run_id: Optional[str] = None  # For child jobs, reference to parent
    child_stats: Optional[ChildJobStats] = None  # For parent jobs, stats about children


class ActiveJobsResponse(BaseModel):
    """Active jobs list response for unified Job Manager."""
    items: List[ActiveJobItem]
    total: int
    run_types: List[str]  # Available run_types in the result set


class QueueDefinitionResponse(BaseModel):
    """Queue type definition for registry endpoint."""
    queue_type: str
    celery_queue: str
    label: str
    description: str
    icon: str
    color: str
    can_cancel: bool
    can_retry: bool
    max_concurrent: Optional[int]
    timeout_seconds: int
    is_throttled: bool
    enabled: bool


class QueueRegistryResponse(BaseModel):
    """Queue registry configuration response."""
    queues: Dict[str, QueueDefinitionResponse]
    run_type_mapping: Dict[str, str]


class CancelResponse(BaseModel):
    """Cancellation response."""
    status: str
    run_id: str
    reason: Optional[str]
    children_cancelled: int = 0
    children_skipped: int = 0


# ============================================================================
# Endpoints
# ============================================================================


@router.get(
    "/stats",
    response_model=QueueStatsResponse,
    summary="Get extraction queue statistics",
    description="Get comprehensive extraction queue statistics including counts by status, throughput, and timing metrics.",
)
async def get_queue_stats(
    current_user: User = Depends(get_current_user),
):
    """
    Get extraction queue statistics.

    Returns:
    - Count of extractions by status (pending, submitted, running, etc.)
    - Max concurrent setting
    - Average extraction time
    - Throughput per minute
    - Recent 24h statistics
    """
    async with database_service.get_session() as session:
        # Get stats from queue service
        stats = await extraction_queue_service.get_queue_stats(
            session=session,
            organization_id=current_user.organization_id,
        )

        # Get 24h statistics
        day_ago = datetime.utcnow() - timedelta(hours=24)

        recent_stats = {}
        for status in ["completed", "failed", "timed_out"]:
            result = await session.execute(
                select(func.count(Run.id))
                .where(and_(
                    Run.run_type == "extraction",
                    Run.organization_id == current_user.organization_id,
                    Run.status == status,
                    Run.completed_at >= day_ago,
                ))
            )
            recent_stats[status] = result.scalar() or 0

        return QueueStatsResponse(
            pending_count=stats.get("pending_count", 0),
            submitted_count=stats.get("submitted_count", 0),
            running_count=stats.get("running_count", 0),
            completed_count=stats.get("completed_count", 0),
            failed_count=stats.get("failed_count", 0),
            timed_out_count=stats.get("timed_out_count", 0),
            max_concurrent=stats.get("max_concurrent", 10),
            avg_extraction_time_seconds=stats.get("avg_extraction_time_seconds"),
            throughput_per_minute=stats.get("throughput_per_minute", 0),
            recent_24h=recent_stats,
        )


@router.get(
    "/unified",
    response_model=UnifiedQueueStatsResponse,
    summary="Get unified queue statistics",
    description="Get comprehensive queue statistics in a unified format. "
                "This is the canonical endpoint for queue monitoring.",
)
async def get_unified_queue_stats(
    current_user: User = Depends(get_current_user),
):
    """
    Get unified queue statistics.

    This endpoint consolidates all queue information into a single response:
    - extraction_queue: Database-tracked extraction queue counts
    - celery_queues: Redis queue lengths (processing_priority, processing, maintenance)
    - throughput: Processing rate and average extraction time
    - recent_24h: Completions, failures, and timeouts in the last 24 hours
    - workers: Active workers and running tasks

    Use this endpoint for dashboard displays and monitoring.
    """
    async with database_service.get_session() as session:
        # Get extraction queue stats
        stats = await extraction_queue_service.get_queue_stats(
            session=session,
            organization_id=current_user.organization_id,
        )

        # Get 5-minute statistics (all job types)
        five_min_ago = datetime.utcnow() - timedelta(minutes=5)
        recent_5m_stats = {}
        for status in ["completed", "failed", "timed_out"]:
            result = await session.execute(
                select(func.count(Run.id))
                .where(and_(
                    Run.organization_id == current_user.organization_id,
                    Run.status == status,
                    Run.completed_at >= five_min_ago,
                ))
            )
            recent_5m_stats[status] = result.scalar() or 0

        # Get 24h statistics (extraction only for backwards compat)
        day_ago = datetime.utcnow() - timedelta(hours=24)
        recent_stats = {}
        for status in ["completed", "failed", "timed_out"]:
            result = await session.execute(
                select(func.count(Run.id))
                .where(and_(
                    Run.run_type == "extraction",
                    Run.organization_id == current_user.organization_id,
                    Run.status == status,
                    Run.completed_at >= day_ago,
                ))
            )
            recent_stats[status] = result.scalar() or 0

        # Get Celery queue lengths from Redis
        celery_queues = {"processing_priority": 0, "extraction": 0, "enhancement": 0, "maintenance": 0}
        workers_info = {"active": 0, "tasks_running": 0}
        try:
            import redis
            r = redis.Redis(host='redis', port=6379, db=0)
            celery_queues = {
                "processing_priority": r.llen("processing_priority") or 0,
                "extraction": r.llen("extraction") or 0,
                "enhancement": r.llen("enhancement") or 0,
                "sam": r.llen("sam") or 0,
                "scrape": r.llen("scrape") or 0,
                "sharepoint": r.llen("sharepoint") or 0,
                "maintenance": r.llen("maintenance") or 0,
            }

            # Try to get worker info from Celery
            try:
                from ....celery_app import app as celery_app
                inspector = celery_app.control.inspect()
                active = inspector.active() or {}
                workers_info["active"] = len(active)
                workers_info["tasks_running"] = sum(len(tasks) for tasks in active.values())
            except Exception as e:
                logger.debug(f"Could not get Celery worker info: {e}")
        except Exception as e:
            logger.debug(f"Could not connect to Redis for queue lengths: {e}")

        return UnifiedQueueStatsResponse(
            extraction_queue=ExtractionQueueInfo(
                pending=stats.get("pending_count", 0),
                submitted=stats.get("submitted_count", 0),
                running=stats.get("running_count", 0),
                max_concurrent=stats.get("max_concurrent", 10),
            ),
            celery_queues=CeleryQueuesInfo(
                processing_priority=celery_queues.get("processing_priority", 0),
                extraction=celery_queues.get("extraction", 0),
                enhancement=celery_queues.get("enhancement", 0),
                sam=celery_queues.get("sam", 0),
                scrape=celery_queues.get("scrape", 0),
                sharepoint=celery_queues.get("sharepoint", 0),
                maintenance=celery_queues.get("maintenance", 0),
            ),
            throughput=ThroughputInfo(
                per_minute=stats.get("throughput_per_minute", 0.0),
                avg_extraction_seconds=stats.get("avg_extraction_time_seconds"),
            ),
            recent_5m=Recent5mInfo(
                completed=recent_5m_stats.get("completed", 0),
                failed=recent_5m_stats.get("failed", 0),
                timed_out=recent_5m_stats.get("timed_out", 0),
            ),
            recent_24h=Recent24hInfo(
                completed=recent_stats.get("completed", 0),
                failed=recent_stats.get("failed", 0),
                timed_out=recent_stats.get("timed_out", 0),
            ),
            workers=WorkersInfo(
                active=workers_info.get("active", 0),
                tasks_running=workers_info.get("tasks_running", 0),
            ),
        )


@router.get(
    "/active",
    response_model=ActiveExtractionsResponse,
    summary="List active extractions",
    description="List all pending, submitted, and running extractions for the organization.",
)
async def list_active_extractions(
    current_user: User = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500),
    include_completed: bool = Query(False, description="Include recently completed extractions"),
    status_filter: Optional[str] = Query(None, description="Filter by specific status: pending, submitted, running, completed, failed, timed_out"),
):
    """
    List all active extractions.

    Returns extractions that are pending, submitted, or running.
    Optionally includes recently completed extractions.
    Use status_filter to show only extractions with a specific status.
    """
    async with database_service.get_session() as session:
        # Build status filter
        if status_filter:
            # If specific status requested, use only that
            statuses = [status_filter]
        else:
            statuses = ["pending", "submitted", "running"]
            if include_completed:
                statuses.extend(["completed", "failed", "timed_out"])

        logger.debug(
            f"Listing active extractions for org={current_user.organization_id}, "
            f"statuses={statuses}, limit={limit}"
        )

        # Query runs first (simpler query without complex JSON join)
        result = await session.execute(
            select(Run)
            .where(and_(
                Run.run_type == "extraction",
                Run.organization_id == current_user.organization_id,
                Run.status.in_(statuses),
            ))
            .order_by(Run.queue_priority.desc(), Run.created_at.asc())
            .limit(limit)
        )
        runs = result.scalars().all()

        logger.debug(f"Found {len(runs)} active extraction runs")

        # Collect asset IDs and fetch assets separately
        asset_ids = set()
        for run in runs:
            if run.input_asset_ids:
                for aid in run.input_asset_ids:
                    try:
                        asset_ids.add(UUID(aid) if isinstance(aid, str) else aid)
                    except (ValueError, TypeError):
                        pass

        # Fetch all assets in one query
        assets_map = {}
        if asset_ids:
            assets_result = await session.execute(
                select(Asset).where(Asset.id.in_(asset_ids))
            )
            for asset in assets_result.scalars().all():
                assets_map[asset.id] = asset

        items = []
        for run in runs:
            # Get first asset ID
            asset_id_str = ""
            asset = None
            if run.input_asset_ids:
                try:
                    first_id = run.input_asset_ids[0]
                    asset_uuid = UUID(first_id) if isinstance(first_id, str) else first_id
                    asset_id_str = str(asset_uuid)
                    asset = assets_map.get(asset_uuid)
                except (ValueError, TypeError, IndexError):
                    pass

            # Get queue position for pending runs
            queue_position = None
            if run.status == "pending":
                pos_info = await extraction_queue_service.get_queue_position(session, run.id)
                queue_position = pos_info.get("queue_position")

            # Get extractor version from config or extraction result
            extractor_version = run.config.get("extractor_version") if run.config else None

            items.append(ActiveExtractionItem(
                run_id=str(run.id),
                asset_id=asset_id_str,
                filename=asset.original_filename if asset else "Unknown",
                source_type=asset.source_type if asset else "unknown",
                status=run.status,
                queue_position=queue_position,
                queue_priority=run.queue_priority or 0,
                created_at=run.created_at.isoformat() if run.created_at else "",
                submitted_at=run.submitted_to_celery_at.isoformat() if run.submitted_to_celery_at else None,
                timeout_at=run.timeout_at.isoformat() if run.timeout_at else None,
                extractor_version=extractor_version,
            ))

        # Get total count
        count_result = await session.execute(
            select(func.count(Run.id))
            .where(and_(
                Run.run_type == "extraction",
                Run.organization_id == current_user.organization_id,
                Run.status.in_(statuses),
            ))
        )
        total = count_result.scalar() or 0

        return ActiveExtractionsResponse(items=items, total=total)


@router.post(
    "/{run_id}/cancel",
    response_model=CancelResponse,
    summary="Cancel an extraction",
    description="Cancel a pending, submitted, or running extraction.",
)
async def cancel_extraction(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
):
    """
    Cancel a specific extraction.

    Can cancel extractions in pending, submitted, or running state.
    Will attempt to revoke the Celery task if already submitted.
    """
    async with database_service.get_session() as session:
        # Verify run belongs to user's organization
        run = await session.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        if run.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        if run.run_type != "extraction":
            raise HTTPException(status_code=400, detail="Not an extraction run")

        # Cancel via queue service
        result = await extraction_queue_service.cancel_extraction(
            session=session,
            run_id=run_id,
            reason=f"Cancelled by user {current_user.email}",
        )

        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail="Run not found")

        if result["status"] == "not_cancellable":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel run in '{result.get('current_status')}' status"
            )

        return CancelResponse(
            status=result["status"],
            run_id=str(run_id),
            reason=result.get("reason"),
        )


class BulkCancelRequest(BaseModel):
    """Bulk cancellation request."""
    run_ids: List[str]


class BulkCancelResponse(BaseModel):
    """Bulk cancellation response."""
    cancelled: List[str]
    failed: List[Dict[str, str]]
    total_requested: int
    total_cancelled: int


@router.post(
    "/cancel-bulk",
    response_model=BulkCancelResponse,
    summary="Cancel multiple extractions",
    description="Cancel multiple pending, submitted, or running extractions at once.",
)
async def cancel_extractions_bulk(
    request: BulkCancelRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Cancel multiple extractions at once.

    Useful for clearing the queue or cancelling a batch of extractions.
    Returns lists of successfully cancelled and failed run IDs.
    """
    cancelled = []
    failed = []

    async with database_service.get_session() as session:
        for run_id_str in request.run_ids:
            try:
                run_id = UUID(run_id_str)

                # Verify run belongs to user's organization
                run = await session.get(Run, run_id)
                if not run:
                    failed.append({"run_id": run_id_str, "error": "Run not found"})
                    continue

                if run.organization_id != current_user.organization_id:
                    failed.append({"run_id": run_id_str, "error": "Access denied"})
                    continue

                if run.run_type != "extraction":
                    failed.append({"run_id": run_id_str, "error": "Not an extraction run"})
                    continue

                # Cancel via queue service
                result = await extraction_queue_service.cancel_extraction(
                    session=session,
                    run_id=run_id,
                    reason=f"Bulk cancelled by user {current_user.email}",
                )

                if result["status"] == "cancelled":
                    cancelled.append(run_id_str)
                else:
                    failed.append({
                        "run_id": run_id_str,
                        "error": result.get("reason", f"Status: {result['status']}")
                    })

            except ValueError:
                failed.append({"run_id": run_id_str, "error": "Invalid UUID format"})
            except Exception as e:
                failed.append({"run_id": run_id_str, "error": str(e)})

    return BulkCancelResponse(
        cancelled=cancelled,
        failed=failed,
        total_requested=len(request.run_ids),
        total_cancelled=len(cancelled),
    )


@router.get(
    "/config",
    summary="Get queue configuration",
    description="Get current queue configuration settings.",
)
async def get_queue_config(
    current_user: User = Depends(get_current_user),
):
    """
    Get current queue configuration.

    Returns the current settings for:
    - Max concurrent extractions
    - Submission interval
    - Duplicate cooldown
    - Timeout buffer
    """
    return {
        "max_concurrent": extraction_queue_service.max_concurrent,
        "submission_interval_seconds": extraction_queue_service.submission_interval,
        "duplicate_cooldown_seconds": extraction_queue_service.duplicate_cooldown,
        "timeout_buffer_seconds": extraction_queue_service.timeout_buffer,
        "queue_enabled": extraction_queue_service.queue_enabled,
    }


# =============================================================================
# UNIFIED JOB MANAGER ENDPOINTS
# =============================================================================


@router.get(
    "/registry",
    response_model=QueueRegistryResponse,
    summary="Get queue registry",
    description="Get the queue registry with all queue type definitions and capabilities.",
)
async def get_queue_registry(
    current_user: User = Depends(get_current_user),
):
    """
    Get the queue registry configuration.

    Returns all queue type definitions with their:
    - Display metadata (label, icon, color)
    - Capabilities (can_cancel, can_retry)
    - Configuration (max_concurrent, timeout_seconds)
    - Run type mappings (e.g., sam_pull -> sam)

    Used by the Job Manager UI to determine available actions per job type.
    """
    registry_data = queue_registry.to_api_response()

    # Convert to response model
    queues = {}
    for queue_type, queue_def in registry_data["queues"].items():
        queues[queue_type] = QueueDefinitionResponse(**queue_def)

    return QueueRegistryResponse(
        queues=queues,
        run_type_mapping=registry_data["run_type_mapping"],
    )


@router.get(
    "/jobs",
    response_model=ActiveJobsResponse,
    summary="List all active jobs",
    description="List all active jobs across all queue types for the unified Job Manager.",
)
async def list_active_jobs(
    current_user: User = Depends(get_current_user),
    run_type: Optional[str] = Query(None, description="Filter by run_type (extraction, sam_pull, scrape, sharepoint_sync, system_maintenance)"),
    status_filter: Optional[str] = Query(None, description="Filter by status (pending, submitted, running, completed, failed, timed_out)"),
    include_completed: bool = Query(False, description="Include recently completed jobs"),
    limit: int = Query(100, ge=1, le=500),
):
    """
    List all active jobs for the unified Job Manager.

    Unlike /active (which only lists extractions), this endpoint returns
    jobs of all types: extractions, SAM pulls, web scrapes, SharePoint syncs,
    and maintenance tasks.

    Supports filtering by:
    - run_type: Show only specific job type
    - status_filter: Show only specific status
    - include_completed: Include recently completed jobs (default: false)
    """
    async with database_service.get_session() as session:
        # Determine which run_types to query
        if run_type:
            # Check if this is a parent queue type (e.g., "sharepoint")
            # If so, expand to all its aliases (sharepoint_sync, sharepoint_import, sharepoint_delete)
            queue_def = queue_registry.get(run_type)
            if queue_def and queue_def.run_type_aliases:
                # Include the queue_type itself plus all aliases
                run_types = [queue_def.queue_type] + queue_def.run_type_aliases
            else:
                run_types = [run_type]
        else:
            run_types = ALL_RUN_TYPES

        # Build status filter
        if status_filter:
            statuses = [status_filter]
        else:
            statuses = ["pending", "submitted", "running"]
            if include_completed:
                statuses.extend(["completed", "failed", "timed_out", "cancelled"])

        logger.debug(
            f"Listing active jobs for org={current_user.organization_id}, "
            f"run_types={run_types}, statuses={statuses}, limit={limit}"
        )

        # Query runs
        result = await session.execute(
            select(Run)
            .where(and_(
                Run.run_type.in_(run_types),
                Run.organization_id == current_user.organization_id,
                Run.status.in_(statuses),
            ))
            .order_by(Run.queue_priority.desc(), Run.created_at.desc())
            .limit(limit)
        )
        runs = result.scalars().all()

        logger.debug(f"Found {len(runs)} active jobs")

        # Collect asset IDs for extraction and enhancement runs
        asset_ids = set()
        for run in runs:
            if run.run_type in ("extraction", "extraction_enhancement") and run.input_asset_ids:
                for aid in run.input_asset_ids:
                    try:
                        asset_ids.add(UUID(aid) if isinstance(aid, str) else aid)
                    except (ValueError, TypeError):
                        pass

        # Fetch all assets in one query
        assets_map = {}
        if asset_ids:
            assets_result = await session.execute(
                select(Asset).where(Asset.id.in_(asset_ids))
            )
            for asset in assets_result.scalars().all():
                assets_map[asset.id] = asset

        items = []
        run_types_found = set()

        for run in runs:
            run_types_found.add(run.run_type)

            # Get queue definition for capabilities
            queue_def = queue_registry.get(run.run_type)
            can_cancel = queue_def.can_cancel if queue_def else False
            can_retry = queue_def.can_retry if queue_def else False

            # Build display fields based on run_type
            display_name = ""
            display_context = None
            asset_id_str = None
            filename = None
            source_type = None
            extractor_version = None
            queue_position = None

            if run.run_type == "extraction":
                # Extraction-specific fields
                if run.input_asset_ids:
                    try:
                        first_id = run.input_asset_ids[0]
                        asset_uuid = UUID(first_id) if isinstance(first_id, str) else first_id
                        asset_id_str = str(asset_uuid)
                        asset = assets_map.get(asset_uuid)
                        if asset:
                            display_name = asset.original_filename or "Unknown"
                            source_type = asset.source_type
                            filename = asset.original_filename
                    except (ValueError, TypeError, IndexError):
                        display_name = "Unknown document"
                else:
                    display_name = "Unknown document"

                extractor_version = run.config.get("extractor_version") if run.config else None
                display_context = extractor_version

                # Get queue position for pending extractions
                if run.status == "pending":
                    pos_info = await extraction_queue_service.get_queue_position(session, run.id)
                    queue_position = pos_info.get("queue_position")

            elif run.run_type == "extraction_enhancement":
                # Enhancement-specific fields (Docling enhancement)
                if run.input_asset_ids:
                    try:
                        first_id = run.input_asset_ids[0]
                        asset_uuid = UUID(first_id) if isinstance(first_id, str) else first_id
                        asset_id_str = str(asset_uuid)
                        asset = assets_map.get(asset_uuid)
                        if asset:
                            display_name = asset.original_filename or "Unknown"
                            source_type = asset.source_type
                            filename = asset.original_filename
                    except (ValueError, TypeError, IndexError):
                        display_name = "Unknown document"
                else:
                    display_name = "Unknown document"

                # Enhancement uses Docling
                display_context = "Docling enhancement"

            elif run.run_type == "sam_pull":
                # SAM pull - display search name
                config = run.config or {}
                display_name = config.get("search_name", "SAM.gov Pull")
                display_context = f"{config.get('max_pages', '?')} pages"

            elif run.run_type == "scrape":
                # Web scrape - display collection name
                config = run.config or {}
                display_name = config.get("collection_name", "Web Scrape")
                display_context = f"{config.get('max_pages', '?')} URLs"

            elif run.run_type in ("sharepoint_sync", "sharepoint_import", "sharepoint_delete"):
                # SharePoint jobs - display config name
                config = run.config or {}
                display_name = config.get("sync_config_name") or config.get("config_name") or config.get("sync_name") or config.get("folder_path") or "SharePoint Job"
                if run.run_type == "sharepoint_delete":
                    display_context = "Deleting..."
                elif run.run_type == "sharepoint_import":
                    display_context = "Importing files"
                else:
                    display_context = config.get("site_name") or ("Full sync" if config.get("full_sync") else "Incremental")

            elif run.run_type == "system_maintenance":
                # Maintenance task - display task name with human-readable label
                config = run.config or {}
                task_name = config.get("scheduled_task_name") or config.get("task_name") or "Maintenance Task"

                # Map task names to human-readable labels
                task_labels = {
                    "queue_pending_assets": "Queue Pending Extractions",
                    "cleanup_temp_files": "Cleanup Temp Files",
                    "cleanup_expired_jobs": "Cleanup Expired Jobs",
                    "detect_orphaned_objects": "Detect Orphaned Objects",
                    "enforce_retention": "Enforce Retention Policies",
                    "system_health_report": "System Health Report",
                    "search_reindex": "Search Index Rebuild",
                    "stale_run_cleanup": "Stale Run Cleanup",
                    "reindex_search": "Reindex Search",
                    "sharepoint_sync_hourly": "SharePoint Sync (Hourly)",
                    "sharepoint_sync_daily": "SharePoint Sync (Daily)",
                    "sam_pull_hourly": "SAM.gov Pull (Hourly)",
                    "sam_pull_daily": "SAM.gov Pull (Daily)",
                    "sync_sharepoint": "SharePoint Sync",
                    "sam_scheduled_pull": "SAM.gov Scheduled Pull",
                    "cleanup_old_runs": "Cleanup Old Runs",
                    "vacuum_database": "Vacuum Database",
                    "refresh_materialized_views": "Refresh Views",
                    "check_stale_extractions": "Check Stale Extractions",
                    "expire_old_tokens": "Expire Old Tokens",
                }
                display_name = task_labels.get(task_name, task_name.replace("_", " ").title())

                # Show task type as context if available
                task_type = config.get("task_type")
                display_context = task_type if task_type else None

            elif run.run_type in ("procedure", "procedure_run"):
                # Procedure run - display procedure name
                config = run.config or {}
                procedure_slug = config.get("procedure_slug", "Unknown Procedure")
                display_name = procedure_slug.replace("_", " ").replace("-", " ").title()
                params = config.get("params", {})
                if params:
                    display_context = f"{len(params)} param(s)"
                else:
                    display_context = None

            elif run.run_type in ("pipeline", "pipeline_run"):
                # Pipeline run - display pipeline name
                config = run.config or {}
                pipeline_slug = config.get("pipeline_slug", "Unknown Pipeline")
                display_name = pipeline_slug.replace("_", " ").replace("-", " ").title()
                params = config.get("params", {})
                if params:
                    display_context = f"{len(params)} param(s)"
                else:
                    display_context = None

            else:
                # Unknown type - use run_type as display name
                display_name = run.run_type
                display_context = None

            # Get parent-child relationship info
            is_parent_job = run.is_group_parent if hasattr(run, 'is_group_parent') else False
            group_id_str = str(run.group_id) if run.group_id else None
            parent_run_id_str = None
            child_stats_obj = None

            # For parent jobs, get child stats
            if is_parent_job and run.group_id:
                from ....database.models import RunGroup
                group = await session.get(RunGroup, run.group_id)
                if group:
                    # Get detailed child stats by status
                    child_stats_query = await session.execute(
                        select(Run.status, func.count(Run.id))
                        .where(and_(
                            Run.group_id == run.group_id,
                            Run.is_group_parent == False,
                        ))
                        .group_by(Run.status)
                    )
                    stats_by_status = {status: count for status, count in child_stats_query.all()}
                    child_stats_obj = ChildJobStats(
                        total=sum(stats_by_status.values()),
                        pending=stats_by_status.get("pending", 0),
                        submitted=stats_by_status.get("submitted", 0),
                        running=stats_by_status.get("running", 0),
                        completed=stats_by_status.get("completed", 0),
                        failed=stats_by_status.get("failed", 0),
                        cancelled=stats_by_status.get("cancelled", 0),
                        timed_out=stats_by_status.get("timed_out", 0),
                    )

            # For child jobs, get parent run ID
            elif run.group_id and not is_parent_job:
                from ....database.models import RunGroup
                group = await session.get(RunGroup, run.group_id)
                if group and group.parent_run_id:
                    parent_run_id_str = str(group.parent_run_id)

            items.append(ActiveJobItem(
                run_id=str(run.id),
                run_type=run.run_type,
                status=run.status,
                queue_priority=run.queue_priority or 0,
                created_at=run.created_at.isoformat() if run.created_at else "",
                started_at=run.started_at.isoformat() if run.started_at else None,
                submitted_at=run.submitted_to_celery_at.isoformat() if run.submitted_to_celery_at else None,
                completed_at=run.completed_at.isoformat() if run.completed_at else None,
                timeout_at=run.timeout_at.isoformat() if run.timeout_at else None,
                last_activity_at=run.last_activity_at.isoformat() if run.last_activity_at else None,
                display_name=display_name,
                display_context=display_context,
                asset_id=asset_id_str,
                filename=filename,
                source_type=source_type,
                extractor_version=extractor_version,
                queue_position=queue_position,
                config=run.config,
                progress=run.progress,
                can_cancel=can_cancel and run.status in ["pending", "submitted", "running"],
                can_retry=can_retry and run.status in ["failed", "timed_out"],
                is_parent_job=is_parent_job,
                group_id=group_id_str,
                parent_run_id=parent_run_id_str,
                child_stats=child_stats_obj,
            ))

        # Get total count
        count_result = await session.execute(
            select(func.count(Run.id))
            .where(and_(
                Run.run_type.in_(run_types),
                Run.organization_id == current_user.organization_id,
                Run.status.in_(statuses),
            ))
        )
        total = count_result.scalar() or 0

        return ActiveJobsResponse(
            items=items,
            total=total,
            run_types=sorted(list(run_types_found)),
        )


@router.get(
    "/jobs/{run_id}/children",
    response_model=ActiveJobsResponse,
    summary="Get child jobs for a parent job",
    description="Get all child jobs (e.g., extractions) for a parent job (e.g., SharePoint sync).",
)
async def get_child_jobs(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """
    Get child jobs for a parent job.

    Returns all child jobs linked to the parent job's group, with their status and details.
    """
    async with database_service.get_session() as session:
        from ....database.models import RunGroup

        # Verify parent run exists and belongs to user's organization
        parent_run = await session.get(Run, run_id)
        if not parent_run:
            raise HTTPException(status_code=404, detail="Run not found")

        if parent_run.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        if not parent_run.group_id:
            return ActiveJobsResponse(items=[], total=0, run_types=[])

        # Get child runs
        result = await session.execute(
            select(Run)
            .where(and_(
                Run.group_id == parent_run.group_id,
                Run.is_group_parent == False,
            ))
            .order_by(Run.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        child_runs = list(result.scalars().all())

        # Get total count
        count_result = await session.execute(
            select(func.count(Run.id))
            .where(and_(
                Run.group_id == parent_run.group_id,
                Run.is_group_parent == False,
            ))
        )
        total = count_result.scalar() or 0

        # Build items (simplified for children)
        items = []
        run_types_found = set()

        for run in child_runs:
            run_types_found.add(run.run_type)
            queue_def = queue_registry.get(run.run_type)

            # Get display name from config
            display_name = "Unknown"
            if run.run_type == "extraction" and run.config:
                display_name = run.config.get("filename", "Unknown document")

            items.append(ActiveJobItem(
                run_id=str(run.id),
                run_type=run.run_type,
                status=run.status,
                queue_priority=run.queue_priority or 0,
                created_at=run.created_at.isoformat() if run.created_at else "",
                started_at=run.started_at.isoformat() if run.started_at else None,
                submitted_at=run.submitted_to_celery_at.isoformat() if run.submitted_to_celery_at else None,
                completed_at=run.completed_at.isoformat() if run.completed_at else None,
                timeout_at=run.timeout_at.isoformat() if run.timeout_at else None,
                last_activity_at=run.last_activity_at.isoformat() if run.last_activity_at else None,
                display_name=display_name,
                display_context=None,
                asset_id=run.input_asset_ids[0] if run.input_asset_ids else None,
                filename=run.config.get("filename") if run.config else None,
                source_type=None,
                extractor_version=run.config.get("extractor_version") if run.config else None,
                queue_position=None,
                config=run.config,
                progress=run.progress,
                can_cancel=queue_def.can_cancel if queue_def else False,
                can_retry=queue_def.can_retry if queue_def else False,
                is_parent_job=False,
                group_id=str(run.group_id) if run.group_id else None,
                parent_run_id=str(run_id),
            ))

        return ActiveJobsResponse(
            items=items,
            total=total,
            run_types=sorted(list(run_types_found)),
        )


@router.post(
    "/jobs/{run_id}/cancel",
    response_model=CancelResponse,
    summary="Cancel a job",
    description="Cancel a pending, submitted, or running job (if cancellation is supported for the job type). "
                "For parent jobs, this will also cancel child jobs based on the job type's cascade mode.",
)
async def cancel_job(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
):
    """
    Cancel a job by run ID with cascade cancellation for parent jobs.

    This unified endpoint supports cancelling any job type where cancellation
    is supported (based on queue_registry capabilities).

    Cascade behavior:
    - SharePoint Sync: Cancel queued child extractions (running ones complete)
    - SAM.gov Pull: Cancel queued child extractions (running ones complete)
    - Web Scrape: Cancel queued child extractions (running ones complete)
    - Pipeline: Cancel ALL child jobs (atomicity)
    - Extraction: Cancel single extraction

    Returns:
    - status: "cancelled" if successful
    - children_cancelled: Number of child jobs that were cancelled
    - children_skipped: Number of child jobs that were skipped (already completed/running)
    """
    async with database_service.get_session() as session:
        # Verify run exists and belongs to user's organization
        run = await session.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        if run.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Check if this run type supports cancellation
        if not queue_registry.can_cancel(run.run_type):
            raise HTTPException(
                status_code=400,
                detail=f"Job type '{run.run_type}' does not support cancellation"
            )

        # Check if status allows cancellation
        if run.status not in ["pending", "submitted", "running"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel job in '{run.status}' status"
            )

        # For standalone extractions, use the extraction queue service
        if run.run_type == "extraction" and not run.is_group_parent:
            result = await extraction_queue_service.cancel_extraction(
                session=session,
                run_id=run_id,
                reason=f"Cancelled by user {current_user.email}",
            )

            if result["status"] == "not_found":
                raise HTTPException(status_code=404, detail="Run not found")

            if result["status"] == "not_cancellable":
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot cancel run in '{result.get('current_status')}' status"
                )

            return CancelResponse(
                status=result["status"],
                run_id=str(run_id),
                reason=result.get("reason"),
            )

        # For parent jobs and other job types, use cascade cancellation service
        from ....services.job_cancellation_service import job_cancellation_service

        result = await job_cancellation_service.cancel_parent_job(
            session=session,
            run_id=run_id,
            reason=f"Cancelled by user {current_user.email}",
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=400,
                detail=result.get("error", "Cancellation failed")
            )

        return CancelResponse(
            status="cancelled",
            run_id=str(run_id),
            reason=f"Cancelled by user {current_user.email}",
            children_cancelled=result.get("children_cancelled", 0),
            children_skipped=result.get("children_skipped", 0),
        )
