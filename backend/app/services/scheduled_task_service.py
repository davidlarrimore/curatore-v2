"""
Scheduled task management service for Curatore v2.

This service provides CRUD operations and task execution management
for database-backed scheduled tasks (Phase 5).

Key Features:
- CRUD for ScheduledTask model
- Enable/disable tasks at runtime
- Manual task triggering
- Execution tracking via Run model
- Cron schedule calculation

Usage:
    from app.services.scheduled_task_service import scheduled_task_service

    # Get all enabled tasks
    tasks = await scheduled_task_service.list_enabled_tasks(session)

    # Trigger a task manually
    run = await scheduled_task_service.trigger_task_now(session, task_id)

    # Enable/disable a task
    await scheduled_task_service.enable_task(session, task_id)
    await scheduled_task_service.disable_task(session, task_id)
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from croniter import croniter
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import ScheduledTask, Run, RunLogEvent

logger = logging.getLogger("curatore.services.scheduled_task")


class ScheduledTaskService:
    """
    Service for managing scheduled maintenance tasks.

    Provides CRUD operations, task execution, and schedule management
    for database-backed scheduled tasks.
    """

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    async def get_task(
        self,
        session: AsyncSession,
        task_id: UUID,
    ) -> Optional[ScheduledTask]:
        """
        Get a scheduled task by ID.

        Args:
            session: Database session
            task_id: Task UUID

        Returns:
            ScheduledTask if found, None otherwise
        """
        result = await session.execute(
            select(ScheduledTask).where(ScheduledTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_task_by_name(
        self,
        session: AsyncSession,
        name: str,
    ) -> Optional[ScheduledTask]:
        """
        Get a scheduled task by name.

        Args:
            session: Database session
            name: Task name (unique)

        Returns:
            ScheduledTask if found, None otherwise
        """
        result = await session.execute(
            select(ScheduledTask).where(ScheduledTask.name == name)
        )
        return result.scalar_one_or_none()

    async def list_tasks(
        self,
        session: AsyncSession,
        organization_id: Optional[UUID] = None,
        enabled_only: bool = False,
    ) -> List[ScheduledTask]:
        """
        List scheduled tasks with optional filtering.

        Args:
            session: Database session
            organization_id: Filter by organization (None includes global tasks)
            enabled_only: Only return enabled tasks

        Returns:
            List of ScheduledTask objects
        """
        query = select(ScheduledTask)

        conditions = []
        if organization_id is not None:
            # Include both org-specific and global tasks
            conditions.append(
                (ScheduledTask.organization_id == organization_id)
                | (ScheduledTask.organization_id.is_(None))
            )
        if enabled_only:
            conditions.append(ScheduledTask.enabled == True)

        if conditions:
            query = query.where(and_(*conditions))

        query = query.order_by(ScheduledTask.name)
        result = await session.execute(query)
        return list(result.scalars().all())

    async def list_enabled_tasks(
        self,
        session: AsyncSession,
    ) -> List[ScheduledTask]:
        """
        List all enabled scheduled tasks (global and org-specific).

        Args:
            session: Database session

        Returns:
            List of enabled ScheduledTask objects
        """
        result = await session.execute(
            select(ScheduledTask)
            .where(ScheduledTask.enabled == True)
            .order_by(ScheduledTask.next_run_at)
        )
        return list(result.scalars().all())

    async def list_due_tasks(
        self,
        session: AsyncSession,
        as_of: Optional[datetime] = None,
    ) -> List[ScheduledTask]:
        """
        List tasks that are due to run.

        A task is due if it's enabled and next_run_at <= current time.

        Args:
            session: Database session
            as_of: Time to check against (default: now)

        Returns:
            List of due ScheduledTask objects
        """
        if as_of is None:
            as_of = datetime.utcnow()

        result = await session.execute(
            select(ScheduledTask)
            .where(
                and_(
                    ScheduledTask.enabled == True,
                    ScheduledTask.next_run_at <= as_of,
                )
            )
            .order_by(ScheduledTask.next_run_at)
        )
        return list(result.scalars().all())

    async def create_task(
        self,
        session: AsyncSession,
        name: str,
        display_name: str,
        task_type: str,
        schedule_expression: str,
        description: Optional[str] = None,
        scope_type: str = "global",
        organization_id: Optional[UUID] = None,
        enabled: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ) -> ScheduledTask:
        """
        Create a new scheduled task.

        Args:
            session: Database session
            name: Unique task name
            display_name: Human-readable name
            task_type: Type of maintenance task
            schedule_expression: Cron expression
            description: Optional description
            scope_type: global or organization
            organization_id: Organization ID for scoped tasks
            enabled: Whether task is active
            config: Task-specific configuration

        Returns:
            Created ScheduledTask

        Raises:
            ValueError: If name already exists or cron is invalid
        """
        # Validate cron expression
        if not self._validate_cron(schedule_expression):
            raise ValueError(f"Invalid cron expression: {schedule_expression}")

        # Check for existing task with same name
        existing = await self.get_task_by_name(session, name)
        if existing:
            raise ValueError(f"Task with name '{name}' already exists")

        # Calculate next run time
        next_run = self._calculate_next_run(schedule_expression)

        task = ScheduledTask(
            id=uuid4(),
            name=name,
            display_name=display_name,
            description=description,
            task_type=task_type,
            scope_type=scope_type,
            organization_id=organization_id,
            schedule_expression=schedule_expression,
            enabled=enabled,
            config=config or {},
            next_run_at=next_run if enabled else None,
        )

        session.add(task)
        await session.flush()
        await session.refresh(task)

        logger.info(f"Created scheduled task: {name} (id={task.id})")
        return task

    async def update_task(
        self,
        session: AsyncSession,
        task_id: UUID,
        **updates,
    ) -> Optional[ScheduledTask]:
        """
        Update a scheduled task.

        Args:
            session: Database session
            task_id: Task UUID
            **updates: Fields to update

        Returns:
            Updated ScheduledTask or None if not found
        """
        task = await self.get_task(session, task_id)
        if not task:
            return None

        # Apply updates
        for key, value in updates.items():
            if hasattr(task, key):
                setattr(task, key, value)

        # Recalculate next_run if schedule changed
        if "schedule_expression" in updates or "enabled" in updates:
            if task.enabled:
                task.next_run_at = self._calculate_next_run(task.schedule_expression)
            else:
                task.next_run_at = None

        await session.flush()
        await session.refresh(task)

        logger.info(f"Updated scheduled task: {task.name} (id={task_id})")
        return task

    async def delete_task(
        self,
        session: AsyncSession,
        task_id: UUID,
    ) -> bool:
        """
        Delete a scheduled task.

        Args:
            session: Database session
            task_id: Task UUID

        Returns:
            True if deleted, False if not found
        """
        task = await self.get_task(session, task_id)
        if not task:
            return False

        await session.delete(task)
        logger.info(f"Deleted scheduled task: {task.name} (id={task_id})")
        return True

    # =========================================================================
    # Enable/Disable Operations
    # =========================================================================

    async def enable_task(
        self,
        session: AsyncSession,
        task_id: UUID,
    ) -> Optional[ScheduledTask]:
        """
        Enable a scheduled task.

        Args:
            session: Database session
            task_id: Task UUID

        Returns:
            Updated ScheduledTask or None if not found
        """
        task = await self.get_task(session, task_id)
        if not task:
            return None

        task.enabled = True
        task.next_run_at = self._calculate_next_run(task.schedule_expression)

        await session.flush()
        await session.refresh(task)

        logger.info(f"Enabled scheduled task: {task.name}")
        return task

    async def disable_task(
        self,
        session: AsyncSession,
        task_id: UUID,
    ) -> Optional[ScheduledTask]:
        """
        Disable a scheduled task.

        Args:
            session: Database session
            task_id: Task UUID

        Returns:
            Updated ScheduledTask or None if not found
        """
        task = await self.get_task(session, task_id)
        if not task:
            return None

        task.enabled = False
        task.next_run_at = None

        await session.flush()
        await session.refresh(task)

        logger.info(f"Disabled scheduled task: {task.name}")
        return task

    # =========================================================================
    # Execution Operations
    # =========================================================================

    async def trigger_task_now(
        self,
        session: AsyncSession,
        task_id: UUID,
        triggered_by: Optional[UUID] = None,
        user_organization_id: Optional[UUID] = None,
    ) -> Optional[Run]:
        """
        Trigger a task to run immediately.

        Creates a Run with origin="user" (manual trigger) and enqueues
        the task for execution.

        Args:
            session: Database session
            task_id: Task UUID
            triggered_by: User ID who triggered the task
            user_organization_id: Organization ID for global tasks (from current user)

        Returns:
            Created Run object or None if task not found
        """
        task = await self.get_task(session, task_id)
        if not task:
            logger.warning(f"Task not found for trigger: {task_id}")
            return None

        # For global tasks (organization_id is None), use the triggering user's org
        # Runs require an organization_id (NOT NULL constraint)
        run_org_id = task.organization_id or user_organization_id
        if not run_org_id:
            logger.error(f"Cannot trigger task without organization context: {task_id}")
            return None

        # Create a Run for this execution
        run = Run(
            id=uuid4(),
            organization_id=run_org_id,
            run_type="system_maintenance",
            origin="user",  # Manual trigger
            status="pending",
            config={
                "scheduled_task_id": str(task.id),
                "scheduled_task_name": task.name,
                "task_type": task.task_type,
                "task_config": task.config,
            },
            created_by=triggered_by,
        )
        session.add(run)

        # Log the trigger
        log_event = RunLogEvent(
            id=uuid4(),
            run_id=run.id,
            level="INFO",
            event_type="start",
            message=f"Scheduled task '{task.display_name}' triggered manually",
            context={
                "task_id": str(task.id),
                "task_name": task.name,
                "triggered_by": str(triggered_by) if triggered_by else None,
            },
        )
        session.add(log_event)

        await session.flush()
        await session.refresh(run)

        logger.info(f"Triggered scheduled task: {task.name} (run_id={run.id})")

        # Enqueue the task for execution
        # Import here to avoid circular imports
        from ..tasks import execute_scheduled_task_async

        execute_scheduled_task_async.delay(
            task_id=str(task.id),
            run_id=str(run.id),
        )

        return run

    async def update_last_run(
        self,
        session: AsyncSession,
        task_id: UUID,
        run_id: UUID,
        status: str,
    ) -> Optional[ScheduledTask]:
        """
        Update task after execution completes.

        Updates last_run_id, last_run_at, last_run_status, and
        calculates next_run_at.

        Args:
            session: Database session
            task_id: Task UUID
            run_id: Run UUID
            status: Run status (success, failed)

        Returns:
            Updated ScheduledTask or None if not found
        """
        task = await self.get_task(session, task_id)
        if not task:
            return None

        task.last_run_id = run_id
        task.last_run_at = datetime.utcnow()
        task.last_run_status = status

        # Calculate next run time
        if task.enabled:
            task.next_run_at = self._calculate_next_run(task.schedule_expression)

        await session.flush()
        await session.refresh(task)

        logger.info(f"Updated last run for task: {task.name} (status={status})")
        return task

    # =========================================================================
    # Schedule Calculation
    # =========================================================================

    def _validate_cron(self, expression: str) -> bool:
        """
        Validate a cron expression.

        Args:
            expression: Cron expression (5 fields: minute hour day month weekday)

        Returns:
            True if valid, False otherwise
        """
        try:
            croniter(expression)
            return True
        except (ValueError, KeyError):
            return False

    def _calculate_next_run(
        self,
        schedule_expression: str,
        base_time: Optional[datetime] = None,
    ) -> Optional[datetime]:
        """
        Calculate the next run time from a cron expression.

        Args:
            schedule_expression: Cron expression
            base_time: Time to calculate from (default: now)

        Returns:
            Next run datetime or None if invalid
        """
        try:
            if base_time is None:
                base_time = datetime.utcnow()
            cron = croniter(schedule_expression, base_time)
            return cron.get_next(datetime)
        except (ValueError, KeyError) as e:
            logger.warning(f"Invalid cron expression '{schedule_expression}': {e}")
            return None

    def _get_schedule_description(self, expression: str) -> str:
        """
        Get human-readable description of a cron schedule.

        Args:
            expression: Cron expression

        Returns:
            Human-readable description
        """
        try:
            parts = expression.split()
            if len(parts) != 5:
                return expression

            minute, hour, day, month, weekday = parts

            # Common patterns
            if expression == "0 * * * *":
                return "Every hour"
            elif minute == "0" and hour != "*" and day == "*" and month == "*" and weekday == "*":
                return f"Daily at {hour}:00 UTC"
            elif minute == "0" and hour != "*" and weekday == "0" and day == "*" and month == "*":
                return f"Weekly on Sunday at {hour}:00 UTC"
            elif minute == "0" and hour != "*" and day == "1" and month == "*" and weekday == "*":
                return f"Monthly on the 1st at {hour}:00 UTC"
            else:
                return expression
        except Exception:
            return expression

    # =========================================================================
    # Task Run History
    # =========================================================================

    async def get_task_runs(
        self,
        session: AsyncSession,
        task_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Run]:
        """
        Get recent runs for a scheduled task.

        Args:
            session: Database session
            task_id: Task UUID
            limit: Maximum runs to return
            offset: Number of runs to skip

        Returns:
            List of Run objects
        """
        from sqlalchemy import func, cast, String

        task = await self.get_task(session, task_id)
        if not task:
            return []

        # Find runs that were created for this task
        # PostgreSQL JSON: column["key"].astext
        result = await session.execute(
            select(Run)
            .where(
                and_(
                    Run.run_type == "system_maintenance",
                    Run.config["scheduled_task_id"].astext == str(task_id),
                )
            )
            .order_by(Run.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_maintenance_stats(
        self,
        session: AsyncSession,
        days: int = 7,
    ) -> Dict[str, Any]:
        """
        Get maintenance task statistics.

        Args:
            session: Database session
            days: Number of days to look back

        Returns:
            Dict with task counts, run counts, success rates
        """
        from sqlalchemy import func

        # Count tasks
        total_tasks_result = await session.execute(
            select(func.count(ScheduledTask.id))
        )
        total_tasks = total_tasks_result.scalar() or 0

        enabled_tasks_result = await session.execute(
            select(func.count(ScheduledTask.id))
            .where(ScheduledTask.enabled == True)
        )
        enabled_tasks = enabled_tasks_result.scalar() or 0

        # Count runs in time period
        cutoff = datetime.utcnow() - timedelta(days=days)

        total_runs_result = await session.execute(
            select(func.count(Run.id))
            .where(
                and_(
                    Run.run_type == "system_maintenance",
                    Run.created_at >= cutoff,
                )
            )
        )
        total_runs = total_runs_result.scalar() or 0

        successful_runs_result = await session.execute(
            select(func.count(Run.id))
            .where(
                and_(
                    Run.run_type == "system_maintenance",
                    Run.status == "completed",
                    Run.created_at >= cutoff,
                )
            )
        )
        successful_runs = successful_runs_result.scalar() or 0

        failed_runs_result = await session.execute(
            select(func.count(Run.id))
            .where(
                and_(
                    Run.run_type == "system_maintenance",
                    Run.status == "failed",
                    Run.created_at >= cutoff,
                )
            )
        )
        failed_runs = failed_runs_result.scalar() or 0

        # Get last run
        last_run_result = await session.execute(
            select(Run)
            .where(Run.run_type == "system_maintenance")
            .order_by(Run.created_at.desc())
            .limit(1)
        )
        last_run = last_run_result.scalar_one_or_none()

        return {
            "total_tasks": total_tasks,
            "enabled_tasks": enabled_tasks,
            "disabled_tasks": total_tasks - enabled_tasks,
            "total_runs": total_runs,
            "successful_runs": successful_runs,
            "failed_runs": failed_runs,
            "success_rate": (successful_runs / total_runs * 100) if total_runs > 0 else 0,
            "last_run_at": last_run.created_at.isoformat() if last_run else None,
            "last_run_status": last_run.status if last_run else None,
            "period_days": days,
        }


# Global singleton instance
scheduled_task_service = ScheduledTaskService()
