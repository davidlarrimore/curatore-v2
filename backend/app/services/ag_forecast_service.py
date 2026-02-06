"""
AG Forecast Service for GSA Acquisition Gateway Forecast Records.

Provides CRUD operations for AgForecast records pulled from the GSA
Acquisition Gateway API. Handles upsert logic based on nid (AG's internal ID).

Usage:
    from app.services.ag_forecast_service import ag_forecast_service

    # Upsert a forecast from API data
    forecast = await ag_forecast_service.upsert_forecast(
        session=session,
        organization_id=org_id,
        sync_id=sync_id,
        nid="12345",
        title="IT Services",
        raw_data={...},
    )

    # List forecasts
    forecasts, total = await ag_forecast_service.list_forecasts(
        session=session,
        organization_id=org_id,
    )
"""

import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import AgForecast

logger = logging.getLogger("curatore.ag_forecast_service")


# Key fields for change detection
AG_KEY_FIELDS = [
    "title",
    "award_status",
    "estimated_award_fy",
    "estimated_award_quarter",
    "set_aside_type",
    "acquisition_phase",
]


def compute_change_hash(data: Dict[str, Any], key_fields: List[str]) -> str:
    """Compute hash of key fields to detect meaningful changes."""
    values = [str(data.get(f, "")) for f in key_fields]
    return hashlib.sha256("|".join(values).encode()).hexdigest()[:16]


def build_history_entry(
    version: int,
    data: Dict[str, Any],
    sync_date: datetime,
) -> Dict[str, Any]:
    """
    Build a history entry for version tracking.

    Args:
        version: Version number (1, 2, 3, ...)
        data: All field values at this version
        sync_date: When this version was synced

    Returns:
        History entry dict with version, sync_date, and all field values
    """
    return {
        "version": version,
        "sync_date": sync_date.isoformat(),
        "data": data,
    }


class AgForecastService:
    """
    Service for managing AG (Acquisition Gateway) forecast records.

    Handles CRUD operations and upsert logic for forecasts from AG API.
    """

    # =========================================================================
    # FORECAST OPERATIONS
    # =========================================================================

    async def upsert_forecast(
        self,
        session: AsyncSession,
        organization_id: UUID,
        sync_id: UUID,
        nid: str,
        title: str,
        description: Optional[str] = None,
        agency_name: Optional[str] = None,
        agency_id: Optional[int] = None,
        organization_name: Optional[str] = None,
        naics_codes: Optional[List[Dict[str, Any]]] = None,
        acquisition_phase: Optional[str] = None,
        acquisition_strategies: Optional[List[Dict[str, Any]]] = None,
        award_status: Optional[str] = None,
        requirement_type: Optional[str] = None,
        procurement_method: Optional[str] = None,
        set_aside_type: Optional[str] = None,
        extent_competed: Optional[str] = None,
        listing_id: Optional[str] = None,
        estimated_solicitation_date: Optional[datetime] = None,
        estimated_award_fy: Optional[int] = None,
        estimated_award_quarter: Optional[str] = None,
        period_of_performance: Optional[str] = None,
        poc_name: Optional[str] = None,
        poc_email: Optional[str] = None,
        sbs_name: Optional[str] = None,
        sbs_email: Optional[str] = None,
        source_url: Optional[str] = None,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> Tuple[AgForecast, bool]:
        """
        Upsert a forecast record.

        Creates a new record if nid doesn't exist, updates if it does.
        Tracks changes via change_hash.

        Args:
            session: Database session
            organization_id: Organization UUID
            sync_id: Parent ForecastSync UUID
            nid: AG's unique record identifier
            title: Forecast title
            ... (other fields)

        Returns:
            Tuple of (forecast, is_new) where is_new indicates if record was created
        """
        # Check for existing record
        existing = await self.get_forecast_by_nid(session, organization_id, nid)

        # Compute change hash
        data = {
            "title": title,
            "award_status": award_status,
            "estimated_award_fy": estimated_award_fy,
            "estimated_award_quarter": estimated_award_quarter,
            "set_aside_type": set_aside_type,
            "acquisition_phase": acquisition_phase,
        }
        new_hash = compute_change_hash(data, AG_KEY_FIELDS)

        if existing:
            # Update existing record
            existing.sync_id = sync_id
            existing.title = title
            existing.description = description
            existing.agency_name = agency_name
            existing.agency_id = agency_id
            existing.organization_name = organization_name
            existing.naics_codes = naics_codes
            existing.acquisition_phase = acquisition_phase
            existing.acquisition_strategies = acquisition_strategies
            existing.award_status = award_status
            existing.requirement_type = requirement_type
            existing.procurement_method = procurement_method
            existing.set_aside_type = set_aside_type
            existing.extent_competed = extent_competed
            existing.listing_id = listing_id
            existing.estimated_solicitation_date = estimated_solicitation_date
            existing.estimated_award_fy = estimated_award_fy
            existing.estimated_award_quarter = estimated_award_quarter
            existing.period_of_performance = period_of_performance
            existing.poc_name = poc_name
            existing.poc_email = poc_email
            existing.sbs_name = sbs_name
            existing.sbs_email = sbs_email
            existing.source_url = source_url
            existing.raw_data = raw_data

            # Check if content changed
            if existing.change_hash != new_hash:
                now = datetime.utcnow()
                existing.last_updated_at = now
                existing.change_hash = new_hash
                existing.indexed_at = None  # Mark for re-indexing

                # Add new version to history
                current_history = existing.history or []
                new_version = len(current_history) + 1
                history_data = {
                    "title": title,
                    "description": description,
                    "agency_name": agency_name,
                    "award_status": award_status,
                    "acquisition_phase": acquisition_phase,
                    "set_aside_type": set_aside_type,
                    "estimated_award_fy": estimated_award_fy,
                    "estimated_award_quarter": estimated_award_quarter,
                    "estimated_solicitation_date": estimated_solicitation_date.isoformat() if estimated_solicitation_date else None,
                    "naics_codes": naics_codes,
                    "poc_name": poc_name,
                    "poc_email": poc_email,
                }
                current_history.append(build_history_entry(new_version, history_data, now))
                existing.history = current_history

            await session.commit()
            await session.refresh(existing)

            return existing, False

        else:
            # Create new record with initial history
            now = datetime.utcnow()
            history_data = {
                "title": title,
                "description": description,
                "agency_name": agency_name,
                "award_status": award_status,
                "acquisition_phase": acquisition_phase,
                "set_aside_type": set_aside_type,
                "estimated_award_fy": estimated_award_fy,
                "estimated_award_quarter": estimated_award_quarter,
                "estimated_solicitation_date": estimated_solicitation_date.isoformat() if estimated_solicitation_date else None,
                "naics_codes": naics_codes,
                "poc_name": poc_name,
                "poc_email": poc_email,
            }
            initial_history = [build_history_entry(1, history_data, now)]

            forecast = AgForecast(
                organization_id=organization_id,
                sync_id=sync_id,
                nid=nid,
                title=title,
                description=description,
                agency_name=agency_name,
                agency_id=agency_id,
                organization_name=organization_name,
                naics_codes=naics_codes,
                acquisition_phase=acquisition_phase,
                acquisition_strategies=acquisition_strategies,
                award_status=award_status,
                requirement_type=requirement_type,
                procurement_method=procurement_method,
                set_aside_type=set_aside_type,
                extent_competed=extent_competed,
                listing_id=listing_id,
                estimated_solicitation_date=estimated_solicitation_date,
                estimated_award_fy=estimated_award_fy,
                estimated_award_quarter=estimated_award_quarter,
                period_of_performance=period_of_performance,
                poc_name=poc_name,
                poc_email=poc_email,
                sbs_name=sbs_name,
                sbs_email=sbs_email,
                source_url=source_url,
                raw_data=raw_data,
                change_hash=new_hash,
                history=initial_history,
            )

            session.add(forecast)
            await session.commit()
            await session.refresh(forecast)

            logger.info(f"Created AG forecast {forecast.id}: nid={nid}")

            return forecast, True

    async def get_forecast(
        self,
        session: AsyncSession,
        forecast_id: UUID,
    ) -> Optional[AgForecast]:
        """Get forecast by ID."""
        result = await session.execute(
            select(AgForecast).where(AgForecast.id == forecast_id)
        )
        return result.scalar_one_or_none()

    async def get_forecast_by_nid(
        self,
        session: AsyncSession,
        organization_id: UUID,
        nid: str,
    ) -> Optional[AgForecast]:
        """Get forecast by nid within organization."""
        result = await session.execute(
            select(AgForecast).where(
                and_(
                    AgForecast.organization_id == organization_id,
                    AgForecast.nid == nid,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_forecasts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        sync_id: Optional[UUID] = None,
        agency_id: Optional[int] = None,
        award_status: Optional[str] = None,
        fiscal_year: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[AgForecast], int]:
        """
        List forecasts for an organization.

        Args:
            session: Database session
            organization_id: Organization UUID
            sync_id: Filter by sync configuration
            agency_id: Filter by agency
            award_status: Filter by award status
            fiscal_year: Filter by estimated award fiscal year
            limit: Maximum records to return
            offset: Records to skip

        Returns:
            Tuple of (forecasts list, total count)
        """
        query = select(AgForecast).where(
            AgForecast.organization_id == organization_id
        )

        if sync_id:
            query = query.where(AgForecast.sync_id == sync_id)
        if agency_id:
            query = query.where(AgForecast.agency_id == agency_id)
        if award_status:
            query = query.where(AgForecast.award_status == award_status)
        if fiscal_year:
            query = query.where(AgForecast.estimated_award_fy == fiscal_year)

        # Get total count
        count_query = select(func.count(AgForecast.id)).where(
            AgForecast.organization_id == organization_id
        )
        if sync_id:
            count_query = count_query.where(AgForecast.sync_id == sync_id)
        if agency_id:
            count_query = count_query.where(AgForecast.agency_id == agency_id)
        if award_status:
            count_query = count_query.where(AgForecast.award_status == award_status)
        if fiscal_year:
            count_query = count_query.where(AgForecast.estimated_award_fy == fiscal_year)

        count_result = await session.execute(count_query)
        total = count_result.scalar_one()

        # Get paginated results
        query = query.order_by(AgForecast.last_updated_at.desc())
        query = query.limit(limit).offset(offset)

        result = await session.execute(query)
        forecasts = list(result.scalars().all())

        return forecasts, total

    async def count_by_sync(
        self,
        session: AsyncSession,
        sync_id: UUID,
    ) -> int:
        """Count forecasts for a sync configuration."""
        count_query = select(func.count(AgForecast.id)).where(
            AgForecast.sync_id == sync_id
        )
        result = await session.execute(count_query)
        return result.scalar_one()

    async def get_unindexed(
        self,
        session: AsyncSession,
        organization_id: UUID,
        limit: int = 100,
    ) -> List[AgForecast]:
        """Get forecasts that need to be indexed."""
        query = select(AgForecast).where(
            and_(
                AgForecast.organization_id == organization_id,
                AgForecast.indexed_at.is_(None),
            )
        ).limit(limit)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def mark_indexed(
        self,
        session: AsyncSession,
        forecast_id: UUID,
    ) -> None:
        """Mark a forecast as indexed."""
        forecast = await self.get_forecast(session, forecast_id)
        if forecast:
            forecast.indexed_at = datetime.utcnow()
            await session.commit()

    async def delete_by_sync(
        self,
        session: AsyncSession,
        sync_id: UUID,
    ) -> int:
        """Delete all forecasts for a sync (used when deleting sync)."""
        query = select(AgForecast).where(AgForecast.sync_id == sync_id)
        result = await session.execute(query)
        forecasts = list(result.scalars().all())

        count = len(forecasts)
        for forecast in forecasts:
            await session.delete(forecast)

        await session.commit()

        logger.info(f"Deleted {count} AG forecasts for sync {sync_id}")

        return count


# Singleton instance
ag_forecast_service = AgForecastService()
