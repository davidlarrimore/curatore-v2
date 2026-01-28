# backend/app/api/v1/routers/runs.py
"""
Runs API Router for Phase 0.

Provides endpoints for querying runs, log events, and triggering retries.
"""

import logging
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ....database.models import User
from ....dependencies import get_current_user
from ....services.database_service import database_service
from ....services.run_service import run_service
from ....services.run_log_service import run_log_service
from ....services.asset_service import asset_service
from ....services.extraction_result_service import extraction_result_service
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

        # Enqueue extraction task
        from ....tasks import execute_extraction_task
        from ....config import settings

        task = execute_extraction_task.apply_async(
            kwargs={
                "asset_id": str(asset_id),
                "run_id": str(new_run.id),
                "extraction_id": str(extraction.id),
            },
            queue=settings.celery_default_queue or "processing",
        )

        logger.info(
            f"Retry extraction triggered for asset {asset_id}: "
            f"new_run={new_run.id}, task={task.id}"
        )

        await session.commit()

        return RunResponse.model_validate(new_run)
