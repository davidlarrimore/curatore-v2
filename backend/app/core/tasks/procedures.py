"""
Celery tasks for procedure and pipeline execution.

Handles running procedures (sequence of function calls) and pipelines
(multi-stage document processing) with Run-based tracking.
"""
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict

from app.celery_app import app as celery_app
from app.core.shared.database_service import database_service


@celery_app.task(bind=True, name="app.tasks.execute_procedure_task")
def execute_procedure_task(
    self,
    run_id: str,
    organization_id: str,
    procedure_slug: str,
    params: Dict[str, Any] = None,
    user_id: str = None,
) -> Dict[str, Any]:
    """
    Execute a procedure asynchronously.

    This task runs a procedure (sequence of function calls) and tracks
    the execution through a Run record.

    Args:
        run_id: Run UUID string for tracking
        organization_id: Organization UUID string
        procedure_slug: Slug of the procedure to execute
        params: Parameters to pass to the procedure
        user_id: Optional user UUID who triggered the execution

    Returns:
        Dict with procedure execution results
    """
    logger = logging.getLogger("curatore.tasks.procedure")
    logger.info(f"Starting procedure task: {procedure_slug} (run_id={run_id})")

    try:
        result = asyncio.run(
            _execute_procedure_async(
                run_id=uuid.UUID(run_id),
                organization_id=uuid.UUID(organization_id),
                procedure_slug=procedure_slug,
                params=params or {},
                user_id=uuid.UUID(user_id) if user_id else None,
            )
        )

        logger.info(f"Procedure {procedure_slug} completed: {result.get('status')}")
        return result

    except Exception as e:
        logger.error(f"Procedure task failed for {procedure_slug}: {e}", exc_info=True)
        # Mark run as failed
        asyncio.run(_fail_procedure_run(uuid.UUID(run_id), str(e)))
        raise


async def _execute_procedure_async(
    run_id,
    organization_id,
    procedure_slug: str,
    params: Dict[str, Any],
    user_id,
) -> Dict[str, Any]:
    """Async implementation of procedure execution."""
    from app.cwr.procedures import procedure_executor
    from app.core.shared.run_service import run_service

    async with database_service.get_session() as session:
        # Start the run
        await run_service.start_run(session, run_id)
        await session.commit()

        # Execute the procedure
        result = await procedure_executor.execute(
            session=session,
            organization_id=organization_id,
            procedure_slug=procedure_slug,
            params=params,
            user_id=user_id,
            run_id=run_id,
        )

        # Complete or fail the run based on result
        if result.get("status") == "completed":
            await run_service.complete_run(
                session=session,
                run_id=run_id,
                results_summary=result,
            )
        else:
            await run_service.fail_run(
                session=session,
                run_id=run_id,
                error_message=result.get("error", "Procedure failed"),
            )

        await session.commit()
        return result


async def _fail_procedure_run(run_id, error: str) -> None:
    """Mark a procedure run as failed."""
    from app.core.shared.run_service import run_service

    async with database_service.get_session() as session:
        await run_service.fail_run(session, run_id, error)
        await session.commit()


@celery_app.task(bind=True, name="app.tasks.execute_pipeline_task")
def execute_pipeline_task(
    self,
    run_id: str,
    pipeline_run_id: str,
    organization_id: str,
    pipeline_slug: str,
    params: Dict[str, Any] = None,
    user_id: str = None,
    resume_from_stage: int = 0,
) -> Dict[str, Any]:
    """
    Execute a pipeline asynchronously.

    This task runs a pipeline (multi-stage document processing) and tracks
    both the Run and PipelineRun records.

    Args:
        run_id: Run UUID string for tracking
        pipeline_run_id: PipelineRun UUID string for stage tracking
        organization_id: Organization UUID string
        pipeline_slug: Slug of the pipeline to execute
        params: Parameters to pass to the pipeline
        user_id: Optional user UUID who triggered the execution
        resume_from_stage: Stage index to resume from (for failed pipelines)

    Returns:
        Dict with pipeline execution results
    """
    logger = logging.getLogger("curatore.tasks.pipeline")
    logger.info(f"Starting pipeline task: {pipeline_slug} (run_id={run_id})")

    try:
        result = asyncio.run(
            _execute_pipeline_async(
                run_id=uuid.UUID(run_id),
                pipeline_run_id=uuid.UUID(pipeline_run_id),
                organization_id=uuid.UUID(organization_id),
                pipeline_slug=pipeline_slug,
                params=params or {},
                user_id=uuid.UUID(user_id) if user_id else None,
                resume_from_stage=resume_from_stage,
            )
        )

        logger.info(f"Pipeline {pipeline_slug} completed: {result.get('status')}")
        return result

    except Exception as e:
        logger.error(f"Pipeline task failed for {pipeline_slug}: {e}", exc_info=True)
        # Mark run as failed
        asyncio.run(_fail_pipeline_run(uuid.UUID(run_id), uuid.UUID(pipeline_run_id), str(e)))
        raise


async def _execute_pipeline_async(
    run_id,
    pipeline_run_id,
    organization_id,
    pipeline_slug: str,
    params: Dict[str, Any],
    user_id,
    resume_from_stage: int,
) -> Dict[str, Any]:
    """Async implementation of pipeline execution."""
    from app.cwr.pipelines import pipeline_executor
    from app.core.shared.run_service import run_service
    from app.core.database.procedures import PipelineRun
    from sqlalchemy import select

    async with database_service.get_session() as session:
        # Start the run
        await run_service.start_run(session, run_id)

        # Update pipeline run status
        query = select(PipelineRun).where(PipelineRun.id == pipeline_run_id)
        result = await session.execute(query)
        pipeline_run = result.scalar_one_or_none()
        if pipeline_run:
            pipeline_run.status = "running"
            pipeline_run.started_at = datetime.utcnow()

        await session.commit()

        # Execute the pipeline
        result = await pipeline_executor.execute(
            session=session,
            organization_id=organization_id,
            pipeline_slug=pipeline_slug,
            params=params,
            user_id=user_id,
            run_id=run_id,
            pipeline_run_id=pipeline_run_id,
            resume_from_stage=resume_from_stage,
        )

        # Update pipeline run with results
        if pipeline_run:
            pipeline_run.status = result.get("status", "completed")
            pipeline_run.completed_at = datetime.utcnow()
            pipeline_run.stage_results = result.get("stage_results", {})
            pipeline_run.items_processed = result.get("items_processed", 0)

        # Complete or fail the run based on result
        if result.get("status") == "completed":
            await run_service.complete_run(
                session=session,
                run_id=run_id,
                results_summary=result,
            )
        elif result.get("status") == "partial":
            await run_service.complete_run(
                session=session,
                run_id=run_id,
                results_summary=result,
            )
        else:
            await run_service.fail_run(
                session=session,
                run_id=run_id,
                error_message=result.get("error", "Pipeline failed"),
            )

        await session.commit()
        return result


async def _fail_pipeline_run(run_id, pipeline_run_id, error: str) -> None:
    """Mark a pipeline run as failed."""
    from app.core.shared.run_service import run_service
    from app.core.database.procedures import PipelineRun
    from sqlalchemy import select

    async with database_service.get_session() as session:
        # Update pipeline run
        query = select(PipelineRun).where(PipelineRun.id == pipeline_run_id)
        result = await session.execute(query)
        pipeline_run = result.scalar_one_or_none()
        if pipeline_run:
            pipeline_run.status = "failed"
            pipeline_run.completed_at = datetime.utcnow()
            pipeline_run.error_message = error

        await run_service.fail_run(session, run_id, error)
        await session.commit()
