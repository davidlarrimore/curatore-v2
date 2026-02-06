"""
Heartbeat service for long-running tasks.

Provides a simple mechanism for tasks to signal they're still alive by updating
the last_activity_at timestamp on their Run record. This enables reliable
stale job detection.

Usage in tasks:
    from app.services.heartbeat_service import heartbeat_service

    # Simple heartbeat
    await heartbeat_service.beat(session, run_id)

    # Heartbeat with progress update
    await heartbeat_service.beat(session, run_id, progress={"processed": 50, "total": 100})

    # Context manager for periodic heartbeats (async)
    async with heartbeat_service.auto_heartbeat(session, run_id, interval=30):
        # Do long-running work - heartbeat happens automatically every 30s
        await do_work()
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import Run

logger = logging.getLogger("curatore.services.heartbeat")


class HeartbeatService:
    """
    Service for managing task heartbeats.

    Heartbeats update the last_activity_at timestamp on Run records,
    enabling the timeout checker to distinguish between:
    - Active jobs (recent heartbeat)
    - Stale jobs (no heartbeat for 2+ minutes)
    - Dead jobs (no heartbeat for 5+ minutes)
    """

    # Heartbeat interval in seconds (how often tasks should call beat())
    DEFAULT_INTERVAL = 30

    # Stale threshold in seconds (job shows warning after this)
    STALE_THRESHOLD_SECONDS = 120  # 2 minutes

    # Timeout threshold in seconds (job marked timed_out after this)
    TIMEOUT_THRESHOLD_SECONDS = 300  # 5 minutes

    async def beat(
        self,
        session: AsyncSession,
        run_id: UUID,
        progress: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ) -> bool:
        """
        Send a heartbeat for a run.

        Updates last_activity_at to now. Optionally updates progress info.

        Args:
            session: Database session
            run_id: The run ID to heartbeat
            progress: Optional progress dict to store (e.g., {"processed": 50, "total": 100})
            message: Optional log message

        Returns:
            True if heartbeat was recorded, False if run not found or not running
        """
        try:
            update_values = {"last_activity_at": datetime.utcnow()}

            if progress is not None:
                update_values["progress"] = progress

            result = await session.execute(
                update(Run)
                .where(Run.id == run_id)
                .where(Run.status.in_(["running", "submitted"]))
                .values(**update_values)
            )

            if result.rowcount > 0:
                await session.commit()
                logger.debug(f"Heartbeat for run {run_id}")
                return True
            else:
                logger.debug(f"No heartbeat - run {run_id} not found or not running")
                return False

        except Exception as e:
            logger.warning(f"Failed to send heartbeat for run {run_id}: {e}")
            return False

    async def beat_sync(
        self,
        run_id: UUID,
        progress: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Send a heartbeat using a new database session.

        Use this when you don't have access to the current session,
        or when the session might be in a transaction.
        """
        from .database_service import database_service

        async with database_service.get_session() as session:
            return await self.beat(session, run_id, progress)

    @asynccontextmanager
    async def auto_heartbeat(
        self,
        session: AsyncSession,
        run_id: UUID,
        interval: int = DEFAULT_INTERVAL,
    ):
        """
        Context manager that automatically sends heartbeats at a regular interval.

        Usage:
            async with heartbeat_service.auto_heartbeat(session, run_id):
                # Do long-running work
                await process_files()

        Args:
            session: Database session
            run_id: The run ID to heartbeat
            interval: Seconds between heartbeats (default: 30)
        """
        stop_event = asyncio.Event()

        async def heartbeat_loop():
            while not stop_event.is_set():
                try:
                    await asyncio.sleep(interval)
                    if not stop_event.is_set():
                        # Use a fresh session for heartbeats to avoid transaction issues
                        await self.beat_sync(run_id)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning(f"Auto-heartbeat error for run {run_id}: {e}")

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(heartbeat_loop())

        try:
            yield
        finally:
            # Stop heartbeat task
            stop_event.set()
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass


# Singleton instance
heartbeat_service = HeartbeatService()
