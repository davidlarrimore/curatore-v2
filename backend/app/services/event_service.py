# backend/app/services/event_service.py
"""
Event Service for Curatore v2.

Provides a central event emission and subscription system for triggering
procedures and pipelines based on system events.

Events are lightweight triggers - the actual execution happens via Celery tasks.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.procedures import (
    Procedure, Pipeline,
    ProcedureTrigger, PipelineTrigger,
    PipelineRun,
)
from ..database.models import Run

logger = logging.getLogger("curatore.services.event_service")


class EventService:
    """
    Central event service for triggering procedures and pipelines.

    Events follow a dotted naming convention:
    - sam_pull.completed
    - sharepoint_sync.completed
    - asset.extraction_completed
    - asset.indexed
    - scrape.completed

    Event payloads are arbitrary JSON that gets passed to triggered
    procedures/pipelines as parameters.
    """

    async def emit(
        self,
        session: AsyncSession,
        event_name: str,
        organization_id: UUID,
        payload: Dict[str, Any],
        source_run_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Emit an event and trigger matching procedures/pipelines.

        Args:
            session: Database session
            event_name: Event name (e.g., "sam_pull.completed")
            organization_id: Organization UUID
            payload: Event payload to pass to triggered items
            source_run_id: Optional run ID that triggered this event

        Returns:
            Dict with triggered procedures and pipelines
        """
        logger.info(f"Event emitted: {event_name} for org {organization_id}")

        triggered_procedures = await self._trigger_procedures(
            session, event_name, organization_id, payload, source_run_id
        )

        triggered_pipelines = await self._trigger_pipelines(
            session, event_name, organization_id, payload, source_run_id
        )

        total_triggered = len(triggered_procedures) + len(triggered_pipelines)
        logger.info(f"Event {event_name} triggered {total_triggered} items")

        return {
            "event_name": event_name,
            "procedures_triggered": triggered_procedures,
            "pipelines_triggered": triggered_pipelines,
        }

    async def _trigger_procedures(
        self,
        session: AsyncSession,
        event_name: str,
        organization_id: UUID,
        payload: Dict[str, Any],
        source_run_id: Optional[UUID],
    ) -> List[Dict[str, Any]]:
        """Find and trigger matching procedure triggers."""
        from .run_service import run_service

        # Find matching triggers
        query = select(ProcedureTrigger).join(Procedure).where(
            and_(
                ProcedureTrigger.organization_id == organization_id,
                ProcedureTrigger.trigger_type == "event",
                ProcedureTrigger.event_name == event_name,
                ProcedureTrigger.is_active == True,
                Procedure.is_active == True,
            )
        )

        result = await session.execute(query)
        triggers = result.scalars().all()

        triggered = []

        for trigger in triggers:
            # Check event filter if specified
            if trigger.event_filter:
                if not self._matches_filter(payload, trigger.event_filter):
                    continue

            # Get procedure
            proc_query = select(Procedure).where(Procedure.id == trigger.procedure_id)
            proc_result = await session.execute(proc_query)
            procedure = proc_result.scalar_one_or_none()

            if not procedure:
                continue

            # Merge trigger params with event payload
            params = {**(trigger.trigger_params or {}), **payload}

            # Create run
            run = await run_service.create_run(
                session=session,
                organization_id=organization_id,
                run_type="procedure",
                origin="event",
                config={
                    "procedure_slug": procedure.slug,
                    "params": params,
                    "triggered_by_event": event_name,
                    "source_run_id": str(source_run_id) if source_run_id else None,
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
            from ..tasks import execute_procedure_task

            execute_procedure_task.delay(
                str(run.id),
                str(organization_id),
                procedure.slug,
                params,
                None,  # user_id
            )

            triggered.append({
                "procedure_slug": procedure.slug,
                "run_id": str(run.id),
                "trigger_id": str(trigger.id),
            })

            logger.info(f"Triggered procedure {procedure.slug} from event {event_name}")

        return triggered

    async def _trigger_pipelines(
        self,
        session: AsyncSession,
        event_name: str,
        organization_id: UUID,
        payload: Dict[str, Any],
        source_run_id: Optional[UUID],
    ) -> List[Dict[str, Any]]:
        """Find and trigger matching pipeline triggers."""
        from .run_service import run_service

        # Find matching triggers
        query = select(PipelineTrigger).join(Pipeline).where(
            and_(
                PipelineTrigger.organization_id == organization_id,
                PipelineTrigger.trigger_type == "event",
                PipelineTrigger.event_name == event_name,
                PipelineTrigger.is_active == True,
                Pipeline.is_active == True,
            )
        )

        result = await session.execute(query)
        triggers = result.scalars().all()

        triggered = []

        for trigger in triggers:
            # Check event filter if specified
            if trigger.event_filter:
                if not self._matches_filter(payload, trigger.event_filter):
                    continue

            # Get pipeline
            pipe_query = select(Pipeline).where(Pipeline.id == trigger.pipeline_id)
            pipe_result = await session.execute(pipe_query)
            pipeline = pipe_result.scalar_one_or_none()

            if not pipeline:
                continue

            # Merge trigger params with event payload
            params = {**(trigger.trigger_params or {}), **payload}

            # Create run
            run = await run_service.create_run(
                session=session,
                organization_id=organization_id,
                run_type="pipeline",
                origin="event",
                config={
                    "pipeline_slug": pipeline.slug,
                    "params": params,
                    "triggered_by_event": event_name,
                    "source_run_id": str(source_run_id) if source_run_id else None,
                },
            )

            # Create pipeline run
            pipeline_run = PipelineRun(
                pipeline_id=pipeline.id,
                run_id=run.id,
                organization_id=organization_id,
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
            from ..tasks import execute_pipeline_task

            execute_pipeline_task.delay(
                run_id=str(run.id),
                pipeline_run_id=str(pipeline_run.id),
                organization_id=str(organization_id),
                pipeline_slug=pipeline.slug,
                params=params,
            )

            triggered.append({
                "pipeline_slug": pipeline.slug,
                "run_id": str(run.id),
                "pipeline_run_id": str(pipeline_run.id),
                "trigger_id": str(trigger.id),
            })

            logger.info(f"Triggered pipeline {pipeline.slug} from event {event_name}")

        return triggered

    def _matches_filter(self, payload: Dict[str, Any], filter_spec: Dict[str, Any]) -> bool:
        """
        Check if event payload matches a filter specification.

        Filter spec supports:
        - Simple equality: {"key": "value"}
        - Nested paths: {"run.status": "completed"}
        - List contains: {"tags": {"$contains": "important"}}
        """
        for key, expected in filter_spec.items():
            # Get value from payload using dot notation
            actual = self._get_nested(payload, key)

            if isinstance(expected, dict):
                # Handle operators
                if "$contains" in expected:
                    if not isinstance(actual, list):
                        return False
                    if expected["$contains"] not in actual:
                        return False
                elif "$in" in expected:
                    if actual not in expected["$in"]:
                        return False
                elif "$ne" in expected:
                    if actual == expected["$ne"]:
                        return False
                else:
                    # Nested dict comparison
                    if actual != expected:
                        return False
            else:
                # Simple equality
                if actual != expected:
                    return False

        return True

    def _get_nested(self, data: Dict[str, Any], path: str) -> Any:
        """Get a nested value from a dict using dot notation."""
        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current


# Global singleton
event_service = EventService()
