# backend/app/functions/search/search_solicitations.py
"""
Search Solicitations function - Search SAM.gov solicitations.

Search and filter SAM.gov solicitations from the database.
Returns results as ContentItem instances for unified handling.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime, timedelta
import logging

from sqlalchemy import select, and_, or_, func, desc

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
)
from ..context import FunctionContext
from ..content import ContentItem

logger = logging.getLogger("curatore.functions.search.search_solicitations")


class SearchSolicitationsFunction(BaseFunction):
    """
    Search SAM.gov solicitations from the database.

    Filters and retrieves federal contract opportunities.
    Returns ContentItem instances for unified handling.

    Example:
        result = await fn.search_solicitations(ctx,
            naics_codes=["541512", "541519"],
            posted_within_days=7,
            response_deadline_after="today",
        )
    """

    meta = FunctionMeta(
        name="search_solicitations",
        category=FunctionCategory.SEARCH,
        description="Search SAM.gov solicitations with filters, returns ContentItem list",
        parameters=[
            ParameterDoc(
                name="naics_codes",
                type="list[str]",
                description="Filter by NAICS codes",
                required=False,
                default=None,
                example=["541512", "541519"],
            ),
            ParameterDoc(
                name="set_asides",
                type="list[str]",
                description="Filter by set-aside types",
                required=False,
                default=None,
                example=["SBA", "8(a)", "HUBZone"],
            ),
            ParameterDoc(
                name="types",
                type="list[str]",
                description="Filter by procurement/solicitation types",
                required=False,
                default=None,
                example=["o", "p", "k"],
                enum_values=[
                    "u|Justification (J&A)",
                    "p|Presolicitation",
                    "a|Award Notice",
                    "r|Sources Sought",
                    "s|Special Notice",
                    "o|Solicitation",
                    "g|Sale of Surplus Property",
                    "k|Combined Synopsis/Solicitation",
                    "i|Intent to Bundle Requirements (DoD-Funded)",
                ],
            ),
            ParameterDoc(
                name="posted_within_days",
                type="int",
                description="Only include solicitations posted within N days",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="response_deadline_after",
                type="str",
                description="Response deadline must be after this date (YYYY-MM-DD or 'today')",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="keyword",
                type="str",
                description="Search in title and description",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="search_id",
                type="str",
                description="Filter by SAM search ID (to get solicitations from a specific search)",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="has_summary",
                type="bool",
                description="Filter by whether solicitation has an AI summary",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="order_by",
                type="str",
                description="Field to order by",
                required=False,
                default="-posted_date",
                enum_values=["-posted_date", "posted_date", "-response_deadline", "response_deadline"],
            ),
            ParameterDoc(
                name="limit",
                type="int",
                description="Maximum number of results",
                required=False,
                default=50,
            ),
        ],
        returns="list[ContentItem]: Matching solicitations as ContentItem instances",
        tags=["search", "sam", "solicitations", "content"],
        requires_llm=False,
        examples=[
            {
                "description": "Recent IT solicitations",
                "params": {
                    "naics_codes": ["541512"],
                    "posted_within_days": 7,
                    "response_deadline_after": "today",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Query solicitations."""
        from ...database.models import SamSolicitation

        naics_codes = params.get("naics_codes")
        set_asides = params.get("set_asides")
        types = params.get("types")
        posted_within_days = params.get("posted_within_days")
        response_deadline_after = params.get("response_deadline_after")
        keyword = params.get("keyword")
        search_id = params.get("search_id")
        has_summary = params.get("has_summary")
        order_by = params.get("order_by", "-posted_date")

        # Coerce types - Jinja2 templates render as strings
        limit_val = params.get("limit", 50)
        if isinstance(limit_val, str):
            limit_val = int(limit_val) if limit_val else 50
        limit = min(limit_val, 500)

        if isinstance(posted_within_days, str):
            posted_within_days = int(posted_within_days) if posted_within_days else None

        try:
            # Build query
            conditions = [SamSolicitation.organization_id == ctx.organization_id]

            # NAICS codes filter (check if any code matches)
            if naics_codes:
                # naics_code is a single String field, filter by any matching code
                naics_conditions = []
                for code in naics_codes:
                    naics_conditions.append(
                        SamSolicitation.naics_code == code
                    )
                if naics_conditions:
                    conditions.append(or_(*naics_conditions))

            # Set-aside filter
            if set_asides:
                set_aside_conditions = []
                for sa in set_asides:
                    set_aside_conditions.append(
                        SamSolicitation.set_aside_code.ilike(f"%{sa}%")
                    )
                if set_aside_conditions:
                    conditions.append(or_(*set_aside_conditions))

            # Type filter (notice_type)
            if types:
                conditions.append(SamSolicitation.notice_type.in_(types))

            # Posted date filter
            # Use start of day (midnight) for cutoff to handle SAM.gov date-only timestamps
            if posted_within_days:
                cutoff_date = (datetime.utcnow() - timedelta(days=posted_within_days)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                conditions.append(SamSolicitation.posted_date >= cutoff_date)

            # Response deadline filter
            if response_deadline_after:
                if response_deadline_after.lower() == "today":
                    deadline_date = datetime.utcnow().date()
                else:
                    deadline_date = datetime.strptime(response_deadline_after, "%Y-%m-%d").date()
                conditions.append(SamSolicitation.response_deadline >= deadline_date)

            # Keyword search
            if keyword:
                keyword_pattern = f"%{keyword}%"
                conditions.append(
                    or_(
                        SamSolicitation.title.ilike(keyword_pattern),
                        SamSolicitation.description.ilike(keyword_pattern),
                    )
                )

            # Search ID filter
            if search_id:
                conditions.append(
                    SamSolicitation.sam_search_id == UUID(search_id)
                )

            # Summary filter
            if has_summary is not None:
                if has_summary:
                    conditions.append(SamSolicitation.summary.isnot(None))
                else:
                    conditions.append(SamSolicitation.summary.is_(None))

            # Build query
            query = select(SamSolicitation).where(and_(*conditions))

            # Apply ordering
            if order_by:
                desc_order = order_by.startswith("-")
                field_name = order_by.lstrip("-")
                field_map = {
                    "posted_date": SamSolicitation.posted_date,
                    "response_deadline": SamSolicitation.response_deadline,
                }
                if field_name in field_map:
                    order_col = field_map[field_name]
                    query = query.order_by(desc(order_col) if desc_order else order_col)

            # Apply limit
            query = query.limit(limit)

            # Execute
            result = await ctx.session.execute(query)
            solicitations = result.scalars().all()

            # Format results as ContentItem instances
            results = []
            for sol in solicitations:
                item = ContentItem(
                    id=str(sol.id),
                    type="solicitation",
                    display_type="Opportunity",
                    title=sol.title,
                    text=None,  # Text not loaded by default for search results
                    text_format="json",
                    fields={
                        "notice_id": sol.notice_id,
                        "solicitation_number": sol.solicitation_number,
                        "notice_type": sol.notice_type,
                        "posted_date": sol.posted_date.isoformat() if sol.posted_date else None,
                        "response_deadline": sol.response_deadline.isoformat() if sol.response_deadline else None,
                        "naics_code": sol.naics_code,
                        "psc_code": sol.psc_code,
                        "set_aside_code": sol.set_aside_code,
                        "agency_name": sol.agency_name,
                        "bureau_name": sol.bureau_name,
                        "office_name": sol.office_name,
                        "status": sol.status,
                        "notice_count": sol.notice_count,
                        "attachment_count": sol.attachment_count,
                        "summary_status": sol.summary_status,
                    },
                    metadata={
                        "description_preview": sol.description[:500] + "..." if sol.description and len(sol.description) > 500 else sol.description,
                        "has_summary": sol.summary_status == "ready",
                        "sam_url": f"https://sam.gov/opp/{sol.notice_id}/view" if sol.notice_id else None,
                        "ui_link": sol.ui_link,
                        "place_of_performance": sol.place_of_performance,
                    },
                )
                results.append(item)

            # Return both ContentItem list and dict representations
            return FunctionResult.success_result(
                data=results,  # List of ContentItem
                message=f"Found {len(results)} solicitations",
                metadata={
                    "filters": {
                        "naics_codes": naics_codes,
                        "set_asides": set_asides,
                        "types": types,
                        "posted_within_days": posted_within_days,
                        "response_deadline_after": response_deadline_after,
                        "keyword": keyword,
                        "has_summary": has_summary,
                    },
                    "total_found": len(results),
                    "result_type": "ContentItem",
                },
                items_processed=len(results),
            )

        except Exception as e:
            logger.exception(f"Query failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Solicitation query failed",
            )
