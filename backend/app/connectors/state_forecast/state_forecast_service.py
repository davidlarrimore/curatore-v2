"""
State Forecast Service for State Department Forecast Records.

Provides CRUD operations for StateForecast records parsed from the State
Department's monthly Excel procurement forecast. Handles upsert logic
based on row_hash (computed from row content).

Usage:
    from app.connectors.state_forecast.state_forecast_service import state_forecast_service

    # Upsert a forecast from Excel data
    forecast = await state_forecast_service.upsert_forecast(
        session=session,
        organization_id=org_id,
        sync_id=sync_id,
        row_hash="abc123...",
        title="IT Support Services",
        raw_data={...},
    )

    # List forecasts
    forecasts, total = await state_forecast_service.list_forecasts(
        session=session,
        organization_id=org_id,
    )
"""

import hashlib
import logging
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database.models import StateForecast

logger = logging.getLogger("curatore.state_forecast_service")


# Key fields for change detection
STATE_KEY_FIELDS = [
    "title",
    "acquisition_phase",
    "fiscal_year",
    "estimated_award_quarter",
    "set_aside_type",
    "estimated_value",
]


def compute_change_hash(data: Dict[str, Any], key_fields: List[str]) -> str:
    """Compute hash of key fields to detect meaningful changes."""
    values = [str(data.get(f, "")) for f in key_fields]
    return hashlib.sha256("|".join(values).encode()).hexdigest()[:16]


def compute_row_hash(row_data: Dict[str, Any]) -> str:
    """
    Compute hash to identify unique rows.

    Uses title + NAICS + fiscal_year + estimated_value as identity.
    This allows detecting the same forecast across file updates.
    """
    identity_fields = [
        str(row_data.get("title", "")),
        str(row_data.get("naics_code", "")),
        str(row_data.get("fiscal_year", "")),
        str(row_data.get("estimated_value", "")),
    ]
    return hashlib.sha256("|".join(identity_fields).encode()).hexdigest()


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


class StateForecastService:
    """
    Service for managing State Department forecast records.

    Handles CRUD operations and upsert logic for forecasts from State Dept Excel.
    """

    # =========================================================================
    # FORECAST OPERATIONS
    # =========================================================================

    async def upsert_forecast(
        self,
        session: AsyncSession,
        organization_id: UUID,
        sync_id: UUID,
        row_hash: str,
        title: str,
        description: Optional[str] = None,
        naics_code: Optional[str] = None,
        pop_city: Optional[str] = None,
        pop_state: Optional[str] = None,
        pop_country: Optional[str] = None,
        acquisition_phase: Optional[str] = None,
        set_aside_type: Optional[str] = None,
        contract_type: Optional[str] = None,
        anticipated_award_type: Optional[str] = None,
        estimated_value: Optional[str] = None,
        fiscal_year: Optional[int] = None,
        estimated_award_quarter: Optional[str] = None,
        estimated_solicitation_date: Optional[date] = None,
        incumbent_contractor: Optional[str] = None,
        awarded_contract_order: Optional[str] = None,
        facility_clearance: Optional[str] = None,
        source_file: Optional[str] = None,
        source_row: Optional[int] = None,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> Tuple[StateForecast, bool]:
        """
        Upsert a forecast record.

        Creates a new record if row_hash doesn't exist, updates if it does.
        Tracks changes via change_hash.

        Args:
            session: Database session
            organization_id: Organization UUID
            sync_id: Parent ForecastSync UUID
            row_hash: Hash identifying the row content
            title: Forecast title
            ... (other fields)

        Returns:
            Tuple of (forecast, is_new) where is_new indicates if record was created
        """
        # Check for existing record
        existing = await self.get_forecast_by_row_hash(session, organization_id, row_hash)

        # Compute change hash
        data = {
            "title": title,
            "acquisition_phase": acquisition_phase,
            "fiscal_year": fiscal_year,
            "estimated_award_quarter": estimated_award_quarter,
            "set_aside_type": set_aside_type,
            "estimated_value": estimated_value,
        }
        new_hash = compute_change_hash(data, STATE_KEY_FIELDS)

        if existing:
            # Update existing record
            existing.sync_id = sync_id
            existing.title = title
            existing.description = description
            existing.naics_code = naics_code
            existing.pop_city = pop_city
            existing.pop_state = pop_state
            existing.pop_country = pop_country
            existing.acquisition_phase = acquisition_phase
            existing.set_aside_type = set_aside_type
            existing.contract_type = contract_type
            existing.anticipated_award_type = anticipated_award_type
            existing.estimated_value = estimated_value
            existing.fiscal_year = fiscal_year
            existing.estimated_award_quarter = estimated_award_quarter
            existing.estimated_solicitation_date = estimated_solicitation_date
            existing.incumbent_contractor = incumbent_contractor
            existing.awarded_contract_order = awarded_contract_order
            existing.facility_clearance = facility_clearance
            existing.source_file = source_file
            existing.source_row = source_row
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
                    "acquisition_phase": acquisition_phase,
                    "set_aside_type": set_aside_type,
                    "estimated_value": estimated_value,
                    "fiscal_year": fiscal_year,
                    "estimated_award_quarter": estimated_award_quarter,
                    "estimated_solicitation_date": estimated_solicitation_date.isoformat() if estimated_solicitation_date else None,
                    "naics_code": naics_code,
                    "pop_city": pop_city,
                    "pop_state": pop_state,
                    "pop_country": pop_country,
                    "incumbent_contractor": incumbent_contractor,
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
                "acquisition_phase": acquisition_phase,
                "set_aside_type": set_aside_type,
                "estimated_value": estimated_value,
                "fiscal_year": fiscal_year,
                "estimated_award_quarter": estimated_award_quarter,
                "estimated_solicitation_date": estimated_solicitation_date.isoformat() if estimated_solicitation_date else None,
                "naics_code": naics_code,
                "pop_city": pop_city,
                "pop_state": pop_state,
                "pop_country": pop_country,
                "incumbent_contractor": incumbent_contractor,
            }
            initial_history = [build_history_entry(1, history_data, now)]

            forecast = StateForecast(
                organization_id=organization_id,
                sync_id=sync_id,
                row_hash=row_hash,
                title=title,
                description=description,
                naics_code=naics_code,
                pop_city=pop_city,
                pop_state=pop_state,
                pop_country=pop_country,
                acquisition_phase=acquisition_phase,
                set_aside_type=set_aside_type,
                contract_type=contract_type,
                anticipated_award_type=anticipated_award_type,
                estimated_value=estimated_value,
                fiscal_year=fiscal_year,
                estimated_award_quarter=estimated_award_quarter,
                estimated_solicitation_date=estimated_solicitation_date,
                incumbent_contractor=incumbent_contractor,
                awarded_contract_order=awarded_contract_order,
                facility_clearance=facility_clearance,
                source_file=source_file,
                source_row=source_row,
                raw_data=raw_data,
                change_hash=new_hash,
                history=initial_history,
            )

            session.add(forecast)
            await session.commit()
            await session.refresh(forecast)

            logger.info(f"Created State forecast {forecast.id}: row_hash={row_hash[:16]}...")

            return forecast, True

    async def get_forecast(
        self,
        session: AsyncSession,
        forecast_id: UUID,
    ) -> Optional[StateForecast]:
        """Get forecast by ID."""
        result = await session.execute(
            select(StateForecast).where(StateForecast.id == forecast_id)
        )
        return result.scalar_one_or_none()

    async def get_forecast_by_row_hash(
        self,
        session: AsyncSession,
        organization_id: UUID,
        row_hash: str,
    ) -> Optional[StateForecast]:
        """Get forecast by row hash within organization."""
        result = await session.execute(
            select(StateForecast).where(
                and_(
                    StateForecast.organization_id == organization_id,
                    StateForecast.row_hash == row_hash,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_forecasts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        sync_id: Optional[UUID] = None,
        fiscal_year: Optional[int] = None,
        pop_country: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[StateForecast], int]:
        """
        List forecasts for an organization.

        Args:
            session: Database session
            organization_id: Organization UUID
            sync_id: Filter by sync configuration
            fiscal_year: Filter by fiscal year
            pop_country: Filter by place of performance country
            limit: Maximum records to return
            offset: Records to skip

        Returns:
            Tuple of (forecasts list, total count)
        """
        query = select(StateForecast).where(
            StateForecast.organization_id == organization_id
        )

        if sync_id:
            query = query.where(StateForecast.sync_id == sync_id)
        if fiscal_year:
            query = query.where(StateForecast.fiscal_year == fiscal_year)
        if pop_country:
            query = query.where(StateForecast.pop_country == pop_country)

        # Get total count
        count_query = select(func.count(StateForecast.id)).where(
            StateForecast.organization_id == organization_id
        )
        if sync_id:
            count_query = count_query.where(StateForecast.sync_id == sync_id)
        if fiscal_year:
            count_query = count_query.where(StateForecast.fiscal_year == fiscal_year)
        if pop_country:
            count_query = count_query.where(StateForecast.pop_country == pop_country)

        count_result = await session.execute(count_query)
        total = count_result.scalar_one()

        # Get paginated results
        query = query.order_by(StateForecast.last_updated_at.desc())
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
        count_query = select(func.count(StateForecast.id)).where(
            StateForecast.sync_id == sync_id
        )
        result = await session.execute(count_query)
        return result.scalar_one()

    async def get_unindexed(
        self,
        session: AsyncSession,
        organization_id: UUID,
        limit: int = 100,
    ) -> List[StateForecast]:
        """Get forecasts that need to be indexed."""
        query = select(StateForecast).where(
            and_(
                StateForecast.organization_id == organization_id,
                StateForecast.indexed_at.is_(None),
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
        query = select(StateForecast).where(StateForecast.sync_id == sync_id)
        result = await session.execute(query)
        forecasts = list(result.scalars().all())

        count = len(forecasts)
        for forecast in forecasts:
            await session.delete(forecast)

        await session.commit()

        logger.info(f"Deleted {count} State forecasts for sync {sync_id}")

        return count


# Singleton instance
state_forecast_service = StateForecastService()
