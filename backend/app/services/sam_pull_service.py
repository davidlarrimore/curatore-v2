"""
SAM.gov Pull Service for Federal Opportunity Data Ingestion.

Handles fetching data from the SAM.gov Opportunities API v2, creating/updating
solicitations and notices, downloading attachments, and storing raw responses.

Key Features:
- SAM.gov Opportunities API v2 client with rate limiting
- Opportunity search with configurable filters
- Automatic solicitation/notice creation and updates
- Attachment discovery and download tracking
- Raw JSON storage in object storage for full data preservation

API Documentation:
- Opportunities API: https://open.gsa.gov/api/sam-entity-management/
- Rate limits: 1000 requests per day for public API

Usage:
    from app.services.sam_pull_service import sam_pull_service

    # Pull opportunities for a search
    result = await sam_pull_service.pull_opportunities(
        session=session,
        search_id=search.id,
        organization_id=org_id,
    )

    # Download an attachment
    asset = await sam_pull_service.download_attachment(
        session=session,
        attachment_id=attachment.id,
    )
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
# Note: We don't use urljoin because it strips path for absolute endpoints
from uuid import UUID

import httpx

from ..config import settings
from ..database.models import (
    Asset,
    Artifact,
    Run,
    SamAttachment,
    SamNotice,
    SamSearch,
    SamSolicitation,
)
from .sam_api_usage_service import sam_api_usage_service
from .sam_service import sam_service

logger = logging.getLogger("curatore.api.sam_pull_service")


# SAM.gov Opportunities API v2 Base URL
SAM_API_BASE_URL = "https://api.sam.gov/opportunities/v2"

# Notice type mappings
NOTICE_TYPE_MAP = {
    "o": "Combined Synopsis/Solicitation",
    "p": "Presolicitation",
    "k": "Sources Sought",
    "r": "Special Notice",
    "s": "Sale of Surplus Property",
    "g": "Grant Notice",
    "a": "Award Notice",
    "u": "Justification",
    "i": "Intent to Bundle",
    "m": "Modification",
}


class SamPullService:
    """
    Service for pulling data from SAM.gov Opportunities API.

    Handles API communication, data transformation, and storage operations.
    """

    def __init__(self):
        self.api_key: Optional[str] = None
        self.base_url = SAM_API_BASE_URL
        self.timeout = 60
        self.rate_limit_delay = 0.5  # Delay between requests in seconds

    async def _get_api_key_async(
        self,
        session=None,
        organization_id: Optional[UUID] = None,
    ) -> str:
        """
        Get SAM.gov API key from connection or settings.

        Priority:
            1. Instance api_key (if set via configure())
            2. Database connection (if session and organization_id provided)
            3. Environment variable (SAM_API_KEY)
        """
        # Check instance-level override first
        if self.api_key:
            return self.api_key

        # Try database connection
        if session and organization_id:
            try:
                from .connection_service import connection_service

                connection = await connection_service.get_default_connection(
                    session, organization_id, "sam_gov"
                )

                if connection and connection.is_active:
                    config = connection.config
                    api_key = config.get("api_key")
                    if api_key:
                        logger.debug(f"Using SAM.gov API key from connection for org {organization_id}")
                        return api_key
            except Exception as e:
                logger.warning(f"Failed to get SAM.gov connection: {e}")
                # Fall through to ENV fallback

        # Fallback to environment variable
        api_key = getattr(settings, "sam_api_key", None)
        if api_key:
            return api_key

        raise ValueError(
            "SAM.gov API key not configured. "
            "Either create a SAM.gov connection in the UI or set SAM_API_KEY in environment."
        )

    def _get_api_key(self) -> str:
        """Get SAM.gov API key from settings (sync version for backward compatibility)."""
        if self.api_key:
            return self.api_key

        # Try getting from settings
        api_key = getattr(settings, "sam_api_key", None)
        if api_key:
            return api_key

        raise ValueError(
            "SAM.gov API key not configured. "
            "Either create a SAM.gov connection in the UI or set SAM_API_KEY in environment."
        )

    def configure(
        self,
        api_key: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        """
        Configure the pull service with custom settings.

        Note: base_url is intentionally not configurable - SAM.gov API has a fixed
        endpoint (https://api.sam.gov/opportunities/v2) that cannot be changed.
        """
        if api_key:
            self.api_key = api_key
        if timeout:
            self.timeout = timeout

    def _sanitize_path_component(self, value: str) -> str:
        """
        Sanitize a string for use as a path component.

        Replaces special characters with underscores and limits length.

        Args:
            value: The string to sanitize

        Returns:
            Sanitized string safe for use in file paths
        """
        if not value:
            return "unknown"

        import re
        # Replace special characters with underscores
        sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value)
        # Replace multiple underscores/spaces with single underscore
        sanitized = re.sub(r'[\s_]+', '_', sanitized)
        # Remove leading/trailing underscores and dots
        sanitized = sanitized.strip('_.').strip()
        # Limit length to 100 characters
        if len(sanitized) > 100:
            sanitized = sanitized[:100]
        return sanitized or "unknown"

    async def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        session=None,
        organization_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Make an authenticated request to SAM.gov API.

        Args:
            endpoint: API endpoint (e.g., "/search")
            params: Query parameters
            session: Optional database session for connection lookup
            organization_id: Optional organization ID for connection lookup

        Returns:
            JSON response data

        Raises:
            httpx.HTTPError: On request failure
        """
        # Get API key (tries connection first, then env var)
        api_key = await self._get_api_key_async(session, organization_id)

        # Build URL (don't use urljoin as it strips the path for absolute endpoints)
        url = self.base_url.rstrip("/") + endpoint

        headers = {
            "X-Api-Key": api_key,
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params, headers=headers)

            # Log response details for debugging
            if response.status_code != 200:
                logger.error(
                    f"SAM.gov API returned {response.status_code}: {response.text[:500] if response.text else 'No body'}"
                )

            response.raise_for_status()
            return response.json()

    def _convert_date_format(self, date_str: str) -> str:
        """
        Convert date from YYYY-MM-DD to MM/DD/YYYY format for SAM.gov API.

        Args:
            date_str: Date string in YYYY-MM-DD format

        Returns:
            Date string in MM/DD/YYYY format
        """
        try:
            # Parse YYYY-MM-DD format
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            # Return MM/DD/YYYY format
            return date_obj.strftime("%m/%d/%Y")
        except ValueError:
            # If already in MM/DD/YYYY or other format, return as-is
            return date_str

    def _build_search_params(
        self,
        search_config: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Build API query parameters from search configuration.

        Args:
            search_config: Search configuration from SamSearch.search_config
            limit: Number of results per page
            offset: Offset for pagination

        Returns:
            Query parameters dict for API request
        """
        params = {
            "limit": limit,
            "offset": offset,
        }

        # NAICS codes - SAM.gov API only supports filtering by ONE NAICS code
        # If multiple NAICS codes are configured, we skip the API filter and
        # filter locally after fetching results (see pull_opportunities)
        naics_codes = search_config.get("naics_codes", [])
        if len(naics_codes) == 1:
            # Single NAICS - use API filter for efficiency
            params["naics"] = naics_codes[0]
        elif len(naics_codes) > 1:
            # Multiple NAICS - skip API filter, will filter locally
            logger.info(
                f"Multiple NAICS codes configured ({len(naics_codes)}). "
                "Fetching all results and filtering locally."
            )

        # PSC codes
        if search_config.get("psc_codes"):
            params["psc"] = ",".join(search_config["psc_codes"])

        # Set-aside types
        if search_config.get("set_aside_codes"):
            params["typeOfSetAside"] = ",".join(search_config["set_aside_codes"])

        # Notice types
        if search_config.get("notice_types"):
            params["ptype"] = ",".join(search_config["notice_types"])

        # Keywords
        if search_config.get("keyword"):
            params["q"] = search_config["keyword"]

        # Date range - SAM.gov requires MM/DD/YYYY format
        # SAM.gov requires BOTH postedFrom AND postedTo when using date filtering
        # EXCEPTION: When searching by solicitation_number, skip date filtering to get full history
        # We use predefined date range options for better UX
        if search_config.get("solicitation_number"):
            # Skip date filtering when searching by exact solicitation number
            # We want ALL results for that solicitation regardless of date
            logger.debug("Skipping date filter for solicitation_number search")
        else:
            date_range = search_config.get("date_range", "last_30_days")
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

            # Translate date range option to actual dates
            if date_range == "today":
                posted_from_date = today
                posted_to_date = today
            elif date_range == "yesterday":
                posted_from_date = today - timedelta(days=1)
                posted_to_date = today - timedelta(days=1)
            elif date_range == "last_7_days":
                posted_from_date = today - timedelta(days=7)
                posted_to_date = today
            elif date_range == "last_90_days":
                posted_from_date = today - timedelta(days=90)
                posted_to_date = today
            else:  # default to last_30_days
                posted_from_date = today - timedelta(days=30)
                posted_to_date = today

            params["postedFrom"] = posted_from_date.strftime("%m/%d/%Y")
            params["postedTo"] = posted_to_date.strftime("%m/%d/%Y")
            logger.debug(f"Date range '{date_range}': {params['postedFrom']} to {params['postedTo']}")

        # Response deadline - SAM.gov requires MM/DD/YYYY format
        if search_config.get("deadline_from"):
            params["rdlfrom"] = self._convert_date_format(search_config["deadline_from"])
        if search_config.get("deadline_to"):
            params["rdlto"] = self._convert_date_format(search_config["deadline_to"])

        # Active only
        if search_config.get("active_only", True):
            params["active"] = "true"

        # Organization/Agency filter by ID
        if search_config.get("organization_id"):
            params["organizationId"] = search_config["organization_id"]

        # Organization/Agency filter by name (department)
        if search_config.get("department"):
            params["organizationName"] = search_config["department"]

        # Solicitation number filter (exact match)
        if search_config.get("solicitation_number"):
            params["solnum"] = search_config["solicitation_number"]

        return params

    def _parse_opportunity(
        self,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Parse opportunity data from API response.

        Args:
            data: Raw opportunity data from API

        Returns:
            Parsed opportunity dict with normalized fields
        """
        # Extract dates
        posted_date = None
        if data.get("postedDate"):
            try:
                posted_date = datetime.fromisoformat(data["postedDate"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        response_deadline = None
        if data.get("responseDeadLine"):
            try:
                response_deadline = datetime.fromisoformat(
                    data["responseDeadLine"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        archive_date = None
        if data.get("archiveDate"):
            try:
                archive_date = datetime.fromisoformat(data["archiveDate"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # Extract contact info
        contact_info = None
        if data.get("pointOfContact"):
            contact_info = data["pointOfContact"]

        # Extract place of performance
        place_of_performance = None
        if data.get("placeOfPerformance"):
            place_of_performance = data["placeOfPerformance"]

        # Parse organization hierarchy from fullParentPathName
        # Format: AGENCY.BUREAU.OFFICE (e.g., "HOMELAND SECURITY, DEPARTMENT OF.US COAST GUARD.AVIATION LOGISTICS CENTER")
        full_parent_path = data.get("fullParentPathName", "")
        agency_name = None
        bureau_name = None
        office_name = None

        if full_parent_path:
            parts = full_parent_path.split(".")
            if len(parts) >= 1:
                agency_name = parts[0].strip() if parts[0] else None
            if len(parts) >= 2:
                bureau_name = parts[1].strip() if parts[1] else None
            if len(parts) >= 3:
                # Office may contain dots, so join remaining parts
                office_name = ".".join(parts[2:]).strip() if parts[2:] else None

        # Build UI link
        notice_id = data.get("noticeId", "")
        ui_link = f"https://sam.gov/opp/{notice_id}/view" if notice_id else None

        return {
            "notice_id": notice_id,
            "solicitation_number": data.get("solicitationNumber"),
            "title": data.get("title", "Untitled"),
            "description": data.get("description"),
            "notice_type": data.get("type", "o"),
            "naics_code": data.get("naicsCode"),
            "psc_code": data.get("classificationCode"),
            "set_aside_code": data.get("typeOfSetAsideDescription"),
            "posted_date": posted_date,
            "response_deadline": response_deadline,
            "archive_date": archive_date,
            "ui_link": ui_link,
            "api_link": data.get("uiLink"),
            "contact_info": contact_info,
            "place_of_performance": place_of_performance,
            "agency_name": agency_name,
            "bureau_name": bureau_name,
            "office_name": office_name,
            "full_parent_path": full_parent_path,
            "attachments": data.get("resourceLinks", []),
            "raw_data": data,
        }

    async def fetch_notice_description(
        self,
        notice_id: str,
        session=None,
        organization_id: Optional[UUID] = None,
    ) -> Optional[str]:
        """
        Fetch the full HTML description for a notice from the SAM.gov description API.

        The main search API returns a URL in the description field that points to
        another API endpoint containing the full HTML description.

        Args:
            notice_id: SAM.gov notice ID
            session: Optional database session for connection lookup
            organization_id: Optional organization ID for connection lookup

        Returns:
            HTML description string or None if fetch fails
        """
        # Get API key
        try:
            api_key = await self._get_api_key_async(session, organization_id)
        except ValueError:
            logger.warning("No API key available for description fetch")
            return None

        # The description API is at a different path than the search API
        # https://api.sam.gov/prod/opportunities/v1/noticedesc?noticeid={notice_id}
        description_url = f"https://api.sam.gov/prod/opportunities/v1/noticedesc"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    description_url,
                    params={
                        "noticeid": notice_id,
                        "api_key": api_key,
                    },
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()

                data = response.json()
                description = data.get("description")

                if description:
                    logger.debug(f"Fetched description for notice {notice_id}: {len(description)} chars")
                    return description

                return None

        except httpx.HTTPError as e:
            logger.warning(f"Failed to fetch description for notice {notice_id}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Error fetching description for notice {notice_id}: {e}")
            return None

    async def search_opportunities(
        self,
        search_config: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        session=None,
        organization_id: Optional[UUID] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Search for opportunities using SAM.gov API.

        Args:
            search_config: Search configuration
            limit: Results per page
            offset: Pagination offset
            session: Optional database session for connection lookup
            organization_id: Optional organization ID for connection lookup

        Returns:
            Tuple of (opportunities list, total count)
        """
        params = self._build_search_params(search_config, limit, offset)

        try:
            response = await self._make_request(
                "/search", params, session=session, organization_id=organization_id
            )

            total = response.get("totalRecords", 0)
            opportunities = []

            for opp_data in response.get("opportunitiesData", []):
                parsed = self._parse_opportunity(opp_data)
                opportunities.append(parsed)

            return opportunities, total

        except httpx.TimeoutException as e:
            logger.error(f"SAM.gov API timeout after {self.timeout}s: {e}")
            raise RuntimeError(f"SAM.gov API request timed out after {self.timeout} seconds. The API may be slow or unavailable.")
        except httpx.HTTPError as e:
            logger.error(f"SAM.gov API error: {type(e).__name__}: {e}")
            raise

    async def get_opportunity_details(
        self,
        notice_id: str,
        session=None,
        organization_id: Optional[UUID] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get detailed information for a specific opportunity.

        Args:
            notice_id: SAM.gov notice ID
            session: Optional database session for connection lookup
            organization_id: Optional organization ID for connection lookup

        Returns:
            Parsed opportunity data or None if not found
        """
        try:
            response = await self._make_request(
                f"/opportunities/{notice_id}",
                session=session,
                organization_id=organization_id,
            )

            if response:
                return self._parse_opportunity(response)
            return None

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def pull_opportunities(
        self,
        session,  # AsyncSession
        search_id: UUID,
        organization_id: UUID,
        max_pages: int = 10,
        page_size: int = 100,
        check_rate_limit: bool = True,
        auto_download_attachments: bool = True,
    ) -> Dict[str, Any]:
        """
        Pull opportunities for a search and update database.

        This is the main entry point for pulling data from SAM.gov.

        Args:
            session: Database session
            search_id: SamSearch UUID
            organization_id: Organization UUID
            max_pages: Maximum pages to fetch
            page_size: Results per page
            check_rate_limit: Whether to check/record API rate limits
            auto_download_attachments: Whether to download attachments after pull

        Returns:
            Pull results summary
        """
        search = await sam_service.get_search(session, search_id)
        if not search:
            raise ValueError(f"Search not found: {search_id}")

        search_config = search.search_config or {}

        # Log NAICS filtering strategy
        configured_naics = search_config.get("naics_codes", [])
        if len(configured_naics) == 0:
            logger.info(f"Starting pull for search {search_id}: No NAICS filter configured")
        elif len(configured_naics) == 1:
            logger.info(f"Starting pull for search {search_id}: NAICS filter via API: {configured_naics[0]}")
        else:
            logger.info(
                f"Starting pull for search {search_id}: Local NAICS filter for {len(configured_naics)} codes: "
                f"{', '.join(configured_naics)}"
            )

        results = {
            "search_id": str(search_id),
            "started_at": datetime.utcnow().isoformat(),
            "total_fetched": 0,
            "filtered_by_naics": 0,  # Count of opportunities filtered out by local NAICS check
            "processed": 0,  # Count of opportunities that passed filters and were processed
            "new_solicitations": 0,
            "updated_solicitations": 0,
            "new_notices": 0,
            "new_attachments": 0,
            "api_calls_made": 0,
            "errors": [],
            "processed_solicitation_ids": [],  # Track solicitation IDs for auto-download
        }

        # Check rate limit before starting (if enabled)
        if check_rate_limit:
            can_call, remaining = await sam_api_usage_service.check_limit(
                session, organization_id, required_calls=max_pages
            )
            if not can_call:
                logger.warning(
                    f"Rate limit exceeded for org {organization_id}. "
                    f"Remaining: {remaining}, needed: {max_pages}"
                )
                results["status"] = "rate_limited"
                results["error"] = f"API rate limit exceeded. Remaining calls: {remaining}"
                results["rate_limit_remaining"] = remaining
                return results

        offset = 0
        pages_fetched = 0

        try:
            while pages_fetched < max_pages:
                # Check rate limit before each page (if enabled)
                if check_rate_limit:
                    can_call, remaining = await sam_api_usage_service.check_limit(
                        session, organization_id
                    )
                    if not can_call:
                        logger.warning(f"Rate limit reached mid-pull. Stopping at page {pages_fetched}")
                        results["rate_limit_hit"] = True
                        results["rate_limit_remaining"] = remaining
                        break

                # Fetch page of opportunities
                opportunities, total = await self.search_opportunities(
                    search_config,
                    limit=page_size,
                    offset=offset,
                    session=session,
                    organization_id=organization_id,
                )

                # Record the API call (if enabled)
                if check_rate_limit:
                    await sam_api_usage_service.record_call(
                        session, organization_id, "search"
                    )
                    results["api_calls_made"] += 1

                if not opportunities:
                    break

                results["total_fetched"] += len(opportunities)

                # Local NAICS filtering - always applied when NAICS codes are configured
                # This serves as a safety check even when API filter is used (single NAICS),
                # and is required when multiple NAICS codes are configured (API only supports one)
                configured_naics = search_config.get("naics_codes", [])
                if configured_naics:
                    # Filter opportunities to only include those matching configured NAICS
                    original_count = len(opportunities)
                    opportunities = [
                        opp for opp in opportunities
                        if opp.get("naics_code") in configured_naics
                    ]
                    filtered_count = original_count - len(opportunities)
                    if filtered_count > 0:
                        logger.info(
                            f"Filtered {filtered_count} opportunities not matching "
                            f"configured NAICS codes ({configured_naics}). {len(opportunities)} remaining."
                        )
                    results["filtered_by_naics"] += filtered_count

                # Process each opportunity (those that passed NAICS filter)
                for opp in opportunities:
                    try:
                        await self._process_opportunity(
                            session=session,
                            organization_id=organization_id,
                            opportunity=opp,
                            results=results,
                            search_config=search_config,
                        )
                        results["processed"] += 1
                    except Exception as e:
                        logger.error(f"Error processing opportunity {opp.get('notice_id')}: {e}")
                        results["errors"].append({
                            "notice_id": opp.get("notice_id"),
                            "error": str(e),
                        })

                # Check if we've fetched all results
                offset += page_size
                pages_fetched += 1

                if offset >= total:
                    break

                # Rate limiting delay
                await asyncio.sleep(self.rate_limit_delay)

            # Update search status
            await sam_service.update_search_pull_status(
                session, search_id, "success" if not results["errors"] else "partial"
            )

            results["completed_at"] = datetime.utcnow().isoformat()
            results["status"] = "success" if not results["errors"] else "partial"

            # Auto-download attachments if enabled
            # Check search_config for override, default to parameter value
            # Download attachments for solicitations processed in this pull
            should_download = search_config.get("download_attachments", auto_download_attachments)
            print(f"[SAM_DEBUG] Auto-download check: should_download={should_download}, auto_download_attachments={auto_download_attachments}")
            logger.info(f"Auto-download check: should_download={should_download}, auto_download_attachments={auto_download_attachments}")
            if should_download:
                results["attachment_downloads"] = {
                    "total": 0,
                    "downloaded": 0,
                    "failed": 0,
                    "skipped": 0,
                    "errors": [],
                }

                # Download attachments for solicitations processed in this pull
                solicitation_ids = results.get("processed_solicitation_ids", [])
                print(f"[SAM_DEBUG] Found {len(solicitation_ids)} solicitations processed in this pull")
                for sol_id in solicitation_ids:
                    print(f"[SAM_DEBUG] Processing solicitation: {sol_id}...")
                    download_result = await self.download_all_attachments(
                        session=session,
                        solicitation_id=UUID(sol_id),
                        organization_id=organization_id,
                    )
                    results["attachment_downloads"]["total"] += download_result["total"]
                    results["attachment_downloads"]["downloaded"] += download_result["downloaded"]
                    results["attachment_downloads"]["failed"] += download_result["failed"]
                    results["attachment_downloads"]["errors"].extend(download_result.get("errors", []))

                # Only log if there were attachments to process
                if results["attachment_downloads"]["total"] > 0:
                    logger.info(
                        f"Attachment download complete: {results['attachment_downloads']['downloaded']} downloaded, "
                        f"{results['attachment_downloads']['failed']} failed out of {results['attachment_downloads']['total']} pending"
                    )
                else:
                    logger.debug("No pending attachments to download")

        except Exception as e:
            import traceback
            print(f"[SAM_DEBUG] EXCEPTION in pull_opportunities: {e}")
            print(f"[SAM_DEBUG] Traceback: {traceback.format_exc()}")
            logger.error(f"Pull failed for search {search_id}: {e}")
            await sam_service.update_search_pull_status(session, search_id, "failed")
            results["status"] = "failed"
            results["error"] = str(e)

        return results

    async def _process_opportunity(
        self,
        session,  # AsyncSession
        organization_id: UUID,
        opportunity: Dict[str, Any],
        results: Dict[str, Any],
        search_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Process a single opportunity - create/update solicitation or standalone notice.

        Special Notices (notice_type='s') are created as standalone notices without
        a parent solicitation, since they are informational and don't have solicitation numbers.

        Args:
            session: Database session
            organization_id: Organization UUID
            opportunity: Parsed opportunity data
            results: Results dict to update
            search_config: Optional search configuration (for download_attachments setting)
        """
        notice_id = opportunity.get("notice_id")
        if not notice_id:
            logger.warning("Skipping opportunity without notice_id")
            return

        notice_type = opportunity.get("notice_type", "o")

        # Fetch full HTML description from the notice description API
        # The search API returns a URL in the description field, not the actual description
        description = opportunity.get("description")
        if description and description.startswith("http"):
            # The description field is a URL - fetch the actual description
            logger.debug(f"Fetching full description for notice {notice_id}")
            full_description = await self.fetch_notice_description(
                notice_id, session, organization_id
            )
            if full_description:
                description = full_description
                # Add rate limiting delay after description fetch
                await asyncio.sleep(self.rate_limit_delay)

        # Special Notices (type='s') are standalone - no solicitation record
        if notice_type == "s":
            await self._process_standalone_notice(
                session, organization_id, opportunity, description, results
            )
            return

        # For other notice types, create/update solicitation
        # Check if solicitation already exists
        existing = await sam_service.get_solicitation_by_notice_id(session, notice_id)

        if existing:
            # Update existing solicitation
            await sam_service.update_solicitation(
                session,
                solicitation_id=existing.id,
                title=opportunity.get("title"),
                description=description,
                response_deadline=opportunity.get("response_deadline"),
            )
            results["updated_solicitations"] += 1
            solicitation = existing
            # Track solicitation ID for auto-download
            if "processed_solicitation_ids" in results:
                results["processed_solicitation_ids"].append(str(solicitation.id))
        else:
            # Create new solicitation
            solicitation = await sam_service.create_solicitation(
                session=session,
                organization_id=organization_id,
                notice_id=notice_id,
                title=opportunity.get("title", "Untitled"),
                notice_type=notice_type,
                solicitation_number=opportunity.get("solicitation_number"),
                description=description,
                naics_code=opportunity.get("naics_code"),
                psc_code=opportunity.get("psc_code"),
                set_aside_code=opportunity.get("set_aside_code"),
                posted_date=opportunity.get("posted_date"),
                response_deadline=opportunity.get("response_deadline"),
                ui_link=opportunity.get("ui_link"),
                api_link=opportunity.get("api_link"),
                contact_info=opportunity.get("contact_info"),
                place_of_performance=opportunity.get("place_of_performance"),
                agency_name=opportunity.get("agency_name"),
                bureau_name=opportunity.get("bureau_name"),
                office_name=opportunity.get("office_name"),
                full_parent_path=opportunity.get("full_parent_path"),
            )
            results["new_solicitations"] += 1

        # Track solicitation ID for auto-download
        if "processed_solicitation_ids" in results:
            results["processed_solicitation_ids"].append(str(solicitation.id))

        # Check for new notices (amendments)
        # For simplicity, we create a notice for each pull if it's new
        latest_notice = await sam_service.get_latest_notice(session, solicitation.id)

        is_new_notice = False
        if not latest_notice:
            # Create initial notice
            notice = await sam_service.create_notice(
                session=session,
                solicitation_id=solicitation.id,
                sam_notice_id=notice_id,
                notice_type=notice_type,
                version_number=1,
                title=opportunity.get("title"),
                description=description,  # Use fetched HTML description
                posted_date=opportunity.get("posted_date"),
                response_deadline=opportunity.get("response_deadline"),
            )
            results["new_notices"] += 1
            is_new_notice = True
        else:
            notice = latest_notice

        # Process attachments - only if enabled in search config
        # The download_attachments setting controls whether we track attachments for download
        download_attachments = True  # Default to True for backward compatibility
        if search_config:
            download_attachments = search_config.get("download_attachments", True)

        if download_attachments:
            attachments = opportunity.get("attachments", [])
            for att_data in attachments:
                await self._process_attachment(
                    session=session,
                    solicitation_id=solicitation.id,
                    notice_id=notice.id,
                    attachment_data=att_data,
                    results=results,
                )

        # Update solicitation counts
        await sam_service.update_solicitation_counts(session, solicitation.id)

        # Index to OpenSearch for unified search (Phase 7.6)
        await self._index_to_opensearch(
            session=session,
            solicitation=solicitation,
            notice=notice,
            opportunity=opportunity,
        )

        # Trigger auto-summary for new solicitations (Phase 7.6)
        # For updates, we don't regenerate summary unless explicitly requested
        if not existing:
            from app.tasks import sam_auto_summarize_task
            sam_auto_summarize_task.delay(
                solicitation_id=str(solicitation.id),
                organization_id=str(organization_id),
                is_update=False,
            )
            logger.debug(f"Triggered auto-summary task for new solicitation {solicitation.id}")

        # Trigger auto-summary for new notices (Phase 7.6)
        # This generates a notice-specific summary focused on what the notice is about
        if is_new_notice:
            from app.tasks import sam_auto_summarize_notice_task
            try:
                sam_auto_summarize_notice_task.delay(
                    notice_id=str(notice.id),
                    organization_id=str(organization_id),
                )
                logger.debug(f"Triggered auto-summary task for notice {notice.id}")
            except Exception as e:
                logger.warning(f"Could not trigger auto-summary for notice: {e}")

    async def _process_standalone_notice(
        self,
        session,  # AsyncSession
        organization_id: UUID,
        opportunity: Dict[str, Any],
        description: Optional[str],
        results: Dict[str, Any],
    ):
        """
        Process a Special Notice as a standalone notice (no parent solicitation).

        Special Notices are informational and don't have solicitation numbers,
        so they are stored as standalone notices with their own organization_id.

        Args:
            session: Database session
            organization_id: Organization UUID
            opportunity: Parsed opportunity data
            description: Fetched description (already resolved from URL)
            results: Results dict to update
        """
        notice_id = opportunity.get("notice_id")

        # Check if standalone notice already exists
        existing_notice = await sam_service.get_notice_by_sam_notice_id(
            session, notice_id, organization_id=organization_id
        )

        if existing_notice:
            # Update existing standalone notice
            await sam_service.update_notice(
                session,
                notice_id=existing_notice.id,
                title=opportunity.get("title"),
                description=description,
                response_deadline=opportunity.get("response_deadline"),
            )
            results["updated_notices"] = results.get("updated_notices", 0) + 1
            notice = existing_notice
            logger.debug(f"Updated standalone notice {notice.id}")
        else:
            # Create new standalone notice
            notice = await sam_service.create_notice(
                session=session,
                solicitation_id=None,  # Standalone - no parent solicitation
                organization_id=organization_id,
                sam_notice_id=notice_id,
                notice_type="s",  # Special Notice
                version_number=1,
                title=opportunity.get("title", "Untitled"),
                description=description,
                posted_date=opportunity.get("posted_date"),
                response_deadline=opportunity.get("response_deadline"),
                naics_code=opportunity.get("naics_code"),
                psc_code=opportunity.get("psc_code"),
                set_aside_code=opportunity.get("set_aside_code"),
                agency_name=opportunity.get("agency_name"),
                bureau_name=opportunity.get("bureau_name"),
                office_name=opportunity.get("office_name"),
                ui_link=opportunity.get("ui_link"),
            )
            results["new_standalone_notices"] = results.get("new_standalone_notices", 0) + 1
            logger.info(f"Created standalone notice {notice.id}: {notice.title}")

            # Trigger auto-summary for new standalone notices
            from app.tasks import sam_auto_summarize_notice_task
            try:
                sam_auto_summarize_notice_task.delay(
                    notice_id=str(notice.id),
                    organization_id=str(organization_id),
                )
                logger.debug(f"Triggered auto-summary task for standalone notice {notice.id}")
            except Exception as e:
                # Task may not exist yet - log and continue
                logger.warning(f"Could not trigger auto-summary for notice: {e}")

        # Process attachments for standalone notices
        attachments = opportunity.get("attachments", [])
        for att_data in attachments:
            await self._process_standalone_notice_attachment(
                session=session,
                notice_id=notice.id,
                attachment_data=att_data,
                results=results,
            )

    async def _process_standalone_notice_attachment(
        self,
        session,  # AsyncSession
        notice_id: UUID,
        attachment_data,
        results: Dict[str, Any],
    ):
        """
        Process an attachment for a standalone notice.

        Similar to _process_attachment but without solicitation_id requirement.
        """
        # Handle both dict format and simple URL string format
        if isinstance(attachment_data, str):
            download_url = attachment_data
            import re
            match = re.search(r'/files/([a-f0-9]+)/download', attachment_data)
            if match:
                resource_id = match.group(1)
            else:
                import hashlib
                resource_id = hashlib.md5(attachment_data.encode()).hexdigest()
            filename = f"pending_{resource_id}"
            file_type = None
            file_size = None
            description = None
        else:
            resource_id = attachment_data.get("resource_id")
            download_url = attachment_data.get("download_url")
            filename = attachment_data.get("filename", f"pending_{resource_id}")
            file_type = attachment_data.get("file_type")
            file_size = attachment_data.get("file_size")
            description = attachment_data.get("description")

        if not resource_id and not download_url:
            return

        # Check for existing attachment by resource_id or download_url
        existing = await sam_service.get_attachment_by_resource_or_url(
            session, resource_id=resource_id, download_url=download_url
        )

        if existing:
            # Already have this attachment
            results["skipped_attachments"] = results.get("skipped_attachments", 0) + 1
            return

        # Create new attachment record for standalone notice
        attachment = await sam_service.create_attachment(
            session=session,
            solicitation_id=None,  # No solicitation for standalone notices
            notice_id=notice_id,
            resource_id=resource_id,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            download_url=download_url,
            description=description,
        )
        results["new_attachments"] = results.get("new_attachments", 0) + 1
        logger.debug(f"Created attachment {attachment.id} for standalone notice {notice_id}")

    async def _process_attachment(
        self,
        session,  # AsyncSession
        solicitation_id: UUID,
        notice_id: UUID,
        attachment_data,  # Can be Dict[str, Any] or str (URL)
        results: Dict[str, Any],
    ):
        """
        Process an attachment record.

        Includes deduplication by both resource_id and download_url to
        prevent redundant downloads of the same file.

        Args:
            session: Database session
            solicitation_id: Parent solicitation UUID
            notice_id: Parent notice UUID
            attachment_data: Attachment data from API (dict or URL string)
            results: Results dict to update
        """
        # Handle both dict format and simple URL string format
        if isinstance(attachment_data, str):
            # SAM.gov resourceLinks is a list of URL strings
            # URL format: https://sam.gov/api/prod/opps/v3/opportunities/resources/files/{resource_id}/download
            download_url = attachment_data
            # Extract resource_id from URL (the GUID before /download)
            import re
            match = re.search(r'/files/([a-f0-9]+)/download', attachment_data)
            if match:
                resource_id = match.group(1)
            else:
                # Fallback: use URL hash as resource_id
                import hashlib
                resource_id = hashlib.md5(attachment_data.encode()).hexdigest()
            # Filename will be resolved during download from Content-Disposition header
            # Use resource_id as placeholder for now
            filename = f"pending_{resource_id}"
            file_type = None
            file_size = None
            description = None
        else:
            resource_id = attachment_data.get("resourceId") or attachment_data.get("url", "")
            download_url = attachment_data.get("url") or attachment_data.get("downloadUrl")
            filename = attachment_data.get("name") or attachment_data.get("fileName") or f"pending_{resource_id}"
            file_size = attachment_data.get("size")
            description = attachment_data.get("description")
            file_type = None
            if filename and "." in filename and not filename.startswith("pending_"):
                file_type = filename.rsplit(".", 1)[-1].lower()

        if not resource_id:
            return

        # Check if attachment already exists by resource_id
        existing = await sam_service.get_attachment_by_resource_id(session, resource_id)

        if existing:
            return

        # Extract file type from filename if not already set
        if not file_type and "." in filename:
            file_type = filename.rsplit(".", 1)[-1].lower()

        # Check for deduplication by download_url
        # If another attachment with the same URL has already been downloaded,
        # we can link to its asset instead of downloading again
        existing_asset_id = None
        if download_url:
            existing_by_url = await sam_service.get_attachment_by_download_url(
                session, download_url
            )
            if existing_by_url and existing_by_url.asset_id:
                existing_asset_id = existing_by_url.asset_id
                logger.info(
                    f"Found existing download for URL: {download_url[:50]}... "
                    f"Linking to Asset {existing_asset_id}"
                )

        # Create attachment record
        # If we found an existing asset, the attachment is created as already downloaded
        attachment = await sam_service.create_attachment(
            session=session,
            solicitation_id=solicitation_id,
            notice_id=notice_id,
            resource_id=resource_id,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            description=description,
            download_url=download_url,
        )

        # If we found an existing asset, link to it and mark as downloaded
        if existing_asset_id:
            await sam_service.update_attachment_download_status(
                session=session,
                attachment_id=attachment.id,
                status="downloaded",
                asset_id=existing_asset_id,
            )
            # Track deduplication in results
            if "deduplicated_attachments" not in results:
                results["deduplicated_attachments"] = 0
            results["deduplicated_attachments"] += 1
        else:
            results["new_attachments"] += 1

    async def download_attachment(
        self,
        session,  # AsyncSession
        attachment_id: UUID,
        organization_id: UUID,
        minio_service=None,
        check_rate_limit: bool = True,
    ) -> Optional[Asset]:
        """
        Download an attachment and create an Asset.

        Args:
            session: Database session
            attachment_id: SamAttachment UUID
            organization_id: Organization UUID
            minio_service: MinIO service instance (optional)
            check_rate_limit: Whether to check/record API rate limits

        Returns:
            Created Asset or None on failure
        """
        print(f"[SAM_DEBUG] download_attachment called: {attachment_id}")
        attachment = await sam_service.get_attachment(session, attachment_id)
        if not attachment:
            print(f"[SAM_DEBUG] Attachment not found: {attachment_id}")
            logger.error(f"Attachment not found: {attachment_id}")
            return None

        print(f"[SAM_DEBUG] Attachment found: status={attachment.download_status}, url={attachment.download_url[:50] if attachment.download_url else 'None'}...")
        if attachment.download_status == "downloaded" and attachment.asset_id:
            print(f"[SAM_DEBUG] Attachment already downloaded: {attachment_id}")
            logger.info(f"Attachment {attachment_id} already downloaded")
            return None

        if not attachment.download_url:
            print(f"[SAM_DEBUG] No download URL for attachment: {attachment_id}")
            logger.error(f"No download URL for attachment {attachment_id}")
            await sam_service.update_attachment_download_status(
                session, attachment_id, "failed", error="No download URL"
            )
            return None

        # Check rate limit before downloading (if enabled)
        if check_rate_limit:
            can_call, remaining = await sam_api_usage_service.check_limit(
                session, organization_id
            )
            if not can_call:
                logger.warning(
                    f"Rate limit exceeded for attachment download. "
                    f"Attachment {attachment_id}, remaining: {remaining}"
                )
                await sam_service.update_attachment_download_status(
                    session, attachment_id, "pending", error="Rate limit exceeded - queued"
                )
                return None

        # Update status to downloading
        await sam_service.update_attachment_download_status(
            session, attachment_id, "downloading"
        )

        try:
            # Download file - API key goes as query parameter, not header
            api_key = await self._get_api_key_async(session, organization_id)
            download_url = attachment.download_url
            # Add api_key as query parameter
            if "?" in download_url:
                download_url = f"{download_url}&api_key={api_key}"
            else:
                download_url = f"{download_url}?api_key={api_key}"

            print(f"[SAM_DEBUG] Downloading from URL: {download_url[:100]}...")
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                response = await client.get(download_url)
                print(f"[SAM_DEBUG] HTTP response: status={response.status_code}, content-length={len(response.content)}")
                response.raise_for_status()

                file_content = response.content
                content_type = response.headers.get("content-type", "application/octet-stream")

                # Extract real filename from Content-Disposition header
                # Example: 'attachment; filename="Statement_of_Work.pdf"'
                content_disposition = response.headers.get("content-disposition", "")
                real_filename = None
                if content_disposition:
                    import re
                    # Try to extract filename from Content-Disposition
                    # Handle both filename="..." and filename*=UTF-8''...
                    match = re.search(r'filename[*]?=["\']?([^"\';\r\n]+)["\']?', content_disposition)
                    if match:
                        real_filename = match.group(1).strip()
                        # Handle URL-encoded filenames
                        if real_filename.startswith("UTF-8''"):
                            from urllib.parse import unquote
                            real_filename = unquote(real_filename[7:])

                # If no filename from header, try to guess from content type
                if not real_filename:
                    # Fallback to resource_id with extension from content type
                    ext_map = {
                        "application/pdf": ".pdf",
                        "application/msword": ".doc",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                        "application/vnd.ms-excel": ".xls",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
                        "application/vnd.ms-powerpoint": ".ppt",
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
                        "text/plain": ".txt",
                        "text/html": ".html",
                        "application/zip": ".zip",
                    }
                    ext = ext_map.get(content_type, "")
                    real_filename = f"{attachment.resource_id}{ext}"

                logger.info(f"Resolved filename for attachment {attachment_id}: {real_filename}")

            # Record the API call (if enabled)
            if check_rate_limit:
                await sam_api_usage_service.record_call(
                    session, organization_id, "attachment"
                )

            # Get MinIO service if not provided
            if minio_service is None:
                from .minio_service import get_minio_service
                minio_service = get_minio_service()

            # Get solicitation for path building
            solicitation = await sam_service.get_solicitation(
                session, attachment.solicitation_id
            )

            # Build storage path following the SAM storage structure
            # Format: {org_id}/sam/{agency_code}/{subagency_code}/solicitations/{number}/attachments/{filename}
            sol_number = solicitation.solicitation_number or solicitation.notice_id
            safe_sol_number = sol_number.replace("/", "_").replace("\\", "_")

            # Build agency path if available
            agency_code = self._sanitize_path_component(solicitation.agency_name or "unknown")
            bureau_code = self._sanitize_path_component(solicitation.bureau_name or "general")

            # Safe filename
            safe_filename = self._sanitize_path_component(real_filename)

            object_key = f"{organization_id}/sam/{agency_code}/{bureau_code}/solicitations/{safe_sol_number}/attachments/{safe_filename}"

            # Upload to MinIO
            bucket = getattr(settings, "minio_bucket_uploads", "curatore-uploads")

            from io import BytesIO
            data_stream = BytesIO(file_content)
            minio_service.put_object(
                bucket=bucket,
                key=object_key,
                data=data_stream,
                length=len(file_content),
                content_type=content_type,
            )
            logger.info(f"Uploaded attachment to {bucket}/{object_key}")

            # Determine file type from filename
            file_type = None
            if "." in real_filename:
                file_type = real_filename.rsplit(".", 1)[-1].lower()

            # Update attachment with real filename and file info
            await sam_service.update_attachment(
                session,
                attachment_id=attachment_id,
                filename=real_filename,
                file_type=file_type,
                file_size=len(file_content),
            )

            # Check if asset already exists with same bucket/key (from previous failed attempt)
            from sqlalchemy import select
            existing_asset_result = await session.execute(
                select(Asset).where(
                    Asset.raw_bucket == bucket,
                    Asset.raw_object_key == object_key,
                )
            )
            asset = existing_asset_result.scalar_one_or_none()

            if asset:
                logger.info(f"Found existing asset {asset.id} for {object_key}, reusing")
            else:
                # Create new Asset using centralized asset_service
                # This automatically queues extraction
                from .asset_service import asset_service
                asset = await asset_service.create_asset(
                    session=session,
                    organization_id=organization_id,
                    source_type="sam_gov",
                    source_metadata={
                        "attachment_id": str(attachment_id),
                        "solicitation_id": str(attachment.solicitation_id),
                        "notice_id": str(attachment.notice_id) if attachment.notice_id else None,
                        "resource_id": attachment.resource_id,
                        "download_url": attachment.download_url,
                        "downloaded_at": datetime.utcnow().isoformat(),
                        "agency": solicitation.agency_name,
                        "bureau": solicitation.bureau_name,
                        "solicitation_number": sol_number,
                    },
                    original_filename=real_filename,
                    content_type=content_type,
                    file_size=len(file_content),
                    raw_bucket=bucket,
                    raw_object_key=object_key,
                    # auto_extract=True is default, extraction queued automatically
                )

            # Update attachment with asset link
            await sam_service.update_attachment_download_status(
                session, attachment_id, "downloaded", asset_id=asset.id
            )

            logger.info(f"Downloaded attachment {attachment_id} -> Asset {asset.id} ({real_filename})")

            return asset

        except httpx.HTTPError as e:
            error_msg = f"HTTP error downloading attachment: {e}"
            print(f"[SAM_DEBUG] HTTP ERROR: {error_msg}")
            logger.error(error_msg)
            try:
                await session.rollback()
                await sam_service.update_attachment_download_status(
                    session, attachment_id, "failed", error=error_msg
                )
            except Exception:
                pass  # Ignore errors updating status after rollback
            return None
        except Exception as e:
            import traceback
            error_msg = f"Error downloading attachment: {e}"
            print(f"[SAM_DEBUG] EXCEPTION in download_attachment: {error_msg}")
            print(f"[SAM_DEBUG] Traceback: {traceback.format_exc()}")
            logger.error(error_msg)
            try:
                await session.rollback()
                await sam_service.update_attachment_download_status(
                    session, attachment_id, "failed", error=error_msg
                )
            except Exception:
                pass  # Ignore errors updating status after rollback
            return None

    async def download_all_attachments(
        self,
        session,  # AsyncSession
        solicitation_id: UUID,
        organization_id: UUID,
        minio_service=None,
    ) -> Dict[str, Any]:
        """
        Download all pending attachments for a solicitation.

        Args:
            session: Database session
            solicitation_id: SamSolicitation UUID
            organization_id: Organization UUID
            minio_service: MinIO service instance (optional)

        Returns:
            Download results summary
        """
        print(f"[SAM_DEBUG] download_all_attachments called for solicitation {solicitation_id}")
        logger.info(f"download_all_attachments called for solicitation {solicitation_id}")
        attachments = await sam_service.list_attachments(
            session, solicitation_id, download_status="pending"
        )
        print(f"[SAM_DEBUG] Found {len(attachments)} pending attachments for solicitation {solicitation_id}")
        logger.info(f"Found {len(attachments)} pending attachments for solicitation {solicitation_id}")

        results = {
            "total": len(attachments),
            "downloaded": 0,
            "failed": 0,
            "errors": [],
        }

        for attachment in attachments:
            logger.info(f"Downloading attachment {attachment.id}: {attachment.filename}")
            try:
                asset = await self.download_attachment(
                    session=session,
                    attachment_id=attachment.id,
                    organization_id=organization_id,
                    minio_service=minio_service,
                    check_rate_limit=True,
                )
                if asset:
                    results["downloaded"] += 1
                else:
                    results["failed"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({
                    "attachment_id": str(attachment.id),
                    "error": str(e),
                })

            # Rate limiting
            await asyncio.sleep(0.5)

        return results

    async def test_connection(
        self,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Test connection to SAM.gov API.

        Args:
            api_key: Optional API key to test (uses configured key if not provided)

        Returns:
            Connection test results
        """
        if api_key:
            self.api_key = api_key

        try:
            # Make a minimal search request
            response = await self._make_request("/search", {"limit": 1})

            return {
                "success": True,
                "status": "healthy",
                "message": "Successfully connected to SAM.gov API",
                "details": {
                    "api_version": "v2",
                    "total_opportunities": response.get("totalRecords", 0),
                },
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {
                    "success": False,
                    "status": "unhealthy",
                    "message": "Authentication failed - invalid API key",
                    "error": f"HTTP {e.response.status_code}",
                }
            elif e.response.status_code == 403:
                return {
                    "success": False,
                    "status": "unhealthy",
                    "message": "Access forbidden - check API key permissions",
                    "error": f"HTTP {e.response.status_code}",
                }
            else:
                return {
                    "success": False,
                    "status": "unhealthy",
                    "message": f"API error: HTTP {e.response.status_code}",
                    "error": str(e),
                }
        except httpx.TimeoutException:
            return {
                "success": False,
                "status": "unhealthy",
                "message": "Connection timeout",
                "error": "Request timed out",
            }
        except Exception as e:
            return {
                "success": False,
                "status": "unhealthy",
                "message": "Connection failed",
                "error": str(e),
            }

    async def preview_search(
        self,
        session,  # AsyncSession
        organization_id: UUID,
        search_config: Dict[str, Any],
        limit: int = 10,
        check_rate_limit: bool = True,
    ) -> Dict[str, Any]:
        """
        Preview a search configuration without storing results.

        This allows users to test their search filters and see
        a sample of matching opportunities before saving the search.

        Args:
            session: Database session
            organization_id: Organization UUID (for rate limiting)
            search_config: Search configuration to test
            limit: Number of sample results to return (default 10, max 25)
            check_rate_limit: Whether to check/record API rate limits

        Returns:
            Preview results including sample opportunities and total count
        """
        # Limit preview results to avoid excessive API usage
        limit = min(limit, 25)

        # Check rate limit before testing (if enabled)
        if check_rate_limit:
            can_call, remaining = await sam_api_usage_service.check_limit(
                session, organization_id
            )
            if not can_call:
                return {
                    "success": False,
                    "error": "rate_limited",
                    "message": f"API rate limit exceeded. Remaining calls: {remaining}",
                    "remaining_calls": remaining,
                }

        try:
            # Fetch sample opportunities
            opportunities, total = await self.search_opportunities(
                search_config, limit=limit, offset=0,
                session=session, organization_id=organization_id,
            )

            # Record the API call (if enabled)
            if check_rate_limit:
                await sam_api_usage_service.record_call(
                    session, organization_id, "search"
                )

            # Build preview response
            preview_results = []
            for opp in opportunities:
                preview_results.append({
                    "notice_id": opp.get("notice_id"),
                    "title": opp.get("title"),
                    "solicitation_number": opp.get("solicitation_number"),
                    "notice_type": opp.get("notice_type"),
                    "naics_code": opp.get("naics_code"),
                    "psc_code": opp.get("psc_code"),
                    "set_aside": opp.get("set_aside"),
                    "posted_date": opp.get("posted_date").isoformat() if opp.get("posted_date") else None,
                    "response_deadline": opp.get("response_deadline").isoformat() if opp.get("response_deadline") else None,
                    "agency": opp.get("organization", {}).get("name") if isinstance(opp.get("organization"), dict) else None,
                    "ui_link": opp.get("ui_link"),
                    "attachments_count": len(opp.get("attachments") or []),
                })

            return {
                "success": True,
                "total_matching": total,
                "sample_count": len(preview_results),
                "sample_results": preview_results,
                "search_config": search_config,
                "message": f"Found {total} matching opportunities. Showing {len(preview_results)} samples.",
            }

        except httpx.TimeoutException as e:
            logger.error(f"SAM.gov API timeout during preview: {e}")
            return {
                "success": False,
                "error": "timeout",
                "message": f"SAM.gov API request timed out after {self.timeout} seconds. Please try again.",
            }
        except httpx.HTTPError as e:
            logger.error(f"SAM.gov API error during preview: {type(e).__name__}: {e}")
            return {
                "success": False,
                "error": "api_error",
                "message": f"API request failed: {type(e).__name__}: {e}",
            }
        except RuntimeError as e:
            # Raised by search_opportunities on timeout
            logger.error(f"Runtime error during preview: {e}")
            return {
                "success": False,
                "error": "timeout",
                "message": str(e),
            }
        except Exception as e:
            logger.error(f"Error during search preview: {type(e).__name__}: {e}")
            return {
                "success": False,
                "error": "unknown",
                "message": str(e) or f"Unknown error: {type(e).__name__}",
            }

    async def _index_to_opensearch(
        self,
        session,  # AsyncSession
        solicitation,  # SamSolicitation
        notice,  # SamNotice
        opportunity: Dict[str, Any],
    ):
        """
        Index solicitation and notice to OpenSearch for unified search.

        This enables SAM.gov data to appear in the platform's unified search
        results alongside assets and other content.

        Args:
            session: Database session
            solicitation: SamSolicitation instance
            notice: SamNotice instance
            opportunity: Raw opportunity data from API
        """
        from .config_loader import config_loader
        from .opensearch_service import opensearch_service

        # Check if OpenSearch is enabled
        opensearch_config = config_loader.get_opensearch_config()
        if not opensearch_config or not opensearch_config.enabled:
            return

        if not opensearch_service.is_available:
            logger.debug("OpenSearch not available, skipping SAM indexing")
            return

        try:
            # Index the solicitation
            await opensearch_service.index_sam_solicitation(
                organization_id=solicitation.organization_id,
                solicitation_id=solicitation.id,
                solicitation_number=solicitation.solicitation_number,
                title=solicitation.title,
                description=solicitation.description,
                notice_type=solicitation.notice_type,
                agency=solicitation.agency_name,
                sub_agency=solicitation.bureau_name,
                office=solicitation.office_name,
                posted_date=solicitation.posted_date,
                response_deadline=solicitation.response_deadline,
                naics_codes=[solicitation.naics_code] if solicitation.naics_code else None,
                psc_codes=[solicitation.psc_code] if solicitation.psc_code else None,
                set_aside=solicitation.set_aside_code,
                place_of_performance=solicitation.place_of_performance.get("city") if solicitation.place_of_performance else None,
                notice_count=solicitation.notice_count or 0,
                attachment_count=solicitation.attachment_count or 0,
                summary_status=solicitation.summary_status,
                is_active=solicitation.is_active,
                created_at=solicitation.created_at,
            )

            # Index the notice
            await opensearch_service.index_sam_notice(
                organization_id=solicitation.organization_id,
                notice_id=notice.id,
                sam_notice_id=notice.sam_notice_id,
                solicitation_id=solicitation.id,
                solicitation_number=solicitation.solicitation_number,
                title=notice.title,
                description=notice.description,
                notice_type=notice.notice_type,
                agency=solicitation.agency_name,
                sub_agency=solicitation.bureau_name,
                office=solicitation.office_name,
                posted_date=notice.posted_date,
                response_deadline=notice.response_deadline,
                naics_codes=[solicitation.naics_code] if solicitation.naics_code else None,
                psc_codes=[solicitation.psc_code] if solicitation.psc_code else None,
                set_aside=solicitation.set_aside_code,
                place_of_performance=solicitation.place_of_performance.get("city") if solicitation.place_of_performance else None,
                version_number=notice.version_number,
                created_at=notice.created_at,
            )

            logger.debug(
                f"Indexed SAM solicitation {solicitation.id} and notice {notice.id} to OpenSearch"
            )

        except Exception as e:
            # Don't fail the pull if indexing fails
            logger.warning(f"Failed to index SAM data to OpenSearch: {e}")

    async def refresh_solicitation(
        self,
        session,  # AsyncSession
        solicitation_id: UUID,
        organization_id: UUID,
    ) -> Dict[str, Any]:
        """
        Refresh a solicitation by re-fetching data from SAM.gov.

        If the solicitation has a solicitation_number, searches by that to get
        all related notices. If not (e.g., Special Notices), just fetches the
        description for the existing notice_id.

        Args:
            session: Database session
            solicitation_id: SamSolicitation UUID to refresh
            organization_id: Organization UUID for connection lookup

        Returns:
            Refresh results summary
        """
        from .sam_service import sam_service

        # Get the solicitation
        solicitation = await sam_service.get_solicitation(
            session, solicitation_id, include_notices=True
        )
        if not solicitation:
            raise ValueError(f"Solicitation not found: {solicitation_id}")

        if solicitation.organization_id != organization_id:
            raise ValueError("Access denied to this solicitation")

        notice_id = solicitation.notice_id
        sol_number = solicitation.solicitation_number

        results = {
            "solicitation_id": str(solicitation_id),
            "solicitation_number": sol_number,
            "notice_id": notice_id,
            "opportunities_found": 0,
            "notices_created": 0,
            "notices_updated": 0,
            "description_updated": False,
            "error": None,
        }

        # If no solicitation_number, just refresh the description for existing notices
        # Don't search broadly - that could return unrelated results
        if not sol_number:
            logger.info(
                f"Solicitation {solicitation_id} has no solicitation_number. "
                f"Refreshing description only for notice_id: {notice_id}"
            )
            return await self._refresh_description_only(
                session, solicitation, organization_id, results
            )

        # Has solicitation_number - search SAM.gov by solnum to get all related notices
        logger.info(f"Refreshing solicitation {solicitation_id} from SAM.gov (solnum: {sol_number})")

        try:
            # Search SAM.gov by solicitation number
            # Don't include date filters to get full history
            search_config = {
                "solicitation_number": sol_number,
                "active_only": False,
            }

            opportunities, total = await self.search_opportunities(
                search_config,
                limit=100,
                session=session,
                organization_id=organization_id,
            )

            results["opportunities_found"] = len(opportunities)
            logger.info(f"Found {len(opportunities)} opportunities for solicitation {sol_number}")

            if not opportunities:
                # No results from solnum search - fall back to description-only refresh
                logger.info(f"No results for solnum search, falling back to description refresh")
                return await self._refresh_description_only(
                    session, solicitation, organization_id, results
                )

            # Get existing notices for this solicitation
            existing_notices = await sam_service.list_notices(session, solicitation_id)
            existing_notice_ids = {n.sam_notice_id for n in existing_notices}

            # Track the latest opportunity for updating solicitation description
            latest_opportunity = None
            latest_posted_date = None

            # Process each opportunity (notice)
            for opp in opportunities:
                opp_notice_id = opp.get("notice_id")
                if not opp_notice_id:
                    continue

                # Fetch full description
                description = opp.get("description")
                if description and description.startswith("http"):
                    logger.debug(f"Fetching full description for notice {opp_notice_id}")
                    full_description = await self.fetch_notice_description(
                        opp_notice_id, session, organization_id
                    )
                    if full_description:
                        description = full_description
                    # Rate limiting
                    await asyncio.sleep(self.rate_limit_delay)

                # Track latest for solicitation description
                posted_date = opp.get("posted_date")
                if posted_date and (latest_posted_date is None or posted_date > latest_posted_date):
                    latest_posted_date = posted_date
                    latest_opportunity = opp
                    latest_opportunity["_fetched_description"] = description

                # Check if notice already exists
                if opp_notice_id in existing_notice_ids:
                    # Update existing notice
                    existing_notice = next(
                        (n for n in existing_notices if n.sam_notice_id == opp_notice_id), None
                    )
                    if existing_notice:
                        # Update if description was a URL or is different
                        needs_update = (
                            existing_notice.description and
                            (existing_notice.description.startswith("http") or
                             existing_notice.description != description)
                        )
                        if needs_update and description:
                            await sam_service.update_notice(
                                session,
                                notice_id=existing_notice.id,
                                title=opp.get("title"),
                                description=description,
                                response_deadline=opp.get("response_deadline"),
                            )
                            results["notices_updated"] += 1
                            logger.debug(f"Updated notice {existing_notice.id} with fresh description")
                else:
                    # Create new notice (historical data we didn't have)
                    version_number = len(existing_notices) + results["notices_created"] + 1
                    await sam_service.create_notice(
                        session=session,
                        solicitation_id=solicitation_id,
                        sam_notice_id=opp_notice_id,
                        notice_type=opp.get("notice_type", "o"),
                        version_number=version_number,
                        title=opp.get("title"),
                        description=description,
                        posted_date=opp.get("posted_date"),
                        response_deadline=opp.get("response_deadline"),
                    )
                    results["notices_created"] += 1
                    logger.info(f"Created new notice {opp_notice_id} (version {version_number})")

            # Update solicitation with latest opportunity's description
            if latest_opportunity:
                latest_description = latest_opportunity.get("_fetched_description")
                if latest_description and latest_description != solicitation.description:
                    await sam_service.update_solicitation(
                        session,
                        solicitation_id=solicitation.id,
                        title=latest_opportunity.get("title") or solicitation.title,
                        description=latest_description,
                        response_deadline=latest_opportunity.get("response_deadline"),
                    )
                    results["description_updated"] = True
                    logger.info(
                        f"Updated solicitation {solicitation_id} with latest description "
                        f"({len(latest_description)} chars)"
                    )

            await session.commit()
            logger.info(f"Refresh completed for solicitation {solicitation_id}: {results}")

        except Exception as e:
            results["error"] = str(e)
            logger.error(f"Error refreshing solicitation {solicitation_id}: {e}")

        return results

    async def _refresh_description_only(
        self,
        session,
        solicitation,
        organization_id: UUID,
        results: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Refresh only the description for a solicitation without searching broadly.

        Used when there's no solicitation_number to search by.
        """
        from .sam_service import sam_service

        notice_id = solicitation.notice_id
        if not notice_id:
            results["error"] = "Solicitation has no notice_id"
            return results

        try:
            # Fetch the full description for this specific notice
            logger.debug(f"Fetching description for notice {notice_id}")
            description = await self.fetch_notice_description(
                notice_id, session, organization_id
            )

            if not description:
                results["error"] = f"Could not fetch description from SAM.gov for notice_id: {notice_id}"
                logger.warning(results["error"])
                return results

            # Update solicitation description if different
            if description != solicitation.description:
                await sam_service.update_solicitation(
                    session,
                    solicitation_id=solicitation.id,
                    description=description,
                )
                results["description_updated"] = True
                logger.info(f"Updated solicitation description ({len(description)} chars)")

            # Update notices with the same notice_id
            notices = await sam_service.list_notices(session, solicitation.id)
            for notice in notices:
                if notice.sam_notice_id == notice_id:
                    if notice.description and notice.description.startswith("http"):
                        await sam_service.update_notice(
                            session,
                            notice_id=notice.id,
                            description=description,
                        )
                        results["notices_updated"] += 1
                        logger.debug(f"Updated notice {notice.id} with fresh description")

            await session.commit()
            logger.info(f"Description refresh completed: {results}")

        except Exception as e:
            results["error"] = str(e)
            logger.error(f"Error refreshing description: {e}")

        return results


# Singleton instance
sam_pull_service = SamPullService()
