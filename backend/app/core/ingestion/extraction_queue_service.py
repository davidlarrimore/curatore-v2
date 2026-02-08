"""
Extraction Queue Service for Curatore v2.

Provides a database-backed queue layer between extraction requests and Celery
submission to handle thousands of concurrent extraction jobs without overwhelming
workers.

Key Features:
1. Throttled Celery submissions - Only submit N concurrent jobs based on capacity
2. Explicit timeout tracking - 'timed_out' status distinct from 'failed'
3. Duplicate prevention - Block re-extract if extraction already pending/running
4. Queue position tracking - Return position and estimated wait time

Design Principle: Extends the existing Run model rather than creating parallel
tracking systems.

Usage:
    from app.core.ingestion.extraction_queue_service import extraction_queue_service

    # Queue an extraction (does NOT immediately submit to Celery)
    run, extraction, status = await extraction_queue_service.queue_extraction(
        session=session,
        asset_id=asset_id,
        organization_id=org_id,
        origin="system",
        priority=0,
    )

    # Process queue (called periodically by Celery beat)
    result = await extraction_queue_service.process_queue(session)

    # Check timeouts (called periodically by Celery beat)
    result = await extraction_queue_service.check_timeouts(session)

Configuration (env vars):
    EXTRACTION_MAX_CONCURRENT=10      # Max extractions in Celery at once
    EXTRACTION_SUBMISSION_INTERVAL=5  # Seconds between queue checks
    EXTRACTION_DUPLICATE_COOLDOWN=30  # Seconds before allowing re-extract
    EXTRACTION_TIMEOUT_BUFFER=60      # Extra seconds for timeout_at calculation
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from pathlib import Path

from app.core.database.models import Asset, Run, ExtractionResult
from app.config import settings
from .extraction.file_type_registry import file_type_registry

logger = logging.getLogger("curatore.extraction_queue")


class ExtractionQueueService:
    """
    Database-backed queue between extraction requests and Celery.

    This service manages the extraction queue lifecycle:
    1. queue_extraction() - Create Run in 'pending' (not submitted to Celery)
    2. process_queue() - Submit up to N pending runs based on capacity
    3. check_timeouts() - Mark runs past timeout_at as 'timed_out'
    4. get_queue_position() - Return position and estimated wait
    5. prevent_duplicate() - Check if extraction already active
    """

    # Configuration loaded from config.yml via queue_registry
    @property
    def max_concurrent(self) -> int:
        """Maximum concurrent extractions to submit to Celery.

        Configured via config.yml queues.extraction.max_concurrent
        """
        from ..queue_registry import queue_registry
        return queue_registry.get_max_concurrent("extraction") or 10

    @property
    def submission_interval(self) -> int:
        """Seconds between queue submission checks.

        Configured via config.yml queues.extraction.submission_interval
        """
        from ..queue_registry import queue_registry
        queue_def = queue_registry.get("extraction")
        return queue_def.submission_interval if queue_def else 5

    @property
    def duplicate_cooldown(self) -> int:
        """Seconds before allowing re-extract on same asset.

        Configured via config.yml queues.extraction.duplicate_cooldown
        """
        from ..queue_registry import queue_registry
        queue_def = queue_registry.get("extraction")
        return queue_def.duplicate_cooldown if queue_def else 30

    @property
    def timeout_buffer(self) -> int:
        """Extra seconds added to soft_time_limit for timeout_at."""
        return settings.extraction_timeout_buffer

    @property
    def queue_enabled(self) -> bool:
        """Whether to use database-backed queue (vs direct Celery submission)."""
        return settings.extraction_queue_enabled

    def _get_celery_soft_time_limit(self) -> int:
        """Get Celery soft time limit from environment."""
        return int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "600"))

    async def queue_extraction(
        self,
        session: AsyncSession,
        asset_id: UUID,
        organization_id: UUID,
        origin: str = "system",
        priority: Optional[int] = None,
        user_id: Optional[UUID] = None,
        extractor_version: Optional[str] = None,
        group_id: Optional[UUID] = None,
    ) -> Tuple[Run, ExtractionResult, str]:
        """
        Queue an extraction request (does NOT immediately submit to Celery).

        Creates a Run with status="pending" and an ExtractionResult linked to it.
        The run will be submitted to Celery later by process_queue().

        Priority is auto-determined based on context:
        - 0: SharePoint sync extractions (background)
        - 1: SAM.gov/Scrape extractions (background)
        - 2: Pipeline extractions (workflow)
        - 3: User upload extractions (default)
        - 4: User boosted (manually prioritized)

        Args:
            session: Database session
            asset_id: Asset UUID to extract
            organization_id: Organization UUID
            origin: Who triggered ("system" or "user")
            priority: Queue priority (None = auto-determine based on group_type)
            user_id: User UUID if user-initiated
            extractor_version: Extractor version to use
            group_id: Optional group UUID to link this extraction to (for parent-child tracking)

        Returns:
            Tuple of (Run, ExtractionResult, status_message)
            - status_message: "queued" for new, "already_pending" if duplicate blocked
        """
        # Check for duplicate prevention
        allowed, reason, existing_run = await self.prevent_duplicate(session, asset_id)
        if not allowed and existing_run:
            # Return existing run instead of creating new
            extraction = await self._get_extraction_for_run(session, existing_run.id, asset_id)
            if extraction:
                return existing_run, extraction, "already_pending"

        # Get extractor version from config if not provided
        if not extractor_version:
            from ..config_loader import config_loader
            default_engine = config_loader.get_default_extraction_engine()
            if default_engine:
                extractor_version = default_engine.name
            else:
                extractor_version = "extraction-service"

        # Get asset for metadata
        asset = await session.get(Asset, asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")

        # Get current asset version
        from ..asset_service import asset_service
        current_version = await asset_service.get_current_asset_version(session, asset_id)
        asset_version_id = current_version.id if current_version else None

        # Create Run with status="pending" (NOT submitted to Celery yet)
        from ..run_service import run_service
        run = await run_service.create_run(
            session=session,
            organization_id=organization_id,
            run_type="extraction",
            origin=origin,
            config={
                "extractor_version": extractor_version,
                "asset_id": str(asset_id),
                "asset_version_id": str(asset_version_id) if asset_version_id else None,
                "version_number": asset.current_version_number,
                "filename": asset.original_filename,
            },
            input_asset_ids=[str(asset_id)],
            created_by=user_id,
        )

        # Determine queue priority and set spawned_by_parent flag
        from ..queue_registry import QueuePriority

        if group_id:
            # This is a child extraction spawned by a parent job
            run.group_id = group_id
            run.is_group_parent = False
            run.spawned_by_parent = True

            # Auto-determine priority based on group type if not explicitly set
            if priority is None:
                from ...database.models import RunGroup
                group = await session.get(RunGroup, group_id)
                if group:
                    # Map group_type to priority level
                    group_type_priorities = {
                        "sharepoint_sync": QueuePriority.SHAREPOINT_SYNC,  # 0
                        "sam_pull": QueuePriority.SAM_SCRAPE,              # 1
                        "scrape": QueuePriority.SAM_SCRAPE,                # 1
                        "upload_group": QueuePriority.USER_UPLOAD,         # 3
                        "pipeline": QueuePriority.PIPELINE,                # 2
                    }
                    priority = group_type_priorities.get(group.group_type, QueuePriority.SAM_SCRAPE)
                else:
                    priority = QueuePriority.SAM_SCRAPE  # Default for unknown group

        # Default to USER_UPLOAD priority for standalone extractions
        if priority is None:
            priority = QueuePriority.USER_UPLOAD  # 3 = direct user upload

        run.queue_priority = priority

        await session.flush()

        # Create extraction result
        from ..extraction_result_service import extraction_result_service
        extraction = await extraction_result_service.create_extraction_result(
            session=session,
            asset_id=asset_id,
            run_id=run.id,
            extractor_version=extractor_version,
            asset_version_id=asset_version_id,
        )

        # Log queue entry
        from ..run_log_service import run_log_service
        await run_log_service.log_event(
            session=session,
            run_id=run.id,
            level="INFO",
            event_type="queued",
            message=f"Extraction queued for {asset.original_filename} (priority={priority})",
            context={
                "asset_id": str(asset_id),
                "extraction_id": str(extraction.id),
                "queue_priority": priority,
                "origin": origin,
            },
        )

        logger.info(
            f"Queued extraction for asset {asset_id}: "
            f"run={run.id}, extraction={extraction.id}, priority={priority}"
        )

        await session.commit()
        return run, extraction, "queued"

    async def process_queue(
        self,
        session: AsyncSession,
        max_to_submit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Submit queued extractions to Celery based on available capacity.

        Called periodically by Celery beat task. Calculates available slots
        and submits pending runs ordered by priority (desc) and created_at (asc).

        Args:
            session: Database session
            max_to_submit: Override max submissions (for testing)

        Returns:
            Dict with processing statistics
        """
        # Count currently active extractions (submitted + running)
        active_count = await self._count_active_extractions(session)

        # Calculate available slots
        max_concurrent = max_to_submit or self.max_concurrent
        available_slots = max(0, max_concurrent - active_count)

        if available_slots == 0:
            logger.debug(f"No available slots (active={active_count}, max={max_concurrent})")
            return {
                "status": "no_slots",
                "active_count": active_count,
                "max_concurrent": max_concurrent,
                "submitted": 0,
            }

        # Fetch pending runs ordered by priority (desc), created_at (asc)
        # NOTE: Exclude inline extraction runs (playwright_inline) which are handled
        # synchronously and should not go through the Celery queue.
        result = await session.execute(
            select(Run)
            .where(and_(
                Run.run_type == "extraction",
                Run.status == "pending",
                # Exclude inline extraction runs (they complete synchronously)
                # Use PostgreSQL ->> operator to extract text from JSON
                # coalesce handles missing "method" key (returns '' which != 'playwright_inline')
                func.coalesce(Run.config.op('->>')('method'), '') != 'playwright_inline',
            ))
            .order_by(Run.queue_priority.desc(), Run.created_at.asc())
            .limit(available_slots)
        )
        pending_runs = list(result.scalars().all())

        if not pending_runs:
            return {
                "status": "queue_empty",
                "active_count": active_count,
                "max_concurrent": max_concurrent,
                "submitted": 0,
            }

        # Submit each run to Celery
        submitted = 0
        errors = []
        for run in pending_runs:
            try:
                await self._submit_to_celery(session, run)
                submitted += 1
            except Exception as e:
                logger.error(f"Failed to submit run {run.id}: {e}")
                errors.append({"run_id": str(run.id), "error": str(e)})
                # Mark as failed so it doesn't retry indefinitely
                run.status = "failed"
                run.error_message = f"Submission failed: {e}"
                run.completed_at = datetime.utcnow()

        await session.commit()

        logger.info(
            f"Queue processing complete: submitted={submitted}, "
            f"errors={len(errors)}, active_after={active_count + submitted}"
        )

        return {
            "status": "submitted",
            "active_count": active_count,
            "max_concurrent": max_concurrent,
            "submitted": submitted,
            "errors": errors,
        }

    async def _submit_to_celery(
        self,
        session: AsyncSession,
        run: Run,
    ) -> None:
        """
        Submit a single run to Celery and update its status to 'submitted'.

        Args:
            session: Database session
            run: Run to submit
        """
        # Get extraction result for this run
        asset_id_str = run.input_asset_ids[0] if run.input_asset_ids else None
        if not asset_id_str:
            raise ValueError(f"Run {run.id} has no input_asset_ids")

        extraction = await self._get_extraction_for_run(session, run.id, UUID(asset_id_str))
        if not extraction:
            raise ValueError(f"No extraction found for run {run.id}")

        # Calculate timeout_at based on soft time limit + buffer
        soft_limit = self._get_celery_soft_time_limit()
        timeout_at = datetime.utcnow() + timedelta(seconds=soft_limit + self.timeout_buffer)

        # Import and call Celery task
        from ...tasks import execute_extraction_task
        from ..queue_registry import QueuePriority

        # Determine queue based on priority
        # Priority >= PIPELINE (2) goes to priority queue, lower goes to regular extraction queue
        queue = QueuePriority.get_celery_queue(run.queue_priority)

        task = execute_extraction_task.apply_async(
            kwargs={
                "asset_id": asset_id_str,
                "run_id": str(run.id),
                "extraction_id": str(extraction.id),
            },
            queue=queue,
        )

        # Update run with Celery task info
        now = datetime.utcnow()
        run.status = "submitted"
        run.celery_task_id = task.id
        run.submitted_to_celery_at = now
        run.last_activity_at = now  # Initialize activity tracking
        run.timeout_at = timeout_at  # Legacy field, kept for backwards compatibility

        await session.flush()

        logger.info(
            f"Submitted run {run.id} to Celery: task_id={task.id}, queue={queue}"
        )

    async def check_timeouts(
        self,
        session: AsyncSession,
    ) -> Dict[str, Any]:
        """
        Check for stale and timed-out jobs using a two-phase approach.

        Phase 1: Mark jobs as "stale" after 2 minutes of inactivity (warning state)
        Phase 2: Mark jobs as "timed_out" after 5 minutes of inactivity (terminal state)

        Called periodically by Celery beat task (every 30 seconds recommended).
        Uses activity-based timeouts via last_activity_at field.

        All job types are checked - jobs should use heartbeat_service to stay alive.
        Parent jobs with active children are NOT timed out (they're waiting for children).

        Args:
            session: Database session

        Returns:
            Dict with timeout check statistics
        """
        from ...database.models import RunGroup
        from ..heartbeat_service import HeartbeatService

        now = datetime.utcnow()

        # Two-phase thresholds
        stale_threshold = HeartbeatService.STALE_THRESHOLD_SECONDS  # 2 minutes
        timeout_threshold = HeartbeatService.TIMEOUT_THRESHOLD_SECONDS  # 5 minutes

        stale_cutoff = now - timedelta(seconds=stale_threshold)
        timeout_cutoff = now - timedelta(seconds=timeout_threshold)

        # Find parent run IDs that have active children (should not be timed out)
        # A parent should not timeout while its children are still queued or running
        parent_runs_with_active_children_subquery = (
            select(Run.id)
            .where(
                Run.is_group_parent == True,
                Run.group_id.isnot(None),
                Run.group_id.in_(
                    select(RunGroup.id).where(
                        # Group has children that haven't all finished
                        RunGroup.completed_children + RunGroup.failed_children < RunGroup.total_children
                    )
                )
            )
        )

        # Helper to get last activity time for a run
        def get_last_activity(run: Run) -> Optional[datetime]:
            return run.last_activity_at or run.submitted_to_celery_at or run.started_at

        # ========================================================================
        # PHASE 1: Mark stale jobs (running/submitted -> stale after 2 min)
        # ========================================================================
        result = await session.execute(
            select(Run)
            .where(and_(
                Run.status.in_(["submitted", "running"]),
                # Exclude parent jobs that have active children
                Run.id.notin_(parent_runs_with_active_children_subquery),
                or_(
                    # No activity recorded - use submitted_to_celery_at or started_at
                    and_(
                        Run.last_activity_at.is_(None),
                        or_(
                            Run.submitted_to_celery_at < stale_cutoff,
                            and_(
                                Run.submitted_to_celery_at.is_(None),
                                Run.started_at < stale_cutoff,
                            ),
                        ),
                    ),
                    # Has activity but it's stale
                    Run.last_activity_at < stale_cutoff,
                ),
            ))
        )
        potentially_stale_runs = list(result.scalars().all())

        stale_count = 0
        timed_out_count = 0

        for run in potentially_stale_runs:
            try:
                last_activity = get_last_activity(run)
                if not last_activity:
                    continue

                inactivity_seconds = int((now - last_activity).total_seconds())

                # Check if it should be timed out (5 min) or just stale (2 min)
                if inactivity_seconds >= timeout_threshold:
                    # Terminal state - job is dead
                    run.status = "timed_out"
                    run.completed_at = now
                    run.error_message = (
                        f"Job timed out after {inactivity_seconds} seconds of inactivity "
                        f"(threshold: {timeout_threshold}s). The worker may have crashed."
                    )

                    # For extraction runs, update associated asset status
                    if run.run_type == "extraction" and run.input_asset_ids:
                        asset_id = UUID(run.input_asset_ids[0])
                        asset = await session.get(Asset, asset_id)
                        if asset and asset.status in ("pending", "extracting"):
                            asset.status = "failed"

                        # Update extraction result status
                        ext_result = await session.execute(
                            select(ExtractionResult)
                            .where(ExtractionResult.run_id == run.id)
                            .limit(1)
                        )
                        extraction = ext_result.scalar_one_or_none()
                        if extraction:
                            extraction.status = "failed"
                            extraction.error_message = run.error_message

                    timed_out_count += 1
                    logger.warning(
                        f"Marked run {run.id} ({run.run_type}) as timed_out: "
                        f"no activity for {inactivity_seconds}s"
                    )

                else:
                    # Warning state - job might be stuck but could recover
                    run.status = "stale"
                    # Don't set completed_at - job can still recover
                    run.error_message = (
                        f"Job appears stale after {inactivity_seconds} seconds of inactivity. "
                        f"Will timeout at {timeout_threshold}s if no heartbeat received."
                    )
                    stale_count += 1
                    logger.info(
                        f"Marked run {run.id} ({run.run_type}) as stale: "
                        f"no activity for {inactivity_seconds}s"
                    )

            except Exception as e:
                logger.error(f"Failed to check run {run.id} for timeout: {e}")

        # ========================================================================
        # PHASE 2: Check if stale jobs recovered (got heartbeat) or timed out
        # ========================================================================
        result = await session.execute(
            select(Run)
            .where(Run.status == "stale")
        )
        stale_runs = list(result.scalars().all())

        recovered_count = 0
        for run in stale_runs:
            try:
                last_activity = get_last_activity(run)
                if not last_activity:
                    continue

                inactivity_seconds = int((now - last_activity).total_seconds())

                if inactivity_seconds < stale_threshold:
                    # Job recovered! Got a heartbeat
                    run.status = "running"
                    run.error_message = None
                    recovered_count += 1
                    logger.info(f"Run {run.id} ({run.run_type}) recovered from stale state")

                elif inactivity_seconds >= timeout_threshold:
                    # Job is dead
                    run.status = "timed_out"
                    run.completed_at = now
                    run.error_message = (
                        f"Job timed out after {inactivity_seconds} seconds of inactivity "
                        f"(threshold: {timeout_threshold}s). The worker may have crashed."
                    )

                    # For extraction runs, update associated asset status
                    if run.run_type == "extraction" and run.input_asset_ids:
                        asset_id = UUID(run.input_asset_ids[0])
                        asset = await session.get(Asset, asset_id)
                        if asset and asset.status in ("pending", "extracting"):
                            asset.status = "failed"

                        ext_result = await session.execute(
                            select(ExtractionResult)
                            .where(ExtractionResult.run_id == run.id)
                            .limit(1)
                        )
                        extraction = ext_result.scalar_one_or_none()
                        if extraction:
                            extraction.status = "failed"
                            extraction.error_message = run.error_message

                    timed_out_count += 1
                    logger.warning(
                        f"Marked stale run {run.id} ({run.run_type}) as timed_out: "
                        f"no recovery after {inactivity_seconds}s"
                    )

            except Exception as e:
                logger.error(f"Failed to check stale run {run.id}: {e}")

        await session.commit()

        logger.info(
            f"Timeout check complete: {stale_count} marked stale, "
            f"{timed_out_count} timed out, {recovered_count} recovered"
        )
        return {
            "status": "processed",
            "stale_count": stale_count,
            "timed_out_count": timed_out_count,
            "recovered_count": recovered_count,
            "checked_at": now.isoformat(),
        }

    async def prevent_duplicate(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> Tuple[bool, str, Optional[Run]]:
        """
        Check if extraction is already pending/running for this asset.

        Prevents duplicate extraction spam by blocking requests within
        the cooldown period.

        Args:
            session: Database session
            asset_id: Asset UUID to check

        Returns:
            Tuple of (allowed, reason, existing_run)
            - allowed: True if new extraction can proceed
            - reason: Explanation string
            - existing_run: Existing Run if blocked, None if allowed
        """
        asset_id_str = str(asset_id)

        # Find any pending/submitted/running extraction for this asset
        result = await session.execute(
            select(Run)
            .where(and_(
                Run.run_type == "extraction",
                Run.status.in_(["pending", "submitted", "running"]),
                Run.input_asset_ids.contains([asset_id_str]),
            ))
            .order_by(Run.created_at.desc())
            .limit(1)
        )
        existing_run = result.scalar_one_or_none()

        if existing_run:
            return False, "extraction_already_active", existing_run

        # Check cooldown - was there a recent extraction?
        cooldown_cutoff = datetime.utcnow() - timedelta(seconds=self.duplicate_cooldown)
        result = await session.execute(
            select(Run)
            .where(and_(
                Run.run_type == "extraction",
                Run.input_asset_ids.contains([asset_id_str]),
                Run.created_at >= cooldown_cutoff,
            ))
            .order_by(Run.created_at.desc())
            .limit(1)
        )
        recent_run = result.scalar_one_or_none()

        if recent_run:
            logger.debug(f"Cooldown active for asset {asset_id}, recent run: {recent_run.id}")
            # Allow if the recent run completed or failed
            if recent_run.status in ("completed", "failed", "timed_out", "cancelled"):
                return True, "previous_completed", None
            # Block if still active
            return False, "cooldown_active", recent_run

        return True, "no_existing", None

    async def get_queue_position(
        self,
        session: AsyncSession,
        run_id: UUID,
    ) -> Dict[str, Any]:
        """
        Get queue position and estimated wait time for a run.

        Args:
            session: Database session
            run_id: Run UUID to check

        Returns:
            Dict with queue position info
        """
        run = await session.get(Run, run_id)
        if not run:
            return {"status": "not_found", "run_id": str(run_id)}

        # If not pending, no queue position
        if run.status != "pending":
            return {
                "status": run.status,
                "run_id": str(run_id),
                "in_queue": run.status == "submitted",
                "queue_position": None,
            }

        # Count runs ahead of this one (same or higher priority, earlier created_at)
        result = await session.execute(
            select(func.count(Run.id))
            .where(and_(
                Run.run_type == "extraction",
                Run.status == "pending",
                or_(
                    Run.queue_priority > run.queue_priority,
                    and_(
                        Run.queue_priority == run.queue_priority,
                        Run.created_at < run.created_at,
                    ),
                ),
            ))
        )
        position = (result.scalar() or 0) + 1  # 1-indexed

        # Count total pending
        total_result = await session.execute(
            select(func.count(Run.id))
            .where(and_(
                Run.run_type == "extraction",
                Run.status == "pending",
            ))
        )
        total_pending = total_result.scalar() or 0

        # Estimate wait time (rough: avg 45s per extraction / max_concurrent)
        avg_extraction_time = 45  # seconds
        estimated_wait = (position * avg_extraction_time) / self.max_concurrent

        return {
            "status": "pending",
            "run_id": str(run_id),
            "in_queue": True,
            "queue_position": position,
            "total_pending": total_pending,
            "estimated_wait_seconds": estimated_wait,
            "queue_priority": run.queue_priority,
        }

    async def get_queue_stats(
        self,
        session: AsyncSession,
        organization_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Get extraction queue statistics.

        Args:
            session: Database session
            organization_id: Optional org filter

        Returns:
            Dict with queue statistics
        """
        base_filter = [Run.run_type == "extraction"]
        if organization_id:
            base_filter.append(Run.organization_id == organization_id)

        # Count by status
        counts = {}
        for status in ["pending", "submitted", "running", "completed", "failed", "timed_out"]:
            result = await session.execute(
                select(func.count(Run.id))
                .where(and_(*base_filter, Run.status == status))
            )
            counts[f"{status}_count"] = result.scalar() or 0

        # Calculate throughput (completed in last hour)
        hour_ago = datetime.utcnow() - timedelta(hours=1)
        result = await session.execute(
            select(func.count(Run.id))
            .where(and_(
                *base_filter,
                Run.status == "completed",
                Run.completed_at >= hour_ago,
            ))
        )
        completed_last_hour = result.scalar() or 0
        throughput_per_minute = completed_last_hour / 60.0

        # Average extraction time (from submitted to completed)
        # PostgreSQL: use EXTRACT(EPOCH FROM interval) to get seconds
        result = await session.execute(
            select(func.avg(
                func.extract('epoch', Run.completed_at - Run.submitted_to_celery_at)
            ))
            .where(and_(
                *base_filter,
                Run.status == "completed",
                Run.submitted_to_celery_at.isnot(None),
                Run.completed_at.isnot(None),
                Run.completed_at >= hour_ago,
            ))
        )
        avg_extraction_time = result.scalar()  # Already in seconds

        return {
            **counts,
            "max_concurrent": self.max_concurrent,
            "throughput_per_minute": round(throughput_per_minute, 2),
            "avg_extraction_time_seconds": round(avg_extraction_time, 1) if avg_extraction_time else None,
        }

    async def _count_active_extractions(
        self,
        session: AsyncSession,
    ) -> int:
        """Count extractions currently submitted or running."""
        result = await session.execute(
            select(func.count(Run.id))
            .where(and_(
                Run.run_type == "extraction",
                Run.status.in_(["submitted", "running"]),
            ))
        )
        return result.scalar() or 0

    async def _get_extraction_for_run(
        self,
        session: AsyncSession,
        run_id: UUID,
        asset_id: UUID,
    ) -> Optional[ExtractionResult]:
        """Get extraction result for a run and asset."""
        result = await session.execute(
            select(ExtractionResult)
            .where(and_(
                ExtractionResult.run_id == run_id,
                ExtractionResult.asset_id == asset_id,
            ))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def cancel_extraction(
        self,
        session: AsyncSession,
        run_id: UUID,
        reason: str = "User cancelled",
    ) -> Dict[str, Any]:
        """
        Cancel a pending or running extraction.

        Args:
            session: Database session
            run_id: Run UUID to cancel
            reason: Cancellation reason

        Returns:
            Dict with cancellation result
        """
        run = await session.get(Run, run_id)
        if not run:
            return {"status": "not_found", "run_id": str(run_id)}

        if run.status not in ("pending", "submitted", "running"):
            return {
                "status": "not_cancellable",
                "run_id": str(run_id),
                "current_status": run.status,
            }

        # If submitted to Celery, try to revoke
        if run.celery_task_id and run.status in ("submitted", "running"):
            try:
                from ...celery_app import app as celery_app
                celery_app.control.revoke(run.celery_task_id, terminate=True)
                logger.info(f"Revoked Celery task {run.celery_task_id} for run {run_id}")
            except Exception as e:
                logger.warning(f"Failed to revoke Celery task: {e}")

        # Update run status
        run.status = "cancelled"
        run.completed_at = datetime.utcnow()
        run.error_message = reason

        # Update asset status if needed
        if run.input_asset_ids:
            asset_id = UUID(run.input_asset_ids[0])
            asset = await session.get(Asset, asset_id)
            if asset and asset.status in ("pending", "extracting"):
                # Don't mark as failed - just reset to pending so it can be re-tried
                pass  # Leave asset status as-is

        await session.commit()

        logger.info(f"Cancelled run {run_id}: {reason}")
        return {
            "status": "cancelled",
            "run_id": str(run_id),
            "reason": reason,
        }

    async def boost_extraction(
        self,
        session: AsyncSession,
        run_id: UUID,
    ) -> Dict[str, Any]:
        """
        Boost a pending extraction to high priority.

        Args:
            session: Database session
            run_id: Run UUID to boost

        Returns:
            Dict with boost result
        """
        run = await session.get(Run, run_id)
        if not run:
            return {"status": "not_found", "run_id": str(run_id)}

        if run.status != "pending":
            return {
                "status": "not_boostable",
                "run_id": str(run_id),
                "current_status": run.status,
            }

        old_priority = run.queue_priority
        run.queue_priority = 1  # High priority

        await session.commit()

        logger.info(f"Boosted run {run_id} priority: {old_priority} -> 1")
        return {
            "status": "boosted",
            "run_id": str(run_id),
            "old_priority": old_priority,
            "new_priority": 1,
        }


    async def queue_extraction_for_asset(
        self,
        session: AsyncSession,
        asset_id: UUID,
        priority: Optional[int] = None,
        user_id: Optional[UUID] = None,
        skip_content_type_check: bool = False,
        group_id: Optional[UUID] = None,
    ) -> Tuple[Optional[Run], Optional[ExtractionResult], str]:
        """
        Queue extraction for an asset if needed.

        This is the centralized entry point for triggering extractions.
        Called automatically by asset_service when assets are created/updated,
        and by the safety-net maintenance task.

        Handles:
        - Content type checking (skips HTML - already extracted inline)
        - Duplicate prevention
        - Queue management

        Priority is auto-determined based on context when not specified:
        - 0: SharePoint sync extractions (background)
        - 1: SAM.gov/Scrape extractions (background)
        - 2: Pipeline extractions (workflow)
        - 3: User upload extractions (default)
        - 4: User boosted (manually prioritized)

        Args:
            session: Database session
            asset_id: Asset UUID
            priority: Queue priority (None = auto-determine based on group_type)
            user_id: User UUID if user-initiated
            skip_content_type_check: Skip HTML/inline check (for re-extraction)
            group_id: Optional group UUID to link this extraction to (for parent-child tracking)

        Returns:
            Tuple of (Run, ExtractionResult, status_message)
            - status_message: "queued", "already_pending", "skipped_content_type",
              "skipped_unsupported_type", "asset_not_found"
        """
        # Get asset
        asset = await session.get(Asset, asset_id)
        if not asset:
            logger.warning(f"Asset {asset_id} not found for extraction queueing")
            return None, None, "asset_not_found"

        # Check content type - skip HTML (already extracted inline by Playwright)
        if not skip_content_type_check:
            content_type = asset.content_type or ""
            if content_type.startswith("text/html") or content_type == "application/xhtml+xml":
                logger.debug(f"Skipping extraction for HTML asset {asset_id}")
                return None, None, "skipped_content_type"

        # Check file extension - skip unsupported file types
        file_ext = Path(asset.original_filename).suffix.lower()
        is_supported, supporting_engines = file_type_registry.is_supported(file_ext)
        if not is_supported:
            logger.info(
                f"Skipping extraction for unsupported file type: {asset.original_filename} ({file_ext})"
            )
            # Update asset status to indicate it's not extractable
            asset.status = "unsupported"
            await session.commit()
            return None, None, "skipped_unsupported_type"

        # Determine origin based on whether user initiated
        origin = "user" if user_id else "system"

        try:
            run, extraction, status = await self.queue_extraction(
                session=session,
                asset_id=asset_id,
                organization_id=asset.organization_id,
                origin=origin,
                priority=priority,
                user_id=user_id,
                group_id=group_id,
            )
            return run, extraction, status
        except Exception as e:
            logger.error(f"Failed to queue extraction for asset {asset_id}: {e}")
            return None, None, f"error: {str(e)}"

    async def find_assets_needing_extraction(
        self,
        session: AsyncSession,
        limit: int = 100,
        min_age_seconds: int = 60,
    ) -> List[UUID]:
        """
        Find assets with status='pending' that don't have an active extraction run.

        Used by the safety-net maintenance task to catch any assets that
        slipped through without extraction being queued.

        Args:
            session: Database session
            limit: Maximum assets to return
            min_age_seconds: Minimum age to avoid race conditions with normal flow

        Returns:
            List of asset IDs needing extraction
        """
        from sqlalchemy import text

        # Find pending assets older than min_age_seconds
        cutoff = datetime.utcnow() - timedelta(seconds=min_age_seconds)

        result = await session.execute(
            select(Asset.id)
            .where(and_(
                Asset.status == "pending",
                Asset.created_at < cutoff,
            ))
            .order_by(Asset.created_at.asc())
            .limit(limit)
        )
        pending_asset_ids = [row[0] for row in result.fetchall()]

        if not pending_asset_ids:
            return []

        # For each pending asset, check if there's an active extraction run
        orphaned_ids = []
        for asset_id in pending_asset_ids:
            asset_id_str = str(asset_id)

            # Check for active extraction run
            run_result = await session.execute(
                select(Run.id)
                .where(and_(
                    Run.run_type == "extraction",
                    Run.status.in_(["pending", "submitted", "running"]),
                    Run.input_asset_ids.contains([asset_id_str]),
                ))
                .limit(1)
            )

            if not run_result.scalar_one_or_none():
                orphaned_ids.append(asset_id)

        return orphaned_ids


# Global singleton instance
extraction_queue_service = ExtractionQueueService()
