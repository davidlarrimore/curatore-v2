# backend/app/api/v1/routers/runs.py
"""
Runs API Router.

Provides endpoints for querying runs, viewing log events, triggering retries,
and getting run group status for parent-child job tracking.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.database.models import User
from app.dependencies import get_current_user
from app.core.shared.database_service import database_service
from app.core.shared.run_service import run_service
from app.core.shared.run_log_service import run_log_service
from app.core.shared.run_group_service import run_group_service
from app.core.shared.asset_service import asset_service
from app.core.ingestion.extraction_result_service import extraction_result_service
from app.core.ops.priority_queue_service import PriorityTier
from app.api.v1.ops.schemas import (
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
        from app.core.database.models import Run, Asset

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
    "/{run_id}/group-status",
    summary="Get run with group status",
    description="Get run status with child job counts if part of a run group.",
)
async def get_run_group_status(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
):
    """
    Get run status with child job counts.

    If the run is a group parent (e.g., SAM pull spawning extractions),
    this returns child job statistics from the associated RunGroup.

    Used by the Running Job Panel to display progress for parent jobs.
    """
    async with database_service.get_session() as session:
        run = await run_service.get_run(session=session, run_id=run_id)

        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        if run.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        response = {
            "run": RunResponse.model_validate(run).model_dump(),
            "group": None,
        }

        # If this is a group parent, get child stats
        if run.is_group_parent and run.group_id:
            group = await run_group_service.get_group(session, run.group_id)
            if group:
                response["group"] = {
                    "id": str(group.id),
                    "group_type": group.group_type,
                    "status": group.status,
                    "total_children": group.total_children,
                    "completed_children": group.completed_children,
                    "failed_children": group.failed_children,
                    "started_at": group.started_at.isoformat() if group.started_at else None,
                    "completed_at": group.completed_at.isoformat() if group.completed_at else None,
                }

        return response


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

        # Commit before dispatching Celery task to ensure Run and ExtractionResult
        # are visible to the worker
        await session.commit()

        # Enqueue extraction task on priority queue (user-initiated retry)
        from app.core.tasks import execute_extraction_task

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

        return RunResponse.model_validate(new_run)
