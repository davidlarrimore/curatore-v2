# backend/app/functions/search/search_notices.py
"""
Search Notices function - Query SAM.gov notices.

Query and filter SAM.gov notices (amendments, standalone notices) from the database.
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

logger = logging.getLogger("curatore.functions.search.search_notices")


class SearchNoticesFunction(BaseFunction):
    """
    Search SAM.gov notices from the database.

    Queries notices (amendments, special notices) with various filters.
    Returns ContentItem instances for unified handling.

    Example:
        result = await fn.search_notices(ctx,
            notice_types=["r"],  # Special notices
            posted_within_days=30,
        )
    """

    meta = FunctionMeta(
        name="search_notices",
        category=FunctionCategory.SEARCH,
        description="Search SAM.gov notices with filters, returns ContentItem list",
        parameters=[
            ParameterDoc(
                name="notice_id",
                type="str",
                description="Search by notice identifier - matches SAM.gov notice ID (UUID) OR solicitation number (e.g., '70RSAT26RFI000006'). Note: SAM.gov website calls solicitation_number the 'Notice ID'.",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="notice_types",
                type="list[str]",
                description="Filter by notice types (ptype codes from SAM.gov API)",
                required=False,
                default=None,
                example=["s", "r"],
                enum_values=[
                    "o|Solicitation",
                    "p|Presolicitation",
                    "k|Combined Synopsis/Solicitation",
                    "r|Sources Sought",
                    "s|Special Notice",
                    "g|Sale of Surplus Property",
                    "a|Award Notice",
                    "u|Justification (J&A)",
                    "i|Intent to Bundle",
                ],
            ),
            ParameterDoc(
                name="standalone_only",
                type="bool",
                description="Only return standalone notices (no solicitation)",
                required=False,
                default=False,
            ),
            ParameterDoc(
                name="posted_within_days",
                type="int",
                description="Only include notices posted within N days",
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
                name="order_by",
                type="str",
                description="Field to order by",
                required=False,
                default="-posted_date",
                enum_values=["-posted_date", "posted_date", "-version_number", "version_number"],
            ),
            ParameterDoc(
                name="limit",
                type="int",
                description="Maximum number of results",
                required=False,
                default=50,
            ),
            ParameterDoc(
                name="include_solicitation",
                type="bool",
                description="Include parent solicitation data if linked",
                required=False,
                default=False,
            ),
        ],
        returns="list[ContentItem]: Matching notices as ContentItem instances",
        tags=["search", "sam", "notices", "content"],
        requires_llm=False,
        examples=[
            {
                "description": "Get a specific notice by identifier (UUID or solicitation number)",
                "params": {
                    "notice_id": "70RSAT26RFI000006",
                },
            },
            {
                "description": "Recent special notices",
                "params": {
                    "notice_types": ["s"],
                    "posted_within_days": 30,
                },
            },
            {
                "description": "Search by SAM.gov internal ID",
                "params": {
                    "notice_id": "74cef92c649b410db3ae44f158bf25a7",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Query notices."""
        from sqlalchemy.orm import selectinload
        from ...database.models import SamNotice, SamSolicitation

        notice_id = params.get("notice_id")
        notice_types = params.get("notice_types")
        standalone_only = params.get("standalone_only", False)
        posted_within_days = params.get("posted_within_days")
        keyword = params.get("keyword")
        order_by = params.get("order_by", "-posted_date")
        include_solicitation = params.get("include_solicitation", False)

        # Coerce types
        limit_val = params.get("limit", 50)
        if isinstance(limit_val, str):
            limit_val = int(limit_val) if limit_val else 50
        limit = min(limit_val, 500)

        if isinstance(posted_within_days, str):
            posted_within_days = int(posted_within_days) if posted_within_days else None

        try:
            # Build query
            conditions = []

            # Organization filter - notices are linked via solicitation or directly
            conditions.append(
                or_(
                    SamNotice.organization_id == ctx.organization_id,
                    SamNotice.solicitation.has(
                        SamSolicitation.organization_id == ctx.organization_id
                    ),
                )
            )

            # Unified notice identifier search
            # Searches: SAM.gov internal ID (UUID), solicitation_number on notice, or parent solicitation number
            # Note: SAM.gov website calls "solicitation_number" the "Notice ID" - confusing!
            if notice_id:
                conditions.append(
                    or_(
                        # Match SAM.gov internal notice ID (UUID)
                        SamNotice.sam_notice_id == notice_id,
                        # Match solicitation_number on standalone notices
                        SamNotice.solicitation_number == notice_id,
                        # Match solicitation_number via parent solicitation (for linked notices)
                        SamNotice.solicitation.has(
                            SamSolicitation.solicitation_number == notice_id
                        ),
                    )
                )

            # Standalone filter
            if standalone_only:
                conditions.append(SamNotice.solicitation_id.is_(None))

            # Notice type filter
            if notice_types:
                conditions.append(SamNotice.notice_type.in_(notice_types))

            # Posted date filter
            if posted_within_days:
                cutoff_date = datetime.utcnow() - timedelta(days=posted_within_days)
                conditions.append(SamNotice.posted_date >= cutoff_date)

            # Keyword search
            if keyword:
                keyword_pattern = f"%{keyword}%"
                conditions.append(
                    or_(
                        SamNotice.title.ilike(keyword_pattern),
                        SamNotice.description.ilike(keyword_pattern),
                    )
                )

            # Build query
            query = select(SamNotice).where(and_(*conditions))

            # Eagerly load solicitation if requested
            if include_solicitation:
                query = query.options(selectinload(SamNotice.solicitation))

            # Apply ordering
            if order_by:
                desc_order = order_by.startswith("-")
                field_name = order_by.lstrip("-")
                field_map = {
                    "posted_date": SamNotice.posted_date,
                    "version_number": SamNotice.version_number,
                }
                if field_name in field_map:
                    order_col = field_map[field_name]
                    query = query.order_by(desc(order_col) if desc_order else order_col)

            # Apply limit
            query = query.limit(limit)

            # Execute
            result = await ctx.session.execute(query)
            notices = result.scalars().all()

            # Format results as ContentItem instances
            results = []
            for notice in notices:
                # Determine display type based on context
                if notice.solicitation_id:
                    display_type = "Amendment" if notice.version_number > 1 else "Notice"
                else:
                    display_type = "Special Notice"

                # Build fields dict
                fields = {
                    "sam_notice_id": notice.sam_notice_id,
                    "notice_type": notice.notice_type,
                    "version_number": notice.version_number,
                    "posted_date": notice.posted_date.isoformat() if notice.posted_date else None,
                    "response_deadline": notice.response_deadline.isoformat() if notice.response_deadline else None,
                    "agency_name": notice.agency_name,
                    "bureau_name": notice.bureau_name,
                    "office_name": notice.office_name,
                    "naics_code": notice.naics_code,
                    "psc_code": notice.psc_code,
                    "set_aside_code": notice.set_aside_code,
                }

                # Build metadata dict
                metadata = {
                    "description": notice.description,
                    "description_preview": notice.description[:500] + "..." if notice.description and len(notice.description) > 500 else notice.description,
                    "has_changes_summary": notice.changes_summary is not None,
                    "changes_summary": notice.changes_summary,
                    "ui_link": notice.ui_link,
                }

                # Include solicitation data if requested and available
                if include_solicitation and notice.solicitation_id and notice.solicitation:
                    sol = notice.solicitation
                    fields["solicitation"] = {
                        "id": str(sol.id),
                        "solicitation_number": sol.solicitation_number,
                        "title": sol.title,
                        "description": sol.description,
                        "description_preview": sol.description[:500] + "..." if sol.description and len(sol.description) > 500 else sol.description,
                        "status": sol.status,
                        "notice_count": sol.notice_count,
                        "notice_type": sol.notice_type,
                        "response_deadline": sol.response_deadline.isoformat() if sol.response_deadline else None,
                        "agency_name": sol.agency_name,
                        "naics_code": sol.naics_code,
                        "set_aside_code": sol.set_aside_code,
                        "summary_status": sol.summary_status,
                        "ui_link": sol.ui_link,
                    }

                item = ContentItem(
                    id=str(notice.id),
                    type="notice",
                    display_type=display_type,
                    title=notice.title,
                    text=None,  # Text not loaded by default
                    text_format="json",
                    fields=fields,
                    metadata=metadata,
                    parent_id=str(notice.solicitation_id) if notice.solicitation_id else None,
                    parent_type="solicitation" if notice.solicitation_id else None,
                )
                results.append(item)

            return FunctionResult.success_result(
                data=results,
                message=f"Found {len(results)} notices",
                metadata={
                    "filters": {
                        "notice_id": notice_id,
                        "notice_types": notice_types,
                        "standalone_only": standalone_only,
                        "posted_within_days": posted_within_days,
                        "keyword": keyword,
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
                message="Notice query failed",
            )
