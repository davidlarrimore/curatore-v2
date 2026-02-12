"""
Job Cancellation Service for Curatore v2.

Provides centralized cascade cancellation logic for parent-child job relationships.
Different job types have different cancellation behaviors:

- SharePoint Sync: Cancel queued children only (running extractions complete)
- SAM.gov Pull: Cancel queued children only (running extractions complete)
- Web Scrape: Cancel queued children only (running extractions complete)
- Pipeline: Cancel ALL children (atomicity - partial results are useless)

Usage:
    from app.core.ops.job_cancellation_service import job_cancellation_service

    result = await job_cancellation_service.cancel_parent_job(
        session=session,
        run_id=run_id,
        reason="User cancelled",
    )
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database.models import Run, RunGroup

logger = logging.getLogger("curatore.services.job_cancellation")


class CascadeMode(str, Enum):
    """Cascade mode for child job cancellation."""
    QUEUED_ONLY = "queued_only"  # Cancel only pending/submitted children
    ALL = "all"                   # Cancel all children including running


# Map job types to their cascade modes
JOB_TYPE_CASCADE_MODES = {
    "sharepoint_sync": CascadeMode.QUEUED_ONLY,
    "sharepoint_import": CascadeMode.QUEUED_ONLY,
    "sharepoint_delete": CascadeMode.QUEUED_ONLY,
    "sam_pull": CascadeMode.QUEUED_ONLY,
    "scrape_crawl": CascadeMode.QUEUED_ONLY,
    "scrape": CascadeMode.QUEUED_ONLY,
    "pipeline": CascadeMode.ALL,
    "pipeline_run": CascadeMode.ALL,
}


class JobCancellationService:
    """
    Service for cancelling jobs with proper cascade behavior.

    Handles parent-child job relationships and ensures proper cleanup
    based on job type-specific cascade modes.
    """

    async def cancel_parent_job(
        self,
        session: AsyncSession,
        run_id: UUID,
        reason: str = "User cancelled",
        cascade_mode: Optional[CascadeMode] = None,
    ) -> Dict[str, Any]:
        """
        Cancel a parent job with appropriate child handling.

        Args:
            session: Database session
            run_id: Run UUID to cancel
            reason: Cancellation reason
            cascade_mode: Override cascade mode (default: determined by job type)

        Returns:
            Dict with cancellation results including child cancellation counts
        """
        run = await session.get(Run, run_id)
        if not run:
            return {"success": False, "error": "Run not found"}

        # Check if job can be cancelled
        from .queue_registry import queue_registry
        if not queue_registry.can_cancel(run.run_type):
            return {"success": False, "error": f"Job type {run.run_type} cannot be cancelled"}

        # Check if job is in a cancellable state
        if run.status not in ("pending", "submitted", "running"):
            return {
                "success": False,
                "error": f"Cannot cancel job in '{run.status}' status"
            }

        # Determine cascade mode
        if cascade_mode is None:
            cascade_mode = JOB_TYPE_CASCADE_MODES.get(run.run_type, CascadeMode.QUEUED_ONLY)

        # Track results
        result = {
            "success": True,
            "run_id": str(run_id),
            "run_type": run.run_type,
            "cascade_mode": cascade_mode.value,
            "children_cancelled": 0,
            "children_skipped": 0,
        }

        # Handle child jobs if this is a group parent
        if run.is_group_parent and run.group_id:
            child_result = await self._cancel_child_jobs(
                session=session,
                group_id=run.group_id,
                cascade_mode=cascade_mode,
                reason=reason,
            )
            result["children_cancelled"] = child_result["cancelled"]
            result["children_skipped"] = child_result["skipped"]

            # Mark group as cancelled
            group = await session.get(RunGroup, run.group_id)
            if group:
                group.status = "cancelled"
                group.completed_at = datetime.utcnow()
                group.results_summary = {
                    "cancelled_by_user": True,
                    "reason": reason,
                    "children_cancelled": result["children_cancelled"],
                }

        # Cancel the parent job itself
        await self._cancel_run(session, run, reason)

        # Attempt to revoke Celery task if running
        if run.celery_task_id and run.status in ("submitted", "running"):
            await self._revoke_celery_task(run.celery_task_id)

        await session.commit()

        logger.info(
            f"Cancelled job {run_id} ({run.run_type}): "
            f"children_cancelled={result['children_cancelled']}, "
            f"children_skipped={result['children_skipped']}"
        )

        return result

    async def _cancel_child_jobs(
        self,
        session: AsyncSession,
        group_id: UUID,
        cascade_mode: CascadeMode,
        reason: str,
    ) -> Dict[str, int]:
        """
        Cancel child jobs in a group based on cascade mode.

        Args:
            session: Database session
            group_id: RunGroup UUID
            cascade_mode: Which children to cancel
            reason: Cancellation reason

        Returns:
            Dict with cancelled and skipped counts
        """
        # Determine which statuses to cancel
        if cascade_mode == CascadeMode.ALL:
            cancellable_statuses = ["pending", "submitted", "running"]
        else:
            cancellable_statuses = ["pending", "submitted"]

        # Find child runs in this group
        result = await session.execute(
            select(Run)
            .where(and_(
                Run.group_id == group_id,
                Run.is_group_parent == False,
            ))
        )
        children = list(result.scalars().all())

        cancelled = 0
        skipped = 0

        for child in children:
            if child.status in cancellable_statuses:
                await self._cancel_run(session, child, f"Parent cancelled: {reason}")

                # Revoke Celery task if applicable
                if child.celery_task_id and child.status in ("submitted", "running"):
                    await self._revoke_celery_task(child.celery_task_id)

                cancelled += 1
            else:
                # Already completed/failed - skip
                skipped += 1

        return {"cancelled": cancelled, "skipped": skipped}

    async def _cancel_run(
        self,
        session: AsyncSession,
        run: Run,
        reason: str,
    ) -> None:
        """
        Cancel a single run and update associated resources.

        Args:
            session: Database session
            run: Run to cancel
            reason: Cancellation reason
        """
        now = datetime.utcnow()
        run.status = "cancelled"
        run.completed_at = now
        run.error_message = reason

        # Log cancellation
        from app.core.shared.run_log_service import run_log_service
        await run_log_service.log_event(
            session=session,
            run_id=run.id,
            level="INFO",
            event_type="cancelled",
            message=reason,
            context={"cancelled_at": now.isoformat()},
        )

        # Update associated extraction result if this is an extraction
        if run.run_type == "extraction" and run.input_asset_ids:
            from uuid import UUID as PyUUID

            from app.core.database.models import Asset, ExtractionResult

            asset_id = PyUUID(run.input_asset_ids[0])

            # Update extraction result
            ext_result = await session.execute(
                select(ExtractionResult)
                .where(ExtractionResult.run_id == run.id)
                .limit(1)
            )
            extraction = ext_result.scalar_one_or_none()
            if extraction:
                extraction.status = "cancelled"
                extraction.error_message = reason

            # Update asset status if it was pending
            asset = await session.get(Asset, asset_id)
            if asset and asset.status in ("pending", "extracting"):
                asset.status = "cancelled"

    async def _revoke_celery_task(self, task_id: str) -> bool:
        """
        Attempt to revoke a Celery task.

        Args:
            task_id: Celery task ID

        Returns:
            True if revocation was sent, False on error
        """
        try:
            from app.celery_app import app as celery_app
            celery_app.control.revoke(task_id, terminate=True)
            logger.info(f"Revoked Celery task {task_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to revoke Celery task {task_id}: {e}")
            return False

    async def handle_parent_failure(
        self,
        session: AsyncSession,
        run_id: UUID,
        error_message: str,
    ) -> Dict[str, Any]:
        """
        Handle a parent job failure.

        When a parent job fails:
        1. Mark the group as failed (prevents post-job triggers)
        2. For pipelines: cancel all active children
        3. For other types: let running children complete

        Args:
            session: Database session
            run_id: Failed parent run ID
            error_message: Failure reason

        Returns:
            Dict with failure handling results
        """
        run = await session.get(Run, run_id)
        if not run:
            return {"success": False, "error": "Run not found"}

        if not run.is_group_parent or not run.group_id:
            return {"success": True, "message": "Not a group parent, no children to handle"}

        result = {
            "success": True,
            "run_id": str(run_id),
            "children_cancelled": 0,
        }

        # Get the group
        group = await session.get(RunGroup, run.group_id)
        if group:
            # Mark group as failed (prevents post-job triggers from running)
            group.status = "failed"
            group.completed_at = datetime.utcnow()
            group.results_summary = {
                "parent_failed": True,
                "error": error_message,
            }

            # For pipelines: cancel all active children (atomicity requirement)
            cascade_mode = JOB_TYPE_CASCADE_MODES.get(run.run_type)
            if cascade_mode == CascadeMode.ALL:
                child_result = await self._cancel_child_jobs(
                    session=session,
                    group_id=run.group_id,
                    cascade_mode=CascadeMode.ALL,
                    reason=f"Parent failed: {error_message}",
                )
                result["children_cancelled"] = child_result["cancelled"]

        await session.commit()

        logger.info(
            f"Handled parent failure for {run_id}: "
            f"children_cancelled={result['children_cancelled']}"
        )

        return result

    async def should_spawn_children(
        self,
        session: AsyncSession,
        group_id: UUID,
    ) -> bool:
        """
        Check if a group should spawn new children.

        Returns False if the parent has failed or been cancelled.

        Args:
            session: Database session
            group_id: RunGroup UUID

        Returns:
            True if new children can be spawned
        """
        group = await session.get(RunGroup, group_id)
        if not group:
            return False

        # Don't spawn children if group is already failed/cancelled
        return group.status not in ("failed", "cancelled")

    async def get_child_job_stats(
        self,
        session: AsyncSession,
        group_id: UUID,
    ) -> Dict[str, int]:
        """
        Get statistics about child jobs in a group.

        Args:
            session: Database session
            group_id: RunGroup UUID

        Returns:
            Dict with counts by status
        """
        result = await session.execute(
            select(Run.status, func.count(Run.id))
            .where(and_(
                Run.group_id == group_id,
                Run.is_group_parent == False,
            ))
            .group_by(Run.status)
        )

        stats = {
            "total": 0,
            "pending": 0,
            "submitted": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "timed_out": 0,
        }

        for status, count in result.all():
            stats[status] = count
            stats["total"] += count

        return stats


# Global singleton
job_cancellation_service = JobCancellationService()
