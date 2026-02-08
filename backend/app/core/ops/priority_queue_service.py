"""
Priority Queue Service for Curatore v2.

Provides a centralized, reusable abstraction for task prioritization across the platform.
This service allows any workflow to boost task priority based on user actions while
preventing system overload through rate limiting and queue monitoring.

Key Concepts:
- Priority Tiers: HIGH (user-initiated), NORMAL (background), LOW (maintenance)
- Dependency Tracking: Wait for related tasks to complete before proceeding
- Rate Limiting: Prevent priority queue abuse/overload
- Visibility: Track boosted tasks for debugging and monitoring

Usage Examples:
    # Boost extraction for a specific asset
    await priority_service.boost_extraction(asset_id, reason="user_requested")

    # Boost all extractions for a solicitation's attachments
    pending = await priority_service.boost_related_extractions(
        asset_ids=[...],
        reason="sam_summarization",
        callback_task="sam_auto_summarize_task",
        callback_kwargs={...}
    )

    # Check if assets are ready for processing
    ready = await priority_service.check_assets_ready(asset_ids)
"""

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database.models import Asset, Run, ExtractionResult, SamAttachment

logger = logging.getLogger("curatore.priority")


class PriorityTier(str, Enum):
    """Task priority tiers mapped to Celery queues."""
    HIGH = "processing_priority"      # User-initiated, time-sensitive
    NORMAL = "extraction"             # Default extraction queue
    LOW = "maintenance"               # Scheduled maintenance, cleanup


class BoostReason(str, Enum):
    """Reasons for priority boost - used for tracking and analytics."""
    USER_REQUESTED = "user_requested"           # Manual user action
    SAM_SUMMARIZATION = "sam_summarization"     # SAM AI summary generation
    DOCUMENT_PREVIEW = "document_preview"       # User viewing document
    EXPORT_REQUESTED = "export_requested"       # User exporting documents
    SEARCH_INDEXING = "search_indexing"         # Search result needs content
    RETRY_FAILED = "retry_failed"               # Retrying failed extraction
    DEPENDENCY_CHAIN = "dependency_chain"       # Part of a dependency chain


class PriorityQueueService:
    """
    Centralized service for managing task prioritization.

    This service provides:
    1. Priority boosting for extraction tasks
    2. Dependency tracking and waiting
    3. Rate limiting to prevent queue abuse
    4. Monitoring and analytics

    Architecture:
    - Uses Redis-backed Celery queues with priority ordering
    - Workers consume queues left-to-right: priority > normal > maintenance
    - Boosting re-queues a task on the priority queue
    """

    # Rate limiting: max boosts per minute per organization
    MAX_BOOSTS_PER_MINUTE = 50

    # Tracking: keep boost history for analytics
    _boost_history: Dict[str, List[datetime]] = {}

    async def boost_extraction(
        self,
        session: AsyncSession,
        asset_id: UUID,
        reason: BoostReason = BoostReason.USER_REQUESTED,
        organization_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Boost priority for a single asset's extraction.

        If the asset has a pending extraction, re-queues it on the priority queue.
        If already completed or failed, returns appropriate status.

        Args:
            session: Database session
            asset_id: Asset to boost
            reason: Why the boost is happening (for analytics)
            organization_id: For rate limiting (optional)

        Returns:
            Dict with status and details:
            - status: "boosted", "already_ready", "already_failed", "not_found"
            - asset_id: The asset UUID
            - queue: Queue the task was sent to (if boosted)
        """
        # Check rate limiting
        if organization_id and not self._check_rate_limit(organization_id):
            logger.warning(f"Rate limit exceeded for org {organization_id}")
            return {
                "status": "rate_limited",
                "asset_id": str(asset_id),
                "message": "Too many priority boosts, please wait",
            }

        # Get asset status
        asset = await session.get(Asset, asset_id)
        if not asset:
            return {"status": "not_found", "asset_id": str(asset_id)}

        if asset.status == "ready":
            return {"status": "already_ready", "asset_id": str(asset_id)}

        if asset.status == "failed":
            return {"status": "already_failed", "asset_id": str(asset_id)}

        # Find pending extraction run
        run_result = await session.execute(
            select(Run)
            .where(and_(
                Run.run_type == "extraction",
                Run.status.in_(["pending", "running"]),
                Run.input_asset_ids.contains([str(asset_id)])
            ))
            .order_by(Run.created_at.desc())
            .limit(1)
        )
        run = run_result.scalar_one_or_none()

        if not run:
            logger.info(f"No pending run found for asset {asset_id}, may need to create one")
            return {
                "status": "no_pending_run",
                "asset_id": str(asset_id),
                "message": "No pending extraction found",
            }

        # Find extraction result
        ext_result = await session.execute(
            select(ExtractionResult)
            .where(and_(
                ExtractionResult.run_id == run.id,
                ExtractionResult.asset_id == asset_id,
                ExtractionResult.status.in_(["pending", "running"])
            ))
            .limit(1)
        )
        extraction = ext_result.scalar_one_or_none()

        if not extraction:
            return {
                "status": "no_extraction",
                "asset_id": str(asset_id),
                "message": "No extraction record found",
            }

        # Re-queue on priority queue
        from app.core.tasks import execute_extraction_task

        execute_extraction_task.apply_async(
            kwargs={
                "asset_id": str(asset_id),
                "run_id": str(run.id),
                "extraction_id": str(extraction.id),
            },
            queue=PriorityTier.HIGH.value,
        )

        # Track boost for analytics
        self._record_boost(organization_id, asset_id, reason)

        logger.info(
            f"Boosted extraction priority for asset {asset_id} "
            f"(reason: {reason.value}, run: {run.id})"
        )

        return {
            "status": "boosted",
            "asset_id": str(asset_id),
            "run_id": str(run.id),
            "queue": PriorityTier.HIGH.value,
            "reason": reason.value,
        }

    async def boost_multiple_extractions(
        self,
        session: AsyncSession,
        asset_ids: List[UUID],
        reason: BoostReason = BoostReason.USER_REQUESTED,
        organization_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Boost priority for multiple assets.

        Args:
            session: Database session
            asset_ids: List of asset UUIDs to boost
            reason: Why the boost is happening
            organization_id: For rate limiting

        Returns:
            Dict with aggregate results and per-asset details
        """
        results = []
        boosted = 0
        already_ready = 0
        failed = 0

        for asset_id in asset_ids:
            result = await self.boost_extraction(
                session=session,
                asset_id=asset_id,
                reason=reason,
                organization_id=organization_id,
            )
            results.append(result)

            if result["status"] == "boosted":
                boosted += 1
            elif result["status"] == "already_ready":
                already_ready += 1
            elif result["status"] in ("already_failed", "rate_limited"):
                failed += 1

        return {
            "total": len(asset_ids),
            "boosted": boosted,
            "already_ready": already_ready,
            "failed": failed,
            "details": results,
        }

    async def boost_related_extractions(
        self,
        session: AsyncSession,
        asset_ids: List[UUID],
        reason: BoostReason,
        organization_id: UUID,
        callback_task: Optional[str] = None,
        callback_kwargs: Optional[Dict[str, Any]] = None,
        max_wait_seconds: int = 300,
    ) -> Dict[str, Any]:
        """
        Boost extractions for related assets and optionally schedule a callback.

        This is the main method for dependency chains - boost all related assets
        and schedule a follow-up task to run once they're ready.

        Args:
            session: Database session
            asset_ids: Assets that need to be ready
            reason: Why the boost is happening
            organization_id: Organization context
            callback_task: Task name to call when assets are ready (optional)
            callback_kwargs: Arguments for callback task
            max_wait_seconds: Maximum time to wait for assets

        Returns:
            Dict with boost results and callback info
        """
        # Check which assets are pending
        pending_ids = await self.get_pending_asset_ids(session, asset_ids)

        if not pending_ids:
            return {
                "status": "all_ready",
                "pending_count": 0,
                "boosted_count": 0,
            }

        # Boost pending assets
        boost_result = await self.boost_multiple_extractions(
            session=session,
            asset_ids=pending_ids,
            reason=reason,
            organization_id=organization_id,
        )

        # Schedule callback if provided
        if callback_task and callback_kwargs:
            from celery import current_app

            # Add metadata to callback for dependency tracking
            callback_kwargs["_priority_boost"] = {
                "reason": reason.value,
                "pending_assets": [str(aid) for aid in pending_ids],
                "boosted_at": datetime.utcnow().isoformat(),
                "max_wait_seconds": max_wait_seconds,
            }

            # Schedule callback with delay to allow extractions to complete
            current_app.send_task(
                callback_task,
                kwargs=callback_kwargs,
                countdown=30,  # Check again in 30 seconds
                queue=PriorityTier.HIGH.value,
            )

            logger.info(
                f"Boosted {boost_result['boosted']} extractions and scheduled "
                f"callback {callback_task} (reason: {reason.value})"
            )

        return {
            "status": "boosted_with_callback" if callback_task else "boosted",
            "pending_count": len(pending_ids),
            "boosted_count": boost_result["boosted"],
            "already_ready_count": boost_result["already_ready"],
            "callback_task": callback_task,
            "boost_details": boost_result,
        }

    async def get_pending_asset_ids(
        self,
        session: AsyncSession,
        asset_ids: List[UUID],
    ) -> List[UUID]:
        """
        Filter asset IDs to only those with pending status.

        Args:
            session: Database session
            asset_ids: Asset IDs to check

        Returns:
            List of asset IDs that are still pending
        """
        if not asset_ids:
            return []

        result = await session.execute(
            select(Asset.id)
            .where(and_(
                Asset.id.in_(asset_ids),
                Asset.status.in_(["pending", "extracting"])
            ))
        )
        return [row[0] for row in result.fetchall()]

    async def check_assets_ready(
        self,
        session: AsyncSession,
        asset_ids: List[UUID],
    ) -> Tuple[bool, List[UUID], List[UUID]]:
        """
        Check if all specified assets are ready.

        Args:
            session: Database session
            asset_ids: Asset IDs to check

        Returns:
            Tuple of (all_ready, ready_ids, pending_ids)
        """
        if not asset_ids:
            return True, [], []

        result = await session.execute(
            select(Asset.id, Asset.status)
            .where(Asset.id.in_(asset_ids))
        )

        ready_ids = []
        pending_ids = []

        for asset_id, status in result.fetchall():
            if status == "ready":
                ready_ids.append(asset_id)
            elif status in ("pending", "extracting"):
                pending_ids.append(asset_id)
            # Failed assets are not pending but also not ready

        all_ready = len(pending_ids) == 0
        return all_ready, ready_ids, pending_ids

    async def get_solicitation_attachment_assets(
        self,
        session: AsyncSession,
        solicitation_id: UUID,
    ) -> List[UUID]:
        """
        Get asset IDs for all attachments of a solicitation.

        Args:
            session: Database session
            solicitation_id: SAM solicitation ID

        Returns:
            List of asset IDs (only those that have been downloaded)
        """
        result = await session.execute(
            select(SamAttachment.asset_id)
            .where(and_(
                SamAttachment.solicitation_id == solicitation_id,
                SamAttachment.asset_id.isnot(None)
            ))
        )
        return [row[0] for row in result.fetchall()]

    async def get_queue_stats(self) -> Dict[str, int]:
        """
        Get current queue lengths for monitoring.

        Returns:
            Dict mapping queue names to lengths
        """
        try:
            import redis
            r = redis.Redis(host='redis', port=6379, db=0)
            return {
                PriorityTier.HIGH.value: r.llen(PriorityTier.HIGH.value),
                PriorityTier.NORMAL.value: r.llen(PriorityTier.NORMAL.value),
                PriorityTier.LOW.value: r.llen(PriorityTier.LOW.value),
            }
        except Exception as e:
            logger.error(f"Failed to get queue stats: {e}")
            return {
                PriorityTier.HIGH.value: -1,
                PriorityTier.NORMAL.value: -1,
                PriorityTier.LOW.value: -1,
            }

    async def get_asset_queue_info(
        self,
        session: AsyncSession,
        asset_id: UUID,
    ) -> Dict[str, Any]:
        """
        Get queue position and extraction info for a specific asset.

        Returns information about:
        - Current extraction status
        - Queue position (if pending)
        - Extraction service being used
        - Total items in queue

        Args:
            session: Database session
            asset_id: Asset UUID to check

        Returns:
            Dict with queue position and extraction info
        """
        # Get asset
        asset = await session.get(Asset, asset_id)
        if not asset:
            return {"status": "not_found", "asset_id": str(asset_id)}

        # If asset is already ready or failed, no queue info needed
        if asset.status == "ready":
            return {
                "status": "ready",
                "asset_id": str(asset_id),
                "in_queue": False,
            }

        if asset.status == "failed":
            return {
                "status": "failed",
                "asset_id": str(asset_id),
                "in_queue": False,
            }

        # Find the pending/running extraction run
        run_result = await session.execute(
            select(Run)
            .where(and_(
                Run.run_type == "extraction",
                Run.status.in_(["pending", "running"]),
                Run.input_asset_ids.contains([str(asset_id)])
            ))
            .order_by(Run.created_at.desc())
            .limit(1)
        )
        run = run_result.scalar_one_or_none()

        if not run:
            return {
                "status": "pending",
                "asset_id": str(asset_id),
                "in_queue": False,
                "message": "No active extraction run found",
            }

        # Get extraction result to find extractor version
        ext_result = await session.execute(
            select(ExtractionResult)
            .where(and_(
                ExtractionResult.run_id == run.id,
                ExtractionResult.asset_id == asset_id,
            ))
            .limit(1)
        )
        extraction = ext_result.scalar_one_or_none()

        extractor_version = None
        if extraction:
            extractor_version = extraction.extractor_version
        elif run.config:
            extractor_version = run.config.get("extractor_version")

        # Get queue stats
        queue_stats = await self.get_queue_stats()

        # Count pending extraction runs to estimate position
        # We count runs created before this one that are still pending
        position_result = await session.execute(
            select(func.count(Run.id))
            .where(and_(
                Run.run_type == "extraction",
                Run.status == "pending",
                Run.created_at <= run.created_at,
            ))
        )
        queue_position = position_result.scalar() or 1

        # Total pending extractions in organization
        total_result = await session.execute(
            select(func.count(Run.id))
            .where(and_(
                Run.run_type == "extraction",
                Run.status.in_(["pending", "running"]),
                Run.organization_id == asset.organization_id,
            ))
        )
        total_pending = total_result.scalar() or 0

        return {
            "status": "processing" if run.status == "running" else "queued",
            "asset_id": str(asset_id),
            "run_id": str(run.id),
            "run_status": run.status,
            "in_queue": True,
            "queue_position": queue_position,
            "total_pending": total_pending,
            "extractor_version": extractor_version,
            "queue_stats": queue_stats,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
        }

    def _check_rate_limit(self, organization_id: UUID) -> bool:
        """
        Check if organization has exceeded boost rate limit.

        Returns True if boost is allowed, False if rate limited.
        """
        org_key = str(organization_id)
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=1)

        # Clean old entries
        if org_key in self._boost_history:
            self._boost_history[org_key] = [
                ts for ts in self._boost_history[org_key]
                if ts > cutoff
            ]
        else:
            self._boost_history[org_key] = []

        # Check limit
        return len(self._boost_history[org_key]) < self.MAX_BOOSTS_PER_MINUTE

    def _record_boost(
        self,
        organization_id: Optional[UUID],
        asset_id: UUID,
        reason: BoostReason,
    ) -> None:
        """Record a boost for rate limiting and analytics."""
        if organization_id:
            org_key = str(organization_id)
            if org_key not in self._boost_history:
                self._boost_history[org_key] = []
            self._boost_history[org_key].append(datetime.utcnow())

        # Could also log to database for long-term analytics
        logger.debug(f"Recorded boost: asset={asset_id}, reason={reason.value}")


# Global singleton instance
priority_queue_service = PriorityQueueService()
