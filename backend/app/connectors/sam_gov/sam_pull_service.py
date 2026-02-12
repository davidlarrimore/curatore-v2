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
    from app.connectors.sam_gov.sam_pull_service import sam_pull_service

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
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

# Note: We don't use urljoin because it strips path for absolute endpoints
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.core.database.models import (
    Asset,
    Run,
)
from app.core.shared.run_log_service import run_log_service

from .sam_api_usage_service import sam_api_usage_service
from .sam_service import sam_service

logger = logging.getLogger("curatore.api.sam_pull_service")


# SAM.gov Opportunities API v2 Base URL
SAM_API_BASE_URL = "https://api.sam.gov/opportunities/v2"

# Errors that should trigger a retry with wait
TRANSIENT_ERRORS = (
    "Server disconnected",
    "Connection reset",
    "Connection refused",
    "Read timed out",
    "Timeout",
    "TimeoutException",
    "ConnectError",
    "RemoteProtocolError",
)


def _format_error(e: Exception) -> str:
    """
    Format exception with type name when message is empty.

    Some network exceptions (e.g., httpx.RemoteProtocolError) can have empty
    string representations, making error logs useless. This ensures we always
    have meaningful error information.

    Args:
        e: The exception to format

    Returns:
        Formatted error string with type and message
    """
    msg = str(e)
    if not msg or msg.isspace():
        return f"{type(e).__name__}: Connection error (no details available)"
    return f"{type(e).__name__}: {msg}"


async def _retry_on_transient_error(
    func: Callable,
    *args,
    max_retries: int = 3,
    retry_delay_seconds: int = 10,
    on_retry: Optional[Callable[[int, str, int], Any]] = None,
    **kwargs,
) -> Any:
    """
    Execute a function with retry logic for transient network errors.

    Implements exponential backoff for network-related failures that are
    likely to be transient (connection drops, timeouts, 5xx errors).

    Args:
        func: Async function to execute
        max_retries: Maximum number of retry attempts (default 3)
        retry_delay_seconds: Base seconds to wait between retries (default 10)
        on_retry: Optional async callback(attempt, error_message, wait_time) called before each retry
        *args, **kwargs: Arguments to pass to func

    Returns:
        Result from func

    Raises:
        Last exception if all retries exhausted
    """
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except httpx.HTTPStatusError as e:
            # Don't retry on 4xx errors except 429 (rate limiting)
            if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                raise
            last_error = e
            error_msg = f"HTTP {e.response.status_code}"
        except (
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.ConnectTimeout,
            httpx.RemoteProtocolError,
        ) as e:
            last_error = e
            error_msg = _format_error(e)
        except Exception as e:
            # Check if error message contains transient error patterns
            error_str = str(e)
            if any(pattern.lower() in error_str.lower() for pattern in TRANSIENT_ERRORS):
                last_error = e
                error_msg = _format_error(e)
            else:
                raise

        # If we get here, we had a retryable error
        if attempt < max_retries:
            # Exponential backoff: 10s, 20s, 40s
            wait_time = retry_delay_seconds * (2 ** attempt)
            if on_retry:
                await on_retry(attempt + 1, error_msg, wait_time)
            logger.warning(
                f"Transient error (attempt {attempt + 1}/{max_retries + 1}): {error_msg}. "
                f"Waiting {wait_time}s before retry..."
            )
            await asyncio.sleep(wait_time)

    # All retries exhausted
    raise last_error

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


def _parse_sam_date(date_str: Optional[str]) -> Optional[datetime]:
    """
    Parse a SAM.gov date string and return a naive UTC datetime.

    SAM.gov returns dates in various formats:
    - ISO format with Z suffix: "2026-01-29T00:00:00Z"
    - ISO format with offset: "2026-02-06T16:00:00-05:00"
    - Date only: "2026-01-29"

    This function normalizes all dates to naive UTC datetimes for storage
    in PostgreSQL TIMESTAMP WITHOUT TIME ZONE columns.

    For date-only strings (no time component), the time is set to noon EST
    (17:00 UTC) so that converting to EST for display never shifts the
    calendar date.

    Args:
        date_str: Date string from SAM.gov API

    Returns:
        Naive datetime in UTC, or None if parsing fails
    """
    if not date_str:
        return None

    try:
        # Replace Z suffix with +00:00 for consistent parsing
        normalized = date_str.replace("Z", "+00:00")

        # Try parsing as ISO format (handles both datetime and date-only)
        dt = datetime.fromisoformat(normalized)

        # If timezone-aware, convert to UTC and make naive
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        elif "T" not in date_str and " " not in date_str:
            # Date-only string: anchor to noon EST so EST display stays on
            # the correct calendar date (midnight UTC would roll back a day)
            est = ZoneInfo("America/New_York")
            dt = datetime(dt.year, dt.month, dt.day, 12, 0, 0, tzinfo=est)
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)

        return dt
    except (ValueError, AttributeError):
        return None


class SamPullService:
    """
    Service for pulling data from SAM.gov Opportunities API.

    Handles API communication, data transformation, and storage operations.
    """

    def __init__(self):
        self.api_key: Optional[str] = None
        self.base_url = SAM_API_BASE_URL
        # Structured timeout: separate connect vs read phases
        # SAM.gov API can be slow to respond, so read timeout is longer
        self.timeout = httpx.Timeout(
            connect=10.0,    # Connection establishment
            read=60.0,       # Response read (SAM API can be slow)
            write=10.0,      # Request write
            pool=10.0,       # Pool acquisition
        )
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
                from app.core.auth.connection_service import connection_service

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
        timeout: Optional[Dict[str, float]] = None,
    ):
        """
        Configure the pull service with custom settings.

        Args:
            api_key: SAM.gov API key override
            timeout: Timeout configuration dict with keys: connect, read, write, pool
                     Example: {"connect": 10.0, "read": 120.0}

        Note: base_url is intentionally not configurable - SAM.gov API has a fixed
        endpoint (https://api.sam.gov/opportunities/v2) that cannot be changed.
        """
        if api_key:
            self.api_key = api_key
        if timeout:
            self.timeout = httpx.Timeout(
                connect=timeout.get("connect", 10.0),
                read=timeout.get("read", 60.0),
                write=timeout.get("write", 10.0),
                pool=timeout.get("pool", 10.0),
            )

    async def _is_run_cancelled(
        self,
        session,
        run_id: Optional[UUID],
    ) -> bool:
        """
        Check if a run has been cancelled.

        This allows long-running SAM pulls to be stopped gracefully when the user
        cancels the job. The check should be performed periodically during pagination.

        Args:
            session: Database session
            run_id: Run UUID to check

        Returns:
            True if run is cancelled, False otherwise
        """
        if not run_id:
            return False

        try:
            # Refresh the run from database to get current status
            run = await session.get(Run, run_id)
            if run and run.status == "cancelled":
                logger.info(f"SAM pull {run_id} has been cancelled, stopping")
                return True
        except Exception as e:
            logger.warning(f"Error checking run cancellation status: {e}")

        return False

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
        department_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build API query parameters from search configuration.

        Args:
            search_config: Search configuration from SamSearch.search_config
            limit: Number of results per page
            offset: Offset for pagination
            department_override: If provided, use this department instead of search_config

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
        # department_override is used when iterating through departments array in multi-department mode
        # For single-department mode, use the department directly from search_config
        if department_override:
            params["organizationName"] = department_override
        else:
            # Check for single department in search_config
            departments = search_config.get("departments", [])
            if len(departments) == 1:
                params["organizationName"] = departments[0]
                logger.debug(f"Using single department filter: {departments[0]}")

        # Solicitation number filter (exact match)
        if search_config.get("solicitation_number"):
            params["solnum"] = search_config["solicitation_number"]

        # Notice ID filter (exact match for standalone notices)
        if search_config.get("notice_id"):
            params["noticeid"] = search_config["notice_id"]

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
        # Extract dates - convert to naive UTC for database storage
        posted_date = _parse_sam_date(data.get("postedDate"))
        response_deadline = _parse_sam_date(data.get("responseDeadLine"))
        archive_date = _parse_sam_date(data.get("archiveDate"))

        # If postedDate is today, use current EST time as the posted time
        # since that's when we first observed the notice (SAM.gov API only
        # provides a date, not a timestamp, for postedDate)
        if posted_date:
            est = ZoneInfo("America/New_York")
            now_est = datetime.now(est)
            posted_est = posted_date.replace(tzinfo=timezone.utc).astimezone(est)
            if posted_est.date() == now_est.date():
                posted_date = now_est.astimezone(timezone.utc).replace(tzinfo=None)

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
            "notice_type": data.get("type", "Solicitation"),
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
            "attachments": data.get("resourceLinks") or [],
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
        description_url = "https://api.sam.gov/prod/opportunities/v1/noticedesc"

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

    async def _fetch_all_for_department(
        self,
        search_config: Dict[str, Any],
        department: str,
        session,
        organization_id: UUID,
        max_pages: int,
        page_size: int,
        run_id: Optional[UUID] = None,
        department_index: int = 0,
        total_departments: int = 1,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Fetch all opportunities for a single department, paginating through results.

        Args:
            search_config: Search configuration
            department: Department name to search for
            session: Database session
            organization_id: Organization UUID
            max_pages: Maximum pages to fetch per department
            page_size: Results per page
            run_id: Optional Run UUID for activity logging
            department_index: 0-based index of this department in the list
            total_departments: Total number of departments being searched

        Returns:
            Tuple of (opportunities list, stats dict)
        """
        opportunities = []
        stats = {
            "department": department,
            "api_calls": 0,
            "total_fetched": 0,
            "pages_fetched": 0,
        }

        offset = 0
        pages_fetched = 0

        # Log department search start
        if run_id:
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="department_search_start",
                message=f"Searching department {department_index + 1}/{total_departments}: {department}",
                context={
                    "department": department,
                    "index": department_index,
                    "total": total_departments,
                },
            )
            await session.commit()

        while pages_fetched < max_pages:
            # Build params with department override
            params = self._build_search_params(
                search_config,
                limit=page_size,
                offset=offset,
                department_override=department,
            )

            try:
                # Define retry callback to log retry attempts
                async def on_retry(attempt: int, error_msg: str, wait_time: int):
                    logger.warning(
                        f"Department {department}: Retry {attempt} after error: {error_msg}"
                    )
                    if run_id:
                        await run_log_service.log_event(
                            session=session,
                            run_id=run_id,
                            level="WARNING",
                            event_type="retry",
                            message=f"Retrying {department} after error (attempt {attempt})",
                            context={
                                "department": department,
                                "error": error_msg,
                                "wait_seconds": wait_time,
                                "attempt": attempt,
                            },
                        )
                        await session.commit()

                # Use retry helper for transient errors
                response = await _retry_on_transient_error(
                    self._make_request,
                    "/search",
                    params,
                    session=session,
                    organization_id=organization_id,
                    max_retries=3,
                    retry_delay_seconds=10,
                    on_retry=on_retry,
                )
                stats["api_calls"] += 1

                # Check for cancellation after each API call
                if await self._is_run_cancelled(session, run_id):
                    stats["cancelled"] = True
                    break

                total = response.get("totalRecords", 0)
                page_opportunities = []

                for opp_data in response.get("opportunitiesData", []):
                    parsed = self._parse_opportunity(opp_data)
                    page_opportunities.append(parsed)

                opportunities.extend(page_opportunities)
                stats["total_fetched"] += len(page_opportunities)
                pages_fetched += 1
                stats["pages_fetched"] = pages_fetched

                if not page_opportunities or offset + page_size >= total:
                    break

                offset += page_size
                await asyncio.sleep(self.rate_limit_delay)

            except Exception as e:
                # After retries exhausted, mark department as failed but don't raise
                error_msg = _format_error(e)
                logger.error(
                    f"Department {department} failed after retries at offset {offset}: {error_msg}"
                )
                stats["failed"] = True
                stats["error"] = error_msg

                if run_id:
                    await run_log_service.log_event(
                        session=session,
                        run_id=run_id,
                        level="ERROR",
                        event_type="department_failed",
                        message=f"Department {department} failed after retries: {error_msg}",
                        context={
                            "department": department,
                            "error": error_msg,
                            "offset": offset,
                            "pages_fetched": pages_fetched,
                            "opportunities_fetched": len(opportunities),
                        },
                    )
                    await session.commit()

                # Stop fetching this department, but return what we have
                break

        # Log department search complete (if not cancelled)
        if run_id:
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="department_search_complete",
                message=f"Completed department {department}: {stats['total_fetched']} opportunities, {stats['api_calls']} API calls",
                context={
                    "department": department,
                    "fetched": stats["total_fetched"],
                    "api_calls": stats["api_calls"],
                    "pages": stats["pages_fetched"],
                },
            )
            await session.commit()

        return opportunities, stats

    async def _fetch_opportunities_multi_department(
        self,
        search_config: Dict[str, Any],
        departments: List[str],
        session,
        organization_id: UUID,
        max_pages: int,
        page_size: int,
        run_id: Optional[UUID] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Fetch opportunities from multiple departments and deduplicate by notice_id.

        Args:
            search_config: Search configuration
            departments: List of department names to search
            session: Database session
            organization_id: Organization UUID
            max_pages: Maximum pages to fetch per department
            page_size: Results per page
            run_id: Optional Run UUID for activity logging

        Returns:
            Tuple of (deduplicated opportunities list, aggregate stats dict)
        """
        all_opportunities = []
        department_stats = []
        seen_notice_ids: set = set()
        total_api_calls = 0
        total_fetched = 0
        duplicates_removed = 0

        for idx, department in enumerate(departments):
            # Check for cancellation before starting each department
            if await self._is_run_cancelled(session, run_id):
                logger.info(f"SAM pull cancelled before department {idx + 1}/{len(departments)}")
                break

            dept_opportunities, stats = await self._fetch_all_for_department(
                search_config=search_config,
                department=department,
                session=session,
                organization_id=organization_id,
                max_pages=max_pages,
                page_size=page_size,
                run_id=run_id,
                department_index=idx,
                total_departments=len(departments),
            )

            # Check if department fetch was cancelled
            if stats.get("cancelled"):
                logger.info(f"SAM pull cancelled during department {department}")
                break

            # Deduplicate by notice_id
            unique_for_dept = 0
            duplicates_for_dept = 0
            for opp in dept_opportunities:
                notice_id = opp.get("notice_id")
                if notice_id and notice_id not in seen_notice_ids:
                    seen_notice_ids.add(notice_id)
                    all_opportunities.append(opp)
                    unique_for_dept += 1
                else:
                    duplicates_for_dept += 1
                    duplicates_removed += 1

            stats["unique"] = unique_for_dept
            stats["duplicates"] = duplicates_for_dept
            stats["status"] = "failed" if stats.get("failed") else "success"
            department_stats.append(stats)
            total_api_calls += stats["api_calls"]
            total_fetched += stats["total_fetched"]

        # Calculate partial success status
        successful_departments = sum(1 for s in department_stats if s.get("status") == "success")
        failed_departments = sum(1 for s in department_stats if s.get("status") == "failed")

        # Determine overall status
        if failed_departments == 0:
            overall_status = "completed"
        elif successful_departments == 0:
            overall_status = "failed"
        else:
            overall_status = "partial"

        aggregate_stats = {
            "departments_searched": len(departments),
            "departments_succeeded": successful_departments,
            "departments_failed": failed_departments,
            "overall_status": overall_status,
            "total_api_calls": total_api_calls,
            "total_fetched": total_fetched,
            "unique_opportunities": len(all_opportunities),
            "duplicates_removed": duplicates_removed,
            "department_breakdown": department_stats,
        }

        # Log partial success if applicable
        if overall_status == "partial" and run_id:
            failed_dept_names = [s["department"] for s in department_stats if s.get("status") == "failed"]
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="WARNING",
                event_type="partial_success",
                message=f"Partial success: {successful_departments}/{len(departments)} departments succeeded. Failed: {', '.join(failed_dept_names)}",
                context={
                    "successful": successful_departments,
                    "failed": failed_departments,
                    "failed_departments": failed_dept_names,
                },
            )
            await session.commit()

        return all_opportunities, aggregate_stats

    async def get_opportunity_details(
        self,
        notice_id: str,
        session=None,
        organization_id: Optional[UUID] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get detailed information for a specific opportunity by searching SAM.gov.

        Uses the search API with a noticeId filter since SAM.gov doesn't have
        a direct endpoint for individual opportunities.

        Args:
            notice_id: SAM.gov notice ID
            session: Optional database session for connection lookup
            organization_id: Optional organization ID for connection lookup

        Returns:
            Parsed opportunity data or None if not found
        """
        try:
            # SAM.gov doesn't have a direct endpoint for individual opportunities.
            # Use the search endpoint with noticeId filter instead.
            params = {
                "noticeId": notice_id,
                "limit": 1,
            }

            response = await self._make_request(
                "/search",
                params=params,
                session=session,
                organization_id=organization_id,
            )

            opportunities_data = response.get("opportunitiesData", [])
            if opportunities_data:
                return self._parse_opportunity(opportunities_data[0])

            logger.warning(f"No opportunity found for notice_id: {notice_id}")
            return None

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            logger.error(f"Error fetching opportunity {notice_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error fetching opportunity {notice_id}: {e}")
            return None

    async def pull_opportunities(
        self,
        session,  # AsyncSession
        search_id: UUID,
        organization_id: UUID,
        max_pages: int = 10,
        page_size: int = 100,
        check_rate_limit: bool = True,
        auto_download_attachments: bool = True,
        run_id: Optional[UUID] = None,
        group_id: Optional[UUID] = None,
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
            run_id: Optional Run UUID for activity logging

        Returns:
            Pull results summary
        """
        search = await sam_service.get_search(session, search_id)
        if not search:
            raise ValueError(f"Search not found: {search_id}")

        search_config = search.search_config or {}

        # Log start of pull
        if run_id:
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="phase",
                message=f"Starting SAM.gov pull for search: {search.name}",
                context={
                    "phase": "init",
                    "search_name": search.name,
                    "max_pages": max_pages,
                    "page_size": page_size,
                },
            )
            await session.commit()

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
            "updated_notices": 0,
            "new_attachments": 0,
            "api_calls_made": 0,
            "errors": [],
            "processed_solicitation_ids": [],  # Track solicitation IDs for auto-download
            "processed_notice_ids": [],  # Track standalone notice IDs for auto-download
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
                if run_id:
                    await run_log_service.log_event(
                        session=session,
                        run_id=run_id,
                        level="WARN",
                        event_type="rate_limit",
                        message=f"API rate limit exceeded. Remaining calls: {remaining}",
                        context={"remaining": remaining, "needed": max_pages},
                    )
                    await session.commit()
                results["status"] = "rate_limited"
                results["error"] = f"API rate limit exceeded. Remaining calls: {remaining}"
                results["rate_limit_remaining"] = remaining
                return results

        # Determine department search strategy
        departments = search_config.get("departments", [])

        # Log department strategy
        if len(departments) > 1:
            logger.info(
                f"Starting pull for search {search_id}: Multi-department mode for {len(departments)} departments"
            )
        elif len(departments) == 1:
            logger.info(f"Starting pull for search {search_id}: Single department: {departments[0]}")

        try:
            # Multi-department path: fetch from each, deduplicate, then process
            if len(departments) > 1:
                all_opportunities, multi_dept_stats = await self._fetch_opportunities_multi_department(
                    search_config=search_config,
                    departments=departments,
                    session=session,
                    organization_id=organization_id,
                    max_pages=max_pages,
                    page_size=page_size,
                    run_id=run_id,
                )

                results["total_fetched"] = multi_dept_stats["total_fetched"]
                results["api_calls_made"] = multi_dept_stats["total_api_calls"]
                results["duplicates_removed"] = multi_dept_stats["duplicates_removed"]
                results["department_breakdown"] = multi_dept_stats["department_breakdown"]
                results["departments_succeeded"] = multi_dept_stats.get("departments_succeeded", 0)
                results["departments_failed"] = multi_dept_stats.get("departments_failed", 0)
                # Track partial success for multi-department pulls
                if multi_dept_stats.get("overall_status") == "partial":
                    results["partial_success"] = True
                elif multi_dept_stats.get("overall_status") == "failed":
                    # All departments failed - this is a complete failure
                    results["status"] = "failed"
                    failed_errors = [
                        s.get("error") for s in multi_dept_stats.get("department_breakdown", [])
                        if s.get("error")
                    ]
                    results["error"] = "; ".join(failed_errors) if failed_errors else "All departments failed"

                # Record API calls for rate limiting
                if check_rate_limit:
                    for _ in range(multi_dept_stats["total_api_calls"]):
                        await sam_api_usage_service.record_call(
                            session, organization_id, "search"
                        )

                # Log multi-department fetch completion
                if run_id:
                    await run_log_service.log_event(
                        session=session,
                        run_id=run_id,
                        level="INFO",
                        event_type="progress",
                        message=f"Multi-department fetch complete: {multi_dept_stats['total_fetched']} total, {multi_dept_stats['unique_opportunities']} unique, {multi_dept_stats['duplicates_removed']} duplicates removed",
                        context={
                            "departments": len(departments),
                            "total_fetched": multi_dept_stats["total_fetched"],
                            "unique": multi_dept_stats["unique_opportunities"],
                            "duplicates_removed": multi_dept_stats["duplicates_removed"],
                            "api_calls": multi_dept_stats["total_api_calls"],
                        },
                    )
                    await session.commit()

                # Apply NAICS filtering and process all opportunities
                configured_naics = search_config.get("naics_codes", [])
                for opp in all_opportunities:
                    # NAICS filter
                    if configured_naics and opp.get("naics_code") not in configured_naics:
                        results["filtered_by_naics"] += 1
                        continue

                    # Process opportunity
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
                        error_msg = _format_error(e)
                        logger.error(f"Error processing opportunity {opp.get('notice_id')}: {error_msg}")
                        results["errors"].append({
                            "notice_id": opp.get("notice_id"),
                            "error": error_msg,
                        })

            else:
                # Single/no department path: use existing efficient pagination
                offset = 0
                pages_fetched = 0

                while pages_fetched < max_pages:
                    # Check for cancellation before each page
                    if await self._is_run_cancelled(session, run_id):
                        results["cancelled"] = True
                        if run_id:
                            await run_log_service.log_event(
                                session=session,
                                run_id=run_id,
                                level="INFO",
                                event_type="cancelled",
                                message=f"SAM pull cancelled after {pages_fetched} pages",
                                context={"pages_fetched": pages_fetched},
                            )
                            await session.commit()
                        break

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
                        if run_id and pages_fetched == 0:
                            await run_log_service.log_event(
                                session=session,
                                run_id=run_id,
                                level="INFO",
                                event_type="progress",
                                message="No opportunities found matching search criteria",
                                context={"pages_fetched": pages_fetched},
                            )
                            await session.commit()
                        break

                    results["total_fetched"] += len(opportunities)

                    # Log page fetch progress
                    if run_id:
                        await run_log_service.log_event(
                            session=session,
                            run_id=run_id,
                            level="INFO",
                            event_type="progress",
                            message=f"Fetched page {pages_fetched + 1}: {len(opportunities)} opportunities (total: {results['total_fetched']})",
                            context={
                                "page": pages_fetched + 1,
                                "page_count": len(opportunities),
                                "total_fetched": results["total_fetched"],
                                "total_available": total,
                            },
                        )
                        await session.commit()

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
                            error_msg = _format_error(e)
                            logger.error(f"Error processing opportunity {opp.get('notice_id')}: {error_msg}")
                            results["errors"].append({
                                "notice_id": opp.get("notice_id"),
                                "error": error_msg,
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

            # Log fetch completion
            if run_id:
                await run_log_service.log_event(
                    session=session,
                    run_id=run_id,
                    level="INFO",
                    event_type="phase",
                    message=f"Fetch complete: {results['total_fetched']} fetched, {results['new_solicitations']} new, {results['updated_solicitations']} updated",
                    context={
                        "phase": "fetch_complete",
                        "total_fetched": results["total_fetched"],
                        "processed": results["processed"],
                        "new_solicitations": results["new_solicitations"],
                        "updated_solicitations": results["updated_solicitations"],
                        "new_notices": results["new_notices"],
                        "new_attachments": results["new_attachments"],
                        "errors": len(results["errors"]),
                        "duplicates_removed": results.get("duplicates_removed", 0),
                        "department_breakdown": results.get("department_breakdown"),
                    },
                )
                await session.commit()

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

                if run_id and len(solicitation_ids) > 0:
                    await run_log_service.log_event(
                        session=session,
                        run_id=run_id,
                        level="INFO",
                        event_type="phase",
                        message=f"Downloading attachments for {len(solicitation_ids)} solicitations",
                        context={"phase": "attachments", "solicitation_count": len(solicitation_ids)},
                    )
                    await session.commit()

                print(f"[SAM_DEBUG] Found {len(solicitation_ids)} solicitations processed in this pull")
                for sol_id in solicitation_ids:
                    print(f"[SAM_DEBUG] Processing solicitation: {sol_id}...")
                    download_result = await self.download_all_attachments(
                        session=session,
                        solicitation_id=UUID(sol_id),
                        organization_id=organization_id,
                        group_id=group_id,
                    )
                    results["attachment_downloads"]["total"] += download_result["total"]
                    results["attachment_downloads"]["downloaded"] += download_result["downloaded"]
                    results["attachment_downloads"]["failed"] += download_result["failed"]
                    results["attachment_downloads"]["errors"].extend(download_result.get("errors", []))

                # Download attachments for standalone notices processed in this pull
                notice_ids = results.get("processed_notice_ids", [])

                if notice_ids:
                    if run_id:
                        await run_log_service.log_event(
                            session=session,
                            run_id=run_id,
                            level="INFO",
                            event_type="phase",
                            message=f"Downloading attachments for {len(notice_ids)} standalone notices",
                            context={"phase": "notice_attachments", "notice_count": len(notice_ids)},
                        )
                        await session.commit()

                    for nid in notice_ids:
                        download_result = await self.download_all_notice_attachments(
                            session=session,
                            notice_id=UUID(nid),
                            organization_id=organization_id,
                            group_id=group_id,
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
                    if run_id:
                        await run_log_service.log_event(
                            session=session,
                            run_id=run_id,
                            level="INFO",
                            event_type="progress",
                            message=f"Attachments: {results['attachment_downloads']['downloaded']} downloaded, {results['attachment_downloads']['failed']} failed",
                            context={
                                "phase": "attachments",
                                "total": results["attachment_downloads"]["total"],
                                "downloaded": results["attachment_downloads"]["downloaded"],
                                "failed": results["attachment_downloads"]["failed"],
                            },
                        )
                        await session.commit()
                else:
                    logger.debug("No pending attachments to download")

        except Exception as e:
            import traceback
            error_msg = _format_error(e)
            print(f"[SAM_DEBUG] EXCEPTION in pull_opportunities: {error_msg}")
            print(f"[SAM_DEBUG] Traceback: {traceback.format_exc()}")
            logger.error(f"Pull failed for search {search_id}: {error_msg}")
            await sam_service.update_search_pull_status(session, search_id, "failed")
            results["status"] = "failed"
            results["error"] = error_msg

            if run_id:
                await run_log_service.log_event(
                    session=session,
                    run_id=run_id,
                    level="ERROR",
                    event_type="error",
                    message=f"Pull failed: {error_msg}",
                    context={"error": error_msg, "traceback": traceback.format_exc()[:1000]},
                )
                await session.commit()

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
        Process a single opportunity — unified flow for all notice types.

        All notice types (solicitations, amendments, special notices, etc.) follow
        the same processing path. The only difference is whether a parent
        SamSolicitation exists: notices with a solicitation_number get linked to
        one, while standalone notices (e.g., Special Notices) have
        solicitation_id=None.

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

        # Step 1: Dedup — skip if this notice already exists (notices are atomic)
        existing_notice = await sam_service.get_notice_by_sam_notice_id(
            session, notice_id, organization_id=organization_id
        )
        if existing_notice:
            return

        # Step 2: Fetch full HTML description from the notice description API
        # The search API returns a URL in the description field, not the actual description
        description = opportunity.get("description")
        description_url = None
        if description and description.startswith("http"):
            description_url = description
            logger.debug(f"Fetching full description for notice {notice_id}")
            full_description = await self.fetch_notice_description(
                notice_id, session, organization_id
            )
            if full_description:
                description = full_description
                await asyncio.sleep(self.rate_limit_delay)

        # Step 3: Solicitation lookup/creation (only when solicitation_number present)
        solicitation_number = opportunity.get("solicitation_number")
        solicitation = None
        is_new_solicitation = False

        if solicitation_number:
            existing_sol = await sam_service.get_solicitation_by_number(
                session, organization_id, solicitation_number
            )

            if existing_sol:
                await sam_service.update_solicitation(
                    session,
                    solicitation_id=existing_sol.id,
                    title=opportunity.get("title"),
                    description=description,
                    response_deadline=opportunity.get("response_deadline"),
                    agency_name=opportunity.get("agency_name"),
                    bureau_name=opportunity.get("bureau_name"),
                    office_name=opportunity.get("office_name"),
                    full_parent_path=opportunity.get("full_parent_path"),
                    naics_code=opportunity.get("naics_code"),
                    psc_code=opportunity.get("psc_code"),
                    set_aside_code=opportunity.get("set_aside_code"),
                    ui_link=opportunity.get("ui_link"),
                    contact_info=opportunity.get("contact_info"),
                    place_of_performance=opportunity.get("place_of_performance"),
                    raw_data=opportunity.get("raw_data"),
                )
                results["updated_solicitations"] += 1
                solicitation = existing_sol
            else:
                solicitation = await sam_service.create_solicitation(
                    session=session,
                    organization_id=organization_id,
                    notice_id=notice_id,
                    title=opportunity.get("title", "Untitled"),
                    notice_type=notice_type,
                    solicitation_number=solicitation_number,
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
                    raw_data=opportunity.get("raw_data"),
                )
                results["new_solicitations"] += 1
                is_new_solicitation = True

            # Track solicitation ID for auto-download
            if "processed_solicitation_ids" in results:
                results["processed_solicitation_ids"].append(str(solicitation.id))

        solicitation_id = solicitation.id if solicitation else None

        # Step 4: Determine version number
        if solicitation_id:
            latest_notice = await sam_service.get_latest_notice(session, solicitation_id)
            version_number = (latest_notice.version_number + 1) if latest_notice else 1
        else:
            version_number = 1

        # Step 5: Create the notice (organization_id always set for consistent querying)
        notice = await sam_service.create_notice(
            session=session,
            solicitation_id=solicitation_id,
            organization_id=organization_id,
            sam_notice_id=notice_id,
            notice_type=notice_type,
            version_number=version_number,
            title=opportunity.get("title"),
            description=description,
            description_url=description_url,
            posted_date=opportunity.get("posted_date"),
            response_deadline=opportunity.get("response_deadline"),
            raw_data=opportunity.get("raw_data"),
            full_parent_path=opportunity.get("full_parent_path"),
            agency_name=opportunity.get("agency_name"),
            bureau_name=opportunity.get("bureau_name"),
            office_name=opportunity.get("office_name"),
            naics_code=opportunity.get("naics_code"),
            psc_code=opportunity.get("psc_code"),
            set_aside_code=opportunity.get("set_aside_code"),
            ui_link=opportunity.get("ui_link"),
            solicitation_number=solicitation_number,
        )
        results["new_notices"] += 1

        # Track standalone notice IDs for auto-download (no solicitation to track)
        if not solicitation_id and "processed_notice_ids" in results:
            results["processed_notice_ids"].append(str(notice.id))

        # Step 6: Update solicitation counts (if solicitation exists)
        if solicitation_id:
            await sam_service.update_solicitation_counts(session, solicitation_id)

        # Step 7: Process attachments — only if enabled in search config
        download_attachments = True
        if search_config:
            download_attachments = search_config.get("download_attachments", True)

        if download_attachments:
            attachments = opportunity.get("attachments") or []
            for att_data in attachments:
                await self._process_attachment(
                    session=session,
                    organization_id=organization_id,
                    solicitation_id=solicitation_id,
                    notice_id=notice.id,
                    attachment_data=att_data,
                    results=results,
                )

        # Step 8: Index to search
        await self._index_to_search(
            session=session,
            organization_id=organization_id,
            solicitation=solicitation,
            notice=notice,
            opportunity=opportunity,
        )

        # Step 9: Trigger auto-summary tasks
        if is_new_solicitation and solicitation:
            from app.core.tasks import sam_auto_summarize_task
            sam_auto_summarize_task.delay(
                solicitation_id=str(solicitation.id),
                organization_id=str(organization_id),
                is_update=False,
            )
            logger.debug(f"Triggered auto-summary task for new solicitation {solicitation.id}")

        from app.core.tasks import sam_auto_summarize_notice_task
        try:
            sam_auto_summarize_notice_task.delay(
                notice_id=str(notice.id),
                organization_id=str(organization_id),
            )
            logger.debug(f"Triggered auto-summary task for notice {notice.id}")
        except Exception as e:
            logger.warning(f"Could not trigger auto-summary for notice: {e}")

    async def _process_attachment(
        self,
        session,  # AsyncSession
        organization_id: UUID,
        solicitation_id: Optional[UUID],
        notice_id: UUID,
        attachment_data,  # Can be Dict[str, Any] or str (URL)
        results: Dict[str, Any],
    ):
        """
        Process an attachment record.

        Includes deduplication by both resource_id and download_url to
        prevent redundant downloads of the same file. Works for both
        solicitation-linked and standalone notices (solicitation_id may be None).

        Args:
            session: Database session
            organization_id: Organization UUID for multi-tenant isolation
            solicitation_id: Parent solicitation UUID (None for standalone notices)
            notice_id: Parent notice UUID
            attachment_data: Attachment data from API (dict or URL string)
            results: Results dict to update
        """
        # Skip None or empty attachment data
        if not attachment_data:
            return

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
            organization_id=organization_id,
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
        group_id: Optional[UUID] = None,
    ) -> Optional[Asset]:
        """
        Download an attachment and create an Asset.

        Args:
            session: Database session
            attachment_id: SamAttachment UUID
            organization_id: Organization UUID
            minio_service: MinIO service instance (optional)
            check_rate_limit: Whether to check/record API rate limits
            group_id: Optional group UUID to link extraction to (for parent-child tracking)

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
                from app.core.storage.minio_service import get_minio_service
                minio_service = get_minio_service()

            # Build storage path - handle both solicitation-linked and standalone notice attachments
            # SAM.gov returns notices; we create solicitation records when notices have solicitation numbers.
            # Standalone notices (e.g., Special Notices) don't have solicitation records.
            safe_filename = self._sanitize_path_component(real_filename)

            if attachment.solicitation_id:
                # Solicitation-linked attachment - use solicitation info for path
                solicitation = await sam_service.get_solicitation(
                    session, attachment.solicitation_id
                )
                # Format: {org_id}/sam/{agency_code}/{bureau_code}/solicitations/{number}/attachments/{filename}
                sol_number = solicitation.solicitation_number or solicitation.notice_id
                safe_sol_number = sol_number.replace("/", "_").replace("\\", "_")
                agency_code = self._sanitize_path_component(solicitation.agency_name or "unknown")
                bureau_code = self._sanitize_path_component(solicitation.bureau_name or "general")
                object_key = f"{organization_id}/sam/{agency_code}/{bureau_code}/solicitations/{safe_sol_number}/attachments/{safe_filename}"
                # Store for metadata later
                path_agency = solicitation.agency_name
                path_bureau = solicitation.bureau_name
                path_sol_number = sol_number
            else:
                # Standalone notice attachment - use notice info for path
                # Format: {org_id}/sam/{agency_code}/{bureau_code}/notices/{notice_id}/attachments/{filename}
                notice = await sam_service.get_notice(session, attachment.notice_id)
                if not notice:
                    raise ValueError(f"Notice not found for attachment {attachment_id}")
                safe_notice_id = notice.sam_notice_id.replace("/", "_").replace("\\", "_")
                agency_code = self._sanitize_path_component(notice.agency_name or "unknown")
                bureau_code = self._sanitize_path_component(notice.bureau_name or "general")
                object_key = f"{organization_id}/sam/{agency_code}/{bureau_code}/notices/{safe_notice_id}/attachments/{safe_filename}"
                # Store for metadata later
                path_agency = notice.agency_name
                path_bureau = notice.bureau_name
                path_sol_number = None  # Standalone notices don't have solicitation numbers

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
                from app.core.shared.asset_service import asset_service
                asset = await asset_service.create_asset(
                    session=session,
                    organization_id=organization_id,
                    source_type="sam_gov",
                    source_metadata={
                        "attachment_id": str(attachment_id),
                        "solicitation_id": str(attachment.solicitation_id) if attachment.solicitation_id else None,
                        "notice_id": str(attachment.notice_id) if attachment.notice_id else None,
                        "resource_id": attachment.resource_id,
                        "download_url": attachment.download_url,
                        "downloaded_at": datetime.utcnow().isoformat(),
                        "agency": path_agency,
                        "bureau": path_bureau,
                        "solicitation_number": path_sol_number,
                        "is_standalone_notice": attachment.solicitation_id is None,
                    },
                    original_filename=real_filename,
                    content_type=content_type,
                    file_size=len(file_content),
                    raw_bucket=bucket,
                    raw_object_key=object_key,
                    group_id=group_id,  # Link child extraction to group for completion tracking
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
        group_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Download all pending attachments for a solicitation.

        Args:
            session: Database session
            solicitation_id: SamSolicitation UUID
            organization_id: Organization UUID
            minio_service: MinIO service instance (optional)
            group_id: Optional group UUID to link child extractions to

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
                    group_id=group_id,
                )
                if asset:
                    results["downloaded"] += 1
                else:
                    results["failed"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({
                    "attachment_id": str(attachment.id),
                    "error": _format_error(e),
                })

            # Rate limiting
            await asyncio.sleep(0.5)

        return results

    async def download_all_notice_attachments(
        self,
        session,  # AsyncSession
        notice_id: UUID,
        organization_id: UUID,
        minio_service=None,
        group_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Download all pending attachments for a standalone notice.

        This is the equivalent of download_all_attachments but for standalone
        notices (e.g., Special Notices) that don't have a parent solicitation.

        Args:
            session: Database session
            notice_id: SamNotice UUID
            organization_id: Organization UUID
            minio_service: MinIO service instance (optional)
            group_id: Optional group UUID to link child extractions to

        Returns:
            Download results summary
        """
        attachments = await sam_service.list_notice_attachments(
            session, notice_id, download_status="pending"
        )

        results = {
            "total": len(attachments),
            "downloaded": 0,
            "failed": 0,
            "errors": [],
        }

        for attachment in attachments:
            logger.info(f"Downloading notice attachment {attachment.id}: {attachment.filename}")
            try:
                asset = await self.download_attachment(
                    session=session,
                    attachment_id=attachment.id,
                    organization_id=organization_id,
                    minio_service=minio_service,
                    check_rate_limit=True,
                    group_id=group_id,
                )
                if asset:
                    results["downloaded"] += 1
                else:
                    results["failed"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({
                    "attachment_id": str(attachment.id),
                    "error": _format_error(e),
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
                    "error": _format_error(e),
                }
        except httpx.TimeoutException as e:
            return {
                "success": False,
                "status": "unhealthy",
                "message": "Connection timeout",
                "error": _format_error(e),
            }
        except Exception as e:
            return {
                "success": False,
                "status": "unhealthy",
                "message": "Connection failed",
                "error": _format_error(e),
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
            # Determine department search strategy
            departments = search_config.get("departments", [])
            api_calls = 0

            if len(departments) > 1:
                # Multi-department preview: sample from each department
                all_opportunities = []
                seen_notice_ids: set = set()
                total_estimate = 0
                samples_per_dept = max(1, limit // len(departments))

                for dept in departments:
                    # Create config with department override
                    params = self._build_search_params(
                        search_config,
                        limit=samples_per_dept,
                        offset=0,
                        department_override=dept,
                    )

                    response = await self._make_request(
                        "/search", params, session=session, organization_id=organization_id
                    )
                    api_calls += 1

                    dept_total = response.get("totalRecords", 0)
                    total_estimate += dept_total

                    for opp_data in response.get("opportunitiesData", []):
                        parsed = self._parse_opportunity(opp_data)
                        notice_id = parsed.get("notice_id")
                        if notice_id and notice_id not in seen_notice_ids:
                            seen_notice_ids.add(notice_id)
                            all_opportunities.append(parsed)

                    # Rate limiting between departments
                    await asyncio.sleep(self.rate_limit_delay)

                opportunities = all_opportunities[:limit]
                # Note: total_estimate may include duplicates
                total = total_estimate
                is_multi_dept = True

            else:
                # Single/no department: use existing path
                opportunities, total = await self.search_opportunities(
                    search_config, limit=limit, offset=0,
                    session=session, organization_id=organization_id,
                )
                api_calls = 1
                is_multi_dept = False

            # Record the API calls (if enabled)
            if check_rate_limit:
                for _ in range(api_calls):
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

            # Build message based on mode
            if is_multi_dept:
                message = f"Found approximately {total} opportunities across {len(departments)} departments (may include duplicates). Showing {len(preview_results)} unique samples."
            else:
                message = f"Found {total} matching opportunities. Showing {len(preview_results)} samples."

            return {
                "success": True,
                "total_matching": total,
                "sample_count": len(preview_results),
                "sample_results": preview_results,
                "search_config": search_config,
                "message": message,
                "is_multi_department": is_multi_dept,
                "departments_searched": len(departments) if is_multi_dept else None,
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
            error_msg = _format_error(e)
            logger.error(f"Runtime error during preview: {error_msg}")
            return {
                "success": False,
                "error": "timeout",
                "message": error_msg,
            }
        except Exception as e:
            error_msg = _format_error(e)
            logger.error(f"Error during search preview: {error_msg}")
            return {
                "success": False,
                "error": "unknown",
                "message": error_msg,
            }

    async def _index_to_search(
        self,
        session,  # AsyncSession
        organization_id: UUID,
        notice,  # SamNotice
        opportunity: Dict[str, Any],
        solicitation=None,  # Optional[SamSolicitation]
    ):
        """
        Index notice (and optionally solicitation) to search for unified search.

        This enables SAM.gov data to appear in the platform's unified search
        results alongside assets and other content. The solicitation is only
        indexed when one exists (standalone notices have no solicitation).

        Args:
            session: Database session
            organization_id: Organization UUID
            notice: SamNotice instance
            opportunity: Raw opportunity data from API
            solicitation: Optional SamSolicitation instance
        """
        from app.config import settings
        from app.core.search.pg_index_service import pg_index_service
        from app.core.shared.config_loader import config_loader

        # Check if search is enabled
        search_config = config_loader.get_search_config()
        if search_config:
            enabled = search_config.enabled
        else:
            enabled = getattr(settings, "search_enabled", True)

        if not enabled:
            return

        try:
            # Index the solicitation (only if one exists)
            if solicitation:
                await pg_index_service.index_sam_solicitation(
                    session=session,
                    organization_id=organization_id,
                    solicitation_id=solicitation.id,
                    solicitation_number=solicitation.solicitation_number,
                    title=solicitation.title,
                    description=solicitation.description or "",
                    agency=solicitation.agency_name,
                    office=solicitation.office_name,
                    naics_code=solicitation.naics_code,
                    set_aside=solicitation.set_aside_code,
                    posted_date=solicitation.posted_date,
                    response_deadline=solicitation.response_deadline,
                    url=solicitation.ui_link,
                )

            # Always index the notice
            solicitation_id = solicitation.id if solicitation else None
            await pg_index_service.index_sam_notice(
                session=session,
                organization_id=organization_id,
                notice_id=notice.id,
                sam_notice_id=notice.sam_notice_id,
                solicitation_id=solicitation_id,
                title=notice.title or "",
                description=notice.description or "",
                notice_type=notice.notice_type,
                agency=notice.agency_name,
                posted_date=notice.posted_date,
                response_deadline=notice.response_deadline,
                url=notice.ui_link,
            )

            if solicitation:
                logger.debug(
                    f"Indexed SAM solicitation {solicitation.id} and notice {notice.id} to search"
                )
            else:
                logger.debug(f"Indexed SAM notice {notice.id} to search")

        except Exception as e:
            # Don't fail the pull if indexing fails
            logger.warning(f"Failed to index SAM data to search: {e}")

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
                logger.info("No results for solnum search, falling back to description refresh")
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

                # Fetch full description - capture URL before fetching content
                description = opp.get("description")
                description_url = None
                if description and description.startswith("http"):
                    description_url = description  # Store the original URL
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
                    latest_opportunity["_description_url"] = description_url

                # Check if notice already exists
                if opp_notice_id in existing_notice_ids:
                    # Update existing notice with all available metadata
                    existing_notice = next(
                        (n for n in existing_notices if n.sam_notice_id == opp_notice_id), None
                    )
                    if existing_notice:
                        # Check what needs updating
                        needs_description_update = (
                            existing_notice.description and
                            (existing_notice.description.startswith("http") or
                             existing_notice.description != description)
                        )
                        needs_url_update = (
                            description_url and
                            not getattr(existing_notice, 'description_url', None)
                        )
                        # Check if any metadata is missing
                        needs_metadata_update = (
                            not existing_notice.agency_name or
                            not existing_notice.raw_data or
                            not existing_notice.full_parent_path
                        )

                        # Always update if description, url, or metadata needs updating
                        if (needs_description_update and description) or needs_url_update or needs_metadata_update:
                            await sam_service.update_notice(
                                session,
                                notice_id=existing_notice.id,
                                title=opp.get("title"),
                                description=description if needs_description_update else None,
                                description_url=description_url,
                                response_deadline=opp.get("response_deadline"),
                                raw_data=opp.get("raw_data"),
                                full_parent_path=opp.get("full_parent_path"),
                                agency_name=opp.get("agency_name"),
                                bureau_name=opp.get("bureau_name"),
                                office_name=opp.get("office_name"),
                                naics_code=opp.get("naics_code"),
                                psc_code=opp.get("psc_code"),
                                set_aside_code=opp.get("set_aside_code"),
                                ui_link=opp.get("ui_link"),
                            )
                            results["notices_updated"] += 1
                            logger.debug(f"Updated notice {existing_notice.id} with fresh data from SAM.gov")
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
                        description_url=description_url,
                        posted_date=opp.get("posted_date"),
                        response_deadline=opp.get("response_deadline"),
                        raw_data=opp.get("raw_data"),
                        full_parent_path=opp.get("full_parent_path"),
                        agency_name=opp.get("agency_name"),
                        bureau_name=opp.get("bureau_name"),
                        office_name=opp.get("office_name"),
                        naics_code=opp.get("naics_code"),
                        psc_code=opp.get("psc_code"),
                        set_aside_code=opp.get("set_aside_code"),
                        ui_link=opp.get("ui_link"),
                    )
                    results["notices_created"] += 1
                    logger.info(f"Created new notice {opp_notice_id} (version {version_number})")

            # Update solicitation with latest opportunity's data (description, agency info, metadata)
            if latest_opportunity:
                latest_description = latest_opportunity.get("_fetched_description")
                # Always update agency/metadata info, even if description unchanged
                await sam_service.update_solicitation(
                    session,
                    solicitation_id=solicitation.id,
                    title=latest_opportunity.get("title") or solicitation.title,
                    description=latest_description if latest_description else None,
                    response_deadline=latest_opportunity.get("response_deadline"),
                    agency_name=latest_opportunity.get("agency_name"),
                    bureau_name=latest_opportunity.get("bureau_name"),
                    office_name=latest_opportunity.get("office_name"),
                    full_parent_path=latest_opportunity.get("full_parent_path"),
                    naics_code=latest_opportunity.get("naics_code"),
                    psc_code=latest_opportunity.get("psc_code"),
                    set_aside_code=latest_opportunity.get("set_aside_code"),
                    ui_link=latest_opportunity.get("ui_link"),
                    contact_info=latest_opportunity.get("contact_info"),
                    place_of_performance=latest_opportunity.get("place_of_performance"),
                    raw_data=latest_opportunity.get("raw_data"),
                )
                if latest_description and latest_description != solicitation.description:
                    results["description_updated"] = True
                logger.info(
                    f"Updated solicitation {solicitation_id} with latest data from SAM.gov"
                )

            await session.commit()
            logger.info(f"Refresh completed for solicitation {solicitation_id}: {results}")

        except Exception as e:
            error_msg = _format_error(e)
            results["error"] = error_msg
            logger.error(f"Error refreshing solicitation {solicitation_id}: {error_msg}")

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
            error_msg = _format_error(e)
            results["error"] = error_msg
            logger.error(f"Error refreshing description: {error_msg}")

        return results


# Singleton instance
sam_pull_service = SamPullService()
