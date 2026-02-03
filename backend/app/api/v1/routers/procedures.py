# backend/app/api/v1/routers/procedures.py
"""
Procedures API router.

Provides endpoints for:
- Listing procedures
- Getting procedure details
- Running procedures
- Managing triggers
"""

from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel, Field
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ....services.database_service import database_service
from ....dependencies import get_current_user, get_current_user_optional, get_optional_current_user, get_current_org_id
from ....database.models import User
from ....database.procedures import Procedure, ProcedureTrigger
from ....procedures import procedure_executor, procedure_loader

logger = logging.getLogger("curatore.api.procedures")

router = APIRouter(prefix="/procedures", tags=["Procedures"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class TriggerSchema(BaseModel):
    """Trigger configuration schema."""
    id: Optional[str] = None
    trigger_type: str
    cron_expression: Optional[str] = None
    event_name: Optional[str] = None
    event_filter: Optional[Dict[str, Any]] = None
    is_active: bool = True
    last_triggered_at: Optional[datetime] = None
    next_trigger_at: Optional[datetime] = None


class ProcedureSchema(BaseModel):
    """Procedure schema."""
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    version: int
    is_active: bool
    is_system: bool
    source_type: str
    definition: Dict[str, Any]
    triggers: List[TriggerSchema] = []
    created_at: datetime
    updated_at: datetime


class ProcedureListItem(BaseModel):
    """Procedure list item schema."""
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    version: int
    is_active: bool
    is_system: bool
    source_type: str
    trigger_count: int = 0
    tags: List[str] = []
    created_at: datetime
    updated_at: datetime


class ProcedureListResponse(BaseModel):
    """List of procedures response."""
    procedures: List[ProcedureListItem]
    total: int


class RunProcedureRequest(BaseModel):
    """Request to run a procedure."""
    params: Dict[str, Any] = Field(default_factory=dict, description="Procedure parameters")
    dry_run: bool = Field(default=False, description="If true, don't make changes")
    async_execution: bool = Field(default=True, description="Run asynchronously via Celery")


class RunProcedureResponse(BaseModel):
    """Procedure run response."""
    run_id: Optional[str] = None
    status: str
    message: Optional[str] = None
    results: Optional[Dict[str, Any]] = None


class CreateTriggerRequest(BaseModel):
    """Request to create a trigger."""
    trigger_type: str = Field(..., description="Type: cron, event, webhook")
    cron_expression: Optional[str] = Field(None, description="Cron expression (for cron triggers)")
    event_name: Optional[str] = Field(None, description="Event name (for event triggers)")
    event_filter: Optional[Dict[str, Any]] = Field(None, description="Event filter")
    trigger_params: Optional[Dict[str, Any]] = Field(None, description="Parameters to pass when triggered")


class UpdateProcedureRequest(BaseModel):
    """Request to update procedure settings."""
    is_active: Optional[bool] = None
    description: Optional[str] = None


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/", response_model=ProcedureListResponse)
async def list_procedures(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    List all procedures.
    """
    async with database_service.get_session() as session:
        query = select(Procedure).where(
            Procedure.organization_id == organization_id,
        )

        if is_active is not None:
            query = query.where(Procedure.is_active == is_active)

        result = await session.execute(query)
        procedures = result.scalars().all()

        items = []
        for proc in procedures:
            definition = proc.definition or {}
            tags = definition.get("tags", [])

            # Filter by tag if specified
            if tag and tag not in tags:
                continue

            # Count triggers
            trigger_query = select(ProcedureTrigger).where(
                ProcedureTrigger.procedure_id == proc.id,
                ProcedureTrigger.is_active == True,
            )
            trigger_result = await session.execute(trigger_query)
            trigger_count = len(trigger_result.scalars().all())

            items.append(ProcedureListItem(
                id=str(proc.id),
                name=proc.name,
                slug=proc.slug,
                description=proc.description,
                version=proc.version,
                is_active=proc.is_active,
                is_system=proc.is_system,
                source_type=proc.source_type,
                trigger_count=trigger_count,
                tags=tags,
                created_at=proc.created_at,
                updated_at=proc.updated_at,
            ))

        return ProcedureListResponse(
            procedures=items,
            total=len(items),
        )


@router.get("/{slug}", response_model=ProcedureSchema)
async def get_procedure(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Get procedure details by slug.
    """
    async with database_service.get_session() as session:
        query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        # Get triggers
        trigger_query = select(ProcedureTrigger).where(
            ProcedureTrigger.procedure_id == procedure.id,
        )
        trigger_result = await session.execute(trigger_query)
        triggers = trigger_result.scalars().all()

        return ProcedureSchema(
            id=str(procedure.id),
            name=procedure.name,
            slug=procedure.slug,
            description=procedure.description,
            version=procedure.version,
            is_active=procedure.is_active,
            is_system=procedure.is_system,
            source_type=procedure.source_type,
            definition=procedure.definition,
            triggers=[
                TriggerSchema(
                    id=str(t.id),
                    trigger_type=t.trigger_type,
                    cron_expression=t.cron_expression,
                    event_name=t.event_name,
                    event_filter=t.event_filter,
                    is_active=t.is_active,
                    last_triggered_at=t.last_triggered_at,
                    next_trigger_at=t.next_trigger_at,
                )
                for t in triggers
            ],
            created_at=procedure.created_at,
            updated_at=procedure.updated_at,
        )


@router.put("/{slug}", response_model=ProcedureSchema)
async def update_procedure(
    slug: str,
    request: UpdateProcedureRequest,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Update procedure settings.
    """
    async with database_service.get_session() as session:
        query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        if procedure.is_system and request.description is not None:
            raise HTTPException(
                status_code=400,
                detail="Cannot modify description of system procedures",
            )

        if request.is_active is not None:
            procedure.is_active = request.is_active
        if request.description is not None:
            procedure.description = request.description

        procedure.updated_at = datetime.utcnow()
        await session.commit()

        return await get_procedure(slug, organization_id)


@router.post("/{slug}/run", response_model=RunProcedureResponse)
async def run_procedure(
    slug: str,
    request: RunProcedureRequest,
    organization_id: UUID = Depends(get_current_org_id),
    user: Optional[Any] = Depends(get_optional_current_user),
):
    """
    Run a procedure.

    If async_execution is true (default), the procedure runs in the background
    via Celery and returns a run_id for tracking.
    """
    async with database_service.get_session() as session:
        # Verify procedure exists and is active
        query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        if not procedure.is_active:
            raise HTTPException(status_code=400, detail="Procedure is not active")

        user_id = user.id if user else None

        if request.async_execution:
            # Create a Run and dispatch to Celery
            from ....services.run_service import run_service

            run = await run_service.create_run(
                session=session,
                organization_id=organization_id,
                run_type="procedure",
                origin="user" if user_id else "api",
                config={
                    "procedure_slug": slug,
                    "params": request.params,
                    "dry_run": request.dry_run,
                },
                created_by=user_id,
            )

            # Update run with procedure reference
            from ....database.models import Run
            run_query = select(Run).where(Run.id == run.id)
            run_result = await session.execute(run_query)
            run_obj = run_result.scalar_one()
            run_obj.procedure_id = procedure.id
            run_obj.procedure_version = procedure.version

            await session.commit()

            # Dispatch to Celery
            from ....tasks import execute_procedure_task
            execute_procedure_task.delay(
                str(run.id),
                str(organization_id),
                slug,
                request.params,
                str(user_id) if user_id else None,
            )

            return RunProcedureResponse(
                run_id=str(run.id),
                status="submitted",
                message=f"Procedure {slug} submitted for execution",
            )
        else:
            # Execute synchronously
            try:
                results = await procedure_executor.execute(
                    session=session,
                    organization_id=organization_id,
                    procedure_slug=slug,
                    params=request.params,
                    user_id=user_id,
                    dry_run=request.dry_run,
                )

                await session.commit()

                return RunProcedureResponse(
                    status=results.get("status", "completed"),
                    message=f"Procedure {slug} executed",
                    results=results,
                )
            except Exception as e:
                logger.exception(f"Procedure execution failed: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Procedure execution failed: {str(e)}",
                )


@router.post("/{slug}/enable", response_model=ProcedureSchema)
async def enable_procedure(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Enable a procedure.
    """
    async with database_service.get_session() as session:
        query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        procedure.is_active = True
        procedure.updated_at = datetime.utcnow()
        await session.commit()

        return await get_procedure(slug, organization_id)


@router.post("/{slug}/disable", response_model=ProcedureSchema)
async def disable_procedure(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Disable a procedure.
    """
    async with database_service.get_session() as session:
        query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        procedure.is_active = False
        procedure.updated_at = datetime.utcnow()
        await session.commit()

        return await get_procedure(slug, organization_id)


# =============================================================================
# TRIGGER ENDPOINTS
# =============================================================================


@router.get("/{slug}/triggers", response_model=List[TriggerSchema])
async def list_triggers(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    List triggers for a procedure.
    """
    async with database_service.get_session() as session:
        # Get procedure
        proc_query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(proc_query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        # Get triggers
        trigger_query = select(ProcedureTrigger).where(
            ProcedureTrigger.procedure_id == procedure.id,
        )
        result = await session.execute(trigger_query)
        triggers = result.scalars().all()

        return [
            TriggerSchema(
                id=str(t.id),
                trigger_type=t.trigger_type,
                cron_expression=t.cron_expression,
                event_name=t.event_name,
                event_filter=t.event_filter,
                is_active=t.is_active,
                last_triggered_at=t.last_triggered_at,
                next_trigger_at=t.next_trigger_at,
            )
            for t in triggers
        ]


@router.post("/{slug}/triggers", response_model=TriggerSchema)
async def create_trigger(
    slug: str,
    request: CreateTriggerRequest,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Create a trigger for a procedure.
    """
    async with database_service.get_session() as session:
        # Get procedure
        proc_query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == slug,
        )
        result = await session.execute(proc_query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        # Validate trigger type
        if request.trigger_type not in ["cron", "event", "webhook"]:
            raise HTTPException(status_code=400, detail="Invalid trigger type")

        if request.trigger_type == "cron" and not request.cron_expression:
            raise HTTPException(status_code=400, detail="Cron expression required for cron triggers")

        if request.trigger_type == "event" and not request.event_name:
            raise HTTPException(status_code=400, detail="Event name required for event triggers")

        # Create trigger
        trigger = ProcedureTrigger(
            procedure_id=procedure.id,
            organization_id=organization_id,
            trigger_type=request.trigger_type,
            cron_expression=request.cron_expression,
            event_name=request.event_name,
            event_filter=request.event_filter,
            trigger_params=request.trigger_params,
            is_active=True,
        )
        session.add(trigger)
        await session.commit()

        return TriggerSchema(
            id=str(trigger.id),
            trigger_type=trigger.trigger_type,
            cron_expression=trigger.cron_expression,
            event_name=trigger.event_name,
            event_filter=trigger.event_filter,
            is_active=trigger.is_active,
            last_triggered_at=trigger.last_triggered_at,
            next_trigger_at=trigger.next_trigger_at,
        )


@router.delete("/{slug}/triggers/{trigger_id}")
async def delete_trigger(
    slug: str,
    trigger_id: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Delete a trigger.
    """
    async with database_service.get_session() as session:
        trigger_query = select(ProcedureTrigger).where(
            ProcedureTrigger.id == UUID(trigger_id),
            ProcedureTrigger.organization_id == organization_id,
        )
        result = await session.execute(trigger_query)
        trigger = result.scalar_one_or_none()

        if not trigger:
            raise HTTPException(status_code=404, detail="Trigger not found")

        await session.delete(trigger)
        await session.commit()

        return {"status": "deleted"}
