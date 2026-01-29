# ============================================================================
# Curatore v2 - SAM.gov API Usage Tracking Service
# ============================================================================
"""
Service for tracking SAM.gov API usage and managing rate limits.

SAM.gov enforces a 1,000 API calls per day limit. This service:
- Tracks API calls by type (search, detail, attachment)
- Checks remaining quota before making calls
- Queues requests when over limit for next-day execution
- Provides usage statistics for the UI

Usage:
    from app.services.sam_api_usage_service import sam_api_usage_service

    # Check if we can make an API call
    can_call, remaining = await sam_api_usage_service.check_limit(session, org_id)

    # Record an API call
    await sam_api_usage_service.record_call(session, org_id, "search", count=1)

    # Get today's usage
    usage = await sam_api_usage_service.get_usage(session, org_id)

    # Queue a request for later
    await sam_api_usage_service.queue_request(session, org_id, "search", params)
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import SamApiUsage, SamQueuedRequest

logger = logging.getLogger(__name__)

# EST timezone (UTC-5) - SAM.gov resets at midnight EST
# Note: This is EST, not EDT. SAM.gov uses fixed EST offset.
EST_OFFSET = timezone(timedelta(hours=-5))


def get_current_est_date() -> date:
    """Get the current date in EST timezone."""
    return datetime.now(EST_OFFSET).date()


def get_next_est_midnight_utc() -> datetime:
    """
    Get the next midnight EST as a UTC datetime.

    SAM.gov API limits reset at 12:00am EST. This function returns
    when that next reset will occur, expressed in UTC.
    """
    now_est = datetime.now(EST_OFFSET)
    # Tomorrow at midnight EST
    tomorrow_midnight_est = datetime.combine(
        now_est.date() + timedelta(days=1),
        datetime.min.time(),
        tzinfo=EST_OFFSET
    )
    # Convert to UTC (remove timezone info for storage)
    return tomorrow_midnight_est.astimezone(timezone.utc).replace(tzinfo=None)

# Default daily limit (can be overridden per organization)
DEFAULT_DAILY_LIMIT = 1000


class SamApiUsageService:
    """
    Service for tracking and managing SAM.gov API rate limits.

    Provides methods to:
    - Track API calls by type
    - Check remaining quota
    - Queue requests when over limit
    - Process queued requests
    - Get usage statistics
    """

    async def get_or_create_usage(
        self,
        session: AsyncSession,
        organization_id: UUID,
        for_date: Optional[date] = None,
    ) -> SamApiUsage:
        """
        Get or create a usage record for the given date.

        Args:
            session: Database session
            organization_id: Organization ID
            for_date: Date to get usage for (defaults to today in EST)

        Returns:
            SamApiUsage record for the date

        Note:
            SAM.gov API limits reset at 12:00am EST, so we track usage
            by EST date rather than UTC date.
        """
        if for_date is None:
            # Use EST date since SAM.gov resets at midnight EST
            for_date = get_current_est_date()

        # Try to find existing record
        result = await session.execute(
            select(SamApiUsage).where(
                and_(
                    SamApiUsage.organization_id == organization_id,
                    SamApiUsage.date == for_date,
                )
            )
        )
        usage = result.scalar_one_or_none()

        if usage:
            return usage

        # Create new record for today
        # Reset time is next midnight EST (expressed in UTC)
        reset_at = get_next_est_midnight_utc()
        usage = SamApiUsage(
            organization_id=organization_id,
            date=for_date,
            search_calls=0,
            detail_calls=0,
            attachment_calls=0,
            total_calls=0,
            daily_limit=DEFAULT_DAILY_LIMIT,
            reset_at=reset_at,
        )
        session.add(usage)
        await session.flush()

        logger.info(
            f"Created new API usage record for org {organization_id} on {for_date} (EST), "
            f"resets at {reset_at} UTC"
        )
        return usage

    async def check_limit(
        self,
        session: AsyncSession,
        organization_id: UUID,
        required_calls: int = 1,
    ) -> Tuple[bool, int]:
        """
        Check if we have enough API quota remaining.

        Args:
            session: Database session
            organization_id: Organization ID
            required_calls: Number of calls we want to make

        Returns:
            Tuple of (can_make_calls, remaining_calls)
        """
        usage = await self.get_or_create_usage(session, organization_id)
        remaining = usage.remaining_calls

        can_call = remaining >= required_calls

        if not can_call:
            logger.warning(
                f"API limit check failed for org {organization_id}: "
                f"need {required_calls}, have {remaining} remaining"
            )

        return can_call, remaining

    async def record_call(
        self,
        session: AsyncSession,
        organization_id: UUID,
        call_type: str,
        count: int = 1,
    ) -> SamApiUsage:
        """
        Record API call(s) made.

        Args:
            session: Database session
            organization_id: Organization ID
            call_type: Type of call ("search", "detail", "attachment")
            count: Number of calls made

        Returns:
            Updated usage record
        """
        usage = await self.get_or_create_usage(session, organization_id)

        # Increment appropriate counter
        if call_type == "search":
            usage.search_calls += count
        elif call_type == "detail":
            usage.detail_calls += count
        elif call_type == "attachment":
            usage.attachment_calls += count
        else:
            logger.warning(f"Unknown call type: {call_type}")

        # Update total
        usage.total_calls += count

        await session.flush()

        logger.debug(
            f"Recorded {count} {call_type} call(s) for org {organization_id}. "
            f"Total: {usage.total_calls}/{usage.daily_limit}"
        )

        return usage

    async def get_usage(
        self,
        session: AsyncSession,
        organization_id: UUID,
        for_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Get usage statistics for display.

        Args:
            session: Database session
            organization_id: Organization ID
            for_date: Date to get usage for (defaults to today)

        Returns:
            Dictionary with usage statistics
        """
        usage = await self.get_or_create_usage(session, organization_id, for_date)

        return {
            "date": usage.date.isoformat(),
            "date_timezone": "EST",  # SAM.gov uses EST for daily limits
            "search_calls": usage.search_calls,
            "detail_calls": usage.detail_calls,
            "attachment_calls": usage.attachment_calls,
            "total_calls": usage.total_calls,
            "daily_limit": usage.daily_limit,
            "remaining_calls": usage.remaining_calls,
            "usage_percent": round(usage.usage_percent, 1),
            "reset_at": usage.reset_at.isoformat() + "Z",  # UTC time
            "reset_at_est": "12:00 AM EST",  # Human-readable
            "is_over_limit": usage.total_calls >= usage.daily_limit,
        }

    async def get_usage_history(
        self,
        session: AsyncSession,
        organization_id: UUID,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Get usage history for the past N days.

        Args:
            session: Database session
            organization_id: Organization ID
            days: Number of days of history

        Returns:
            List of daily usage records
        """
        # Use EST date for consistency with SAM.gov's reset time
        start_date = get_current_est_date() - timedelta(days=days)

        result = await session.execute(
            select(SamApiUsage)
            .where(
                and_(
                    SamApiUsage.organization_id == organization_id,
                    SamApiUsage.date >= start_date,
                )
            )
            .order_by(SamApiUsage.date.desc())
        )
        records = result.scalars().all()

        return [
            {
                "date": r.date.isoformat(),
                "search_calls": r.search_calls,
                "detail_calls": r.detail_calls,
                "attachment_calls": r.attachment_calls,
                "total_calls": r.total_calls,
                "daily_limit": r.daily_limit,
                "usage_percent": round(r.usage_percent, 1),
            }
            for r in records
        ]

    async def estimate_impact(
        self,
        session: AsyncSession,
        organization_id: UUID,
        search_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Estimate the API impact of a search configuration.

        This helps users understand how many API calls their search
        configuration will likely use.

        Args:
            session: Database session
            organization_id: Organization ID
            search_params: Search configuration parameters

        Returns:
            Dictionary with estimated impact
        """
        usage = await self.get_or_create_usage(session, organization_id)

        # Estimate based on search parameters
        # Base search call
        estimated_calls = 1

        # If downloading attachments, estimate 2-5 attachments per result
        # and assume ~10 results per search on average
        download_attachments = search_params.get("download_attachments", False)
        if download_attachments:
            # Rough estimate: 10 results * 3 attachments average
            estimated_calls += 30

        # Factor in detail calls (one per opportunity for full data)
        max_pages = search_params.get("max_pages", 1)
        page_size = search_params.get("page_size", 10)
        max_results = max_pages * page_size
        # Assume we'll get about 50% of max results on average
        estimated_detail_calls = int(max_results * 0.5)
        estimated_calls += estimated_detail_calls

        will_exceed = (usage.total_calls + estimated_calls) > usage.daily_limit
        remaining_after = max(0, usage.remaining_calls - estimated_calls)

        return {
            "estimated_calls": estimated_calls,
            "breakdown": {
                "search_calls": 1,
                "detail_calls": estimated_detail_calls,
                "attachment_calls": 30 if download_attachments else 0,
            },
            "current_usage": usage.total_calls,
            "remaining_before": usage.remaining_calls,
            "remaining_after": remaining_after,
            "will_exceed_limit": will_exceed,
            "daily_limit": usage.daily_limit,
        }

    # =========================================================================
    # QUEUE MANAGEMENT
    # =========================================================================

    async def queue_request(
        self,
        session: AsyncSession,
        organization_id: UUID,
        request_type: str,
        request_params: Dict[str, Any],
        search_id: Optional[UUID] = None,
        solicitation_id: Optional[UUID] = None,
        attachment_id: Optional[UUID] = None,
        priority: int = 100,
    ) -> SamQueuedRequest:
        """
        Queue a request for later execution when over rate limit.

        Args:
            session: Database session
            organization_id: Organization ID
            request_type: Type of request (search, detail, attachment)
            request_params: Parameters for the request
            search_id: Related search (optional)
            solicitation_id: Related solicitation (optional)
            attachment_id: Related attachment (optional)
            priority: Priority (lower = higher priority)

        Returns:
            Created queued request
        """
        # Schedule for after daily reset (next midnight UTC)
        usage = await self.get_or_create_usage(session, organization_id)
        scheduled_for = usage.reset_at

        queued = SamQueuedRequest(
            organization_id=organization_id,
            request_type=request_type,
            status="pending",
            request_params=request_params,
            search_id=search_id,
            solicitation_id=solicitation_id,
            attachment_id=attachment_id,
            scheduled_for=scheduled_for,
            priority=priority,
        )
        session.add(queued)
        await session.flush()

        logger.info(
            f"Queued {request_type} request for org {organization_id}, "
            f"scheduled for {scheduled_for}"
        )

        return queued

    async def get_pending_requests(
        self,
        session: AsyncSession,
        organization_id: Optional[UUID] = None,
        limit: int = 100,
    ) -> List[SamQueuedRequest]:
        """
        Get pending requests that are ready to execute.

        Args:
            session: Database session
            organization_id: Filter by organization (optional)
            limit: Maximum requests to return

        Returns:
            List of pending requests ready for execution
        """
        now = datetime.utcnow()

        query = (
            select(SamQueuedRequest)
            .where(
                and_(
                    SamQueuedRequest.status == "pending",
                    SamQueuedRequest.scheduled_for <= now,
                )
            )
            .order_by(SamQueuedRequest.priority, SamQueuedRequest.scheduled_for)
            .limit(limit)
        )

        if organization_id:
            query = query.where(SamQueuedRequest.organization_id == organization_id)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def mark_request_processing(
        self,
        session: AsyncSession,
        request_id: UUID,
    ) -> Optional[SamQueuedRequest]:
        """
        Mark a queued request as processing.

        Args:
            session: Database session
            request_id: Request ID

        Returns:
            Updated request or None if not found
        """
        result = await session.execute(
            select(SamQueuedRequest).where(SamQueuedRequest.id == request_id)
        )
        request = result.scalar_one_or_none()

        if request:
            request.status = "processing"
            request.attempts += 1
            request.last_attempt_at = datetime.utcnow()
            await session.flush()

        return request

    async def mark_request_completed(
        self,
        session: AsyncSession,
        request_id: UUID,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[SamQueuedRequest]:
        """
        Mark a queued request as completed.

        Args:
            session: Database session
            request_id: Request ID
            result: Optional result data to store

        Returns:
            Updated request or None if not found
        """
        db_result = await session.execute(
            select(SamQueuedRequest).where(SamQueuedRequest.id == request_id)
        )
        request = db_result.scalar_one_or_none()

        if request:
            request.status = "completed"
            request.completed_at = datetime.utcnow()
            if result:
                request.result = result
            await session.flush()

        return request

    async def mark_request_failed(
        self,
        session: AsyncSession,
        request_id: UUID,
        error: str,
    ) -> Optional[SamQueuedRequest]:
        """
        Mark a queued request as failed.

        Args:
            session: Database session
            request_id: Request ID
            error: Error message

        Returns:
            Updated request or None if not found
        """
        result = await session.execute(
            select(SamQueuedRequest).where(SamQueuedRequest.id == request_id)
        )
        request = result.scalar_one_or_none()

        if request:
            request.last_error = error

            # Check if we should retry or mark as permanently failed
            if request.attempts >= request.max_attempts:
                request.status = "failed"
                logger.warning(
                    f"Queued request {request_id} permanently failed after "
                    f"{request.attempts} attempts: {error}"
                )
            else:
                # Reschedule for retry (with exponential backoff)
                backoff_minutes = 5 * (2 ** (request.attempts - 1))
                request.scheduled_for = datetime.utcnow() + timedelta(minutes=backoff_minutes)
                request.status = "pending"
                logger.info(
                    f"Queued request {request_id} will retry in {backoff_minutes} minutes"
                )

            await session.flush()

        return request

    async def get_queue_stats(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> Dict[str, Any]:
        """
        Get queue statistics for an organization.

        Args:
            session: Database session
            organization_id: Organization ID

        Returns:
            Dictionary with queue statistics
        """
        # Count by status
        result = await session.execute(
            select(
                SamQueuedRequest.status,
                func.count(SamQueuedRequest.id).label("count"),
            )
            .where(SamQueuedRequest.organization_id == organization_id)
            .group_by(SamQueuedRequest.status)
        )
        status_counts = {row.status: row.count for row in result}

        # Count ready to process
        now = datetime.utcnow()
        ready_result = await session.execute(
            select(func.count(SamQueuedRequest.id)).where(
                and_(
                    SamQueuedRequest.organization_id == organization_id,
                    SamQueuedRequest.status == "pending",
                    SamQueuedRequest.scheduled_for <= now,
                )
            )
        )
        ready_count = ready_result.scalar() or 0

        return {
            "pending": status_counts.get("pending", 0),
            "processing": status_counts.get("processing", 0),
            "completed": status_counts.get("completed", 0),
            "failed": status_counts.get("failed", 0),
            "ready_to_process": ready_count,
            "total": sum(status_counts.values()),
        }

    async def cleanup_old_requests(
        self,
        session: AsyncSession,
        retention_days: int = 7,
    ) -> int:
        """
        Clean up old completed/failed requests.

        Args:
            session: Database session
            retention_days: Days to retain completed requests

        Returns:
            Number of requests deleted
        """
        cutoff = datetime.utcnow() - timedelta(days=retention_days)

        result = await session.execute(
            select(SamQueuedRequest).where(
                and_(
                    SamQueuedRequest.status.in_(["completed", "failed", "cancelled"]),
                    SamQueuedRequest.updated_at < cutoff,
                )
            )
        )
        requests = result.scalars().all()

        count = len(requests)
        for req in requests:
            await session.delete(req)

        if count > 0:
            await session.flush()
            logger.info(f"Cleaned up {count} old queued requests")

        return count


# Singleton instance
sam_api_usage_service = SamApiUsageService()
