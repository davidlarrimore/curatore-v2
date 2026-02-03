# backend/app/api/v1/routers/webhooks.py
"""
Webhooks API router.

Provides endpoints for triggering procedures and pipelines via webhooks.
Webhooks require authentication via X-Webhook-Secret header.
"""

from typing import Any, Dict, Optional
from uuid import UUID
from datetime import datetime
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ....services.database_service import database_service
from ....dependencies import get_current_org_id
from ....services.run_service import run_service
from ....database.procedures import (
    Procedure, Pipeline, ProcedureTrigger, PipelineTrigger, PipelineRun
)

logger = logging.getLogger("curatore.api.webhooks")

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class WebhookResponse(BaseModel):
    """Webhook execution response."""
    status: str
    run_id: Optional[str] = None
    pipeline_run_id: Optional[str] = None
    message: str


class WebhookSecretResponse(BaseModel):
    """Webhook secret response."""
    webhook_secret: str
    trigger_id: str


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _validate_webhook_secret(
    trigger_params: Optional[Dict[str, Any]],
    provided_secret: Optional[str],
) -> bool:
    """Validate webhook secret against trigger configuration."""
    if not trigger_params:
        return False

    expected_secret = trigger_params.get("webhook_secret")
    if not expected_secret:
        return False

    # Use constant-time comparison to prevent timing attacks
    return secrets.compare_digest(expected_secret, provided_secret or "")


# =============================================================================
# PROCEDURE WEBHOOKS
# =============================================================================


@router.post("/procedures/{slug}", response_model=WebhookResponse)
async def trigger_procedure_webhook(
    slug: str,
    request: Request,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    """
    Trigger a procedure via webhook.

    Requires X-Webhook-Secret header matching the trigger's webhook_secret.
    Request body is passed as params to the procedure.
    """
    # Parse body
    try:
        body = await request.json()
    except Exception:
        body = {}

    async with database_service.get_session() as session:
        # Find procedure with active webhook trigger
        query = select(ProcedureTrigger).join(Procedure).where(
            and_(
                Procedure.slug == slug,
                ProcedureTrigger.trigger_type == "webhook",
                ProcedureTrigger.is_active == True,
                Procedure.is_active == True,
            )
        )

        result = await session.execute(query)
        trigger = result.scalar_one_or_none()

        if not trigger:
            raise HTTPException(
                status_code=404,
                detail=f"No active webhook trigger found for procedure: {slug}"
            )

        # Validate secret
        if not _validate_webhook_secret(trigger.trigger_params, x_webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

        # Get procedure
        proc_query = select(Procedure).where(Procedure.id == trigger.procedure_id)
        proc_result = await session.execute(proc_query)
        procedure = proc_result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail="Procedure not found")

        # Merge trigger params (excluding secret) with request body
        params = {
            k: v for k, v in (trigger.trigger_params or {}).items()
            if k != "webhook_secret"
        }
        params.update(body)

        # Create run
        run = await run_service.create_run(
            session=session,
            organization_id=procedure.organization_id,
            run_type="procedure",
            origin="webhook",
            config={
                "procedure_slug": procedure.slug,
                "params": params,
                "triggered_by": "webhook",
                "trigger_id": str(trigger.id),
            },
        )

        # Update run with procedure reference
        run.procedure_id = procedure.id
        run.procedure_version = procedure.version

        # Update trigger
        trigger.last_triggered_at = datetime.utcnow()
        trigger.trigger_count = (trigger.trigger_count or 0) + 1

        await session.commit()

        # Queue Celery task
        from ....tasks import execute_procedure_task

        execute_procedure_task.delay(
            str(run.id),
            str(procedure.organization_id),
            procedure.slug,
            params,
            None,  # user_id
        )

        logger.info(f"Webhook triggered procedure {slug} (run_id={run.id})")

        return WebhookResponse(
            status="queued",
            run_id=str(run.id),
            message=f"Procedure {slug} triggered via webhook",
        )


@router.post("/procedures/{slug}/generate-secret", response_model=WebhookSecretResponse)
async def generate_procedure_webhook_secret(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Generate a new webhook secret for a procedure.

    Creates a webhook trigger if one doesn't exist, or updates
    the existing trigger's secret.
    """
    async with database_service.get_session() as session:
        # Find procedure
        query = select(Procedure).where(
            and_(
                Procedure.organization_id == organization_id,
                Procedure.slug == slug,
            )
        )
        result = await session.execute(query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            raise HTTPException(status_code=404, detail=f"Procedure not found: {slug}")

        # Find existing webhook trigger or create new one
        trigger_query = select(ProcedureTrigger).where(
            and_(
                ProcedureTrigger.procedure_id == procedure.id,
                ProcedureTrigger.trigger_type == "webhook",
            )
        )
        trigger_result = await session.execute(trigger_query)
        trigger = trigger_result.scalar_one_or_none()

        # Generate new secret
        new_secret = secrets.token_urlsafe(32)

        if trigger:
            # Update existing trigger
            trigger_params = trigger.trigger_params or {}
            trigger_params["webhook_secret"] = new_secret
            trigger.trigger_params = trigger_params
            trigger.is_active = True
        else:
            # Create new trigger
            trigger = ProcedureTrigger(
                procedure_id=procedure.id,
                organization_id=organization_id,
                trigger_type="webhook",
                trigger_params={"webhook_secret": new_secret},
                is_active=True,
            )
            session.add(trigger)

        await session.commit()
        await session.refresh(trigger)

        return WebhookSecretResponse(
            webhook_secret=new_secret,
            trigger_id=str(trigger.id),
        )


# =============================================================================
# PIPELINE WEBHOOKS
# =============================================================================


@router.post("/pipelines/{slug}", response_model=WebhookResponse)
async def trigger_pipeline_webhook(
    slug: str,
    request: Request,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    """
    Trigger a pipeline via webhook.

    Requires X-Webhook-Secret header matching the trigger's webhook_secret.
    Request body is passed as params to the pipeline.
    """
    # Parse body
    try:
        body = await request.json()
    except Exception:
        body = {}

    async with database_service.get_session() as session:
        # Find pipeline with active webhook trigger
        query = select(PipelineTrigger).join(Pipeline).where(
            and_(
                Pipeline.slug == slug,
                PipelineTrigger.trigger_type == "webhook",
                PipelineTrigger.is_active == True,
                Pipeline.is_active == True,
            )
        )

        result = await session.execute(query)
        trigger = result.scalar_one_or_none()

        if not trigger:
            raise HTTPException(
                status_code=404,
                detail=f"No active webhook trigger found for pipeline: {slug}"
            )

        # Validate secret
        if not _validate_webhook_secret(trigger.trigger_params, x_webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

        # Get pipeline
        pipe_query = select(Pipeline).where(Pipeline.id == trigger.pipeline_id)
        pipe_result = await session.execute(pipe_query)
        pipeline = pipe_result.scalar_one_or_none()

        if not pipeline:
            raise HTTPException(status_code=404, detail="Pipeline not found")

        # Merge trigger params (excluding secret) with request body
        params = {
            k: v for k, v in (trigger.trigger_params or {}).items()
            if k != "webhook_secret"
        }
        params.update(body)

        # Create run
        run = await run_service.create_run(
            session=session,
            organization_id=pipeline.organization_id,
            run_type="pipeline",
            origin="webhook",
            config={
                "pipeline_slug": pipeline.slug,
                "params": params,
                "triggered_by": "webhook",
                "trigger_id": str(trigger.id),
            },
        )

        # Create pipeline run
        pipeline_run = PipelineRun(
            pipeline_id=pipeline.id,
            run_id=run.id,
            organization_id=pipeline.organization_id,
            status="pending",
            current_stage=0,
            input_params=params,
        )
        session.add(pipeline_run)

        # Update trigger
        trigger.last_triggered_at = datetime.utcnow()
        trigger.trigger_count = (trigger.trigger_count or 0) + 1

        await session.commit()

        # Queue Celery task
        from ....tasks import execute_pipeline_task

        execute_pipeline_task.delay(
            run_id=str(run.id),
            pipeline_run_id=str(pipeline_run.id),
            organization_id=str(pipeline.organization_id),
            pipeline_slug=pipeline.slug,
            params=params,
        )

        logger.info(f"Webhook triggered pipeline {slug} (run_id={run.id})")

        return WebhookResponse(
            status="queued",
            run_id=str(run.id),
            pipeline_run_id=str(pipeline_run.id),
            message=f"Pipeline {slug} triggered via webhook",
        )


@router.post("/pipelines/{slug}/generate-secret", response_model=WebhookSecretResponse)
async def generate_pipeline_webhook_secret(
    slug: str,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Generate a new webhook secret for a pipeline.

    Creates a webhook trigger if one doesn't exist, or updates
    the existing trigger's secret.
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

        # Find existing webhook trigger or create new one
        trigger_query = select(PipelineTrigger).where(
            and_(
                PipelineTrigger.pipeline_id == pipeline.id,
                PipelineTrigger.trigger_type == "webhook",
            )
        )
        trigger_result = await session.execute(trigger_query)
        trigger = trigger_result.scalar_one_or_none()

        # Generate new secret
        new_secret = secrets.token_urlsafe(32)

        if trigger:
            # Update existing trigger
            trigger_params = trigger.trigger_params or {}
            trigger_params["webhook_secret"] = new_secret
            trigger.trigger_params = trigger_params
            trigger.is_active = True
        else:
            # Create new trigger
            trigger = PipelineTrigger(
                pipeline_id=pipeline.id,
                organization_id=organization_id,
                trigger_type="webhook",
                trigger_params={"webhook_secret": new_secret},
                is_active=True,
            )
            session.add(trigger)

        await session.commit()
        await session.refresh(trigger)

        return WebhookSecretResponse(
            webhook_secret=new_secret,
            trigger_id=str(trigger.id),
        )


# =============================================================================
# EVENT EMISSION
# =============================================================================


class EmitEventRequest(BaseModel):
    """Request to emit an event."""
    event_name: str = Field(..., description="Event name (e.g., 'sam_pull.completed')")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event payload")


class EmitEventResponse(BaseModel):
    """Event emission response."""
    event_name: str
    procedures_triggered: int
    pipelines_triggered: int
    triggered_items: list


@router.post("/events/emit", response_model=EmitEventResponse)
async def emit_event(
    request: EmitEventRequest,
    organization_id: UUID = Depends(get_current_org_id),
):
    """
    Emit an event to trigger subscribed procedures and pipelines.

    This is useful for testing event triggers or integrating with
    external systems.
    """
    from ....services.event_service import event_service

    async with database_service.get_session() as session:
        result = await event_service.emit(
            session=session,
            event_name=request.event_name,
            organization_id=organization_id,
            payload=request.payload,
        )

        triggered_items = (
            result.get("procedures_triggered", []) +
            result.get("pipelines_triggered", [])
        )

        return EmitEventResponse(
            event_name=request.event_name,
            procedures_triggered=len(result.get("procedures_triggered", [])),
            pipelines_triggered=len(result.get("pipelines_triggered", [])),
            triggered_items=triggered_items,
        )
