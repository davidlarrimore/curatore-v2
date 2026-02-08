# backend/app/api/v1/routers/scheduled_tasks.py
"""
Scheduled task management endpoints for Curatore v2 API (v1).

Provides endpoints for managing database-backed scheduled maintenance tasks
with admin visibility and control (Phase 5).

Endpoints:
    GET /scheduled-tasks - List scheduled tasks
    GET /scheduled-tasks/stats - Get maintenance statistics
    GET /scheduled-tasks/{task_id} - Get task details
    POST /scheduled-tasks/{task_id}/enable - Enable a task
    POST /scheduled-tasks/{task_id}/disable - Disable a task
    POST /scheduled-tasks/{task_id}/trigger - Trigger task manually
    GET /scheduled-tasks/{task_id}/runs - Get task run history

Security:
    - All endpoints require org_admin role
    - Tasks are organization-scoped (global tasks visible to all admins)
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.database.models import ScheduledTask, Run, User
from app.dependencies import get_current_user, require_org_admin
from app.core.shared.database_service import database_service
from app.core.ops.scheduled_task_service import scheduled_task_service

# Initialize router
router = APIRouter(prefix="/scheduled-tasks", tags=["Scheduled Tasks"])

# Initialize logger
logger = logging.getLogger("curatore.api.scheduled_tasks")


# =========================================================================
# Pydantic Models
# =========================================================================


class ScheduledTaskResponse(BaseModel):
    """Response model for scheduled task."""
    id: str
    organization_id: Optional[str]
    name: str
    display_name: str
    description: Optional[str]
    task_type: str
    scope_type: str
    schedule_expression: str
    schedule_description: str
    enabled: bool
    config: Dict[str, Any]
    last_run_id: Optional[str]
    last_run_at: Optional[str]
    last_run_status: Optional[str]
    next_run_at: Optional[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ScheduledTaskListResponse(BaseModel):
    """Response model for task list."""
    tasks: List[ScheduledTaskResponse]
    total: int


class MaintenanceStatsResponse(BaseModel):
    """Response model for maintenance statistics."""
    total_tasks: int
    enabled_tasks: int
    disabled_tasks: int
    total_runs: int
    successful_runs: int
    failed_runs: int
    success_rate: float
    last_run_at: Optional[str]
    last_run_status: Optional[str]
    period_days: int


class TaskRunResponse(BaseModel):
    """Response model for a task run."""
    id: str
    run_type: str
    origin: str
    status: str
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    results_summary: Optional[Dict[str, Any]]
    error_message: Optional[str]

    class Config:
        from_attributes = True


class TaskRunListResponse(BaseModel):
    """Response model for task run list."""
    runs: List[TaskRunResponse]
    total: int


class TriggerTaskRequest(BaseModel):
    """Optional request body for triggering a task with config overrides."""
    config_overrides: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Override task config values for this run only. Merged on top of the task's stored config."
    )


class TriggerTaskResponse(BaseModel):
    """Response model for task trigger."""
    message: str
    task_id: str
    task_name: str
    run_id: str


class EnableDisableResponse(BaseModel):
    """Response model for enable/disable."""
    message: str
    task_id: str
    task_name: str
    enabled: bool
    next_run_at: Optional[str]


# =========================================================================
# Helper Functions
# =========================================================================


def _task_to_response(task: ScheduledTask) -> ScheduledTaskResponse:
    """Convert ScheduledTask model to response."""
    return ScheduledTaskResponse(
        id=str(task.id),
        organization_id=str(task.organization_id) if task.organization_id else None,
        name=task.name,
        display_name=task.display_name,
        description=task.description,
        task_type=task.task_type,
        scope_type=task.scope_type,
        schedule_expression=task.schedule_expression,
        schedule_description=scheduled_task_service._get_schedule_description(
            task.schedule_expression
        ),
        enabled=task.enabled,
        config=task.config or {},
        last_run_id=str(task.last_run_id) if task.last_run_id else None,
        last_run_at=task.last_run_at.isoformat() if task.last_run_at else None,
        last_run_status=task.last_run_status,
        next_run_at=task.next_run_at.isoformat() if task.next_run_at else None,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
    )


def _run_to_response(run: Run) -> TaskRunResponse:
    """Convert Run model to response."""
    return TaskRunResponse(
        id=str(run.id),
        run_type=run.run_type,
        origin=run.origin,
        status=run.status,
        created_at=run.created_at.isoformat(),
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        results_summary=run.results_summary,
        error_message=run.error_message,
    )


# =========================================================================
# LIST & STATS ENDPOINTS
# =========================================================================


@router.get(
    "",
    response_model=ScheduledTaskListResponse,
    summary="List scheduled tasks",
    description="List all scheduled tasks (global and organization-scoped)."
)
async def list_scheduled_tasks(
    enabled_only: bool = Query(False, description="Only return enabled tasks"),
    current_user: User = Depends(require_org_admin),
) -> ScheduledTaskListResponse:
    """
    List scheduled tasks.

    Returns global tasks and tasks scoped to the user's organization.
    Requires org_admin role.

    Args:
        enabled_only: Filter to only enabled tasks
        current_user: Current authenticated user (must be org_admin)

    Returns:
        ScheduledTaskListResponse: List of tasks
    """
    async with database_service.get_session() as session:
        tasks = await scheduled_task_service.list_tasks(
            session,
            organization_id=current_user.organization_id,
            enabled_only=enabled_only,
        )

        return ScheduledTaskListResponse(
            tasks=[_task_to_response(t) for t in tasks],
            total=len(tasks),
        )


@router.get(
    "/stats",
    response_model=MaintenanceStatsResponse,
    summary="Get maintenance statistics",
    description="Get statistics about scheduled maintenance tasks and runs."
)
async def get_maintenance_stats(
    days: int = Query(7, ge=1, le=90, description="Number of days to look back"),
    current_user: User = Depends(require_org_admin),
) -> MaintenanceStatsResponse:
    """
    Get maintenance task statistics.

    Returns aggregate statistics about scheduled tasks and their recent runs.
    Requires org_admin role.

    Args:
        days: Number of days to look back for run statistics
        current_user: Current authenticated user (must be org_admin)

    Returns:
        MaintenanceStatsResponse: Maintenance statistics
    """
    async with database_service.get_session() as session:
        stats = await scheduled_task_service.get_maintenance_stats(session, days=days)
        return MaintenanceStatsResponse(**stats)


# =========================================================================
# TASK DETAIL ENDPOINTS
# =========================================================================


@router.get(
    "/{task_id}",
    response_model=ScheduledTaskResponse,
    summary="Get task details",
    description="Get details for a specific scheduled task."
)
async def get_scheduled_task(
    task_id: UUID,
    current_user: User = Depends(require_org_admin),
) -> ScheduledTaskResponse:
    """
    Get scheduled task details.

    Args:
        task_id: Task UUID
        current_user: Current authenticated user (must be org_admin)

    Returns:
        ScheduledTaskResponse: Task details

    Raises:
        HTTPException: 404 if task not found
    """
    async with database_service.get_session() as session:
        task = await scheduled_task_service.get_task(session, task_id)

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Scheduled task not found: {task_id}"
            )

        # Check access (global tasks or same organization)
        if task.organization_id and task.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this task"
            )

        return _task_to_response(task)


@router.get(
    "/{task_id}/runs",
    response_model=TaskRunListResponse,
    summary="Get task run history",
    description="Get recent runs for a specific scheduled task."
)
async def get_task_runs(
    task_id: UUID,
    limit: int = Query(20, ge=1, le=100, description="Maximum runs to return"),
    offset: int = Query(0, ge=0, description="Number of runs to skip"),
    current_user: User = Depends(require_org_admin),
) -> TaskRunListResponse:
    """
    Get run history for a scheduled task.

    Args:
        task_id: Task UUID
        limit: Maximum runs to return
        offset: Number of runs to skip
        current_user: Current authenticated user (must be org_admin)

    Returns:
        TaskRunListResponse: List of runs

    Raises:
        HTTPException: 404 if task not found
    """
    async with database_service.get_session() as session:
        task = await scheduled_task_service.get_task(session, task_id)

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Scheduled task not found: {task_id}"
            )

        # Check access
        if task.organization_id and task.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this task"
            )

        runs = await scheduled_task_service.get_task_runs(
            session, task_id, limit=limit, offset=offset
        )

        return TaskRunListResponse(
            runs=[_run_to_response(r) for r in runs],
            total=len(runs),
        )


# =========================================================================
# TASK CONTROL ENDPOINTS
# =========================================================================


@router.post(
    "/{task_id}/enable",
    response_model=EnableDisableResponse,
    summary="Enable task",
    description="Enable a scheduled task to run on its schedule."
)
async def enable_task(
    task_id: UUID,
    current_user: User = Depends(require_org_admin),
) -> EnableDisableResponse:
    """
    Enable a scheduled task.

    Args:
        task_id: Task UUID
        current_user: Current authenticated user (must be org_admin)

    Returns:
        EnableDisableResponse: Updated task status

    Raises:
        HTTPException: 404 if task not found
    """
    async with database_service.get_session() as session:
        task = await scheduled_task_service.get_task(session, task_id)

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Scheduled task not found: {task_id}"
            )

        # Check access
        if task.organization_id and task.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this task"
            )

        updated_task = await scheduled_task_service.enable_task(session, task_id)
        await session.commit()

        logger.info(f"Task enabled: {task.name} by user {current_user.id}")

        return EnableDisableResponse(
            message=f"Task '{task.display_name}' enabled",
            task_id=str(task_id),
            task_name=task.name,
            enabled=True,
            next_run_at=updated_task.next_run_at.isoformat() if updated_task.next_run_at else None,
        )


@router.post(
    "/{task_id}/disable",
    response_model=EnableDisableResponse,
    summary="Disable task",
    description="Disable a scheduled task from running."
)
async def disable_task(
    task_id: UUID,
    current_user: User = Depends(require_org_admin),
) -> EnableDisableResponse:
    """
    Disable a scheduled task.

    Args:
        task_id: Task UUID
        current_user: Current authenticated user (must be org_admin)

    Returns:
        EnableDisableResponse: Updated task status

    Raises:
        HTTPException: 404 if task not found
    """
    async with database_service.get_session() as session:
        task = await scheduled_task_service.get_task(session, task_id)

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Scheduled task not found: {task_id}"
            )

        # Check access
        if task.organization_id and task.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this task"
            )

        await scheduled_task_service.disable_task(session, task_id)
        await session.commit()

        logger.info(f"Task disabled: {task.name} by user {current_user.id}")

        return EnableDisableResponse(
            message=f"Task '{task.display_name}' disabled",
            task_id=str(task_id),
            task_name=task.name,
            enabled=False,
            next_run_at=None,
        )


@router.post(
    "/{task_id}/trigger",
    response_model=TriggerTaskResponse,
    summary="Trigger task",
    description="Trigger a scheduled task to run immediately."
)
async def trigger_task(
    task_id: UUID,
    body: Optional[TriggerTaskRequest] = None,
    current_user: User = Depends(require_org_admin),
) -> TriggerTaskResponse:
    """
    Trigger a scheduled task to run immediately.

    Creates a Run with origin="user" and enqueues the task for execution.
    Optionally accepts config_overrides to customize this run.

    Args:
        task_id: Task UUID
        body: Optional request body with config overrides
        current_user: Current authenticated user (must be org_admin)

    Returns:
        TriggerTaskResponse: Trigger result with run ID

    Raises:
        HTTPException: 404 if task not found
    """
    async with database_service.get_session() as session:
        task = await scheduled_task_service.get_task(session, task_id)

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Scheduled task not found: {task_id}"
            )

        # Check access
        if task.organization_id and task.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this task"
            )

        config_overrides = body.config_overrides if body else None
        run = await scheduled_task_service.trigger_task_now(
            session, task_id, triggered_by=current_user.id,
            user_organization_id=current_user.organization_id,
            config_overrides=config_overrides,
        )
        await session.commit()

        logger.info(f"Task triggered manually: {task.name} by user {current_user.id} (run={run.id})")

        return TriggerTaskResponse(
            message=f"Task '{task.display_name}' triggered",
            task_id=str(task_id),
            task_name=task.name,
            run_id=str(run.id),
        )
