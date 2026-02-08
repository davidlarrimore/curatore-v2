"""
APFS Pull Service for DHS Acquisition Forecast Data Ingestion.

Handles fetching forecast data from the DHS APFS API. Unlike AG, APFS uses
a single-phase bulk API that returns all records in one response. All
filtering is performed client-side.

Key Features:
- Single-phase bulk ingestion (no pagination)
- Client-side filtering based on sync configuration
- Automatic upsert with change detection
- Full record data available directly

API Endpoint:
- GET https://apfs-cloud.dhs.gov/api/forecast/

Usage:
    from app.connectors.dhs_apfs.apfs_pull_service import apfs_pull_service

    # Pull forecasts for a sync configuration
    result = await apfs_pull_service.pull_forecasts(
        session=session,
        sync_id=sync_id,
        organization_id=org_id,
        run_id=run_id,
    )
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from .apfs_forecast_service import apfs_forecast_service
from app.core.shared.forecast_sync_service import forecast_sync_service
from app.core.shared.run_log_service import run_log_service
from app.core.search.pg_index_service import pg_index_service

logger = logging.getLogger("curatore.apfs_pull_service")


# APFS API endpoint
APFS_API_URL = "https://apfs-cloud.dhs.gov/api/forecast/"


class ApfsPullService:
    """
    Service for pulling data from DHS APFS API.

    Implements single-phase bulk ingestion with client-side filtering.
    """

    def __init__(self):
        self.api_url = APFS_API_URL
        self.timeout = 120  # Longer timeout for bulk response

    async def pull_forecasts(
        self,
        session,
        sync_id: UUID,
        organization_id: UUID,
        run_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Pull all forecasts for a sync configuration.

        Fetches all records from APFS API, applies client-side filters,
        and upserts matching records.

        Args:
            session: Database session
            sync_id: ForecastSync UUID
            organization_id: Organization UUID
            run_id: Optional Run UUID for logging

        Returns:
            Dictionary with pull statistics
        """
        sync = await forecast_sync_service.get_sync(session, sync_id)
        if not sync:
            raise ValueError(f"ForecastSync {sync_id} not found")

        if sync.source_type != "apfs":
            raise ValueError(f"ForecastSync {sync_id} is not an APFS sync")

        filter_config = sync.filter_config or {}

        stats = {
            "total_fetched": 0,
            "total_filtered": 0,
            "total_processed": 0,
            "created": 0,
            "updated": 0,
            "errors": 0,
            "error_details": [],
        }

        try:
            # Fetch all records from APFS
            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "fetch_start",
                    "Fetching all records from APFS API"
                )

            records = await self._fetch_all_records()
            stats["total_fetched"] = len(records)

            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "fetch_complete",
                    f"Fetched {len(records)} records from APFS"
                )

            # Apply client-side filters
            filtered_records = self._apply_filters(records, filter_config)
            stats["total_filtered"] = len(filtered_records)

            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "filter_complete",
                    f"After filtering: {len(filtered_records)} records match criteria"
                )

            # Process each record
            for i, record in enumerate(filtered_records):
                try:
                    # Parse and upsert
                    forecast_data = self._parse_record(record)
                    forecast, is_new = await apfs_forecast_service.upsert_forecast(
                        session=session,
                        organization_id=organization_id,
                        sync_id=sync_id,
                        **forecast_data,
                    )

                    # Index to search
                    naics_codes = None
                    if forecast.naics_code:
                        naics_codes = [{
                            "code": forecast.naics_code,
                            "description": forecast.naics_description
                        }]

                    await pg_index_service.index_forecast(
                        session=session,
                        organization_id=organization_id,
                        forecast_id=forecast.id,
                        source_type="apfs",
                        source_id=forecast.apfs_number,
                        title=forecast.title,
                        description=forecast.description,
                        agency_name="Department of Homeland Security",
                        naics_codes=naics_codes,
                        set_aside_type=forecast.small_business_set_aside,
                        fiscal_year=forecast.fiscal_year,
                        estimated_award_quarter=forecast.award_quarter,
                    )

                    if is_new:
                        stats["created"] += 1
                    else:
                        stats["updated"] += 1

                    stats["total_processed"] += 1

                    # Commit every 50 records to save progress
                    if (i + 1) % 50 == 0:
                        await session.commit()

                    # Log progress every 100 records
                    if run_id and (i + 1) % 100 == 0:
                        await run_log_service.log_event(
                            session, run_id, "INFO", "progress",
                            f"Processed {i + 1}/{len(filtered_records)} records"
                        )

                except Exception as e:
                    # Rollback to recover session state after error
                    await session.rollback()
                    stats["errors"] += 1
                    apfs_number = record.get("apfs_number", "unknown")
                    error_msg = str(e)[:200]  # Truncate long errors
                    stats["error_details"].append(f"Error processing {apfs_number}: {error_msg}")
                    logger.error(f"Error processing APFS record {apfs_number}: {e}")

            # Final commit for any remaining records
            await session.commit()

            # Update sync stats
            count = await apfs_forecast_service.count_by_sync(session, sync_id)
            await forecast_sync_service.update_forecast_count(session, sync_id, count)

            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "complete",
                    f"Completed: {stats['created']} created, {stats['updated']} updated, {stats['errors']} errors"
                )

        except Exception as e:
            stats["errors"] += 1
            stats["error_details"].append(f"Pull failed: {str(e)}")
            logger.error(f"APFS pull failed for sync {sync_id}: {e}")
            raise

        return stats

    async def _fetch_all_records(self) -> List[Dict[str, Any]]:
        """
        Fetch all records from APFS API.

        Returns:
            List of forecast record dicts
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(self.api_url)
            response.raise_for_status()
            data = response.json()

        # API returns array directly
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "data" in data:
            return data["data"]
        else:
            logger.warning(f"Unexpected APFS response format: {type(data)}")
            return []

    def _apply_filters(
        self,
        records: List[Dict[str, Any]],
        filter_config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Apply client-side filters to records.

        Args:
            records: List of raw records
            filter_config: Filter configuration from sync

        Returns:
            Filtered list of records
        """
        # Extract filter criteria
        organizations = filter_config.get("organizations", [])
        fiscal_years = filter_config.get("fiscal_years", [])
        naics_codes = filter_config.get("naics_codes", [])
        contract_statuses = filter_config.get("contract_statuses", [])

        # If no filters, return all
        if not any([organizations, fiscal_years, naics_codes, contract_statuses]):
            return records

        filtered = []
        for record in records:
            # Check organization filter
            if organizations:
                org = record.get("organization", "")
                if org not in organizations:
                    continue

            # Check fiscal year filter
            if fiscal_years:
                fy = record.get("fiscal_year")
                if fy not in fiscal_years:
                    continue

            # Check NAICS filter
            if naics_codes:
                naics = record.get("naics", {})
                naics_code = naics.get("code") if isinstance(naics, dict) else str(naics)
                if not any(code in str(naics_code) for code in naics_codes):
                    continue

            # Check contract status filter
            if contract_statuses:
                status = record.get("contract_status", "")
                if status not in contract_statuses:
                    continue

            filtered.append(record)

        return filtered

    def _parse_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse APFS API record into forecast fields.

        Args:
            record: Raw record from API

        Returns:
            Dictionary of forecast fields for upsert
        """
        # Extract values with safe defaults
        apfs_number = str(record.get("apfs_number", ""))
        apfs_id = record.get("id")

        # Core fields
        title = record.get("requirements_title", "Untitled Forecast")
        description = record.get("requirement", "")

        # Organization/Component
        component = record.get("organization", "")
        mission = record.get("mission", "")

        # NAICS - handle both dict format and string format
        naics_raw = record.get("naics", {})
        if isinstance(naics_raw, dict):
            naics_code = naics_raw.get("code", "")
            naics_description = naics_raw.get("description", "")
        elif naics_raw:
            # String format: "315225 - Men's and Boys' Cut and Sew Work Clothing"
            naics_str = str(naics_raw)
            if " - " in naics_str:
                parts = naics_str.split(" - ", 1)
                naics_code = parts[0].strip()[:20]  # Ensure max 20 chars
                naics_description = parts[1].strip() if len(parts) > 1 else None
            else:
                naics_code = naics_str[:20]  # Ensure max 20 chars
                naics_description = None
        else:
            naics_code = None
            naics_description = None

        # Contract details
        contract_type = record.get("contract_type", {})
        if isinstance(contract_type, dict):
            contract_type = contract_type.get("display_name", "")

        contract_vehicle = record.get("contract_vehicle", {})
        if isinstance(contract_vehicle, dict):
            contract_vehicle = contract_vehicle.get("display_name", "")

        contract_status = record.get("contract_status", {})
        if isinstance(contract_status, dict):
            contract_status = contract_status.get("display_name", "")

        competition_type = record.get("competitive", {})
        if isinstance(competition_type, dict):
            competition_type = competition_type.get("display_name", "")

        # Small business
        small_business_program = record.get("small_business_program", {})
        if isinstance(small_business_program, dict):
            small_business_program = small_business_program.get("display_name", "")

        small_business_set_aside = record.get("small_business_set_aside", {})
        if isinstance(small_business_set_aside, dict):
            small_business_set_aside = small_business_set_aside.get("display_name", "")
        elif isinstance(small_business_set_aside, bool):
            # API sometimes returns True/False instead of dict - convert to string
            small_business_set_aside = "Yes" if small_business_set_aside else None
        elif small_business_set_aside is not None:
            small_business_set_aside = str(small_business_set_aside)

        # Financial
        dollar_range = record.get("dollar_range", {})
        if isinstance(dollar_range, dict):
            dollar_range = dollar_range.get("display_name", "")

        # Timeline
        fiscal_year = record.get("fiscal_year")
        award_quarter = record.get("award_quarter", {})
        if isinstance(award_quarter, dict):
            award_quarter = award_quarter.get("display_name", "")

        anticipated_award_date = self._parse_date(record.get("anticipated_award_date"))
        estimated_solicitation_date = self._parse_date(record.get("estimated_solicitation_release_date"))
        pop_start_date = self._parse_date(record.get("estimated_period_of_performance_start"))
        pop_end_date = self._parse_date(record.get("estimated_period_of_performance_end"))

        # Offices
        requirements_office = record.get("requirements_office", "")
        contracting_office = record.get("contracting_office", "")

        # Contacts - requirements contact
        poc_name = record.get("requirements_contact_name", "")
        poc_email = record.get("requirements_contact_email", "")
        poc_phone = record.get("requirements_contact_phone", "")

        # Alternate contact
        alt_contact_name = record.get("alternate_contact_name", "")
        alt_contact_email = record.get("alternate_contact_email", "")

        # Small business coordinator
        sbs_name = record.get("sbs_coordinator_name", "")
        sbs_email = record.get("sbs_coordinator_email", "")
        sbs_phone = record.get("sbs_coordinator_phone", "")

        # State
        current_state = record.get("current_state", {})
        if isinstance(current_state, dict):
            current_state = current_state.get("display_name", "")

        published_date = self._parse_date(record.get("published_date"))

        return {
            "apfs_number": apfs_number,
            "apfs_id": apfs_id,
            "title": title,
            "description": description,
            "component": component,
            "mission": mission,
            "naics_code": naics_code,
            "naics_description": naics_description,
            "contract_type": contract_type,
            "contract_vehicle": contract_vehicle,
            "contract_status": contract_status,
            "competition_type": competition_type,
            "small_business_program": small_business_program,
            "small_business_set_aside": small_business_set_aside,
            "dollar_range": dollar_range,
            "fiscal_year": fiscal_year,
            "award_quarter": award_quarter,
            "anticipated_award_date": anticipated_award_date,
            "estimated_solicitation_date": estimated_solicitation_date,
            "pop_start_date": pop_start_date,
            "pop_end_date": pop_end_date,
            "requirements_office": requirements_office,
            "contracting_office": contracting_office,
            "poc_name": poc_name,
            "poc_email": poc_email,
            "poc_phone": poc_phone,
            "alt_contact_name": alt_contact_name,
            "alt_contact_email": alt_contact_email,
            "sbs_name": sbs_name,
            "sbs_email": sbs_email,
            "sbs_phone": sbs_phone,
            "current_state": current_state,
            "published_date": published_date,
            "raw_data": record,
        }

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse a date string to date object."""
        if not date_str:
            return None

        try:
            # Try ISO format first
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.date() if hasattr(dt, 'date') else dt
        except ValueError:
            pass

        try:
            # Try common date formats
            for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"]:
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
        except Exception:
            pass

        return None


# Singleton instance
apfs_pull_service = ApfsPullService()
