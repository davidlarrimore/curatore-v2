"""
State Pull Service for State Department Acquisition Forecast Data Ingestion.

Handles scraping the State Department website to find the current Excel forecast
file, downloading it, and parsing the rows into forecast records.

Key Features:
- Playwright-based scraping for JavaScript-rendered content
- Fallback to regex-based scraping if Playwright unavailable
- Excel file parsing with openpyxl
- Automatic row hash generation for upsert
- Change detection across file updates

Website:
- https://www.state.gov/procurement-forecast

Usage:
    from app.connectors.state_forecast.state_pull_service import state_pull_service

    # Pull forecasts for a sync configuration
    result = await state_pull_service.pull_forecasts(
        session=session,
        sync_id=sync_id,
        organization_id=org_id,
        run_id=run_id,
    )
"""

import hashlib
import io
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.scrape.playwright_client import PlaywrightClient, PlaywrightError
from app.core.search.pg_index_service import pg_index_service
from app.core.shared.forecast_sync_service import forecast_sync_service
from app.core.shared.run_log_service import run_log_service

from .state_forecast_service import state_forecast_service

logger = logging.getLogger("curatore.state_pull_service")


# State Department procurement forecast page
STATE_FORECAST_URL = "https://www.state.gov/procurement-forecast"

# Common Excel file patterns on the page
EXCEL_PATTERNS = [
    r'href="([^"]*\.xlsx[^"]*)"',
    r'href="([^"]*procurement[^"]*forecast[^"]*\.xlsx)"',
    r'href="([^"]*FY\d{2}[^"]*\.xlsx)"',
]


class StatePullService:
    """
    Service for pulling data from State Department procurement forecast.

    Implements web scraping + Excel parsing workflow.
    """

    def __init__(self):
        self.page_url = STATE_FORECAST_URL
        self.timeout = 120

    async def pull_forecasts(
        self,
        session: AsyncSession,
        sync_id: UUID,
        organization_id: UUID,
        run_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Pull all forecasts for a sync configuration.

        Process:
        1. Fetch the State Dept procurement forecast page
        2. Find the Excel download link
        3. Download and parse the Excel file
        4. Upsert each row as a forecast record

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

        if sync.source_type != "state":
            raise ValueError(f"ForecastSync {sync_id} is not a State sync")

        # Get filter config for NAICS filtering
        filter_config = sync.filter_config or {}
        naics_filter = filter_config.get("naics_codes", [])

        stats = {
            "excel_url": None,
            "scrape_method": None,
            "total_rows": 0,
            "total_processed": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "filtered_out": 0,
            "errors": 0,
            "error_details": [],
        }

        try:
            # Step 1: Find Excel download link using Playwright (with regex fallback)
            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "scrape_start",
                    f"Scraping {self.page_url} for Excel link (Playwright with regex fallback)"
                )

            excel_url, scrape_method = await self._find_excel_link(
                session=session,
                organization_id=organization_id,
                run_id=run_id,
            )
            if not excel_url:
                raise ValueError("Could not find Excel download link on State Dept page")

            stats["excel_url"] = excel_url
            stats["scrape_method"] = scrape_method

            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "excel_found",
                    f"Found Excel file via {scrape_method}: {excel_url}"
                )

            # Step 2: Download Excel file
            excel_content = await self._download_excel(excel_url)
            filename = excel_url.split("/")[-1].split("?")[0]

            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "download_complete",
                    f"Downloaded {len(excel_content)} bytes"
                )

            # Step 3: Parse Excel file
            rows = self._parse_excel(excel_content)
            stats["total_rows"] = len(rows)

            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "parse_complete",
                    f"Parsed {len(rows)} data rows"
                )

            # Step 4: Process each row
            for i, row in enumerate(rows):
                try:
                    # Skip empty rows - check multiple possible title columns
                    title_value = (
                        row.get("requirement_title") or
                        row.get("title") or
                        row.get("description") or
                        row.get("requirement") or
                        row.get("requirement_description")
                    )
                    if not title_value or not str(title_value).strip():
                        stats["skipped"] += 1
                        continue

                    # Generate row hash for identity
                    row_hash = self._compute_row_hash(row)

                    # Parse and upsert
                    forecast_data = self._parse_row(row, filename, i + 2)  # +2 for header and 0-index
                    forecast_data["row_hash"] = row_hash

                    # Apply NAICS filter if configured
                    if naics_filter:
                        forecast_naics = forecast_data.get("naics_code", "") or ""
                        if not self._matches_naics_filter(forecast_naics, naics_filter):
                            stats["filtered_out"] += 1
                            continue

                    forecast, is_new = await state_forecast_service.upsert_forecast(
                        session=session,
                        organization_id=organization_id,
                        sync_id=sync_id,
                        **forecast_data,
                    )

                    # Index to search
                    naics_codes = None
                    if forecast.naics_code:
                        naics_codes = [{"code": forecast.naics_code}]

                    await pg_index_service.index_forecast(
                        session=session,
                        organization_id=organization_id,
                        forecast_id=forecast.id,
                        source_type="state",
                        source_id=forecast.row_hash,
                        title=forecast.title,
                        description=forecast.description,
                        agency_name="Department of State",
                        naics_codes=naics_codes,
                        set_aside_type=forecast.set_aside_type,
                        fiscal_year=forecast.fiscal_year,
                        estimated_award_quarter=forecast.estimated_award_quarter,
                    )

                    if is_new:
                        stats["created"] += 1
                    else:
                        stats["updated"] += 1

                    stats["total_processed"] += 1

                    # Log progress every 50 records
                    if run_id and (i + 1) % 50 == 0:
                        await run_log_service.log_event(
                            session, run_id, "INFO", "progress",
                            f"Processed {i + 1}/{len(rows)} rows"
                        )

                except Exception as e:
                    stats["errors"] += 1
                    stats["error_details"].append(f"Error processing row {i + 2}: {str(e)}")
                    logger.error(f"Error processing State forecast row {i + 2}: {e}")

            # Update sync stats
            count = await state_forecast_service.count_by_sync(session, sync_id)
            await forecast_sync_service.update_forecast_count(session, sync_id, count)

            if run_id:
                filtered_msg = f", {stats['filtered_out']} filtered" if stats['filtered_out'] else ""
                await run_log_service.log_event(
                    session, run_id, "INFO", "complete",
                    f"Completed: {stats['created']} created, {stats['updated']} updated, "
                    f"{stats['skipped']} skipped{filtered_msg}, {stats['errors']} errors"
                )

        except Exception as e:
            stats["errors"] += 1
            stats["error_details"].append(f"Pull failed: {str(e)}")
            logger.error(f"State pull failed for sync {sync_id}: {e}")
            raise

        return stats

    async def _find_excel_link(
        self,
        session: Optional[AsyncSession] = None,
        organization_id: Optional[UUID] = None,
        run_id: Optional[UUID] = None,
    ) -> Tuple[Optional[str], str]:
        """
        Find the Excel download link using Playwright, with regex fallback.

        Tries Playwright first for JavaScript-rendered content, falls back
        to simple HTTP + regex if Playwright is unavailable or fails.

        Args:
            session: Database session for Playwright client
            organization_id: Organization UUID for Playwright config
            run_id: Optional run ID for logging

        Returns:
            Tuple of (Excel URL or None, method used: 'playwright' or 'regex')
        """
        # Try Playwright first if we have session/org context
        if session and organization_id:
            try:
                url = await self._find_excel_link_with_playwright(
                    session, organization_id, run_id
                )
                if url:
                    return url, "playwright"
            except Exception as e:
                logger.warning(f"Playwright scraping failed, falling back to regex: {e}")
                if run_id and session:
                    await run_log_service.log_event(
                        session, run_id, "WARNING", "playwright_fallback",
                        f"Playwright failed: {str(e)[:200]}. Using regex fallback."
                    )

        # Fallback to simple HTTP + regex
        url = await self._find_excel_link_with_regex()
        if url:
            return url, "regex"

        return None, "none"

    async def _find_excel_link_with_playwright(
        self,
        session: AsyncSession,
        organization_id: UUID,
        run_id: Optional[UUID] = None,
    ) -> Optional[str]:
        """
        Use Playwright to render the page and find Excel download link.

        Playwright handles JavaScript-rendered content that simple HTTP GET misses.

        Args:
            session: Database session
            organization_id: Organization UUID
            run_id: Optional run ID for logging

        Returns:
            Full URL to Excel file or None
        """
        client = await PlaywrightClient.from_database(organization_id, session)

        try:
            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "playwright_render",
                    f"Rendering {self.page_url} with Playwright"
                )

            # Render the page - wait for content to load
            # State Dept site may use JavaScript to populate download links
            result = await client.render_page(
                url=self.page_url,
                wait_for_selector="a[href*='.xlsx'], a[href*='.xls']",  # Wait for Excel links
                wait_timeout_ms=10000,  # 10 second wait for selector
                timeout_ms=60000,  # 60 second total timeout
                extract_documents=True,
                document_extensions=[".xlsx", ".xls"],
            )

            if run_id:
                await run_log_service.log_event(
                    session, run_id, "INFO", "playwright_complete",
                    f"Rendered in {result.render_time_ms}ms, found {len(result.document_links)} document links"
                )

            # Check document_links for Excel files
            for doc in result.document_links:
                if doc.extension.lower() in [".xlsx", ".xls"]:
                    url = doc.url
                    # Make absolute URL if relative
                    if not url.startswith("http"):
                        if url.startswith("/"):
                            url = f"https://www.state.gov{url}"
                        else:
                            url = f"https://www.state.gov/{url}"
                    logger.info(f"Found Excel via Playwright document_links: {url}")
                    return url

            # Also check regular links for Excel patterns
            for link in result.links:
                if ".xlsx" in link.url.lower() or ".xls" in link.url.lower():
                    url = link.url
                    if not url.startswith("http"):
                        if url.startswith("/"):
                            url = f"https://www.state.gov{url}"
                        else:
                            url = f"https://www.state.gov/{url}"
                    logger.info(f"Found Excel via Playwright links: {url}")
                    return url

            # Last resort: search the rendered HTML with regex
            for pattern in EXCEL_PATTERNS:
                matches = re.findall(pattern, result.html, re.IGNORECASE)
                if matches:
                    url = matches[0]
                    if not url.startswith("http"):
                        if url.startswith("/"):
                            url = f"https://www.state.gov{url}"
                        else:
                            url = f"https://www.state.gov/{url}"
                    logger.info(f"Found Excel via Playwright HTML regex: {url}")
                    return url

            logger.warning("No Excel link found in Playwright-rendered page")
            return None

        except PlaywrightError as e:
            logger.error(f"Playwright render failed: {e}")
            raise
        finally:
            await client.aclose()

    async def _find_excel_link_with_regex(self) -> Optional[str]:
        """
        Scrape the State Dept page with simple HTTP GET + regex.

        This is the fallback method when Playwright is unavailable.

        Returns:
            Full URL to Excel file or None
        """
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(self.page_url)
            response.raise_for_status()
            html = response.text

        # Try each pattern
        for pattern in EXCEL_PATTERNS:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                url = matches[0]
                # Make absolute URL if relative
                if not url.startswith("http"):
                    if url.startswith("/"):
                        url = f"https://www.state.gov{url}"
                    else:
                        url = f"https://www.state.gov/{url}"
                logger.info(f"Found Excel via regex fallback: {url}")
                return url

        return None

    async def _download_excel(self, url: str) -> bytes:
        """
        Download Excel file from URL.

        Args:
            url: Full URL to Excel file

        Returns:
            Excel file content as bytes
        """
        # State Dept website blocks requests without a browser User-Agent
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content

    def _parse_excel(self, content: bytes) -> List[Dict[str, Any]]:
        """
        Parse Excel file content into row dictionaries.

        Args:
            content: Excel file bytes

        Returns:
            List of row dictionaries
        """
        try:
            import openpyxl
        except ImportError:
            raise ImportError("openpyxl is required for Excel parsing. Install with: pip install openpyxl")

        # Load workbook from bytes
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        ws = wb.active

        rows = []
        headers = None

        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                # Header row - normalize column names
                headers = [self._normalize_header(str(h) if h else f"col_{j}") for j, h in enumerate(row)]
                continue

            # Skip completely empty rows
            if all(cell is None or str(cell).strip() == "" for cell in row):
                continue

            # Create row dict
            row_dict = {}
            for j, cell in enumerate(row):
                if j < len(headers):
                    row_dict[headers[j]] = cell

            rows.append(row_dict)

        return rows

    def _normalize_header(self, header: str) -> str:
        """Normalize column header to snake_case."""
        # Remove special characters, convert to lowercase
        header = re.sub(r"[^\w\s]", "", header)
        header = header.strip().lower()
        # Replace spaces with underscores
        header = re.sub(r"\s+", "_", header)
        return header

    def _compute_row_hash(self, row: Dict[str, Any]) -> str:
        """
        Compute hash to identify unique rows.

        Uses title + NAICS + fiscal_year + estimated_value as identity.
        """
        # Try multiple possible column names for each field
        title = (
            row.get("requirement_title") or
            row.get("title") or
            row.get("description") or
            row.get("requirement") or
            ""
        )
        naics = (
            row.get("naics_code") or
            row.get("naics") or
            row.get("primary_naics") or
            ""
        )
        fy = (
            row.get("fiscal_year") or
            row.get("fy") or
            row.get("award_fiscal_year") or
            ""
        )
        value = (
            row.get("estimated_value") or
            row.get("value") or
            row.get("dollar_value") or
            row.get("estimated_total_value") or
            ""
        )
        identity_fields = [str(title), str(naics), str(fy), str(value)]
        return hashlib.sha256("|".join(identity_fields).encode()).hexdigest()

    def _parse_row(
        self,
        row: Dict[str, Any],
        source_file: str,
        source_row: int,
    ) -> Dict[str, Any]:
        """
        Parse Excel row into forecast fields.

        Note: Column names may vary. This attempts to handle common variations.
        The State Dept Excel has specific column names that normalize to:
        - requirement_title, requirement_description, naics_code
        - place_of_performance_city/state/country
        - acquistion_phase (note: typo in original file - missing 'i')
        - estimated_contract_value, fiscal_year, etc.

        Args:
            row: Row dictionary from Excel
            source_file: Original filename
            source_row: Row number in Excel

        Returns:
            Dictionary of forecast fields for upsert
        """
        # Helper to get value from multiple possible column names
        def get_value(*keys, default=None):
            for key in keys:
                val = row.get(key)
                if val is not None and str(val).strip():
                    return val
            return default

        # Core fields
        title = str(get_value(
            "requirement_title", "title", "description", "requirement",
            default="Untitled"
        ))
        description = get_value(
            "requirement_description", "requirement_description_",  # trailing space normalizes
            "description", "details"
        )

        # NAICS
        naics_code = get_value("naics_code", "naics", "primary_naics")
        if naics_code:
            naics_code = str(naics_code).split()[0][:20]  # First code, max 20 chars

        # Place of performance (State Dept uses "place_of_performance_city" etc.)
        pop_city = get_value(
            "place_of_performance_city", "pop_city", "city"
        )
        pop_state = get_value(
            "place_of_performance_state", "pop_state", "state"
        )
        pop_country = get_value(
            "place_of_performance_country", "pop_country", "country"
        )

        # Acquisition details
        # Note: State Dept file has typo "Acquistion Phase" which normalizes to "acquistion_phase"
        acquisition_phase = get_value(
            "acquistion_phase", "acquisition_phase", "phase", "status"
        )
        set_aside_type = get_value(
            "setaside_type", "set_aside_type", "set_aside", "small_business_set_aside"
        )
        contract_type = get_value("contract_type", "type_of_contract")
        anticipated_award_type = get_value("anticipated_award_type", "award_type")

        # Financial & Timeline
        # State Dept uses "Estimated Contract Value*" which normalizes to "estimated_contract_value"
        estimated_value = get_value(
            "estimated_contract_value", "estimated_value", "value",
            "dollar_value", "estimated_total_value"
        )
        if estimated_value:
            estimated_value = str(estimated_value)[:255]

        fiscal_year = get_value("fiscal_year", "fy", "award_fiscal_year")
        if fiscal_year:
            try:
                fiscal_year = int(str(fiscal_year).replace("FY", "").strip())
                if fiscal_year < 100:
                    fiscal_year += 2000
            except ValueError:
                fiscal_year = None

        # State Dept uses "Estimated Award FY Quarter" → "estimated_award_fy_quarter"
        estimated_award_quarter = get_value(
            "estimated_award_fy_quarter", "estimated_award_quarter",
            "award_quarter", "quarter"
        )

        solicitation_date = get_value("estimated_solicitation_date", "solicitation_date")
        estimated_solicitation_date = self._parse_date(solicitation_date)

        # Additional
        # State Dept uses "Incumbent Contractor Name" → "incumbent_contractor_name"
        incumbent_contractor = get_value(
            "incumbent_contractor_name", "incumbent_contractor",
            "incumbent", "current_contractor"
        )
        awarded_contract_order = get_value(
            "awarded_contract_order", "contract_number", "award_number"
        )
        # State Dept uses "Facility Security Clearance" → "facility_security_clearance"
        facility_clearance = get_value(
            "facility_security_clearance", "facility_clearance",
            "clearance", "security_clearance"
        )

        # Convert raw_data to JSON-serializable format (datetime objects to strings)
        raw_data_serializable = self._make_json_serializable(row)

        return {
            "title": title,
            "description": str(description) if description else None,
            "naics_code": naics_code,
            "pop_city": str(pop_city) if pop_city else None,
            "pop_state": str(pop_state) if pop_state else None,
            "pop_country": str(pop_country) if pop_country else None,
            "acquisition_phase": str(acquisition_phase) if acquisition_phase else None,
            "set_aside_type": str(set_aside_type) if set_aside_type else None,
            "contract_type": str(contract_type) if contract_type else None,
            "anticipated_award_type": str(anticipated_award_type) if anticipated_award_type else None,
            "estimated_value": estimated_value,
            "fiscal_year": fiscal_year,
            "estimated_award_quarter": str(estimated_award_quarter) if estimated_award_quarter else None,
            "estimated_solicitation_date": estimated_solicitation_date,
            "incumbent_contractor": str(incumbent_contractor)[:255] if incumbent_contractor else None,
            "awarded_contract_order": str(awarded_contract_order)[:255] if awarded_contract_order else None,
            "facility_clearance": str(facility_clearance)[:100] if facility_clearance else None,
            "source_file": source_file,
            "source_row": source_row,
            "raw_data": raw_data_serializable,
        }

    def _make_json_serializable(self, obj: Any) -> Any:
        """
        Convert an object to JSON-serializable format.

        Handles datetime objects from openpyxl Excel parsing.
        """
        if isinstance(obj, dict):
            return {k: self._make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_json_serializable(item) for item in obj]
        elif isinstance(obj, datetime):
            return obj.isoformat()
        elif hasattr(obj, 'isoformat'):  # date objects
            return obj.isoformat()
        else:
            return obj

    def _parse_date(self, date_val: Any) -> Optional[datetime]:
        """Parse a date value to date object."""
        if not date_val:
            return None

        # Handle datetime objects directly
        if isinstance(date_val, datetime):
            return date_val.date()

        date_str = str(date_val).strip()
        if not date_str:
            return None

        try:
            # Try ISO format first
            return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
        except ValueError:
            pass

        try:
            # Try common date formats
            for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d-%b-%Y", "%B %d, %Y"]:
                try:
                    return datetime.strptime(date_str, fmt).date()
                except ValueError:
                    continue
        except Exception:
            pass

        return None

    def _matches_naics_filter(
        self,
        naics_code: str,
        naics_filter: List[str],
    ) -> bool:
        """
        Check if a NAICS code matches any of the filter codes.

        Supports prefix matching (e.g., "5415" matches "541511").
        """
        if not naics_filter:
            return True

        if not naics_code:
            return False

        naics_str = str(naics_code).strip()

        for filter_code in naics_filter:
            filter_str = str(filter_code).strip()
            # Exact match or prefix match
            if naics_str.startswith(filter_str) or filter_str.startswith(naics_str):
                return True

        return False


# Singleton instance
state_pull_service = StatePullService()
