# backend/app/api/v1/routers/runs.py
"""
Runs API Router for Phase 0.

Provides endpoints for querying runs, log events, triggering retries,
and priority boosting for extractions.
"""

import logging
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Response
from pydantic import BaseModel

from ....database.models import User
from ....dependencies import get_current_user
from ....services.database_service import database_service
from ....services.run_service import run_service
from ....services.run_log_service import run_log_service
from ....services.asset_service import asset_service
from ....services.extraction_result_service import extraction_result_service
from ....services.priority_queue_service import (
    priority_queue_service,
    BoostReason,
    PriorityTier,
)
from ..models import (
    RunResponse,
    RunWithLogsResponse,
    RunLogEventResponse,
    RunsListResponse,
)

logger = logging.getLogger("curatore.api.runs")

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get(
    "",
    response_model=RunsListResponse,
    summary="List runs",
    description="List runs for the organization with optional filters.",
)
async def list_runs(
    run_type: Optional[str] = Query(None, description="Filter by type (extraction, processing, etc.)"),
    status: Optional[str] = Query(None, description="Filter by status (pending, running, completed, failed)"),
    origin: Optional[str] = Query(None, description="Filter by origin (user, system, scheduled)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    current_user: User = Depends(get_current_user),
) -> RunsListResponse:
    """List runs for the organization."""
    async with database_service.get_session() as session:
        runs = await run_service.get_runs_by_organization(
            session=session,
            organization_id=current_user.organization_id,
            run_type=run_type,
            status=status,
            origin=origin,
            limit=limit,
            offset=offset,
        )

        total = await run_service.count_runs_by_organization(
            session=session,
            organization_id=current_user.organization_id,
            run_type=run_type,
            status=status,
        )

        return RunsListResponse(
            items=[RunResponse.model_validate(r) for r in runs],
            total=total,
            limit=limit,
            offset=offset,
        )


@router.get(
    "/stats",
    summary="Get run statistics",
    description="Get aggregated statistics about runs for the organization.",
)
async def get_run_stats(
    current_user: User = Depends(get_current_user),
):
    """Get run statistics for the organization."""
    async with database_service.get_session() as session:
        from sqlalchemy import func, select, and_
        from datetime import datetime, timedelta
        from ....database.models import Run, Asset

        org_id = current_user.organization_id

        # Count by status
        status_counts = await session.execute(
            select(Run.status, func.count(Run.id))
            .where(Run.organization_id == org_id)
            .group_by(Run.status)
        )
        by_status = {row[0]: row[1] for row in status_counts.fetchall()}

        # Count by run_type
        type_counts = await session.execute(
            select(Run.run_type, func.count(Run.id))
            .where(Run.organization_id == org_id)
            .group_by(Run.run_type)
        )
        by_type = {row[0]: row[1] for row in type_counts.fetchall()}

        # Recent activity (last 24 hours)
        yesterday = datetime.utcnow() - timedelta(hours=24)
        recent_counts = await session.execute(
            select(Run.status, func.count(Run.id))
            .where(and_(
                Run.organization_id == org_id,
                Run.created_at >= yesterday
            ))
            .group_by(Run.status)
        )
        recent_by_status = {row[0]: row[1] for row in recent_counts.fetchall()}

        # Asset status counts
        asset_counts = await session.execute(
            select(Asset.status, func.count(Asset.id))
            .where(Asset.organization_id == org_id)
            .group_by(Asset.status)
        )
        assets_by_status = {row[0]: row[1] for row in asset_counts.fetchall()}

        # Queue length (from Redis)
        try:
            import redis
            r = redis.Redis(host='redis', port=6379, db=0)
            queue_lengths = {
                "processing_priority": r.llen("processing_priority"),
                "extraction": r.llen("extraction"),
                "sam": r.llen("sam"),
                "scrape": r.llen("scrape"),
                "sharepoint": r.llen("sharepoint"),
                "maintenance": r.llen("maintenance"),
            }
        except Exception:
            queue_lengths = {
                "processing_priority": 0,
                "extraction": 0,
                "sam": 0,
                "scrape": 0,
                "sharepoint": 0,
                "maintenance": 0,
            }

        return {
            "runs": {
                "by_status": by_status,
                "by_type": by_type,
                "total": sum(by_status.values()),
            },
            "recent_24h": {
                "by_status": recent_by_status,
                "total": sum(recent_by_status.values()),
            },
            "assets": {
                "by_status": assets_by_status,
                "total": sum(assets_by_status.values()),
            },
            "queues": queue_lengths,
        }


# =============================================================================
# Queue and Priority Boost Endpoints (must be before /{run_id})
# =============================================================================


class BoostAssetRequest(BaseModel):
    """Request model for boosting a single asset."""
    asset_id: UUID
    reason: Optional[str] = "user_requested"


class BoostAssetsRequest(BaseModel):
    """Request model for boosting multiple assets."""
    asset_ids: List[UUID]
    reason: Optional[str] = "user_requested"


@router.get(
    "/queues",
    summary="Get queue statistics (Deprecated)",
    description="Get current queue lengths and processing status. "
                "DEPRECATED: Use GET /api/v1/queue/unified instead.",
    deprecated=True,
)
async def get_queue_stats(
    response: Response,
    current_user: User = Depends(get_current_user),
):
    """
    Get queue statistics for monitoring.

    Returns lengths of priority, normal, and maintenance queues.

    DEPRECATED: Use GET /api/v1/queue/unified for comprehensive stats.
    """
    # Add deprecation headers
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-06-01"
    response.headers["Link"] = '</api/v1/queue/unified>; rel="successor-version"'

    return await priority_queue_service.get_queue_stats()


@router.post(
    "/boost/asset",
    summary="Boost extraction priority (Deprecated)",
    description="Boost the extraction priority for a single asset. "
                "DEPRECATED: Use POST /api/v1/assets/{asset_id}/boost instead.",
    deprecated=True,
)
async def boost_asset_extraction_endpoint(
    request: BoostAssetRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
):
    """
    Boost extraction priority for a single asset.

    Use this when a user is waiting for a specific document to be processed.
    The extraction will be moved to the high-priority queue.

    DEPRECATED: Use POST /api/v1/assets/{asset_id}/boost instead.
    """
    # Add deprecation headers
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-06-01"
    response.headers["Link"] = '</api/v1/assets/{asset_id}/boost>; rel="successor-version"'

    # Map string reason to enum
    try:
        reason = BoostReason(request.reason) if request.reason else BoostReason.USER_REQUESTED
    except ValueError:
        reason = BoostReason.USER_REQUESTED

    async with database_service.get_session() as session:
        # Verify asset belongs to user's organization
        asset = await asset_service.get_asset(session=session, asset_id=request.asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        result = await priority_queue_service.boost_extraction(
            session=session,
            asset_id=request.asset_id,
            reason=reason,
            organization_id=current_user.organization_id,
        )

        return result


@router.post(
    "/boost/assets",
    summary="Boost multiple extraction priorities",
    description="Boost extraction priority for multiple assets at once.",
)
async def boost_multiple_assets_endpoint(
    request: BoostAssetsRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Boost extraction priority for multiple assets.

    Use this when preparing for a batch operation that needs multiple
    documents to be ready (e.g., export, AI summarization).
    """
    # Map string reason to enum
    try:
        reason = BoostReason(request.reason) if request.reason else BoostReason.USER_REQUESTED
    except ValueError:
        reason = BoostReason.USER_REQUESTED

    async with database_service.get_session() as session:
        # Verify all assets belong to user's organization
        for asset_id in request.asset_ids:
            asset = await asset_service.get_asset(session=session, asset_id=asset_id)
            if not asset:
                raise HTTPException(
                    status_code=404,
                    detail=f"Asset {asset_id} not found"
                )
            if asset.organization_id != current_user.organization_id:
                raise HTTPException(status_code=403, detail="Access denied")

        result = await priority_queue_service.boost_multiple_extractions(
            session=session,
            asset_ids=request.asset_ids,
            reason=reason,
            organization_id=current_user.organization_id,
        )

        return result


@router.post(
    "/boost/check-ready",
    summary="Check if assets are ready",
    description="Check if specified assets have completed extraction.",
)
async def check_assets_ready_endpoint(
    asset_ids: List[UUID] = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
):
    """
    Check if assets are ready for processing.

    Returns which assets are ready and which are still pending.
    Useful for UI to show progress before running operations.
    """
    async with database_service.get_session() as session:
        all_ready, ready_ids, pending_ids = await priority_queue_service.check_assets_ready(
            session=session,
            asset_ids=asset_ids,
        )

        return {
            "all_ready": all_ready,
            "total": len(asset_ids),
            "ready_count": len(ready_ids),
            "pending_count": len(pending_ids),
            "ready_ids": [str(id) for id in ready_ids],
            "pending_ids": [str(id) for id in pending_ids],
        }


# =============================================================================
# Run-specific endpoints (dynamic paths with /{run_id})
# =============================================================================


@router.get(
    "/{run_id}",
    response_model=RunResponse,
    summary="Get run",
    description="Get run details by ID.",
)
async def get_run(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
) -> RunResponse:
    """Get run by ID."""
    async with database_service.get_session() as session:
        run = await run_service.get_run(session=session, run_id=run_id)

        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        # Verify run belongs to user's organization
        if run.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        return RunResponse.model_validate(run)


@router.get(
    "/{run_id}/logs",
    response_model=RunWithLogsResponse,
    summary="Get run with logs",
    description="Get run with all log events.",
)
async def get_run_with_logs(
    run_id: UUID,
    level: Optional[str] = Query(None, description="Filter by log level (INFO, WARN, ERROR)"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Limit log events"),
    current_user: User = Depends(get_current_user),
) -> RunWithLogsResponse:
    """Get run with log events."""
    async with database_service.get_session() as session:
        run = await run_service.get_run(session=session, run_id=run_id)

        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        # Verify run belongs to user's organization
        if run.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Get log events
        logs = await run_log_service.get_events_for_run(
            session=session,
            run_id=run_id,
            level=level,
            event_type=event_type,
            limit=limit,
        )

        return RunWithLogsResponse(
            run=RunResponse.model_validate(run),
            logs=[RunLogEventResponse.model_validate(log) for log in logs],
        )


@router.post(
    "/{run_id}/retry",
    response_model=RunResponse,
    summary="Retry failed extraction",
    description="Retry a failed extraction run (creates new run).",
)
async def retry_extraction(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
) -> RunResponse:
    """
    Retry a failed extraction.

    This creates a new extraction run for the same asset.
    """
    async with database_service.get_session() as session:
        # Get original run
        original_run = await run_service.get_run(session=session, run_id=run_id)

        if not original_run:
            raise HTTPException(status_code=404, detail="Run not found")

        # Verify run belongs to user's organization
        if original_run.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Only allow retry for failed extraction runs
        if original_run.run_type != "extraction":
            raise HTTPException(
                status_code=400,
                detail="Only extraction runs can be retried"
            )

        if original_run.status != "failed":
            raise HTTPException(
                status_code=400,
                detail=f"Run is not failed (status: {original_run.status})"
            )

        # Get the asset ID from input_asset_ids
        if not original_run.input_asset_ids:
            raise HTTPException(
                status_code=400,
                detail="No asset found in run config"
            )

        asset_id = UUID(original_run.input_asset_ids[0])

        # Verify asset exists
        asset = await asset_service.get_asset(session=session, asset_id=asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        # Create new extraction run
        new_run = await run_service.create_run(
            session=session,
            organization_id=current_user.organization_id,
            run_type="extraction",
            origin="user",  # User-triggered retry
            config={
                **original_run.config,
                "retry_of": str(run_id),
            },
            input_asset_ids=[str(asset_id)],
            created_by=current_user.id,
        )

        # Create new extraction result
        extraction = await extraction_result_service.create_extraction_result(
            session=session,
            asset_id=asset_id,
            run_id=new_run.id,
            extractor_version=original_run.config.get("extractor_version", "markitdown-1.0"),
        )

        # Log retry
        await run_log_service.log_start(
            session=session,
            run_id=new_run.id,
            message=f"Manual retry of failed extraction (original run: {run_id})",
            context={
                "original_run_id": str(run_id),
                "asset_id": str(asset_id),
                "extraction_id": str(extraction.id),
            },
        )

        # Enqueue extraction task on priority queue (user-initiated retry)
        from ....tasks import execute_extraction_task

        task = execute_extraction_task.apply_async(
            kwargs={
                "asset_id": str(asset_id),
                "run_id": str(new_run.id),
                "extraction_id": str(extraction.id),
            },
            queue=PriorityTier.HIGH.value,  # User retries get priority
        )

        logger.info(
            f"Retry extraction triggered for asset {asset_id}: "
            f"new_run={new_run.id}, task={task.id}"
        )

        await session.commit()

        return RunResponse.model_validate(new_run)
