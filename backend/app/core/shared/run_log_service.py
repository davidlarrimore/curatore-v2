"""
Run Log Service for Structured Run Logging.

Provides operations for the RunLogEvent model, which tracks structured
log events for runs. Replaces ad-hoc logging with queryable, UI-friendly
event tracking in Phase 0 architecture.

Usage:
    from app.core.shared.run_log_service import run_log_service

    # Log run start
    await run_log_service.log_start(
        session=session,
        run_id=run_id,
        message="Extraction started for 10 documents",
    )

    # Log progress
    await run_log_service.log_progress(
        session=session,
        run_id=run_id,
        current=5,
        total=10,
        unit="documents",
        message="Processed 5 of 10 documents",
    )

    # Log error
    await run_log_service.log_error(
        session=session,
        run_id=run_id,
        message="Failed to extract document",
        context={"document_id": "123", "error": "Unsupported format"},
    )
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database.models import Run, RunLogEvent

logger = logging.getLogger("curatore.run_log_service")


class RunLogService:
    """
    Service for managing RunLogEvent records in the database.

    Provides structured logging for runs with queryable events and
    machine-readable context. Used by UI to display timelines and
    by system for debugging and auditing.
    """

    # =========================================================================
    # CREATE OPERATIONS
    # =========================================================================

    async def log_event(
        self,
        session: AsyncSession,
        run_id: UUID,
        level: str,
        event_type: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RunLogEvent:
        """
        Create a structured log event for a run.

        Args:
            session: Database session
            run_id: Run UUID
            level: Log level (INFO, WARN, ERROR)
            event_type: Event classification (start, progress, retry, error, summary)
            message: Human-readable message
            context: Machine-readable context dict

        Returns:
            Created RunLogEvent instance
        """
        event = RunLogEvent(
            run_id=run_id,
            level=level,
            event_type=event_type,
            message=message,
            context=context,
        )

        session.add(event)

        # Update run's last_activity_at for activity-based timeout tracking
        run = await session.get(Run, run_id)
        if run and run.status in ("submitted", "running"):
            run.last_activity_at = datetime.utcnow()

        await session.commit()
        await session.refresh(event)

        # Also log to application logger at appropriate level
        log_func = {
            "INFO": logger.info,
            "WARN": logger.warning,
            "ERROR": logger.error,
        }.get(level, logger.info)

        log_func(f"[Run {run_id}] {message}")

        # Publish log event to WebSocket clients via pub/sub
        if run and run.organization_id:
            self._publish_log_event(
                organization_id=run.organization_id,
                event=event,
                run_id=run_id,
            )

        return event

    def _publish_log_event(
        self,
        organization_id: UUID,
        event: RunLogEvent,
        run_id: UUID,
    ) -> None:
        """
        Publish a run_log event to Redis pub/sub for WebSocket clients.

        Fire-and-forget - failures are logged but don't affect logging.
        """
        try:
            from .pubsub_service import pubsub_service

            payload = {
                "id": str(event.id),
                "run_id": str(run_id),
                "level": event.level,
                "event_type": event.event_type,
                "message": event.message,
                "context": event.context,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }

            asyncio.create_task(
                pubsub_service.publish_job_update(
                    organization_id=organization_id,
                    event_type="run_log",
                    payload=payload,
                )
            )
        except Exception as e:
            logger.debug(f"Failed to publish run_log event: {e}")

    # =========================================================================
    # CONVENIENCE LOGGING METHODS
    # =========================================================================

    async def log_start(
        self,
        session: AsyncSession,
        run_id: UUID,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RunLogEvent:
        """
        Log run start event.

        Args:
            session: Database session
            run_id: Run UUID
            message: Start message
            context: Optional context

        Returns:
            Created RunLogEvent instance
        """
        return await self.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="start",
            message=message,
            context=context,
        )

    async def log_progress(
        self,
        session: AsyncSession,
        run_id: UUID,
        current: int,
        total: Optional[int],
        unit: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RunLogEvent:
        """
        Log progress event with structured progress info.

        Args:
            session: Database session
            run_id: Run UUID
            current: Current progress value
            total: Total items (None if unknown)
            unit: Progress unit
            message: Progress message
            context: Optional additional context

        Returns:
            Created RunLogEvent instance
        """
        progress_context = {
            "current": current,
            "total": total,
            "unit": unit,
            **(context or {}),
        }

        return await self.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="progress",
            message=message,
            context=progress_context,
        )

    async def log_error(
        self,
        session: AsyncSession,
        run_id: UUID,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RunLogEvent:
        """
        Log error event.

        Args:
            session: Database session
            run_id: Run UUID
            message: Error message
            context: Error context (error type, document_id, etc.)

        Returns:
            Created RunLogEvent instance
        """
        return await self.log_event(
            session=session,
            run_id=run_id,
            level="ERROR",
            event_type="error",
            message=message,
            context=context,
        )

    async def log_warning(
        self,
        session: AsyncSession,
        run_id: UUID,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RunLogEvent:
        """
        Log warning event.

        Args:
            session: Database session
            run_id: Run UUID
            message: Warning message
            context: Warning context

        Returns:
            Created RunLogEvent instance
        """
        return await self.log_event(
            session=session,
            run_id=run_id,
            level="WARN",
            event_type="error",  # Warnings use "error" event_type with WARN level
            message=message,
            context=context,
        )

    async def log_retry(
        self,
        session: AsyncSession,
        run_id: UUID,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RunLogEvent:
        """
        Log retry event.

        Args:
            session: Database session
            run_id: Run UUID
            message: Retry message
            context: Retry context (attempt number, reason, etc.)

        Returns:
            Created RunLogEvent instance
        """
        return await self.log_event(
            session=session,
            run_id=run_id,
            level="WARN",
            event_type="retry",
            message=message,
            context=context,
        )

    async def log_summary(
        self,
        session: AsyncSession,
        run_id: UUID,
        message: str,
        context: Dict[str, Any],
    ) -> RunLogEvent:
        """
        Log summary event (typically at run completion).

        Used for maintenance runs to report counts, or for any run
        to provide a final summary of what was accomplished.

        Args:
            session: Database session
            run_id: Run UUID
            message: Summary message
            context: Summary data (counts, metrics, etc.)

        Returns:
            Created RunLogEvent instance
        """
        return await self.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="summary",
            message=message,
            context=context,
        )

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    async def get_events_for_run(
        self,
        session: AsyncSession,
        run_id: UUID,
        level: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[RunLogEvent]:
        """
        Get log events for a run with optional filters.

        Args:
            session: Database session
            run_id: Run UUID
            level: Filter by level (INFO, WARN, ERROR)
            event_type: Filter by event type
            limit: Maximum results to return

        Returns:
            List of RunLogEvent instances (ordered by created_at asc)
        """
        query = select(RunLogEvent).where(RunLogEvent.run_id == run_id)

        if level:
            query = query.where(RunLogEvent.level == level)

        if event_type:
            query = query.where(RunLogEvent.event_type == event_type)

        query = query.order_by(RunLogEvent.created_at.asc())

        if limit:
            query = query.limit(limit)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_latest_events_for_run(
        self,
        session: AsyncSession,
        run_id: UUID,
        limit: int = 10,
    ) -> List[RunLogEvent]:
        """
        Get the most recent log events for a run.

        Args:
            session: Database session
            run_id: Run UUID
            limit: Number of recent events to return

        Returns:
            List of recent RunLogEvent instances (ordered by created_at desc)
        """
        result = await session.execute(
            select(RunLogEvent)
            .where(RunLogEvent.run_id == run_id)
            .order_by(RunLogEvent.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_errors_for_run(
        self,
        session: AsyncSession,
        run_id: UUID,
    ) -> List[RunLogEvent]:
        """
        Get all error events for a run.

        Args:
            session: Database session
            run_id: Run UUID

        Returns:
            List of error RunLogEvent instances
        """
        return await self.get_events_for_run(
            session=session,
            run_id=run_id,
            level="ERROR",
        )

    async def count_events_by_level(
        self,
        session: AsyncSession,
        run_id: UUID,
    ) -> Dict[str, int]:
        """
        Count log events by level for a run.

        Args:
            session: Database session
            run_id: Run UUID

        Returns:
            Dict mapping level to count (e.g., {"INFO": 10, "ERROR": 2})
        """
        result = await session.execute(
            select(
                RunLogEvent.level,
                func.count(RunLogEvent.id)
            )
            .where(RunLogEvent.run_id == run_id)
            .group_by(RunLogEvent.level)
        )

        return {row[0]: row[1] for row in result.all()}

    async def has_errors(
        self,
        session: AsyncSession,
        run_id: UUID,
    ) -> bool:
        """
        Check if a run has any error events.

        Args:
            session: Database session
            run_id: Run UUID

        Returns:
            True if run has errors, False otherwise
        """
        result = await session.execute(
            select(func.count(RunLogEvent.id))
            .where(
                and_(
                    RunLogEvent.run_id == run_id,
                    RunLogEvent.level == "ERROR",
                )
            )
        )
        return result.scalar_one() > 0


# Singleton instance
run_log_service = RunLogService()
