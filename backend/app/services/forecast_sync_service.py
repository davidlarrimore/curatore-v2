"""
Forecast Sync Service for Managing Acquisition Forecast Sync Configurations.

Provides CRUD operations for ForecastSync configurations, which define how to pull
acquisition forecasts from three federal sources:
- AG (GSA Acquisition Gateway)
- APFS (DHS APFS)
- State (State Department)

Similar to SamSearch for SAM.gov, ForecastSync is the top-level configuration entity.

Usage:
    from app.services.forecast_sync_service import forecast_sync_service

    # Create a sync
    sync = await forecast_sync_service.create_sync(
        session=session,
        organization_id=org_id,
        name="GSA IT Forecasts",
        source_type="ag",
        filter_config={"agency_ids": [2]},
    )

    # List syncs
    syncs, total = await forecast_sync_service.list_syncs(
        session=session,
        organization_id=org_id,
    )
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import ForecastSync

logger = logging.getLogger("curatore.forecast_sync_service")


# Valid source types
VALID_SOURCE_TYPES = {"ag", "apfs", "state"}


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:100]


class ForecastSyncService:
    """
    Service for managing ForecastSync configurations.

    Handles CRUD operations for sync configurations with organization isolation.
    """

    # =========================================================================
    # SYNC OPERATIONS
    # =========================================================================

    async def create_sync(
        self,
        session: AsyncSession,
        organization_id: UUID,
        name: str,
        source_type: str,
        filter_config: Optional[Dict[str, Any]] = None,
        sync_frequency: str = "manual",
        automation_config: Optional[Dict[str, Any]] = None,
        created_by: Optional[UUID] = None,
    ) -> ForecastSync:
        """
        Create a new forecast sync configuration.

        Args:
            session: Database session
            organization_id: Organization UUID
            name: Sync name
            source_type: Source type (ag, apfs, state)
            filter_config: Source-specific filter configuration
            sync_frequency: How often to sync (manual, hourly, daily)
            automation_config: Procedure triggers after sync
            created_by: User who created the sync

        Returns:
            Created ForecastSync instance

        Raises:
            ValueError: If source_type is invalid
        """
        if source_type not in VALID_SOURCE_TYPES:
            raise ValueError(f"Invalid source_type '{source_type}'. Must be one of: {VALID_SOURCE_TYPES}")

        slug = slugify(name)

        # Ensure slug is unique within org
        existing = await session.execute(
            select(ForecastSync).where(
                and_(
                    ForecastSync.organization_id == organization_id,
                    ForecastSync.slug == slug,
                )
            )
        )
        if existing.scalar_one_or_none():
            # Append timestamp to make unique
            slug = f"{slug}-{int(datetime.utcnow().timestamp())}"

        sync = ForecastSync(
            organization_id=organization_id,
            name=name,
            slug=slug,
            source_type=source_type,
            filter_config=filter_config or {},
            sync_frequency=sync_frequency,
            automation_config=automation_config or {},
            created_by=created_by,
        )

        session.add(sync)
        await session.commit()
        await session.refresh(sync)

        logger.info(f"Created forecast sync {sync.id}: {name} (source={source_type})")

        return sync

    async def get_sync(
        self,
        session: AsyncSession,
        sync_id: UUID,
        organization_id: Optional[UUID] = None,
    ) -> Optional[ForecastSync]:
        """Get sync by ID, optionally scoped to organization."""
        query = select(ForecastSync).where(ForecastSync.id == sync_id)
        if organization_id:
            query = query.where(ForecastSync.organization_id == organization_id)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def get_sync_by_slug(
        self,
        session: AsyncSession,
        organization_id: UUID,
        slug: str,
    ) -> Optional[ForecastSync]:
        """Get sync by slug within organization."""
        result = await session.execute(
            select(ForecastSync).where(
                and_(
                    ForecastSync.organization_id == organization_id,
                    ForecastSync.slug == slug,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_syncs(
        self,
        session: AsyncSession,
        organization_id: UUID,
        source_type: Optional[str] = None,
        status: Optional[str] = None,
        is_active: Optional[bool] = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[ForecastSync], int]:
        """
        List syncs for an organization.

        Args:
            session: Database session
            organization_id: Organization UUID
            source_type: Filter by source type (ag, apfs, state)
            status: Filter by status (active, paused, archived)
            is_active: Filter by active state
            include_archived: If False (default), excludes archived syncs
            limit: Maximum records to return
            offset: Records to skip

        Returns:
            Tuple of (syncs list, total count)
        """
        query = select(ForecastSync).where(
            ForecastSync.organization_id == organization_id
        )

        # Exclude archived by default
        if not include_archived and status != "archived":
            query = query.where(ForecastSync.status != "archived")

        if source_type:
            query = query.where(ForecastSync.source_type == source_type)
        if status:
            query = query.where(ForecastSync.status == status)
        if is_active is not None:
            query = query.where(ForecastSync.is_active == is_active)

        # Get total count
        count_query = select(func.count(ForecastSync.id)).where(
            ForecastSync.organization_id == organization_id
        )
        if not include_archived and status != "archived":
            count_query = count_query.where(ForecastSync.status != "archived")
        if source_type:
            count_query = count_query.where(ForecastSync.source_type == source_type)
        if status:
            count_query = count_query.where(ForecastSync.status == status)
        if is_active is not None:
            count_query = count_query.where(ForecastSync.is_active == is_active)

        count_result = await session.execute(count_query)
        total = count_result.scalar_one()

        # Get paginated results
        query = query.order_by(ForecastSync.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await session.execute(query)
        syncs = list(result.scalars().all())

        return syncs, total

    async def list_syncs_by_frequency(
        self,
        session: AsyncSession,
        sync_frequency: str,
        source_type: Optional[str] = None,
    ) -> List[ForecastSync]:
        """
        List all active syncs with a given frequency across all organizations.

        Used by scheduled tasks to find syncs that need to run.

        Args:
            session: Database session
            sync_frequency: Frequency to filter by (hourly, daily)
            source_type: Optional source type filter

        Returns:
            List of active syncs with matching frequency
        """
        query = select(ForecastSync).where(
            and_(
                ForecastSync.sync_frequency == sync_frequency,
                ForecastSync.is_active == True,
                ForecastSync.status == "active",
            )
        )

        if source_type:
            query = query.where(ForecastSync.source_type == source_type)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def update_sync(
        self,
        session: AsyncSession,
        sync_id: UUID,
        name: Optional[str] = None,
        filter_config: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        is_active: Optional[bool] = None,
        sync_frequency: Optional[str] = None,
        automation_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[ForecastSync]:
        """Update sync properties."""
        sync = await self.get_sync(session, sync_id)
        if not sync:
            return None

        if name is not None:
            sync.name = name
        if filter_config is not None:
            sync.filter_config = filter_config
        if status is not None:
            sync.status = status
        if is_active is not None:
            sync.is_active = is_active
        if sync_frequency is not None:
            sync.sync_frequency = sync_frequency
        if automation_config is not None:
            sync.automation_config = automation_config

        await session.commit()
        await session.refresh(sync)

        logger.info(f"Updated forecast sync {sync_id}")

        return sync

    async def delete_sync(
        self,
        session: AsyncSession,
        sync_id: UUID,
    ) -> bool:
        """Delete a sync (soft delete by setting status to archived)."""
        sync = await self.get_sync(session, sync_id)
        if not sync:
            return False

        sync.status = "archived"
        sync.is_active = False
        await session.commit()

        logger.info(f"Archived forecast sync {sync_id}")

        return True

    async def update_sync_status(
        self,
        session: AsyncSession,
        sync_id: UUID,
        status: str,
        run_id: Optional[UUID] = None,
    ) -> Optional[ForecastSync]:
        """Update sync status after a sync operation."""
        sync = await self.get_sync(session, sync_id)
        if not sync:
            return None

        sync.last_sync_at = datetime.utcnow()
        sync.last_sync_status = status
        if run_id:
            sync.last_sync_run_id = run_id

        await session.commit()
        await session.refresh(sync)

        logger.info(f"Updated sync {sync_id} status to {status}")

        return sync

    async def update_forecast_count(
        self,
        session: AsyncSession,
        sync_id: UUID,
        count: int,
    ) -> Optional[ForecastSync]:
        """Update the cached forecast count for a sync."""
        sync = await self.get_sync(session, sync_id)
        if not sync:
            return None

        sync.forecast_count = count
        await session.commit()
        await session.refresh(sync)

        return sync

    async def get_stats(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> Dict[str, Any]:
        """
        Get statistics for forecast syncs in an organization.

        Returns:
            Dictionary with sync counts by source type, total forecasts, etc.
        """
        # Count by source type
        source_counts = {}
        for source in VALID_SOURCE_TYPES:
            count_query = select(func.count(ForecastSync.id)).where(
                and_(
                    ForecastSync.organization_id == organization_id,
                    ForecastSync.source_type == source,
                    ForecastSync.status != "archived",
                )
            )
            result = await session.execute(count_query)
            source_counts[source] = result.scalar_one()

        # Total forecast count
        forecast_count_query = select(func.sum(ForecastSync.forecast_count)).where(
            and_(
                ForecastSync.organization_id == organization_id,
                ForecastSync.status != "archived",
            )
        )
        forecast_result = await session.execute(forecast_count_query)
        total_forecasts = forecast_result.scalar_one() or 0

        # Active syncs count
        active_query = select(func.count(ForecastSync.id)).where(
            and_(
                ForecastSync.organization_id == organization_id,
                ForecastSync.is_active == True,
                ForecastSync.status != "archived",
            )
        )
        active_result = await session.execute(active_query)
        active_syncs = active_result.scalar_one()

        return {
            "syncs_by_source": source_counts,
            "total_syncs": sum(source_counts.values()),
            "active_syncs": active_syncs,
            "total_forecasts": total_forecasts,
        }


# Singleton instance
forecast_sync_service = ForecastSyncService()
