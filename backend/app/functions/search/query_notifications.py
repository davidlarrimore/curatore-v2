# backend/app/functions/search/query_notifications.py
"""
Query Notifications function - Query SAM.gov notices.

Query and filter SAM.gov notices (amendments, modifications, special notices) from the database.
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

logger = logging.getLogger("curatore.functions.search.query_notifications")


class QueryNotificationsFunction(BaseFunction):
    """
    Query SAM.gov notices from the database.

    Notices track solicitation amendments/modifications and standalone notices
    like special notices. Each solicitation can have multiple notices representing
    its version history.

    Example:
        result = await fn.query_notifications(ctx,
            notice_types=["s", "r"],  # Special notices and sources sought
            posted_within_days=7,
        )
    """

    meta = FunctionMeta(
        name="query_notifications",
        category=FunctionCategory.SEARCH,
        description="Query SAM.gov notices (amendments, special notices) with filters",
        parameters=[
            ParameterDoc(
                name="notice_types",
                type="list[str]",
                description="Filter by procurement/notice types",
                required=False,
                default=None,
                example=["s", "r"],
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
                name="solicitation_id",
                type="str",
                description="Filter by parent solicitation ID (for amendments)",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="standalone_only",
                type="bool",
                description="Only include standalone notices (no parent solicitation)",
                required=False,
                default=False,
            ),
            ParameterDoc(
                name="naics_codes",
                type="list[str]",
                description="Filter by NAICS codes (for standalone notices)",
                required=False,
                default=None,
                example=["541512", "541519"],
            ),
            ParameterDoc(
                name="posted_within_days",
                type="int",
                description="Only include notices posted within N days",
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
                name="agency_name",
                type="str",
                description="Filter by agency name (partial match)",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="has_changes_summary",
                type="bool",
                description="Filter by whether notice has a changes summary",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="order_by",
                type="str",
                description="Field to order by",
                required=False,
                default="-posted_date",
                enum_values=["-posted_date", "posted_date", "-response_deadline", "response_deadline", "-created_at", "created_at"],
            ),
            ParameterDoc(
                name="limit",
                type="int",
                description="Maximum number of results",
                required=False,
                default=50,
            ),
        ],
        returns="list[dict]: Matching notices",
        tags=["search", "sam", "notices", "notifications"],
        requires_llm=False,
        examples=[
            {
                "description": "Recent special notices",
                "params": {
                    "notice_types": ["s"],
                    "posted_within_days": 7,
                },
            },
            {
                "description": "Sources sought notices for IT",
                "params": {
                    "notice_types": ["r"],
                    "naics_codes": ["541512"],
                    "posted_within_days": 30,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Query notices."""
        from ...database.models import SamNotice, SamSolicitation

        notice_types = params.get("notice_types")
        solicitation_id = params.get("solicitation_id")
        standalone_only = params.get("standalone_only", False)
        naics_codes = params.get("naics_codes")
        posted_within_days = params.get("posted_within_days")
        response_deadline_after = params.get("response_deadline_after")
        keyword = params.get("keyword")
        agency_name = params.get("agency_name")
        has_changes_summary = params.get("has_changes_summary")
        order_by = params.get("order_by", "-posted_date")

        # Coerce types - Jinja2 templates render as strings
        limit_val = params.get("limit", 50)
        if isinstance(limit_val, str):
            limit_val = int(limit_val) if limit_val else 50
        limit = min(limit_val, 500)

        if isinstance(posted_within_days, str):
            posted_within_days = int(posted_within_days) if posted_within_days else None

        if isinstance(standalone_only, str):
            standalone_only = standalone_only.lower() in ("true", "1", "yes")

        try:
            # Build query - start with base conditions
            conditions = []

            # Filter by organization - either directly on notice or through solicitation
            if standalone_only:
                # Only standalone notices (no parent solicitation)
                conditions.append(SamNotice.solicitation_id.is_(None))
                conditions.append(SamNotice.organization_id == ctx.organization_id)
            elif solicitation_id:
                # Notices for a specific solicitation
                conditions.append(SamNotice.solicitation_id == UUID(solicitation_id))
            else:
                # All notices - need to handle both standalone and linked
                # For linked notices, check org via solicitation
                # For standalone, check org directly
                conditions.append(
                    or_(
                        SamNotice.organization_id == ctx.organization_id,
                        SamNotice.solicitation_id.in_(
                            select(SamSolicitation.id).where(
                                SamSolicitation.organization_id == ctx.organization_id
                            )
                        )
                    )
                )

            # Notice type filter
            if notice_types:
                conditions.append(SamNotice.notice_type.in_(notice_types))

            # NAICS codes filter (for standalone notices)
            if naics_codes:
                naics_conditions = []
                for code in naics_codes:
                    naics_conditions.append(SamNotice.naics_code == code)
                if naics_conditions:
                    conditions.append(or_(*naics_conditions))

            # Posted date filter
            if posted_within_days:
                cutoff_date = datetime.utcnow() - timedelta(days=posted_within_days)
                conditions.append(SamNotice.posted_date >= cutoff_date)

            # Response deadline filter
            if response_deadline_after:
                if response_deadline_after.lower() == "today":
                    deadline_date = datetime.utcnow().date()
                else:
                    deadline_date = datetime.strptime(response_deadline_after, "%Y-%m-%d").date()
                conditions.append(SamNotice.response_deadline >= deadline_date)

            # Keyword search
            if keyword:
                keyword_pattern = f"%{keyword}%"
                conditions.append(
                    or_(
                        SamNotice.title.ilike(keyword_pattern),
                        SamNotice.description.ilike(keyword_pattern),
                    )
                )

            # Agency filter
            if agency_name:
                conditions.append(SamNotice.agency_name.ilike(f"%{agency_name}%"))

            # Changes summary filter
            if has_changes_summary is not None:
                if has_changes_summary:
                    conditions.append(SamNotice.changes_summary.isnot(None))
                else:
                    conditions.append(SamNotice.changes_summary.is_(None))

            # Build query
            query = select(SamNotice).where(and_(*conditions))

            # Apply ordering
            if order_by:
                desc_order = order_by.startswith("-")
                field_name = order_by.lstrip("-")
                field_map = {
                    "posted_date": SamNotice.posted_date,
                    "response_deadline": SamNotice.response_deadline,
                    "created_at": SamNotice.created_at,
                }
                if field_name in field_map:
                    order_col = field_map[field_name]
                    query = query.order_by(desc(order_col) if desc_order else order_col)

            # Apply limit
            query = query.limit(limit)

            # Execute
            result = await ctx.session.execute(query)
            notices = result.scalars().all()

            # Format results
            results = []
            for notice in notices:
                notice_data = {
                    "id": str(notice.id),
                    "sam_notice_id": notice.sam_notice_id,
                    "notice_type": notice.notice_type,
                    "notice_type_label": self._get_notice_type_label(notice.notice_type),
                    "version_number": notice.version_number,
                    "title": notice.title,
                    "posted_date": notice.posted_date.isoformat() if notice.posted_date else None,
                    "response_deadline": notice.response_deadline.isoformat() if notice.response_deadline else None,
                    "description": notice.description[:500] + "..." if notice.description and len(notice.description) > 500 else notice.description,
                    "is_standalone": notice.solicitation_id is None,
                    "solicitation_id": str(notice.solicitation_id) if notice.solicitation_id else None,
                    "has_changes_summary": notice.changes_summary is not None,
                    "changes_summary": notice.changes_summary,
                    "ui_link": notice.ui_link,
                    "sam_url": notice.ui_link or (f"https://sam.gov/opp/{notice.sam_notice_id}/view" if notice.sam_notice_id else None),
                }

                # Add standalone-specific fields
                if notice.solicitation_id is None:
                    notice_data.update({
                        "naics_code": notice.naics_code,
                        "psc_code": notice.psc_code,
                        "set_aside_code": notice.set_aside_code,
                        "agency_name": notice.agency_name,
                        "bureau_name": notice.bureau_name,
                        "office_name": notice.office_name,
                    })

                results.append(notice_data)

            return FunctionResult.success_result(
                data=results,
                message=f"Found {len(results)} notices",
                metadata={
                    "filters": {
                        "notice_types": notice_types,
                        "solicitation_id": solicitation_id,
                        "standalone_only": standalone_only,
                        "naics_codes": naics_codes,
                        "posted_within_days": posted_within_days,
                        "response_deadline_after": response_deadline_after,
                        "keyword": keyword,
                        "agency_name": agency_name,
                        "has_changes_summary": has_changes_summary,
                    },
                    "total_found": len(results),
                },
                items_processed=len(results),
            )

        except Exception as e:
            logger.exception(f"Query failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Notification query failed",
            )

    def _get_notice_type_label(self, notice_type: str) -> str:
        """Get human-readable label for notice type code."""
        labels = {
            "o": "Solicitation",
            "p": "Presolicitation",
            "k": "Combined Synopsis/Solicitation",
            "r": "Sources Sought",
            "s": "Special Notice",
            "a": "Amendment",
            "i": "Intent to Bundle",
            "g": "Sale of Surplus Property",
        }
        return labels.get(notice_type, notice_type)
