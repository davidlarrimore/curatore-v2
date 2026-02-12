"""
AG Pull Service for GSA Acquisition Gateway Forecast Data Ingestion.

Handles fetching forecast data from the GSA Acquisition Gateway API using
a two-phase ingestion process:
1. List API for discovery and pagination (with server-side agency filter)
2. Detail API for complete record data
3. Client-side NAICS code filtering (like SAM.gov pattern)

Key Features:
- Two-phase ingestion (list + detail)
- Server-side agency filtering via AG API
- Client-side NAICS filtering using standard 6-digit codes
- Automatic upsert with change detection
- Rate limiting between API calls

API Endpoints:
- List: GET https://ag-dashboard.acquisitiongateway.gov/api/v3.0/resources/forecast
- Detail: GET https://ag-dashboard.acquisitiongateway.gov/api/v3.0/resources/forecast/details/{nid}

Usage:
    from app.connectors.gsa_gateway.ag_pull_service import ag_pull_service

    # Pull forecasts for a sync configuration
    result = await ag_pull_service.pull_forecasts(
        session=session,
        sync_id=sync_id,
        organization_id=org_id,
        run_id=run_id,
    )
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from app.core.search.pg_index_service import pg_index_service
from app.core.shared.forecast_sync_service import forecast_sync_service
from app.core.shared.run_log_service import run_log_service
from app.core.utils.text_utils import html_to_text

from .ag_forecast_service import ag_forecast_service

logger = logging.getLogger("curatore.ag_pull_service")


# AG Forecast API endpoints
AG_API_BASE_URL = "https://ag-dashboard.acquisitiongateway.gov/api/v3.0/resources/forecast"
AG_DETAIL_URL = f"{AG_API_BASE_URL}/details"

# Page size is fixed by AG API
AG_PAGE_SIZE = 25


class AgPullService:
    """
    Service for pulling data from GSA Acquisition Gateway API.

    Implements two-phase ingestion: list for discovery, detail for complete data.
    """

    def __init__(self):
        self.base_url = AG_API_BASE_URL
        self.detail_url = AG_DETAIL_URL
        self.timeout = 60
        self.rate_limit_delay = 0.3  # Delay between requests in seconds

    async def pull_forecasts(
        self,
        session,
        sync_id: UUID,
        organization_id: UUID,
        run_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Pull all forecasts for a sync configuration.

        Uses streaming approach: processes each page of records as it's fetched,
        rather than collecting all records first. This is faster and more memory efficient.

        For each record:
        1. Fetch detail from API
        2. Skip if NAICS filter configured and record doesn't match (no detail API call needed for filtering)
        3. Upsert matching records

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

        if sync.source_type != "ag":
            raise ValueError(f"ForecastSync {sync_id} is not an AG sync")

        filter_config = sync.filter_config or {}

        stats = {
            "total_listed": 0,
            "total_processed": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,  # Records skipped by NAICS filter (no detail fetch needed)
            "errors": 0,
            "error_details": [],
        }

        # Get NAICS filter codes for client-side filtering
        naics_filter_codes = filter_config.get("naics_codes", [])

        try:
            if run_id:
                filter_msg = ""
                if naics_filter_codes:
                    filter_msg = f" (NAICS filter: {', '.join(naics_filter_codes)})"
                await run_log_service.log_event(
                    session, run_id, "INFO", "sync_start",
                    f"Starting AG forecast sync{filter_msg}"
                )

            # Stream through pages, processing records as we go
            processed_count = 0
            async for nid, list_naics in self._stream_forecast_nids(session, filter_config, run_id, stats):
                try:
                    # Early NAICS filtering from list API data (avoids detail API call)
                    if naics_filter_codes and list_naics:
                        if not self._matches_naics_filter(list_naics, naics_filter_codes):
                            stats["skipped"] += 1
                            continue

                    # Fetch detail
                    detail = await self._fetch_detail(nid)
                    if not detail:
                        stats["errors"] += 1
                        stats["error_details"].append(f"No detail for nid {nid}")
                        continue

                    # Parse detail
                    forecast_data = self._parse_detail(detail)

                    # Double-check NAICS filter with full detail data (list may have incomplete NAICS)
                    if naics_filter_codes:
                        if not self._matches_naics_filter(
                            forecast_data.get("naics_codes"),
                            naics_filter_codes,
                        ):
                            stats["skipped"] += 1
                            continue

                    # Upsert the forecast
                    forecast, is_new = await ag_forecast_service.upsert_forecast(
                        session=session,
                        organization_id=organization_id,
                        sync_id=sync_id,
                        **forecast_data,
                    )

                    # Index to search
                    await pg_index_service.index_forecast(
                        session=session,
                        organization_id=organization_id,
                        forecast_id=forecast.id,
                        source_type="ag",
                        source_id=forecast.nid,
                        title=forecast.title,
                        description=forecast.description,
                        agency_name=forecast.agency_name,
                        naics_codes=forecast.naics_codes,
                        set_aside_type=forecast.set_aside_type,
                        fiscal_year=forecast.estimated_award_fy,
                        estimated_award_quarter=forecast.estimated_award_quarter,
                        url=forecast.source_url,
                    )

                    if is_new:
                        stats["created"] += 1
                    else:
                        stats["updated"] += 1

                    stats["total_processed"] += 1
                    processed_count += 1

                    # Log progress every 25 records
                    if run_id and processed_count % 25 == 0:
                        await run_log_service.log_event(
                            session, run_id, "INFO", "progress",
                            f"Processed {processed_count} records ({stats['skipped']} skipped)"
                        )

                    # Rate limiting
                    await asyncio.sleep(self.rate_limit_delay)

                except Exception as e:
                    stats["errors"] += 1
                    stats["error_details"].append(f"Error processing nid {nid}: {str(e)}")
                    logger.error(f"Error processing AG forecast nid {nid}: {e}")

            # Update sync stats
            count = await ag_forecast_service.count_by_sync(session, sync_id)
            await forecast_sync_service.update_forecast_count(session, sync_id, count)

            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "sync_complete",
                    f"Completed: {stats['total_listed']} listed, {stats['created']} created, "
                    f"{stats['updated']} updated, {stats['skipped']} skipped, {stats['errors']} errors"
                )

        except Exception as e:
            stats["errors"] += 1
            stats["error_details"].append(f"Pull failed: {str(e)}")
            logger.error(f"AG pull failed for sync {sync_id}: {e}")
            raise

        return stats

    async def _stream_forecast_nids(
        self,
        session,
        filter_config: Dict[str, Any],
        run_id: Optional[UUID],
        stats: Dict[str, Any],
    ):
        """
        Stream forecast NIDs from the list API, yielding each one as it's found.

        This is an async generator that paginates through the list API and yields
        (nid, naics_codes) tuples for each record. The naics_codes from the list
        API can be used for early filtering before fetching the detail.

        Args:
            session: Database session
            filter_config: Filter configuration from sync
            run_id: Optional Run UUID for logging
            stats: Stats dict to update total_listed

        Yields:
            Tuple of (nid: str, naics_codes: list or None)
        """
        page = 1
        total_pages = None
        total_records = 0

        while True:
            url = self._build_list_url(filter_config, page)

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

            listing = data.get("listing", {})
            records = listing.get("data", {})

            # Handle empty list response
            if isinstance(records, list):
                records = {}

            # First page: get total and log
            if total_pages is None:
                total_str = listing.get("total", "0")
                total_records = int(total_str) if total_str else 0
                total_pages = (total_records + AG_PAGE_SIZE - 1) // AG_PAGE_SIZE if total_records > 0 else 1

                if run_id:
                    await run_log_service.log_event(
                        session, run_id, "INFO", "pagination",
                        f"Found {total_records} records across {total_pages} pages"
                    )

            # Yield each record from this page
            for nid, record in records.items():
                stats["total_listed"] += 1

                # Extract NAICS from list data for early filtering
                naics_codes = None
                naics_raw = record.get("naics", [])
                if naics_raw and isinstance(naics_raw, list):
                    naics_codes = []
                    for n in naics_raw:
                        if isinstance(n, dict):
                            naics_codes.append({
                                "code": n.get("code"),
                                "description": n.get("description"),
                            })

                yield nid, naics_codes

            # Log page progress
            if run_id and page % 3 == 0:
                await run_log_service.log_event(
                    session, run_id, "INFO", "page_progress",
                    f"Fetched page {page}/{total_pages}"
                )

            # Check if more pages
            if page >= total_pages:
                break

            page += 1
            await asyncio.sleep(self.rate_limit_delay)

    def _build_list_url(
        self,
        filter_config: Dict[str, Any],
        page: int = 1,
    ) -> str:
        """
        Build full URL for list API with query parameters.

        Note: We build the URL manually because httpx URL-encodes brackets
        in parameter names (e.g., filter[x] becomes filter%5Bx%5D), but the
        AG API expects unencoded brackets.

        Server-side filters (AG API parameters):
        - Agency filter: Uses AG taxonomy ID

        Client-side filters (applied after fetching):
        - NAICS codes: Standard 6-digit codes (not AG taxonomy IDs)

        Args:
            filter_config: Filter configuration from sync
            page: Page number (1-based)

        Returns:
            Full URL string with query parameters
        """
        params = [f"page={page}"]

        # Agency filter (single value) - server-side filtering
        agency_ids = filter_config.get("agency_ids", [])
        if agency_ids and len(agency_ids) == 1:
            params.append(f"filter[field_result_id_target_id]={agency_ids[0]}")

        # Award status filter (single value, string) - server-side filtering
        award_status = filter_config.get("award_status")
        if award_status:
            # URL-encode the status value but not the brackets
            from urllib.parse import quote
            params.append(f"filter[field_award_status_target_id]={quote(str(award_status))}")

        # Acquisition strategy filter (multi-value) - server-side filtering
        strategy_ids = filter_config.get("strategy_ids", [])
        for strategy_id in strategy_ids:
            params.append(f"filter[field_acquisition_strategy_target_id][]={strategy_id}")

        # Note: NAICS filtering is done client-side using standard NAICS codes
        # (not AG taxonomy IDs), similar to SAM.gov pattern

        query_string = "&".join(params)
        return f"{self.base_url}?{query_string}"

    def _matches_naics_filter(
        self,
        forecast_naics_codes: Optional[List[Dict[str, Any]]],
        filter_naics_codes: List[str],
    ) -> bool:
        """
        Check if a forecast matches the NAICS code filter.

        Uses standard 6-digit NAICS codes for comparison, similar to SAM.gov.
        A match occurs when the forecast's NAICS code starts with any filter code.

        Examples:
            - Filter: ['541511'], Forecast: ['541511'] -> MATCH (exact)
            - Filter: ['5415'], Forecast: ['541511'] -> MATCH (forecast starts with filter)
            - Filter: ['541511'], Forecast: ['541512'] -> NO MATCH
            - Filter: ['541511'], Forecast: ['541310'] -> NO MATCH

        Args:
            forecast_naics_codes: NAICS codes from forecast (list of dicts with 'code' key)
            filter_naics_codes: Standard NAICS codes from filter config (e.g., ['541511', '541512'])

        Returns:
            True if forecast matches any of the filter NAICS codes (or if filter is empty)
        """
        # No filter = match all
        if not filter_naics_codes:
            return True

        # No NAICS on forecast = no match
        if not forecast_naics_codes:
            return False

        # Extract standard codes from forecast NAICS data
        forecast_codes = set()
        for naics in forecast_naics_codes:
            if isinstance(naics, dict):
                code = naics.get("code")
                if code:
                    code_str = str(code).strip()
                    if code_str:
                        forecast_codes.add(code_str)

        if not forecast_codes:
            return False

        # Normalize filter codes
        filter_codes_normalized = set()
        for code in filter_naics_codes:
            code_str = str(code).strip()
            if code_str:
                filter_codes_normalized.add(code_str)

        # Check for match: forecast code starts with filter code (or exact match)
        for filter_code in filter_codes_normalized:
            for forecast_code in forecast_codes:
                # Forecast code starts with filter code (or exact match)
                if forecast_code.startswith(filter_code):
                    return True

        return False

    async def _fetch_detail(self, nid: str) -> Optional[Dict[str, Any]]:
        """
        Fetch detail for a single forecast.

        Args:
            nid: AG record identifier

        Returns:
            Detail data dict or None if failed
        """
        url = f"{self.detail_url}/{nid}"
        params = {"nid": nid}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

            return data.get("details", {}).get("data", {})

        except Exception as e:
            logger.error(f"Failed to fetch detail for nid {nid}: {e}")
            return None

    def _parse_detail(self, detail: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse detail API response into forecast fields.

        AG API returns fields in array format: [{"value": "text", "tid": "123", ...}]
        Taxonomy fields include tid (taxonomy ID) and extra_fields.

        Args:
            detail: Raw detail data from API

        Returns:
            Dictionary of forecast fields for upsert
        """
        # Helper to extract value from AG's array format: [{"value": "text"}]
        def extract_value(field_data, default=None):
            if isinstance(field_data, list) and len(field_data) > 0:
                first_item = field_data[0]
                if isinstance(first_item, dict):
                    return first_item.get("value", default)
            elif isinstance(field_data, dict):
                return field_data.get("value", default)
            elif isinstance(field_data, str):
                return field_data
            return default

        # Helper to extract taxonomy ID from AG's array format
        def extract_tid(field_data, default=None):
            if isinstance(field_data, list) and len(field_data) > 0:
                first_item = field_data[0]
                if isinstance(first_item, dict):
                    return first_item.get("tid", default)
            return default

        nid = str(detail.get("nid", ""))

        # Title - AG API returns as [{"value": "Title"}]
        title = extract_value(detail.get("title"), "Untitled Forecast")

        # Description - in "body" field with HTML content
        body_data = detail.get("body", [])
        description = ""
        if isinstance(body_data, list) and len(body_data) > 0:
            raw_description = body_data[0].get("value", "")
            # Convert HTML to plain text for consistency with other forecast sources
            description = html_to_text(raw_description) if raw_description else ""

        # Agency - field_result_id contains agency name and tid
        agency_name = extract_value(detail.get("field_result_id"))
        agency_id = extract_tid(detail.get("field_result_id"))
        if agency_id:
            try:
                agency_id = int(agency_id)
            except (ValueError, TypeError):
                agency_id = None

        # Organization - field_organization
        org_name = extract_value(detail.get("field_organization"))

        # NAICS - field_naics_code array
        # Format: [{'value': '541519 Other Computer Related Services', 'tid': '1448', ...}]
        naics_raw = detail.get("field_naics_code", []) or []
        naics_codes = []
        for n in naics_raw if isinstance(naics_raw, list) else []:
            if isinstance(n, dict):
                value = n.get("value", "")
                if value:
                    # Parse "CODE DESCRIPTION" format (e.g., "541519 Other Computer Related Services")
                    parts = value.split(" ", 1)
                    code = parts[0].strip() if parts else None
                    naics_desc = parts[1].strip() if len(parts) > 1 else None
                    if code:
                        naics_codes.append({
                            "id": n.get("tid"),
                            "code": code,
                            "description": naics_desc,
                        })

        # Acquisition strategies - field_acquisition_strategy
        strategies_raw = detail.get("field_acquisition_strategy", []) or []
        acquisition_strategies = []
        for s in strategies_raw if isinstance(strategies_raw, list) else []:
            if isinstance(s, dict):
                acquisition_strategies.append({
                    "id": s.get("tid"),
                    "name": s.get("value"),
                })

        # Award status - field_award_status
        award_status = extract_value(detail.get("field_award_status"))

        # Procurement info from individual fields
        requirement_type = extract_value(detail.get("field_requirement_status"))
        procurement_method = extract_value(detail.get("field_procurement_method"))
        set_aside_type = extract_value(detail.get("field_type_of_awardee"))
        extent_competed = extract_value(detail.get("field_extent_competed"))
        listing_id = extract_value(detail.get("field_source_listing_id"))
        contract_type = extract_value(detail.get("field_contract_type"))

        # Timeline fields
        estimated_solicitation_date = self._parse_date(
            extract_value(detail.get("field_estimated_solicitation_dat"))
        )
        period_of_performance = extract_value(detail.get("field_period_of_performance"))

        # Fiscal year - field_estimated_award_fy
        estimated_award_fy = None
        fy_value = extract_value(detail.get("field_estimated_award_fy"))
        if fy_value:
            try:
                estimated_award_fy = int(fy_value)
            except (ValueError, TypeError):
                pass

        # Award quarter - field_estimated_award_fy_qtr (e.g., "4th (July 1 - September 30)")
        estimated_award_quarter = None
        qtr_value = extract_value(detail.get("field_estimated_award_fy_qtr"))
        if qtr_value:
            # Extract quarter number (e.g., "4th" -> "Q4")
            if qtr_value.startswith("1"):
                estimated_award_quarter = "Q1"
            elif qtr_value.startswith("2"):
                estimated_award_quarter = "Q2"
            elif qtr_value.startswith("3"):
                estimated_award_quarter = "Q3"
            elif qtr_value.startswith("4"):
                estimated_award_quarter = "Q4"
            else:
                estimated_award_quarter = qtr_value  # Keep original if can't parse

        # Contacts - field_point_of_contact_name/email, field_advisor_info_name/email (SBS)
        poc_name = extract_value(detail.get("field_point_of_contact_name"))
        poc_email = extract_value(detail.get("field_point_of_contact_email"))
        sbs_name = extract_value(detail.get("field_advisor_info_name"))
        sbs_email = extract_value(detail.get("field_advisor_info_email"))

        # Source URL
        source_url = f"https://acquisitiongateway.gov/forecast/resources/{nid}?_a^g_nid={nid}"

        return {
            "nid": nid,
            "title": title,
            "description": description,
            "agency_name": agency_name,
            "agency_id": agency_id,
            "organization_name": org_name,
            "naics_codes": naics_codes if naics_codes else None,
            "acquisition_phase": award_status,  # Use award_status as acquisition phase
            "acquisition_strategies": acquisition_strategies if acquisition_strategies else None,
            "award_status": award_status,
            "requirement_type": requirement_type,
            "procurement_method": procurement_method,
            "set_aside_type": set_aside_type,
            "extent_competed": extent_competed,
            "listing_id": listing_id,
            "estimated_solicitation_date": estimated_solicitation_date,
            "estimated_award_fy": estimated_award_fy,
            "estimated_award_quarter": estimated_award_quarter,
            "period_of_performance": period_of_performance,
            "poc_name": poc_name,
            "poc_email": poc_email,
            "sbs_name": sbs_name,
            "sbs_email": sbs_email,
            "source_url": source_url,
            "raw_data": detail,
        }

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse a date string to datetime."""
        if not date_str:
            return None

        try:
            # Try ISO format first
            return datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass

        try:
            # Try common date formats
            for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"]:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
        except Exception:
            pass

        return None


# Singleton instance
ag_pull_service = AgPullService()
