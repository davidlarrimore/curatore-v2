"""
Run Service for Universal Execution Tracking.

Provides CRUD operations for the Run model, which tracks all background
activity in Curatore (extraction, processing, experiments, maintenance, sync).
Runs are the universal execution mechanism in Phase 0 architecture.

Usage:
    from app.services.run_service import run_service

    # Create extraction run
    run = await run_service.create_run(
        session=session,
        organization_id=org_id,
        run_type="extraction",
        origin="system",
        config={"extractor": "markitdown"},
        created_by=None,  # System run
    )

    # Update run progress
    await run_service.update_run_progress(
        session=session,
        run_id=run.id,
        current=5,
        total=10,
        unit="documents",
    )

    # Complete run
    await run_service.complete_run(
        session=session,
        run_id=run.id,
        results_summary={"processed": 10, "failed": 0},
    )
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import UUID

from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database.models import Run, Asset, ExtractionResult, RunLogEvent
from ..config import settings

logger = logging.getLogger("curatore.run_service")


class RunService:
    """
    Service for managing Run records in the database.

    Handles CRUD operations, status transitions, and progress tracking
    for all types of runs (extraction, processing, experiments, etc.).
    """

    # =========================================================================
    # CREATE OPERATIONS
    # =========================================================================

    async def create_run(
        self,
        session: AsyncSession,
        organization_id: UUID,
        run_type: str,
        origin: str = "user",
        config: Optional[Dict[str, Any]] = None,
        input_asset_ids: Optional[List[str]] = None,
        created_by: Optional[UUID] = None,
    ) -> Run:
        """
        Create a new run record.

        Args:
            session: Database session
            organization_id: Organization UUID
            run_type: Run type (extraction, processing, experiment, system_maintenance, sync)
            origin: Who/what triggered the run (user, system, scheduled)
            config: Run-specific configuration dict
            input_asset_ids: List of asset UUIDs used as input
            created_by: User UUID who created the run (None for system runs)

        Returns:
            Created Run instance
        """
        run = Run(
            organization_id=organization_id,
            run_type=run_type,
            origin=origin,
            status="pending",
            config=config or {},
            input_asset_ids=input_asset_ids or [],
            created_by=created_by,
        )

        session.add(run)
        await session.commit()
        await session.refresh(run)

        logger.info(
            f"Created run {run.id} (org: {organization_id}, "
            f"type: {run_type}, origin: {origin})"
        )

        return run

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    async def get_run(
        self,
        session: AsyncSession,
        run_id: UUID,
    ) -> Optional[Run]:
        """
        Get run by ID.

        Args:
            session: Database session
            run_id: Run UUID

        Returns:
            Run instance or None
        """
        result = await session.execute(
            select(Run).where(Run.id == run_id)
        )
        return result.scalar_one_or_none()

    async def get_run_with_logs(
        self,
        session: AsyncSession,
        run_id: UUID,
    ) -> Optional[Run]:
        """
        Get run with log events eagerly loaded.

        Args:
            session: Database session
            run_id: Run UUID

        Returns:
            Run instance with log_events loaded, or None
        """
        result = await session.execute(
            select(Run)
            .options(selectinload(Run.log_events))
            .where(Run.id == run_id)
        )
        return result.scalar_one_or_none()

    async def get_runs_by_organization(
        self,
        session: AsyncSession,
        organization_id: UUID,
        run_type: Optional[str] = None,
        status: Optional[str] = None,
        origin: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Run]:
        """
        Get runs for an organization with optional filters.

        Args:
            session: Database session
            organization_id: Organization UUID
            run_type: Filter by run type
            status: Filter by status (pending, running, completed, failed, cancelled)
            origin: Filter by origin (user, system, scheduled)
            limit: Maximum results to return
            offset: Number of results to skip

        Returns:
            List of Run instances
        """
        query = select(Run).where(Run.organization_id == organization_id)

        if run_type:
            query = query.where(Run.run_type == run_type)

        if status:
            query = query.where(Run.status == status)

        if origin:
            query = query.where(Run.origin == origin)

        query = query.order_by(Run.created_at.desc()).limit(limit).offset(offset)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_runs_by_asset(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> List[Run]:
        """
        Get all runs that operated on a specific asset.

        Args:
            session: Database session
            asset_id: Asset UUID

        Returns:
            List of Run instances
        """
        # Convert UUID to string for JSON array query
        asset_id_str = str(asset_id)

        result = await session.execute(
            select(Run)
            .where(Run.input_asset_ids.contains([asset_id_str]))
            .order_by(Run.created_at.desc())
        )
        return list(result.scalars().all())

    async def cancel_pending_runs_for_asset(
        self,
        session: AsyncSession,
        asset_id: UUID,
        run_type: Optional[str] = None,
    ) -> int:
        """
        Cancel all pending or running runs for an asset.

        Called before starting a new extraction to ensure only one
        extraction runs at a time per asset. This prevents:
        - Duplicate extraction work
        - Race conditions
        - Stale "running" runs from piling up

        Args:
            session: Database session
            asset_id: Asset UUID
            run_type: Optional run type filter (e.g., "extraction")

        Returns:
            Number of runs cancelled
        """
        asset_id_str = str(asset_id)

        # Find all pending/submitted/running runs for this asset
        query = (
            select(Run)
            .where(Run.input_asset_ids.contains([asset_id_str]))
            .where(Run.status.in_(["pending", "submitted", "running"]))
        )

        if run_type:
            query = query.where(Run.run_type == run_type)

        result = await session.execute(query)
        runs_to_cancel = list(result.scalars().all())

        cancelled_count = 0
        for run in runs_to_cancel:
            try:
                # Cancel the run and set error message
                if run.status in ("running", "submitted"):
                    run.status = "cancelled"
                    run.error_message = "Superseded by new extraction request"
                    run.completed_at = datetime.utcnow()
                    cancelled_count += 1
                    logger.info(f"Cancelled {run.status} run {run.id} (superseded)")
                elif run.status == "pending":
                    # Pending runs: just set to cancelled directly
                    run.status = "cancelled"
                    run.error_message = "Superseded by new extraction request"
                    run.completed_at = datetime.utcnow()
                    cancelled_count += 1
                    logger.info(f"Cancelled pending run {run.id} (superseded)")
            except Exception as e:
                logger.warning(f"Failed to cancel run {run.id}: {e}")

        await session.flush()
        return cancelled_count

    async def count_runs_by_organization(
        self,
        session: AsyncSession,
        organization_id: UUID,
        run_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        """
        Count runs for an organization with optional filters.

        Args:
            session: Database session
            organization_id: Organization UUID
            run_type: Filter by run type
            status: Filter by status

        Returns:
            Count of matching runs
        """
        query = select(func.count(Run.id)).where(
            Run.organization_id == organization_id
        )

        if run_type:
            query = query.where(Run.run_type == run_type)

        if status:
            query = query.where(Run.status == status)

        result = await session.execute(query)
        return result.scalar_one()

    # =========================================================================
    # UPDATE OPERATIONS
    # =========================================================================

    async def update_run_status(
        self,
        session: AsyncSession,
        run_id: UUID,
        status: str,
        error_message: Optional[str] = None,
    ) -> Optional[Run]:
        """
        Update run status with strict transition enforcement.

        Status transitions (strict):
        - pending → running
        - running → completed
        - running → failed
        - running → cancelled

        Args:
            session: Database session
            run_id: Run UUID
            status: New status (pending, running, completed, failed, cancelled)
            error_message: Optional error message (for failed status)

        Returns:
            Updated Run instance or None if not found

        Raises:
            ValueError: If status transition is invalid
        """
        run = await self.get_run(session, run_id)
        if not run:
            return None

        old_status = run.status

        # Validate status transition
        # Note: pending can transition to submitted, failed/cancelled directly if the task
        # fails before it starts (e.g., import errors, configuration issues)
        # Status flow for queue-enabled:
        #   pending -> submitted -> running -> completed/failed/timed_out/cancelled
        # Status flow for queue-disabled (legacy):
        #   pending -> running -> completed/failed/cancelled
        valid_transitions = {
            "pending": ["submitted", "running", "failed", "cancelled"],
            "submitted": ["running", "timed_out", "cancelled"],
            "running": ["completed", "failed", "timed_out", "cancelled"],
            "completed": [],
            "failed": [],
            "timed_out": [],
            "cancelled": [],
        }

        if status not in valid_transitions.get(old_status, []):
            raise ValueError(
                f"Invalid status transition: {old_status} → {status}. "
                f"Valid transitions from {old_status}: {valid_transitions.get(old_status, [])}"
            )

        run.status = status
        now = datetime.utcnow()

        # Update timestamps
        if status == "running" and not run.started_at:
            run.started_at = now
        elif status in ["completed", "failed", "timed_out", "cancelled"]:
            run.completed_at = now

        # Track activity for running jobs (activity-based timeout)
        if status in ("submitted", "running"):
            run.last_activity_at = now

        # Set error message for failed/timed_out runs
        if status in ("failed", "timed_out") and error_message:
            run.error_message = error_message

        await session.commit()
        await session.refresh(run)

        logger.info(f"Updated run {run_id} status: {old_status} → {status}")

        return run

    async def update_run_progress(
        self,
        session: AsyncSession,
        run_id: UUID,
        current: int,
        total: Optional[int] = None,
        unit: str = "items",
        phase: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Optional[Run]:
        """
        Update run progress tracking.

        Args:
            session: Database session
            run_id: Run UUID
            current: Current progress value
            total: Total items (None if unknown)
            unit: Progress unit (documents, pages, urls, etc.)
            phase: Current execution phase (e.g., "scanning", "processing", "finalizing")
            details: Additional progress details (e.g., {"new_files": 5, "errors": 1})

        Returns:
            Updated Run instance or None if not found

        Example progress structures:

            # Simple progress
            {"current": 5, "total": 10, "unit": "files", "percent": 50}

            # Detailed progress with phase
            {
                "current": 25,
                "total": 100,
                "unit": "files",
                "percent": 25,
                "phase": "processing",
                "folders_scanned": 10,
                "new_files": 5,
                "updated_files": 3,
                "errors": 0
            }
        """
        run = await self.get_run(session, run_id)
        if not run:
            return None

        # Calculate percentage if total is known
        percent = None
        if total and total > 0:
            percent = min(100, int((current / total) * 100))

        # Build progress dict
        progress = {
            "current": current,
            "total": total,
            "unit": unit,
            "percent": percent,
        }

        # Add phase if provided
        if phase:
            progress["phase"] = phase

        # Merge additional details
        if details:
            progress.update(details)

        run.progress = progress

        # Track activity for timeout detection
        run.last_activity_at = datetime.utcnow()

        await session.commit()
        await session.refresh(run)

        return run

    async def start_run(
        self,
        session: AsyncSession,
        run_id: UUID,
    ) -> Optional[Run]:
        """
        Convenience method to start a run (pending → running).

        Args:
            session: Database session
            run_id: Run UUID

        Returns:
            Updated Run instance or None if not found
        """
        return await self.update_run_status(session, run_id, "running")

    async def complete_run(
        self,
        session: AsyncSession,
        run_id: UUID,
        results_summary: Optional[Dict[str, Any]] = None,
    ) -> Optional[Run]:
        """
        Mark run as completed with optional results summary.

        Args:
            session: Database session
            run_id: Run UUID
            results_summary: Summary of run results (counts, metrics, etc.)

        Returns:
            Updated Run instance or None if not found
        """
        run = await self.get_run(session, run_id)
        if not run:
            return None

        if results_summary:
            run.results_summary = results_summary

        return await self.update_run_status(session, run_id, "completed")

    async def fail_run(
        self,
        session: AsyncSession,
        run_id: UUID,
        error_message: str,
    ) -> Optional[Run]:
        """
        Mark run as failed with error message.

        Args:
            session: Database session
            run_id: Run UUID
            error_message: Error description

        Returns:
            Updated Run instance or None if not found
        """
        return await self.update_run_status(session, run_id, "failed", error_message)

    async def cancel_run(
        self,
        session: AsyncSession,
        run_id: UUID,
    ) -> Optional[Run]:
        """
        Mark run as cancelled.

        Args:
            session: Database session
            run_id: Run UUID

        Returns:
            Updated Run instance or None if not found
        """
        return await self.update_run_status(session, run_id, "cancelled")

    async def touch_activity(
        self,
        session: AsyncSession,
        run_id: UUID,
    ) -> Optional[Run]:
        """
        Update last_activity_at to current time without changing other fields.

        Used to indicate the job is still alive when logging events or
        doing work that doesn't update progress.

        Args:
            session: Database session
            run_id: Run UUID

        Returns:
            Updated Run instance or None if not found
        """
        run = await self.get_run(session, run_id)
        if not run:
            return None

        run.last_activity_at = datetime.utcnow()

        await session.commit()
        await session.refresh(run)

        return run


# Singleton instance
run_service = RunService()
