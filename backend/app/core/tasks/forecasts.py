"""
Celery tasks for acquisition forecast syncing.

Handles dispatching forecast sync jobs to the appropriate pull service
based on the sync's source_type (ag, apfs, state).
"""
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from celery import shared_task

from app.celery_app import app as celery_app
from app.core.shared.database_service import database_service


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3}, name="app.tasks.forecast_sync_task")
def forecast_sync_task(
    self,
    sync_id: str,
    organization_id: str,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Celery task to sync acquisition forecasts from configured source.

    This task dispatches to the appropriate pull service based on the sync's
    source_type (ag, apfs, state).

    Args:
        sync_id: ForecastSync UUID string
        organization_id: Organization UUID string
        run_id: Optional pre-created Run UUID string

    Returns:
        Dict containing pull statistics
    """
    from app.core.shared.forecast_sync_service import forecast_sync_service

    logger = logging.getLogger("curatore.forecast")
    logger.info(f"Starting forecast sync task for sync {sync_id}" + (f" (run_id={run_id})" if run_id else ""))

    try:
        result = asyncio.run(
            _execute_forecast_sync_async(
                sync_id=uuid.UUID(sync_id),
                organization_id=uuid.UUID(organization_id),
                run_id=uuid.UUID(run_id) if run_id else None,
            )
        )

        logger.info(f"Forecast sync completed for sync {sync_id}: {result.get('status', 'unknown')}")
        return result

    except Exception as e:
        logger.error(f"Forecast sync task failed for sync {sync_id}: {e}", exc_info=True)
        raise


async def _execute_forecast_sync_async(
    sync_id,
    organization_id,
    run_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """
    Async wrapper for forecast sync execution.

    Args:
        sync_id: ForecastSync UUID
        organization_id: Organization UUID
        run_id: Optional existing Run UUID

    Returns:
        Dict with sync statistics
    """
    from app.core.shared.run_service import run_service
    from app.core.shared.forecast_sync_service import forecast_sync_service
    from app.connectors.gsa_gateway.ag_pull_service import ag_pull_service
    from app.connectors.dhs_apfs.apfs_pull_service import apfs_pull_service
    from app.connectors.state_forecast.state_pull_service import state_pull_service
    from app.core.database.models import Run

    async with database_service.get_session() as session:
        # Get sync config
        sync = await forecast_sync_service.get_sync(session, sync_id)
        if not sync:
            raise ValueError(f"ForecastSync not found: {sync_id}")

        # Create or get run
        if run_id:
            # Update existing run
            run = await session.get(Run, run_id)
            if not run:
                raise ValueError(f"Run not found: {run_id}")
            run.status = "running"
            run.started_at = datetime.utcnow()
            await session.commit()
        else:
            # Create new run
            run = Run(
                organization_id=organization_id,
                run_type="forecast_sync",
                origin="system",
                status="running",
                config={
                    "sync_id": str(sync_id),
                    "source_type": sync.source_type,
                },
                started_at=datetime.utcnow(),
            )
            session.add(run)
            await session.flush()
            run_id = run.id

            # Update sync with run_id
            sync.last_sync_run_id = run.id
            await session.commit()

        try:
            # Dispatch to appropriate pull service
            if sync.source_type == "ag":
                result = await ag_pull_service.pull_forecasts(
                    session=session,
                    sync_id=sync_id,
                    organization_id=organization_id,
                    run_id=run_id,
                )
            elif sync.source_type == "apfs":
                result = await apfs_pull_service.pull_forecasts(
                    session=session,
                    sync_id=sync_id,
                    organization_id=organization_id,
                    run_id=run_id,
                )
            elif sync.source_type == "state":
                result = await state_pull_service.pull_forecasts(
                    session=session,
                    sync_id=sync_id,
                    organization_id=organization_id,
                    run_id=run_id,
                )
            else:
                raise ValueError(f"Unknown source_type: {sync.source_type}")

            # Determine status
            status = "completed"
            if result.get("errors", 0) > 0:
                if result.get("total_processed", 0) > 0:
                    status = "partial"
                else:
                    status = "failed"

            # Update sync status
            await forecast_sync_service.update_sync_status(
                session=session,
                sync_id=sync_id,
                status="success" if status == "completed" else status,
                run_id=run_id,
            )

            # Complete run
            await run_service.complete_run(
                session=session,
                run_id=run_id,
                results_summary=result,
            )
            await session.commit()

            return {
                "sync_id": str(sync_id),
                "source_type": sync.source_type,
                "status": status,
                **result,
            }

        except Exception as e:
            # Update sync status on failure
            await forecast_sync_service.update_sync_status(
                session=session,
                sync_id=sync_id,
                status="failed",
                run_id=run_id,
            )

            await session.rollback()
            await run_service.fail_run(
                session=session,
                run_id=run_id,
                error_message=str(e),
            )
            await session.commit()
            raise
