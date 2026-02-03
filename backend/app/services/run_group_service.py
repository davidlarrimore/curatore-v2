# backend/app/services/run_group_service.py
"""
Run Group Service for tracking parent-child job relationships.

This service provides a reusable pattern for tracking when a group of related
child jobs is complete. For example, a SAM pull (parent) creates many extraction
jobs (children) - we only want to emit the completion event when ALL extractions
are done.

Supported group types:
- sam_pull: SAM.gov pull + attachment extractions
- sharepoint_sync: SharePoint sync + file extractions
- scrape: Web crawl + page/document extractions
- upload_group: Group of related uploads + extractions

Usage:
    # In parent job (e.g., SAM pull task):
    group = await run_group_service.create_group(
        session=session,
        organization_id=org_id,
        group_type="sam_pull",
        parent_run_id=run_id,
        config={"after_procedure_slug": "sam-weekly-digest"},
    )

    # When creating child jobs:
    await run_group_service.add_child(session, group.id, child_run_id)

    # When child completes (in extraction task):
    await run_group_service.child_completed(session, child_run_id)

    # When child fails:
    await run_group_service.child_failed(session, child_run_id)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Run, RunGroup

logger = logging.getLogger("curatore.services.run_group")


class RunGroupService:
    """
    Service for managing run groups (parent-child job tracking).
    """

    async def create_group(
        self,
        session: AsyncSession,
        organization_id: UUID,
        group_type: str,
        parent_run_id: Optional[UUID] = None,
        config: Optional[Dict[str, Any]] = None,
        expected_children: int = 0,
    ) -> RunGroup:
        """
        Create a new run group.

        Args:
            session: Database session
            organization_id: Organization UUID
            group_type: Type of group (sam_pull, sharepoint_sync, scrape, upload_group)
            parent_run_id: Optional parent run that initiated this group
            config: Group configuration (e.g., procedure triggers)
            expected_children: Expected number of child runs (can be updated later)

        Returns:
            Created RunGroup instance
        """
        group = RunGroup(
            organization_id=organization_id,
            group_type=group_type,
            parent_run_id=parent_run_id,
            status="pending",
            total_children=expected_children,
            config=config or {},
        )
        session.add(group)
        await session.flush()

        # If there's a parent run, mark it as group parent and link to group
        if parent_run_id:
            parent_query = select(Run).where(Run.id == parent_run_id)
            result = await session.execute(parent_query)
            parent_run = result.scalar_one_or_none()
            if parent_run:
                parent_run.group_id = group.id
                parent_run.is_group_parent = True

        logger.info(f"Created group {group.id} (type={group_type}, parent_run={parent_run_id})")
        return group

    async def get_group(
        self,
        session: AsyncSession,
        group_id: UUID,
    ) -> Optional[RunGroup]:
        """Get a group by ID."""
        query = select(RunGroup).where(RunGroup.id == group_id)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def get_group_for_run(
        self,
        session: AsyncSession,
        run_id: UUID,
    ) -> Optional[RunGroup]:
        """Get the group that a run belongs to."""
        query = select(Run).where(Run.id == run_id)
        result = await session.execute(query)
        run = result.scalar_one_or_none()

        if not run or not run.group_id:
            return None

        return await self.get_group(session, run.group_id)

    async def add_child(
        self,
        session: AsyncSession,
        group_id: UUID,
        child_run_id: UUID,
    ) -> None:
        """
        Add a child run to a group.

        Args:
            session: Database session
            group_id: Group UUID
            child_run_id: Child run UUID to add
        """
        # Update the child run to link to group
        child_query = select(Run).where(Run.id == child_run_id)
        result = await session.execute(child_query)
        child_run = result.scalar_one_or_none()

        if not child_run:
            logger.warning(f"Child run {child_run_id} not found")
            return

        child_run.group_id = group_id
        child_run.is_group_parent = False

        # Increment total_children count
        group_query = select(RunGroup).where(RunGroup.id == group_id)
        result = await session.execute(group_query)
        group = result.scalar_one_or_none()

        if group:
            group.total_children += 1
            if group.status == "pending":
                group.status = "running"
                group.started_at = datetime.utcnow()

        logger.debug(f"Added child {child_run_id} to group {group_id}")

    async def set_expected_children(
        self,
        session: AsyncSession,
        group_id: UUID,
        count: int,
    ) -> None:
        """
        Set the expected number of children for a group.
        Useful when you know upfront how many children will be created.
        """
        query = select(RunGroup).where(RunGroup.id == group_id)
        result = await session.execute(query)
        group = result.scalar_one_or_none()

        if group:
            group.total_children = count
            if group.status == "pending" and count > 0:
                group.status = "running"
                group.started_at = datetime.utcnow()

    async def child_completed(
        self,
        session: AsyncSession,
        child_run_id: UUID,
    ) -> Optional[RunGroup]:
        """
        Mark a child run as completed and check if group is done.

        Args:
            session: Database session
            child_run_id: Child run UUID that completed

        Returns:
            RunGroup if group is now complete, None otherwise
        """
        # Get the run and its group
        run_query = select(Run).where(Run.id == child_run_id)
        result = await session.execute(run_query)
        run = result.scalar_one_or_none()

        if not run or not run.group_id:
            return None

        # Get group
        group = await self.get_group(session, run.group_id)
        if not group:
            return None

        # Increment completed count
        group.completed_children += 1

        logger.debug(
            f"Child {child_run_id} completed in group {group.id} "
            f"({group.completed_children + group.failed_children}/{group.total_children})"
        )

        # Check if group is complete
        return await self._check_group_completion(session, group)

    async def child_failed(
        self,
        session: AsyncSession,
        child_run_id: UUID,
        error: Optional[str] = None,
    ) -> Optional[RunGroup]:
        """
        Mark a child run as failed and check if group is done.

        Args:
            session: Database session
            child_run_id: Child run UUID that failed
            error: Optional error message

        Returns:
            RunGroup if group is now complete, None otherwise
        """
        # Get the run and its group
        run_query = select(Run).where(Run.id == child_run_id)
        result = await session.execute(run_query)
        run = result.scalar_one_or_none()

        if not run or not run.group_id:
            return None

        # Get group
        group = await self.get_group(session, run.group_id)
        if not group:
            return None

        # Increment failed count
        group.failed_children += 1

        logger.debug(
            f"Child {child_run_id} failed in group {group.id} "
            f"({group.completed_children + group.failed_children}/{group.total_children})"
        )

        # Check if group is complete
        return await self._check_group_completion(session, group)

    async def _check_group_completion(
        self,
        session: AsyncSession,
        group: RunGroup,
    ) -> Optional[RunGroup]:
        """
        Check if a group is complete and update status accordingly.

        Returns the group if it just completed, None otherwise.
        """
        processed = group.completed_children + group.failed_children

        # Not all children processed yet
        if processed < group.total_children:
            return None

        # Group is complete - determine final status
        group.completed_at = datetime.utcnow()

        if group.failed_children == 0:
            group.status = "completed"
        elif group.completed_children == 0:
            group.status = "failed"
        else:
            group.status = "partial"

        group.results_summary = {
            "total_children": group.total_children,
            "completed_children": group.completed_children,
            "failed_children": group.failed_children,
            "status": group.status,
        }

        logger.info(
            f"Group {group.id} completed: {group.status} "
            f"({group.completed_children} success, {group.failed_children} failed)"
        )

        # Emit group completion event
        await self._emit_group_event(session, group)

        return group

    async def _emit_group_event(
        self,
        session: AsyncSession,
        group: RunGroup,
    ) -> None:
        """
        Emit event for group completion.

        Event names follow the pattern: {group_type}.group_completed
        """
        from .event_service import event_service

        event_name = f"{group.group_type}.group_completed"

        payload = {
            "group_id": str(group.id),
            "group_type": group.group_type,
            "status": group.status,
            "total_children": group.total_children,
            "completed_children": group.completed_children,
            "failed_children": group.failed_children,
            "parent_run_id": str(group.parent_run_id) if group.parent_run_id else None,
            "config": group.config,
        }

        try:
            await event_service.emit(
                session=session,
                event_name=event_name,
                organization_id=group.organization_id,
                payload=payload,
                source_run_id=group.parent_run_id,
            )
            logger.info(f"Emitted {event_name} for group {group.id}")
        except Exception as e:
            logger.warning(f"Failed to emit {event_name}: {e}")

        # Also trigger configured procedures directly
        await self._run_configured_procedures(session, group)

    async def _run_configured_procedures(
        self,
        session: AsyncSession,
        group: RunGroup,
    ) -> None:
        """
        Run procedures configured in the group config.

        Config format:
        {
            "after_procedure_slug": "procedure-to-run-after",
            "after_procedure_params": {...}
        }
        """
        config = group.config or {}

        after_slug = config.get("after_procedure_slug")
        if not after_slug:
            return

        # Only run after procedure if group succeeded or partially succeeded
        if group.status not in ("completed", "partial"):
            logger.info(f"Skipping after procedure for group {group.id} (status={group.status})")
            return

        from ..database.procedures import Procedure
        from .run_service import run_service
        from ..tasks import execute_procedure_task

        # Get procedure
        proc_query = select(Procedure).where(
            and_(
                Procedure.organization_id == group.organization_id,
                Procedure.slug == after_slug,
                Procedure.is_active == True,
            )
        )
        result = await session.execute(proc_query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            logger.warning(f"After procedure not found: {after_slug}")
            return

        # Build params
        params = config.get("after_procedure_params", {})
        params["group_id"] = str(group.id)
        params["group_type"] = group.group_type
        params["group_status"] = group.status

        # Add source-specific info
        if config.get("source_config_id"):
            params["source_config_id"] = config["source_config_id"]

        # Create run
        run = await run_service.create_run(
            session=session,
            organization_id=group.organization_id,
            run_type="procedure",
            origin="group",
            config={
                "procedure_slug": after_slug,
                "params": params,
                "triggered_by_group": str(group.id),
            },
        )

        # Update run with procedure reference
        run.procedure_id = procedure.id
        run.procedure_version = procedure.version

        await session.commit()

        # Queue Celery task
        execute_procedure_task.delay(
            str(run.id),
            str(group.organization_id),
            after_slug,
            params,
            None,  # user_id
        )

        logger.info(f"Triggered after procedure {after_slug} for group {group.id}")

    async def finalize_group(
        self,
        session: AsyncSession,
        group_id: UUID,
    ) -> Optional[RunGroup]:
        """
        Finalize a group - call this when parent job is done creating children.

        If all children are already complete, this will trigger group completion.
        This handles the case where children complete before the parent finishes
        registering them.
        """
        group = await self.get_group(session, group_id)
        if not group:
            return None

        # If group has no children, complete it immediately
        if group.total_children == 0:
            group.status = "completed"
            group.completed_at = datetime.utcnow()
            group.results_summary = {
                "total_children": 0,
                "completed_children": 0,
                "failed_children": 0,
                "status": "completed",
                "message": "No children to process",
            }
            await self._emit_group_event(session, group)
            return group

        # Check if already complete
        return await self._check_group_completion(session, group)

    async def should_spawn_children(
        self,
        session: AsyncSession,
        group_id: UUID,
    ) -> bool:
        """
        Check if a group should spawn new children.

        Returns False if the parent has failed or been cancelled. This prevents
        creating new child jobs when the parent job has terminated.

        Args:
            session: Database session
            group_id: RunGroup UUID

        Returns:
            True if new children can be spawned, False otherwise
        """
        group = await self.get_group(session, group_id)
        if not group:
            logger.warning(f"Group {group_id} not found when checking should_spawn_children")
            return False

        # Don't spawn children if group is already failed/cancelled
        if group.status in ("failed", "cancelled"):
            logger.info(f"Skipping child spawn for group {group_id} (status={group.status})")
            return False

        return True

    async def mark_group_failed(
        self,
        session: AsyncSession,
        group_id: UUID,
        error_message: str,
    ) -> Optional[RunGroup]:
        """
        Mark a group as failed (typically called when parent job fails).

        This prevents:
        - New children from being spawned (should_spawn_children returns False)
        - Post-job triggers from running (_run_configured_procedures checks status)

        Args:
            session: Database session
            group_id: Group UUID
            error_message: Failure reason

        Returns:
            Updated RunGroup or None if not found
        """
        group = await self.get_group(session, group_id)
        if not group:
            return None

        group.status = "failed"
        group.completed_at = datetime.utcnow()
        group.results_summary = {
            "parent_failed": True,
            "error": error_message,
            "total_children": group.total_children,
            "completed_children": group.completed_children,
            "failed_children": group.failed_children,
        }

        logger.info(f"Marked group {group_id} as failed: {error_message}")
        return group

    async def mark_group_cancelled(
        self,
        session: AsyncSession,
        group_id: UUID,
        reason: str,
    ) -> Optional[RunGroup]:
        """
        Mark a group as cancelled (typically called when parent job is cancelled).

        Args:
            session: Database session
            group_id: Group UUID
            reason: Cancellation reason

        Returns:
            Updated RunGroup or None if not found
        """
        group = await self.get_group(session, group_id)
        if not group:
            return None

        group.status = "cancelled"
        group.completed_at = datetime.utcnow()
        group.results_summary = {
            "cancelled": True,
            "reason": reason,
            "total_children": group.total_children,
            "completed_children": group.completed_children,
            "failed_children": group.failed_children,
        }

        logger.info(f"Marked group {group_id} as cancelled: {reason}")
        return group


# Global singleton
run_group_service = RunGroupService()
