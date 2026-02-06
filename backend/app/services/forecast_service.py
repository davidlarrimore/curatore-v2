"""
Unified Forecast Service for Cross-Source Forecast Access.

Provides read-only access to forecasts across all sources (AG, APFS, State)
via the unified_forecasts VIEW. For write operations, use the source-specific
services (ag_forecast_service, apfs_forecast_service, state_forecast_service).

Usage:
    from app.services.forecast_service import forecast_service

    # List all forecasts (unified view)
    forecasts, total = await forecast_service.list_forecasts(
        session=session,
        organization_id=org_id,
        source_types=["ag", "apfs"],
        fiscal_year=2026,
    )

    # Get forecast by ID (with source type)
    forecast = await forecast_service.get_forecast(
        session=session,
        forecast_id=forecast_id,
        source_type="ag",
    )
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import AgForecast, ApfsForecast, StateForecast

logger = logging.getLogger("curatore.forecast_service")


# Source type to model mapping
SOURCE_MODELS = {
    "ag": AgForecast,
    "apfs": ApfsForecast,
    "state": StateForecast,
}


class ForecastService:
    """
    Unified service for accessing forecasts across all sources.

    Provides read access via the unified_forecasts VIEW for listing
    and filtering. For detailed record access, uses source-specific models.
    """

    # =========================================================================
    # UNIFIED OPERATIONS
    # =========================================================================

    # Valid sort fields mapped to actual column names
    SORT_FIELDS = {
        "source_type": "source_type",
        "title": "title",
        "agency_name": "agency_name",
        "naics": "naics_codes",
        "fiscal_year": "fiscal_year",
        "award_quarter": "estimated_award_quarter",
        "last_updated_at": "last_updated_at",
        "created_at": "created_at",
    }

    async def list_forecasts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        source_types: Optional[List[str]] = None,
        sync_id: Optional[UUID] = None,
        fiscal_year: Optional[int] = None,
        agency_name: Optional[str] = None,
        search_query: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_direction: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List forecasts from the unified view.

        Args:
            session: Database session
            organization_id: Organization UUID
            source_types: Filter by source types (ag, apfs, state)
            sync_id: Filter by sync configuration
            fiscal_year: Filter by fiscal year
            agency_name: Filter by agency name (partial match)
            search_query: Text search in title/description
            sort_by: Field to sort by (source_type, title, agency_name, naics, fiscal_year, award_quarter)
            sort_direction: Sort direction (asc, desc)
            limit: Maximum records to return
            offset: Records to skip

        Returns:
            Tuple of (forecasts as dicts, total count)
        """
        # Build base query from VIEW
        base_conditions = [f"organization_id = '{organization_id}'"]

        if source_types:
            sources = ", ".join([f"'{s}'" for s in source_types])
            base_conditions.append(f"source_type IN ({sources})")

        if sync_id:
            base_conditions.append(f"sync_id = '{sync_id}'")

        if fiscal_year:
            base_conditions.append(f"fiscal_year = {fiscal_year}")

        if agency_name:
            # Case-insensitive partial match
            base_conditions.append(f"LOWER(agency_name) LIKE LOWER('%{agency_name}%')")

        if search_query:
            # Search in title and description
            escaped_query = search_query.replace("'", "''")
            base_conditions.append(
                f"(LOWER(title) LIKE LOWER('%{escaped_query}%') OR LOWER(description) LIKE LOWER('%{escaped_query}%'))"
            )

        where_clause = " AND ".join(base_conditions)

        # Count query
        count_sql = text(f"SELECT COUNT(*) FROM unified_forecasts WHERE {where_clause}")
        count_result = await session.execute(count_sql)
        total = count_result.scalar_one()

        # Determine sort column and direction
        sort_column = "last_updated_at"  # Default sort
        sort_dir = "DESC"  # Default direction

        if sort_by and sort_by in self.SORT_FIELDS:
            sort_column = self.SORT_FIELDS[sort_by]
        if sort_direction and sort_direction.lower() in ("asc", "desc"):
            sort_dir = sort_direction.upper()

        # Handle NULL sorting - put NULLs last for ASC, first for DESC
        null_handling = "NULLS LAST" if sort_dir == "ASC" else "NULLS FIRST"

        # Data query with pagination
        data_sql = text(f"""
            SELECT
                id, organization_id, sync_id, source_type, source_id,
                title, description, agency_name, naics_codes,
                acquisition_phase, set_aside_type, contract_type, contract_vehicle,
                estimated_solicitation_date, fiscal_year, estimated_award_quarter,
                dollar_range, pop_start_date, pop_end_date,
                pop_city, pop_state, pop_country,
                poc_name, poc_email, sbs_name, sbs_email,
                incumbent_contractor, source_url,
                first_seen_at, last_updated_at, change_hash,
                indexed_at, created_at, updated_at
            FROM unified_forecasts
            WHERE {where_clause}
            ORDER BY {sort_column} {sort_dir} {null_handling}
            LIMIT {limit} OFFSET {offset}
        """)

        result = await session.execute(data_sql)
        rows = result.fetchall()

        # Convert to dicts
        forecasts = []
        for row in rows:
            forecasts.append({
                "id": str(row.id),
                "organization_id": str(row.organization_id),
                "sync_id": str(row.sync_id),
                "source_type": row.source_type,
                "source_id": row.source_id,
                "title": row.title,
                "description": row.description,
                "agency_name": row.agency_name,
                "naics_codes": row.naics_codes,
                "acquisition_phase": row.acquisition_phase,
                "set_aside_type": row.set_aside_type,
                "contract_type": row.contract_type,
                "contract_vehicle": row.contract_vehicle,
                "estimated_solicitation_date": row.estimated_solicitation_date.isoformat() if row.estimated_solicitation_date else None,
                "fiscal_year": row.fiscal_year,
                "estimated_award_quarter": row.estimated_award_quarter,
                "dollar_range": row.dollar_range,
                "pop_start_date": row.pop_start_date.isoformat() if row.pop_start_date else None,
                "pop_end_date": row.pop_end_date.isoformat() if row.pop_end_date else None,
                "pop_city": row.pop_city,
                "pop_state": row.pop_state,
                "pop_country": row.pop_country,
                "poc_name": row.poc_name,
                "poc_email": row.poc_email,
                "sbs_name": row.sbs_name,
                "sbs_email": row.sbs_email,
                "incumbent_contractor": row.incumbent_contractor,
                "source_url": row.source_url,
                "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
                "last_updated_at": row.last_updated_at.isoformat() if row.last_updated_at else None,
                "indexed_at": row.indexed_at.isoformat() if row.indexed_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            })

        return forecasts, total

    async def get_forecast(
        self,
        session: AsyncSession,
        organization_id: UUID,
        source_type: str,
        source_id: str,
    ) -> Optional[Any]:
        """
        Get a forecast by source type and native source ID.

        Args:
            session: Database session
            organization_id: Organization UUID
            source_type: Source type (ag, apfs, state)
            source_id: Native ID (nid for AG, apfs_number for APFS, row_hash for State)

        Returns:
            Forecast model instance or None
        """
        model = SOURCE_MODELS.get(source_type)
        if not model:
            logger.warning(f"Invalid source_type: {source_type}")
            return None

        # Map source_type to the correct ID field
        if source_type == "ag":
            id_field = model.nid
        elif source_type == "apfs":
            id_field = model.apfs_number
        elif source_type == "state":
            id_field = model.row_hash
        else:
            return None

        result = await session.execute(
            select(model)
            .where(model.organization_id == organization_id)
            .where(id_field == source_id)
        )
        return result.scalar_one_or_none()

    async def get_forecast_by_id(
        self,
        session: AsyncSession,
        forecast_id: UUID,
        source_type: str,
    ) -> Optional[Any]:
        """
        Get a forecast by internal UUID from source-specific table.

        Args:
            session: Database session
            forecast_id: Forecast UUID
            source_type: Source type (ag, apfs, state)

        Returns:
            Forecast model instance or None
        """
        model = SOURCE_MODELS.get(source_type)
        if not model:
            logger.warning(f"Invalid source_type: {source_type}")
            return None

        result = await session.execute(
            select(model).where(model.id == forecast_id)
        )
        return result.scalar_one_or_none()

    async def get_forecast_by_uuid(
        self,
        session: AsyncSession,
        organization_id: UUID,
        forecast_id: UUID,
    ) -> tuple[Optional[Any], Optional[str]]:
        """
        Get a forecast by UUID, searching across all source tables.

        Args:
            session: Database session
            organization_id: Organization UUID
            forecast_id: Forecast UUID

        Returns:
            Tuple of (forecast model instance, source_type) or (None, None)
        """
        # Search each table in order
        for source_type, model in SOURCE_MODELS.items():
            result = await session.execute(
                select(model)
                .where(model.id == forecast_id)
                .where(model.organization_id == organization_id)
            )
            forecast = result.scalar_one_or_none()
            if forecast:
                return forecast, source_type

        return None, None

    async def get_stats(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> Dict[str, Any]:
        """
        Get statistics for forecasts across all sources.

        Returns:
            Dictionary with counts by source, fiscal year distribution, etc.
        """
        stats = {
            "by_source": {},
            "by_fiscal_year": {},
            "total": 0,
        }

        # Count by source type
        for source in ["ag", "apfs", "state"]:
            count_sql = text(f"""
                SELECT COUNT(*) FROM unified_forecasts
                WHERE organization_id = '{organization_id}' AND source_type = '{source}'
            """)
            result = await session.execute(count_sql)
            stats["by_source"][source] = result.scalar_one()

        stats["total"] = sum(stats["by_source"].values())

        # Count by fiscal year (top 5 years)
        fy_sql = text(f"""
            SELECT fiscal_year, COUNT(*) as count
            FROM unified_forecasts
            WHERE organization_id = '{organization_id}' AND fiscal_year IS NOT NULL
            GROUP BY fiscal_year
            ORDER BY fiscal_year DESC
            LIMIT 5
        """)
        fy_result = await session.execute(fy_sql)
        stats["by_fiscal_year"] = {row.fiscal_year: row.count for row in fy_result.fetchall()}

        return stats

    async def get_recent_changes(
        self,
        session: AsyncSession,
        organization_id: UUID,
        since_hours: int = 24,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get recently changed forecasts.

        Args:
            session: Database session
            organization_id: Organization UUID
            since_hours: Look back this many hours
            limit: Maximum records to return

        Returns:
            List of forecast dicts with change info
        """
        sql = text(f"""
            SELECT
                id, source_type, source_id, title, agency_name,
                first_seen_at, last_updated_at, change_hash
            FROM unified_forecasts
            WHERE organization_id = '{organization_id}'
                AND last_updated_at >= NOW() - INTERVAL '{since_hours} hours'
            ORDER BY last_updated_at DESC
            LIMIT {limit}
        """)

        result = await session.execute(sql)
        rows = result.fetchall()

        return [
            {
                "id": str(row.id),
                "source_type": row.source_type,
                "source_id": row.source_id,
                "title": row.title,
                "agency_name": row.agency_name,
                "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
                "last_updated_at": row.last_updated_at.isoformat() if row.last_updated_at else None,
                "is_new": row.first_seen_at and row.first_seen_at == row.last_updated_at,
            }
            for row in rows
        ]


# Singleton instance
forecast_service = ForecastService()
