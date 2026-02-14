# backend/app/functions/search/search_notices.py
"""
Search Notices function - Query SAM.gov notices.

Query and filter SAM.gov notices (amendments, standalone notices) using hybrid search.
Returns results as ContentItem instances for unified handling.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import and_, desc, or_, select

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...content import ContentItem
from ...context import FunctionContext

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
        description="Search SAM.gov notices with hybrid search and filters, returns ContentItem list",
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": (
                        "Short keyword query (2-4 key terms work best). "
                        "Use specific names, solicitation numbers, or acronyms. "
                        "Use filters (naics_codes, agency_name, notice_type) to narrow results instead of adding more query terms."
                    ),
                    "default": None,
                },
                "search_mode": {
                    "type": "string",
                    "description": "Search mode: 'keyword' for exact term matches, 'semantic' for conceptual similarity, 'hybrid' combines both for best results.",
                    "default": "hybrid",
                    "enum": ["keyword", "semantic", "hybrid"],
                },
                "semantic_weight": {
                    "type": "number",
                    "description": "Balance between keyword and semantic search in hybrid mode. 0.0 = keyword only, 1.0 = semantic only, 0.5 = equal weight.",
                    "default": 0.5,
                },
                "notice_id": {
                    "type": "string",
                    "description": "Search by notice identifier - matches SAM.gov notice ID (UUID) OR solicitation number (e.g., '70RSAT26RFI000006'). Note: SAM.gov website calls solicitation_number the 'Notice ID'.",
                    "default": None,
                },
                "notice_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
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
                    },
                    "description": "Filter by notice type codes. Common types: 'r' (Sources Sought/RFI), 's' (Special Notice), 'o' (Solicitation), 'k' (Combined Synopsis). Works with keyword search to narrow results.",
                    "default": None,
                    "examples": [["s", "r"]],
                },
                "standalone_only": {
                    "type": "boolean",
                    "description": "Only return standalone notices (not linked to a solicitation). Useful for finding special notices and announcements.",
                    "default": False,
                },
                "posted_within_days": {
                    "type": "integer",
                    "description": "Only include notices posted within N days (e.g., 7, 30, 90). Combines with keyword and type filters to find recent notices.",
                    "default": None,
                },
                "order_by": {
                    "type": "string",
                    "description": "Field to order by (only used when no keyword search)",
                    "default": "-posted_date",
                    "enum": ["-posted_date", "posted_date", "-version_number", "version_number"],
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 50,
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of results to skip for pagination",
                    "default": 0,
                },
                "include_solicitation": {
                    "type": "boolean",
                    "description": "Include parent solicitation data if linked",
                    "default": False,
                },
                "include_assets": {
                    "type": "boolean",
                    "description": "Include document assets (attachments) from SAM.gov in keyword search results. Only applies when keyword search is used.",
                    "default": False,
                },
            },
            "required": [],
        },
        output_schema={
            "type": "array",
            "description": "List of matching SAM.gov notices",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Notice UUID"},
                    "title": {"type": "string", "description": "Notice title"},
                    "sam_notice_id": {"type": "string", "description": "SAM.gov notice ID"},
                    "notice_type": {"type": "string", "description": "Notice type code", "examples": ["r"]},
                    "version_number": {"type": "integer", "description": "Amendment version number", "examples": [1]},
                    "agency_name": {"type": "string", "description": "Federal agency name"},
                    "bureau_name": {"type": "string", "description": "Bureau name", "nullable": True},
                    "posted_date": {"type": "string", "description": "Date posted (ISO format)"},
                    "response_deadline": {"type": "string", "description": "Response deadline (ISO format)", "nullable": True},
                    "naics_code": {"type": "string", "description": "NAICS industry code", "nullable": True},
                    "set_aside_code": {"type": "string", "description": "Set-aside type", "nullable": True},
                    "description": {"type": "string", "description": "Notice description/synopsis", "nullable": True},
                    "score": {"type": "number", "description": "Relevance score", "nullable": True},
                    "detail_url": {"type": "string", "description": "Link to Curatore detail page"},
                },
            },
        },
        tags=["search", "sam", "notices", "content", "hybrid"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="thin",
        required_data_sources=["sam_gov"],
        examples=[
            {
                "description": "Hybrid search for RFI notices posted recently",
                "params": {
                    "keyword": "request for information cybersecurity",
                    "search_mode": "hybrid",
                    "notice_types": ["r"],
                    "posted_within_days": 30,
                },
            },
            {
                "description": "Semantic search for sources sought notices",
                "params": {
                    "keyword": "cloud infrastructure services",
                    "search_mode": "semantic",
                    "notice_types": ["r", "s"],
                    "posted_within_days": 60,
                },
            },
            {
                "description": "Get a specific notice by identifier (UUID or solicitation number)",
                "params": {
                    "notice_id": "70RSAT26RFI000006",
                },
            },
            {
                "description": "Recent special notices and announcements",
                "params": {
                    "keyword": "industry day",
                    "notice_types": ["s"],
                    "posted_within_days": 30,
                },
            },
            {
                "description": "Search for presolicitations in the last two weeks",
                "params": {
                    "keyword": "software development",
                    "search_mode": "hybrid",
                    "notice_types": ["p"],
                    "posted_within_days": 14,
                },
            },
            {
                "description": "Search notices AND document attachments for AI/ML content",
                "params": {
                    "keyword": "artificial intelligence machine learning",
                    "search_mode": "hybrid",
                    "include_assets": True,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Query notices with optional hybrid search."""
        from sqlalchemy.orm import selectinload

        from app.core.database.models import SamNotice, SamSolicitation

        keyword = params.get("keyword")
        search_mode = params.get("search_mode", "hybrid")
        semantic_weight = params.get("semantic_weight", 0.5)
        notice_id = params.get("notice_id")
        notice_types = params.get("notice_types")
        standalone_only = params.get("standalone_only", False)
        posted_within_days = params.get("posted_within_days")
        order_by = params.get("order_by", "-posted_date")
        include_solicitation = params.get("include_solicitation", False)
        include_assets = params.get("include_assets", False)
        offset = params.get("offset", 0)

        # Coerce types
        limit_val = params.get("limit", 50)
        if isinstance(limit_val, str):
            limit_val = int(limit_val) if limit_val else 50
        limit = min(limit_val, 500)

        if isinstance(posted_within_days, str):
            posted_within_days = int(posted_within_days) if posted_within_days else None

        try:
            # If keyword is provided, use PgSearchService for hybrid search
            if keyword and keyword.strip():
                return await self._search_with_pg_service(
                    ctx=ctx,
                    keyword=keyword.strip(),
                    search_mode=search_mode,
                    semantic_weight=semantic_weight,
                    notice_types=notice_types,
                    posted_within_days=posted_within_days,
                    include_assets=include_assets,
                    limit=limit,
                    offset=offset,
                )

            # Otherwise, use direct database query with filters
            conditions = []

            # Organization filter - notices are linked via solicitation or directly
            conditions.append(
                or_(
                    ctx.org_filter(SamNotice.organization_id),
                    SamNotice.solicitation.has(
                        ctx.org_filter(SamSolicitation.organization_id)
                    ),
                )
            )

            # Unified notice identifier search
            if notice_id:
                conditions.append(
                    or_(
                        SamNotice.sam_notice_id == notice_id,
                        SamNotice.solicitation_number == notice_id,
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
                cutoff_date = (datetime.utcnow() - timedelta(days=posted_within_days)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                conditions.append(SamNotice.posted_date >= cutoff_date)

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

            # Apply pagination
            query = query.offset(offset).limit(limit)

            # Execute
            result = await ctx.session.execute(query)
            notices = result.scalars().all()

            # Format results as ContentItem instances
            results = self._format_notices_as_content_items(notices, include_solicitation)

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

    async def _search_with_pg_service(
        self,
        ctx: FunctionContext,
        keyword: str,
        search_mode: str,
        semantic_weight: float,
        notice_types: Optional[List[str]],
        posted_within_days: Optional[int],
        include_assets: bool,
        limit: int,
        offset: int,
    ) -> FunctionResult:
        """Use PgSearchService for hybrid search with filters."""
        search_results = await ctx.search_service.search_sam(
            session=ctx.session,
            organization_id=ctx.organization_id,
            query=keyword,
            search_mode=search_mode,
            semantic_weight=semantic_weight,
            source_types=["sam_notice"],  # Only notices
            notice_types=notice_types,
            posted_within_days=posted_within_days,
            include_sam_assets=include_assets,
            limit=limit,
            offset=offset,
        )

        # Convert SearchHit results to ContentItem format
        results = []
        for hit in search_results.hits:
            # Determine if this is an asset or a notice based on source_type
            is_asset = hit.source_type not in ("SAM Notice", "sam_notice")

            if is_asset:
                item = ContentItem(
                    id=hit.asset_id,
                    type="asset",
                    display_type="SAM Document",
                    title=hit.title or hit.filename,
                    text=None,
                    text_format="json",
                    fields={
                        "source_type": hit.source_type,
                        "filename": hit.filename,
                        "content_type": hit.content_type,
                        "url": hit.url,
                        "created_at": hit.created_at,
                    },
                    metadata={
                        "score": hit.score,
                        "keyword_score": hit.keyword_score,
                        "semantic_score": hit.semantic_score,
                        "highlights": hit.highlights,
                        "search_mode": search_mode,
                    },
                )
            else:
                item = ContentItem(
                    id=hit.asset_id,
                    type="notice",
                    display_type="Notice",
                    title=hit.title,
                    text=None,
                    text_format="json",
                    fields={
                        "source_type": hit.source_type,
                        "url": hit.url,
                        "created_at": hit.created_at,
                    },
                    metadata={
                        "score": hit.score,
                        "keyword_score": hit.keyword_score,
                        "semantic_score": hit.semantic_score,
                        "highlights": hit.highlights,
                        "search_mode": search_mode,
                    },
                )
            results.append(item)

        # Count notices vs assets
        notice_count = sum(1 for r in results if r.type == "notice")
        asset_count = sum(1 for r in results if r.type == "asset")

        message = f"Found {len(results)} results matching '{keyword}'"
        if include_assets and asset_count > 0:
            message = f"Found {notice_count} notices and {asset_count} documents matching '{keyword}'"

        return FunctionResult.success_result(
            data=results,
            message=message,
            metadata={
                "total": search_results.total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(results) < search_results.total,
                "keyword": keyword,
                "search_mode": search_mode,
                "semantic_weight": semantic_weight,
                "notice_types": notice_types,
                "include_assets": include_assets,
                "notice_count": notice_count,
                "asset_count": asset_count,
                "result_type": "ContentItem",
            },
            items_processed=len(results),
        )

    def _format_notices_as_content_items(self, notices, include_solicitation: bool) -> List[ContentItem]:
        """Format notice records as ContentItem instances."""
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
                text=None,
                text_format="json",
                fields=fields,
                metadata=metadata,
                parent_id=str(notice.solicitation_id) if notice.solicitation_id else None,
                parent_type="solicitation" if notice.solicitation_id else None,
            )
            results.append(item)
        return results
