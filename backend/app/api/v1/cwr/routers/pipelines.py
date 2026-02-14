# backend/app/api/v1/routers/pipelines.py
"""
Pipelines API router.

Provides endpoints for:
- Listing pipelines
- Getting pipeline details
- Running pipelines
- Managing pipeline runs and item states
- Resuming failed pipelines
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select

from app.core.database.procedures import Pipeline, PipelineItemState, PipelineRun, PipelineTrigger
from app.core.shared.database_service import database_service
from app.core.shared.run_service import run_service
from app.cwr.pipelines import pipeline_executor
from app.dependencies import get_current_org_id, get_current_org_id_or_delegated, get_optional_current_user

logger = logging.getLogger("curatore.api.pipelines")

router = APIRouter(prefix="/pipelines", tags=["Pipelines"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class StageSchema(BaseModel):
    """Pipeline stage schema."""
    name: str
    type: str
    function: str
    description: Optional[str] = None
    batch_size: int = 50
    on_error: str = "skip"


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


class PipelineSchema(BaseModel):
    """Pipeline schema."""
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    version: int
    is_active: bool
    is_system: bool
    source_type: str
    stages: List[StageSchema] = []
    triggers: List[TriggerSchema] = []
    created_at: datetime
    updated_at: datetime


class PipelineListItem(BaseModel):
    """Pipeline list item schema."""
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    version: int
    is_active: bool
    is_system: bool
    source_type: str
    stage_count: int = 0
    trigger_count: int = 0
    tags: List[str] = []
    created_at: datetime
    updated_at: datetime


class PipelineListResponse(BaseModel):
    """List of pipelines response."""
    pipelines: List[PipelineListItem]
    total: int


class RunPipelineRequest(BaseModel):
    """Request to run a pipeline."""
    params: Dict[str, Any] = Field(default_factory=dict, description="Pipeline parameters")
    dry_run: bool = Field(default=False, description="If true, don't make changes")
    async_execution: bool = Field(default=True, description="Run asynchronously via Celery")


class RunPipelineResponse(BaseModel):
    """Pipeline run response."""
    run_id: Optional[str] = None
    pipeline_run_id: Optional[str] = None
    status: str
    message: Optional[str] = None
    results: Optional[Dict[str, Any]] = None


class PipelineRunSchema(BaseModel):
    """Pipeline run schema."""
    id: str
    pipeline_id: str
    run_id: Optional[str] = None
    status: str
    current_stage: int = 0
    items_processed: int = 0
    stage_results: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


class PipelineRunListResponse(BaseModel):
    """List of pipeline runs."""
    runs: List[PipelineRunSchema]
    total: int


class ItemStateSchema(BaseModel):
    """Pipeline item state schema."""
    id: str
    item_type: str
    item_id: str
    stage_name: str
    status: str
    stage_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ItemStatesResponse(BaseModel):
    """Pipeline run item states response."""
    items: List[ItemStateSchema]
    total: int
    by_status: Dict[str, int] = {}


class ResumePipelineRequest(BaseModel):
    """Request to resume a failed pipeline run."""
    from_stage: Optional[int] = Field(None, description="Stage index to resume from (default: last failed)")


class CreateTriggerRequest(BaseModel):
    """Request to create a trigger."""
    trigger_type: str = Field(..., description="Type: cron, event, webhook")
    cron_expression: Optional[str] = Field(None, description="Cron expression (for cron triggers)")
    event_name: Optional[str] = Field(None, description="Event name (for event triggers)")
    event_filter: Optional[Dict[str, Any]] = Field(None, description="Event filter")
    trigger_params: Optional[Dict[str, Any]] = Field(None, description="Parameters to pass when triggered")


class UpdatePipelineRequest(BaseModel):
    """Request to update pipeline settings."""
    is_active: Optional[bool] = None
    description: Optional[str] = None


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/", response_model=PipelineListResponse)
async def list_pipelines(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    organization_id: UUID = Depends(get_current_org_id_or_delegated),
):
    """
    List all pipelines.
    """
    from app.config import SYSTEM_ORG_SLUG

    async with database_service.get_session() as session:
        # Determine whether we're in system-org context
        from app.core.database.models import Organization
        org_result = await session.execute(
            select(Organization.slug).where(Organization.id == organization_id)
        )
        org_slug = org_result.scalar_one_or_none()
        is_system_org = org_slug == SYSTEM_ORG_SLUG

        query = select(Pipeline).where(
            Pipeline.organization_id == organization_id,
        )

        # Safety: never show system pipelines in regular org context
        if not is_system_org:
            query = query.where(Pipeline.is_system == False)

        if is_active is not None:
            query = query.where(Pipeline.is_active == is_active)

        result = await session.execute(query)
        pipelines = result.scalars().all()

        items = []
        for pipeline in pipelines:
            stages = pipeline.stages or []
            definition = pipeline.definition or {}
            tags = definition.get("tags", [])

            # Filter by tag if specified
            if tag and tag not in tags:
                continue

            # Count triggers
            trigger_query = select(func.count(PipelineTrigger.id)).where(
                PipelineTrigger.pipeline_id == pipeline.id
            )
            trigger_result = await session.execute(trigger_query)
            trigger_count = trigger_result.scalar() or 0

            items.append(PipelineListItem(
                id=str(pipeline.id),
                name=pipeline.name,
                slug=pipeline.slug,
                description=pipeline.description,
                version=pipeline.version,
                is_active=pipeline.is_active,
                is_system=pipeline.is_system,
                source_type=pipeline.source_type,
                stage_count=len(stages),
                trigger_count=trigger_count,
                tags=tags,
                created_at=pipeline.created_at,
                updated_at=pipeline.updated_at,
            ))

        return PipelineListResponse(pipelines=items, total=len(items))


@router.get("/{slug}", response_model=PipelineSchema)
async def get_pipeline(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id_or_delegated),
):
    """
    Get pipeline details by slug.
    """
    async with database_service.get_session() as session:
        query = select(Pipeline).where(
            and_(
                Pipeline.organization_id == organization_id,
                Pipeline.slug == slug,
            )
        )
        result = await session.execute(query)
        pipeline = result.scalar_one_or_none()

        if not pipeline:
            raise HTTPException(status_code=404, detail=f"Pipeline not found: {slug}")

        # Get stages from definition
        stages = pipeline.stages or []
        stage_schemas = [
            StageSchema(
                name=s.get("name", ""),
                type=s.get("type", ""),
                function=s.get("function", ""),
                description=s.get("description"),
                batch_size=s.get("batch_size", 50),
                on_error=s.get("on_error", "skip"),
            )
            for s in stages
        ]

        # Get triggers
        trigger_query = select(PipelineTrigger).where(
            PipelineTrigger.pipeline_id == pipeline.id
        )
        trigger_result = await session.execute(trigger_query)
        triggers = trigger_result.scalars().all()

        trigger_schemas = [
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

        return PipelineSchema(
            id=str(pipeline.id),
            name=pipeline.name,
            slug=pipeline.slug,
            description=pipeline.description,
            version=pipeline.version,
            is_active=pipeline.is_active,
            is_system=pipeline.is_system,
            source_type=pipeline.source_type,
            stages=stage_schemas,
            triggers=trigger_schemas,
            created_at=pipeline.created_at,
            updated_at=pipeline.updated_at,
        )


@router.post("/{slug}/run", response_model=RunPipelineResponse)
async def run_pipeline(
    slug: str,
    request: RunPipelineRequest = Body(...),
    organization_id: UUID = Depends(get_current_org_id_or_delegated),
    user = Depends(get_optional_current_user),
):
    """
    Run a pipeline.

    By default runs asynchronously via Celery. Set async_execution=false
    to run synchronously (blocking).
    """
    user_id = user.id if user else None

    async with database_service.get_session() as session:
        # Find pipeline
        query = select(Pipeline).where(
            and_(
                Pipeline.organization_id == organization_id,
                Pipeline.slug == slug,
            )
        )
        result = await session.execute(query)
        pipeline = result.scalar_one_or_none()

        if not pipeline:
            raise HTTPException(status_code=404, detail=f"Pipeline not found: {slug}")

        if not pipeline.is_active:
            raise HTTPException(status_code=400, detail="Pipeline is not active")

        # Create Run record
        run = await run_service.create_run(
            session=session,
            organization_id=organization_id,
            run_type="pipeline_run",
            related_id=pipeline.id,
            metadata={
                "pipeline_slug": slug,
                "params": request.params,
                "dry_run": request.dry_run,
            },
        )

        # Create PipelineRun record
        pipeline_run = PipelineRun(
            pipeline_id=pipeline.id,
            run_id=run.id,
            organization_id=organization_id,
            status="pending",
            current_stage=0,
            input_params=request.params,
        )
        session.add(pipeline_run)
        await session.commit()

        if request.async_execution:
            # Queue for async execution
            from app.core.tasks import execute_pipeline_task

            execute_pipeline_task.delay(
                run_id=str(run.id),
                pipeline_run_id=str(pipeline_run.id),
                organization_id=str(organization_id),
                pipeline_slug=slug,
                params=request.params,
                user_id=str(user_id) if user_id else None,
            )

            return RunPipelineResponse(
                run_id=str(run.id),
                pipeline_run_id=str(pipeline_run.id),
                status="queued",
                message=f"Pipeline {slug} queued for execution",
            )
        else:
            # Run synchronously
            exec_result = await pipeline_executor.execute(
                session=session,
                organization_id=organization_id,
                pipeline_slug=slug,
                params=request.params,
                user_id=user_id,
                run_id=run.id,
                pipeline_run_id=pipeline_run.id,
                dry_run=request.dry_run,
            )

            return RunPipelineResponse(
                run_id=str(run.id),
                pipeline_run_id=str(pipeline_run.id),
                status=exec_result.get("status", "completed"),
                results=exec_result,
            )


@router.get("/{slug}/runs", response_model=PipelineRunListResponse)
async def list_pipeline_runs(
    slug: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    List runs for a pipeline.
    """
    async with database_service.get_session() as session:
        # Find pipeline
        query = select(Pipeline).where(
            and_(
                Pipeline.organization_id == organization_id,
                Pipeline.slug == slug,
            )
        )
        result = await session.execute(query)
        pipeline = result.scalar_one_or_none()

        if not pipeline:
            raise HTTPException(status_code=404, detail=f"Pipeline not found: {slug}")

        # Query runs
        runs_query = select(PipelineRun).where(
            PipelineRun.pipeline_id == pipeline.id
        ).order_by(PipelineRun.created_at.desc())

        if status:
            runs_query = runs_query.where(PipelineRun.status == status)

        # Count total
        count_query = select(func.count(PipelineRun.id)).where(
            PipelineRun.pipeline_id == pipeline.id
        )
        if status:
            count_query = count_query.where(PipelineRun.status == status)
        count_result = await session.execute(count_query)
        total = count_result.scalar() or 0

        # Get page
        runs_query = runs_query.offset(offset).limit(limit)
        result = await session.execute(runs_query)
        runs = result.scalars().all()

        run_schemas = [
            PipelineRunSchema(
                id=str(r.id),
                pipeline_id=str(r.pipeline_id),
                run_id=str(r.run_id) if r.run_id else None,
                status=r.status,
                current_stage=r.current_stage or 0,
                items_processed=r.items_processed or 0,
                stage_results=r.stage_results,
                error_message=r.error_message,
                started_at=r.started_at,
                completed_at=r.completed_at,
                created_at=r.created_at,
            )
            for r in runs
        ]

        return PipelineRunListResponse(runs=run_schemas, total=total)


@router.get("/{slug}/runs/{run_id}/items", response_model=ItemStatesResponse)
async def get_pipeline_run_items(
    slug: str,
    run_id: UUID,
    status: Optional[str] = Query(None, description="Filter by status"),
    stage: Optional[str] = Query(None, description="Filter by stage name"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Get item states for a pipeline run.

    Returns per-item processing status for tracking and debugging.
    """
    async with database_service.get_session() as session:
        # Find pipeline run
        query = select(PipelineRun).where(PipelineRun.id == run_id)
        result = await session.execute(query)
        pipeline_run = result.scalar_one_or_none()

        if not pipeline_run:
            raise HTTPException(status_code=404, detail="Pipeline run not found")

        # Query item states
        items_query = select(PipelineItemState).where(
            PipelineItemState.pipeline_run_id == run_id
        )

        if status:
            items_query = items_query.where(PipelineItemState.status == status)
        if stage:
            items_query = items_query.where(PipelineItemState.stage_name == stage)

        # Count total
        count_query = select(func.count(PipelineItemState.id)).where(
            PipelineItemState.pipeline_run_id == run_id
        )
        count_result = await session.execute(count_query)
        total = count_result.scalar() or 0

        # Get status breakdown
        status_query = select(
            PipelineItemState.status,
            func.count(PipelineItemState.id)
        ).where(
            PipelineItemState.pipeline_run_id == run_id
        ).group_by(PipelineItemState.status)
        status_result = await session.execute(status_query)
        by_status = {row[0]: row[1] for row in status_result}

        # Get page
        items_query = items_query.offset(offset).limit(limit)
        result = await session.execute(items_query)
        items = result.scalars().all()

        item_schemas = [
            ItemStateSchema(
                id=str(item.id),
                item_type=item.item_type,
                item_id=item.item_id,
                stage_name=item.stage_name,
                status=item.status,
                stage_data=item.stage_data,
                error_message=item.error_message,
                started_at=item.started_at,
                completed_at=item.completed_at,
            )
            for item in items
        ]

        return ItemStatesResponse(items=item_schemas, total=total, by_status=by_status)


@router.post("/{slug}/runs/{run_id}/resume", response_model=RunPipelineResponse)
async def resume_pipeline_run(
    slug: str,
    run_id: UUID,
    request: ResumePipelineRequest = Body(...),
    organization_id: UUID = Depends(get_current_org_id),
    user = Depends(get_optional_current_user),
):
    """
    Resume a failed or partial pipeline run.

    Continues processing from the specified stage or the last failed stage.
    """
    user_id = user.id if user else None

    async with database_service.get_session() as session:
        # Find pipeline run
        query = select(PipelineRun).where(PipelineRun.id == run_id)
        result = await session.execute(query)
        pipeline_run = result.scalar_one_or_none()

        if not pipeline_run:
            raise HTTPException(status_code=404, detail="Pipeline run not found")

        if pipeline_run.status not in ("failed", "partial"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot resume pipeline run with status: {pipeline_run.status}"
            )

        # Determine resume stage
        resume_from = request.from_stage if request.from_stage is not None else pipeline_run.current_stage

        # Get pipeline
        pipeline_query = select(Pipeline).where(Pipeline.id == pipeline_run.pipeline_id)
        pipeline_result = await session.execute(pipeline_query)
        pipeline = pipeline_result.scalar_one_or_none()

        if not pipeline:
            raise HTTPException(status_code=404, detail="Pipeline not found")

        # Create new Run record
        new_run = await run_service.create_run(
            session=session,
            organization_id=organization_id,
            run_type="pipeline_run",
            related_id=pipeline.id,
            metadata={
                "pipeline_slug": slug,
                "params": pipeline_run.input_params,
                "resume_from": resume_from,
                "original_run_id": str(run_id),
            },
        )

        # Update pipeline run
        pipeline_run.run_id = new_run.id
        pipeline_run.status = "pending"
        await session.commit()

        # Queue for async execution
        from app.core.tasks import execute_pipeline_task

        execute_pipeline_task.delay(
            run_id=str(new_run.id),
            pipeline_run_id=str(pipeline_run.id),
            organization_id=str(organization_id),
            pipeline_slug=slug,
            params=pipeline_run.input_params or {},
            user_id=str(user_id) if user_id else None,
            resume_from_stage=resume_from,
        )

        return RunPipelineResponse(
            run_id=str(new_run.id),
            pipeline_run_id=str(pipeline_run.id),
            status="queued",
            message=f"Pipeline {slug} resumed from stage {resume_from}",
        )


@router.put("/{slug}", response_model=PipelineSchema)
async def update_pipeline(
    slug: str,
    request: UpdatePipelineRequest,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Update pipeline settings.
    """
    async with database_service.get_session() as session:
        query = select(Pipeline).where(
            and_(
                Pipeline.organization_id == organization_id,
                Pipeline.slug == slug,
            )
        )
        result = await session.execute(query)
        pipeline = result.scalar_one_or_none()

        if not pipeline:
            raise HTTPException(status_code=404, detail=f"Pipeline not found: {slug}")

        if request.is_active is not None:
            pipeline.is_active = request.is_active
        if request.description is not None:
            pipeline.description = request.description

        pipeline.updated_at = datetime.utcnow()
        await session.commit()

        return await get_pipeline(slug, organization_id)


@router.post("/{slug}/enable")
async def enable_pipeline(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """Enable a pipeline."""
    async with database_service.get_session() as session:
        query = select(Pipeline).where(
            and_(
                Pipeline.organization_id == organization_id,
                Pipeline.slug == slug,
            )
        )
        result = await session.execute(query)
        pipeline = result.scalar_one_or_none()

        if not pipeline:
            raise HTTPException(status_code=404, detail=f"Pipeline not found: {slug}")

        pipeline.is_active = True
        pipeline.updated_at = datetime.utcnow()
        await session.commit()

        return {"status": "success", "message": f"Pipeline {slug} enabled"}


@router.post("/{slug}/disable")
async def disable_pipeline(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """Disable a pipeline."""
    async with database_service.get_session() as session:
        query = select(Pipeline).where(
            and_(
                Pipeline.organization_id == organization_id,
                Pipeline.slug == slug,
            )
        )
        result = await session.execute(query)
        pipeline = result.scalar_one_or_none()

        if not pipeline:
            raise HTTPException(status_code=404, detail=f"Pipeline not found: {slug}")

        pipeline.is_active = False
        pipeline.updated_at = datetime.utcnow()
        await session.commit()

        return {"status": "success", "message": f"Pipeline {slug} disabled"}


# =============================================================================
# TRIGGER MANAGEMENT
# =============================================================================


@router.get("/{slug}/triggers", response_model=List[TriggerSchema])
async def list_pipeline_triggers(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """List triggers for a pipeline."""
    async with database_service.get_session() as session:
        # Find pipeline
        query = select(Pipeline).where(
            and_(
                Pipeline.organization_id == organization_id,
                Pipeline.slug == slug,
            )
        )
        result = await session.execute(query)
        pipeline = result.scalar_one_or_none()

        if not pipeline:
            raise HTTPException(status_code=404, detail=f"Pipeline not found: {slug}")

        # Get triggers
        trigger_query = select(PipelineTrigger).where(
            PipelineTrigger.pipeline_id == pipeline.id
        )
        trigger_result = await session.execute(trigger_query)
        triggers = trigger_result.scalars().all()

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
async def create_pipeline_trigger(
    slug: str,
    request: CreateTriggerRequest,
    organization_id: UUID = Depends(get_current_org_id),
):
    """Create a trigger for a pipeline."""
    async with database_service.get_session() as session:
        # Find pipeline
        query = select(Pipeline).where(
            and_(
                Pipeline.organization_id == organization_id,
                Pipeline.slug == slug,
            )
        )
        result = await session.execute(query)
        pipeline = result.scalar_one_or_none()

        if not pipeline:
            raise HTTPException(status_code=404, detail=f"Pipeline not found: {slug}")

        # Validate trigger type
        if request.trigger_type not in ("cron", "event", "webhook"):
            raise HTTPException(status_code=400, detail="Invalid trigger type")

        if request.trigger_type == "cron" and not request.cron_expression:
            raise HTTPException(status_code=400, detail="Cron expression required for cron triggers")

        if request.trigger_type == "event" and not request.event_name:
            raise HTTPException(status_code=400, detail="Event name required for event triggers")

        # Create trigger
        trigger = PipelineTrigger(
            pipeline_id=pipeline.id,
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
        await session.refresh(trigger)

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
async def delete_pipeline_trigger(
    slug: str,
    trigger_id: UUID,
    organization_id: UUID = Depends(get_current_org_id),
):
    """Delete a pipeline trigger."""
    async with database_service.get_session() as session:
        # Find trigger
        query = select(PipelineTrigger).where(
            and_(
                PipelineTrigger.id == trigger_id,
                PipelineTrigger.organization_id == organization_id,
            )
        )
        result = await session.execute(query)
        trigger = result.scalar_one_or_none()

        if not trigger:
            raise HTTPException(status_code=404, detail="Trigger not found")

        await session.delete(trigger)
        await session.commit()

        return {"status": "success", "message": "Trigger deleted"}
