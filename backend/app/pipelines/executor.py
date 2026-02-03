# backend/app/pipelines/executor.py
"""
Pipeline Executor - Execute pipeline definitions with per-item state tracking.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .base import PipelineDefinition, StageDefinition, StageType, OnErrorPolicy
from .loader import pipeline_loader
from ..functions import fn, FunctionContext, FunctionResult

logger = logging.getLogger("curatore.pipelines.executor")


class PipelineExecutor:
    """
    Executes pipeline definitions with per-item state tracking.

    Features:
    - Processes items through stages
    - Tracks per-item state for resume capability
    - Supports checkpointing after stages
    - Handles errors per-item (continue other items)
    """

    async def execute(
        self,
        session: AsyncSession,
        organization_id: UUID,
        pipeline_slug: str,
        params: Dict[str, Any] = None,
        user_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
        pipeline_run_id: Optional[UUID] = None,
        resume_from_stage: int = 0,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Execute a pipeline by slug."""
        definition = pipeline_loader.get(pipeline_slug)
        if not definition:
            return {"status": "failed", "error": f"Pipeline not found: {pipeline_slug}"}

        return await self.execute_definition(
            session=session,
            organization_id=organization_id,
            definition=definition,
            params=params,
            user_id=user_id,
            run_id=run_id,
            pipeline_run_id=pipeline_run_id,
            resume_from_stage=resume_from_stage,
            dry_run=dry_run,
        )

    async def execute_definition(
        self,
        session: AsyncSession,
        organization_id: UUID,
        definition: PipelineDefinition,
        params: Dict[str, Any] = None,
        user_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
        pipeline_run_id: Optional[UUID] = None,
        resume_from_stage: int = 0,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Execute a pipeline definition."""
        params = params or {}
        start_time = datetime.utcnow()

        # Create context
        ctx = await FunctionContext.create(
            session=session,
            organization_id=organization_id,
            user_id=user_id,
            run_id=run_id,
            pipeline_id=None,
            params=params,
            dry_run=dry_run,
        )

        # Log start
        await ctx.log_run_event(
            level="INFO",
            event_type="pipeline_start",
            message=f"Starting pipeline: {definition.name}",
            context={
                "pipeline_slug": definition.slug,
                "stages": len(definition.stages),
                "resume_from": resume_from_stage,
            },
        )

        # Track state
        items: List[Dict[str, Any]] = []
        stage_results: Dict[str, Any] = {}
        current_stage = resume_from_stage

        # Execute stages
        for stage_idx, stage in enumerate(definition.stages):
            if stage_idx < resume_from_stage:
                continue

            current_stage = stage_idx

            try:
                result = await self._execute_stage(ctx, stage, items, pipeline_run_id)
                stage_results[stage.name] = result

                # Update items based on stage type
                if stage.type == StageType.GATHER:
                    items = result.get("items", [])
                elif stage.type == StageType.FILTER:
                    items = result.get("items", items)
                elif stage.type in (StageType.TRANSFORM, StageType.ENRICH):
                    items = result.get("items", items)

                # Log stage completion
                await ctx.log_run_event(
                    level="INFO",
                    event_type="stage_complete",
                    message=f"Stage {stage.name} complete: {len(items)} items",
                    context={
                        "stage": stage.name,
                        "items_count": len(items),
                        "status": result.get("status"),
                    },
                )

                # Checkpoint if configured
                if stage.name in definition.checkpoint_after_stages:
                    await self._save_checkpoint(
                        session, pipeline_run_id, stage_idx, items, stage_results
                    )

            except Exception as e:
                logger.exception(f"Stage {stage.name} failed: {e}")
                stage_results[stage.name] = {"status": "failed", "error": str(e)}

                if definition.on_error == OnErrorPolicy.FAIL:
                    break

        # Compute stats
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        completed_stages = len([r for r in stage_results.values() if r.get("status") != "failed"])
        failed_stages = len(definition.stages) - completed_stages

        status = "completed" if failed_stages == 0 else "failed" if completed_stages == 0 else "partial"

        await ctx.log_run_event(
            level="INFO" if status == "completed" else "ERROR",
            event_type="pipeline_complete",
            message=f"Pipeline {definition.name} {status}",
            context={
                "status": status,
                "total_stages": len(definition.stages),
                "completed_stages": completed_stages,
                "items_processed": len(items),
                "duration_ms": duration_ms,
            },
        )

        return {
            "status": status,
            "pipeline_slug": definition.slug,
            "stage_results": stage_results,
            "total_stages": len(definition.stages),
            "completed_stages": completed_stages,
            "items_processed": len(items),
            "final_items": items,
            "duration_ms": duration_ms,
        }

    async def _execute_stage(
        self,
        ctx: FunctionContext,
        stage: StageDefinition,
        items: List[Dict[str, Any]],
        pipeline_run_id: Optional[UUID],
    ) -> Dict[str, Any]:
        """Execute a single stage."""
        logger.info(f"Executing stage: {stage.name} ({stage.type.value})")

        func = fn.get_or_none(stage.function)
        if not func:
            return {"status": "failed", "error": f"Function not found: {stage.function}"}

        # Render params
        rendered_params = ctx.render_params(stage.params)

        if stage.type == StageType.GATHER:
            # Gather stage - function returns items
            result: FunctionResult = await func(ctx, **rendered_params)
            if result.success:
                return {
                    "status": "success",
                    "items": result.data if isinstance(result.data, list) else [],
                }
            return {"status": "failed", "error": result.error}

        elif stage.type == StageType.FILTER:
            # Filter stage - apply function to filter items
            filtered_items = []
            for item in items:
                try:
                    result = await func(ctx, item=item, **rendered_params)
                    if result.success and result.data:
                        filtered_items.append(item)
                except Exception as e:
                    if stage.on_error == OnErrorPolicy.FAIL:
                        raise
            return {"status": "success", "items": filtered_items}

        elif stage.type in (StageType.TRANSFORM, StageType.ENRICH):
            # Transform/Enrich - process items in batches
            processed_items = []
            failed_count = 0

            for i in range(0, len(items), stage.batch_size):
                batch = items[i:i + stage.batch_size]

                for item in batch:
                    try:
                        result = await func(ctx, item=item, **rendered_params)
                        if result.success:
                            # Merge result data into item
                            if isinstance(result.data, dict):
                                processed_items.append({**item, **result.data})
                            else:
                                processed_items.append(item)
                        else:
                            failed_count += 1
                            if stage.on_error == OnErrorPolicy.SKIP:
                                continue
                            elif stage.on_error == OnErrorPolicy.CONTINUE:
                                processed_items.append(item)
                            else:
                                raise Exception(result.error)
                    except Exception as e:
                        failed_count += 1
                        if stage.on_error == OnErrorPolicy.FAIL:
                            raise
                        elif stage.on_error == OnErrorPolicy.CONTINUE:
                            processed_items.append(item)

            return {
                "status": "success" if failed_count == 0 else "partial",
                "items": processed_items,
                "processed": len(processed_items),
                "failed": failed_count,
            }

        elif stage.type == StageType.OUTPUT:
            # Output stage - save results
            result = await func(ctx, items=items, **rendered_params)
            return {
                "status": "success" if result.success else "failed",
                "items": items,
                "output": result.to_dict(),
            }

        return {"status": "failed", "error": f"Unknown stage type: {stage.type}"}

    async def _save_checkpoint(
        self,
        session: AsyncSession,
        pipeline_run_id: Optional[UUID],
        stage_idx: int,
        items: List[Dict[str, Any]],
        stage_results: Dict[str, Any],
    ) -> None:
        """Save checkpoint for resume capability."""
        if not pipeline_run_id:
            return

        from ..database.procedures import PipelineRun

        try:
            query = select(PipelineRun).where(PipelineRun.id == pipeline_run_id)
            result = await session.execute(query)
            pipeline_run = result.scalar_one_or_none()

            if pipeline_run:
                pipeline_run.current_stage = stage_idx + 1
                pipeline_run.stage_results = stage_results
                pipeline_run.checkpoint_data = {
                    "stage_idx": stage_idx,
                    "items_count": len(items),
                    "timestamp": datetime.utcnow().isoformat(),
                }
                await session.flush()

        except Exception as e:
            logger.warning(f"Failed to save checkpoint: {e}")


# Global executor
pipeline_executor = PipelineExecutor()
