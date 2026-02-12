"""
APFS Forecast Service for DHS APFS Forecast Records.

Provides CRUD operations for ApfsForecast records pulled from the DHS
APFS (Acquisition Planning Forecast System) API. Handles upsert logic
based on apfs_number (DHS's forecast number).

Usage:
    from app.connectors.dhs_apfs.apfs_forecast_service import apfs_forecast_service

    # Upsert a forecast from API data
    forecast = await apfs_forecast_service.upsert_forecast(
        session=session,
        organization_id=org_id,
        sync_id=sync_id,
        apfs_number="DHS-FCS-2026-0001",
        title="IT Support Services",
        raw_data={...},
    )

    # List forecasts
    forecasts, total = await apfs_forecast_service.list_forecasts(
        session=session,
        organization_id=org_id,
    )
"""

import hashlib
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database.models import ApfsForecast

logger = logging.getLogger("curatore.apfs_forecast_service")


# Key fields for change detection
APFS_KEY_FIELDS = [
    "title",
    "contract_status",
    "fiscal_year",
    "award_quarter",
    "small_business_set_aside",
    "dollar_range",
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


class ApfsForecastService:
    """
    Service for managing APFS (DHS) forecast records.

    Handles CRUD operations and upsert logic for forecasts from APFS API.
    """

    # =========================================================================
    # FORECAST OPERATIONS
    # =========================================================================

    async def upsert_forecast(
        self,
        session: AsyncSession,
        organization_id: UUID,
        sync_id: UUID,
        apfs_number: str,
        title: str,
        apfs_id: Optional[int] = None,
        description: Optional[str] = None,
        component: Optional[str] = None,
        mission: Optional[str] = None,
        naics_code: Optional[str] = None,
        naics_description: Optional[str] = None,
        contract_type: Optional[str] = None,
        contract_vehicle: Optional[str] = None,
        contract_status: Optional[str] = None,
        competition_type: Optional[str] = None,
        small_business_program: Optional[str] = None,
        small_business_set_aside: Optional[str] = None,
        dollar_range: Optional[str] = None,
        fiscal_year: Optional[int] = None,
        award_quarter: Optional[str] = None,
        anticipated_award_date: Optional[date] = None,
        estimated_solicitation_date: Optional[date] = None,
        pop_start_date: Optional[date] = None,
        pop_end_date: Optional[date] = None,
        requirements_office: Optional[str] = None,
        contracting_office: Optional[str] = None,
        poc_name: Optional[str] = None,
        poc_email: Optional[str] = None,
        poc_phone: Optional[str] = None,
        alt_contact_name: Optional[str] = None,
        alt_contact_email: Optional[str] = None,
        sbs_name: Optional[str] = None,
        sbs_email: Optional[str] = None,
        sbs_phone: Optional[str] = None,
        current_state: Optional[str] = None,
        published_date: Optional[date] = None,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> Tuple[ApfsForecast, bool]:
        """
        Upsert a forecast record.

        Creates a new record if apfs_number doesn't exist, updates if it does.
        Tracks changes via change_hash.

        Args:
            session: Database session
            organization_id: Organization UUID
            sync_id: Parent ForecastSync UUID
            apfs_number: DHS forecast number
            title: Forecast title
            ... (other fields)

        Returns:
            Tuple of (forecast, is_new) where is_new indicates if record was created
        """
        # Check for existing record
        existing = await self.get_forecast_by_apfs_number(session, organization_id, apfs_number)

        # Compute change hash
        data = {
            "title": title,
            "contract_status": contract_status,
            "fiscal_year": fiscal_year,
            "award_quarter": award_quarter,
            "small_business_set_aside": small_business_set_aside,
            "dollar_range": dollar_range,
        }
        new_hash = compute_change_hash(data, APFS_KEY_FIELDS)

        if existing:
            # Update existing record
            existing.sync_id = sync_id
            existing.apfs_id = apfs_id
            existing.title = title
            existing.description = description
            existing.component = component
            existing.mission = mission
            existing.naics_code = naics_code
            existing.naics_description = naics_description
            existing.contract_type = contract_type
            existing.contract_vehicle = contract_vehicle
            existing.contract_status = contract_status
            existing.competition_type = competition_type
            existing.small_business_program = small_business_program
            existing.small_business_set_aside = small_business_set_aside
            existing.dollar_range = dollar_range
            existing.fiscal_year = fiscal_year
            existing.award_quarter = award_quarter
            existing.anticipated_award_date = anticipated_award_date
            existing.estimated_solicitation_date = estimated_solicitation_date
            existing.pop_start_date = pop_start_date
            existing.pop_end_date = pop_end_date
            existing.requirements_office = requirements_office
            existing.contracting_office = contracting_office
            existing.poc_name = poc_name
            existing.poc_email = poc_email
            existing.poc_phone = poc_phone
            existing.alt_contact_name = alt_contact_name
            existing.alt_contact_email = alt_contact_email
            existing.sbs_name = sbs_name
            existing.sbs_email = sbs_email
            existing.sbs_phone = sbs_phone
            existing.current_state = current_state
            existing.published_date = published_date
            existing.raw_data = raw_data

            # Build full snapshot of ALL meaningful fields
            history_data = {
                "title": title,
                "description": description,
                "component": component,
                "contract_status": contract_status,
                "dollar_range": dollar_range,
                "fiscal_year": fiscal_year,
                "award_quarter": award_quarter,
                "small_business_set_aside": small_business_set_aside,
                "anticipated_award_date": anticipated_award_date.isoformat() if anticipated_award_date else None,
                "estimated_solicitation_date": estimated_solicitation_date.isoformat() if estimated_solicitation_date else None,
                "naics_code": naics_code,
                "poc_name": poc_name,
                "poc_email": poc_email,
                "contract_type": contract_type,
                "contract_vehicle": contract_vehicle,
                "competition_type": competition_type,
                "small_business_program": small_business_program,
                "requirements_office": requirements_office,
                "contracting_office": contracting_office,
                "poc_phone": poc_phone,
                "alt_contact_name": alt_contact_name,
                "alt_contact_email": alt_contact_email,
                "sbs_phone": sbs_phone,
                "current_state": current_state,
                "published_date": published_date.isoformat() if published_date else None,
                "mission": mission,
            }

            # History: append if ANY field changed (decoupled from change_hash)
            prev_snapshot = (existing.history or [])[-1].get("data", {}) if existing.history else {}
            if history_data != prev_snapshot:
                now = datetime.utcnow()
                existing.last_updated_at = now
                current_history = list(existing.history or [])
                new_version = len(current_history) + 1
                current_history.append(build_history_entry(new_version, history_data, now))
                existing.history = current_history

            # Re-indexing: keep existing change_hash logic (only key fields)
            if existing.change_hash != new_hash:
                existing.change_hash = new_hash
                existing.indexed_at = None  # Mark for re-indexing

            await session.commit()
            await session.refresh(existing)

            return existing, False

        else:
            # Create new record with initial history
            now = datetime.utcnow()
            history_data = {
                "title": title,
                "description": description,
                "component": component,
                "contract_status": contract_status,
                "dollar_range": dollar_range,
                "fiscal_year": fiscal_year,
                "award_quarter": award_quarter,
                "small_business_set_aside": small_business_set_aside,
                "anticipated_award_date": anticipated_award_date.isoformat() if anticipated_award_date else None,
                "estimated_solicitation_date": estimated_solicitation_date.isoformat() if estimated_solicitation_date else None,
                "naics_code": naics_code,
                "poc_name": poc_name,
                "poc_email": poc_email,
                "contract_type": contract_type,
                "contract_vehicle": contract_vehicle,
                "competition_type": competition_type,
                "small_business_program": small_business_program,
                "requirements_office": requirements_office,
                "contracting_office": contracting_office,
                "poc_phone": poc_phone,
                "alt_contact_name": alt_contact_name,
                "alt_contact_email": alt_contact_email,
                "sbs_phone": sbs_phone,
                "current_state": current_state,
                "published_date": published_date.isoformat() if published_date else None,
                "mission": mission,
            }
            initial_history = [build_history_entry(1, history_data, now)]

            forecast = ApfsForecast(
                organization_id=organization_id,
                sync_id=sync_id,
                apfs_number=apfs_number,
                apfs_id=apfs_id,
                title=title,
                description=description,
                component=component,
                mission=mission,
                naics_code=naics_code,
                naics_description=naics_description,
                contract_type=contract_type,
                contract_vehicle=contract_vehicle,
                contract_status=contract_status,
                competition_type=competition_type,
                small_business_program=small_business_program,
                small_business_set_aside=small_business_set_aside,
                dollar_range=dollar_range,
                fiscal_year=fiscal_year,
                award_quarter=award_quarter,
                anticipated_award_date=anticipated_award_date,
                estimated_solicitation_date=estimated_solicitation_date,
                pop_start_date=pop_start_date,
                pop_end_date=pop_end_date,
                requirements_office=requirements_office,
                contracting_office=contracting_office,
                poc_name=poc_name,
                poc_email=poc_email,
                poc_phone=poc_phone,
                alt_contact_name=alt_contact_name,
                alt_contact_email=alt_contact_email,
                sbs_name=sbs_name,
                sbs_email=sbs_email,
                sbs_phone=sbs_phone,
                current_state=current_state,
                published_date=published_date,
                raw_data=raw_data,
                change_hash=new_hash,
                history=initial_history,
            )

            session.add(forecast)
            await session.commit()
            await session.refresh(forecast)

            logger.info(f"Created APFS forecast {forecast.id}: apfs_number={apfs_number}")

            return forecast, True

    async def get_forecast(
        self,
        session: AsyncSession,
        forecast_id: UUID,
    ) -> Optional[ApfsForecast]:
        """Get forecast by ID."""
        result = await session.execute(
            select(ApfsForecast).where(ApfsForecast.id == forecast_id)
        )
        return result.scalar_one_or_none()

    async def get_forecast_by_apfs_number(
        self,
        session: AsyncSession,
        organization_id: UUID,
        apfs_number: str,
    ) -> Optional[ApfsForecast]:
        """Get forecast by APFS number within organization."""
        result = await session.execute(
            select(ApfsForecast).where(
                and_(
                    ApfsForecast.organization_id == organization_id,
                    ApfsForecast.apfs_number == apfs_number,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_forecasts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        sync_id: Optional[UUID] = None,
        component: Optional[str] = None,
        fiscal_year: Optional[int] = None,
        contract_status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[ApfsForecast], int]:
        """
        List forecasts for an organization.

        Args:
            session: Database session
            organization_id: Organization UUID
            sync_id: Filter by sync configuration
            component: Filter by DHS component (CBP, ICE, etc.)
            fiscal_year: Filter by fiscal year
            contract_status: Filter by contract status
            limit: Maximum records to return
            offset: Records to skip

        Returns:
            Tuple of (forecasts list, total count)
        """
        query = select(ApfsForecast).where(
            ApfsForecast.organization_id == organization_id
        )

        if sync_id:
            query = query.where(ApfsForecast.sync_id == sync_id)
        if component:
            query = query.where(ApfsForecast.component == component)
        if fiscal_year:
            query = query.where(ApfsForecast.fiscal_year == fiscal_year)
        if contract_status:
            query = query.where(ApfsForecast.contract_status == contract_status)

        # Get total count
        count_query = select(func.count(ApfsForecast.id)).where(
            ApfsForecast.organization_id == organization_id
        )
        if sync_id:
            count_query = count_query.where(ApfsForecast.sync_id == sync_id)
        if component:
            count_query = count_query.where(ApfsForecast.component == component)
        if fiscal_year:
            count_query = count_query.where(ApfsForecast.fiscal_year == fiscal_year)
        if contract_status:
            count_query = count_query.where(ApfsForecast.contract_status == contract_status)

        count_result = await session.execute(count_query)
        total = count_result.scalar_one()

        # Get paginated results
        query = query.order_by(ApfsForecast.last_updated_at.desc())
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
        count_query = select(func.count(ApfsForecast.id)).where(
            ApfsForecast.sync_id == sync_id
        )
        result = await session.execute(count_query)
        return result.scalar_one()

    async def get_unindexed(
        self,
        session: AsyncSession,
        organization_id: UUID,
        limit: int = 100,
    ) -> List[ApfsForecast]:
        """Get forecasts that need to be indexed."""
        query = select(ApfsForecast).where(
            and_(
                ApfsForecast.organization_id == organization_id,
                ApfsForecast.indexed_at.is_(None),
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
        query = select(ApfsForecast).where(ApfsForecast.sync_id == sync_id)
        result = await session.execute(query)
        forecasts = list(result.scalars().all())

        count = len(forecasts)
        for forecast in forecasts:
            await session.delete(forecast)

        await session.commit()

        logger.info(f"Deleted {count} APFS forecasts for sync {sync_id}")

        return count

    async def get_components(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> List[str]:
        """Get distinct DHS components with forecasts."""
        query = select(ApfsForecast.component).where(
            and_(
                ApfsForecast.organization_id == organization_id,
                ApfsForecast.component.isnot(None),
            )
        ).distinct()

        result = await session.execute(query)
        return [row[0] for row in result.all() if row[0]]


# Singleton instance
apfs_forecast_service = ApfsForecastService()
