# backend/app/functions/search/search_solicitations.py
"""
Search Solicitations function - Search SAM.gov solicitations.

Search and filter SAM.gov solicitations using hybrid search (keyword + semantic).
Returns results as ContentItem instances for unified handling.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, desc, or_, select

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...content import ContentItem
from ...context import FunctionContext

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
        description=(
            "Search SAM.gov solicitations with hybrid search and filters. "
            "Returns solicitation summaries with relevance scores. "
            "To get full details, use get(item_type='solicitation', item_id='...'). "
            "To read attached documents (SOWs, RFPs), use get_content() with asset IDs from the solicitation's children."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": (
                        "Short keyword query (2-4 key terms work best). "
                        "Use specific names, solicitation numbers, or acronyms. "
                        "Good: 'LESA deployment', 'cybersecurity SDVOSB'. "
                        "Bad: 'Law Enforcement Systems and Analysis Professional Support Services Deployment'. "
                        "Use filters (naics_codes, agency_name, set_aside_code) to narrow results instead of adding more query terms."
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
                "naics_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by NAICS industry codes (e.g., '541512' for IT Services, '541519' for Other Computer Services). Works with keyword search to narrow results.",
                    "default": None,
                    "examples": [["541512", "541519"]],
                },
                "set_asides": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by small business set-aside types. Common values: 'SBA' (Small Business), '8(a)' (8a Program), 'HUBZone', 'SDVOSBC' (Service-Disabled Veteran). Works with keyword search.",
                    "default": None,
                    "examples": [["SBA", "8(a)", "HUBZone"]],
                },
                "types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
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
                    },
                    "description": "Filter by notice type codes. Common types: 'o' (Solicitation), 'k' (Combined Synopsis/Solicitation), 'p' (Presolicitation), 'r' (Sources Sought). Works with keyword search.",
                    "default": None,
                    "examples": [["o", "p", "k"]],
                },
                "posted_within_days": {
                    "type": "integer",
                    "description": "Only include solicitations posted within N days (e.g., 7, 30, 90). Combines with keyword and other filters to find recent matching opportunities.",
                    "default": None,
                },
                "response_deadline_after": {
                    "type": "string",
                    "description": "Filter to opportunities with response deadline after this date. Use 'today' for open opportunities or 'YYYY-MM-DD' format. Works with keyword search.",
                    "default": None,
                },
                "search_id": {
                    "type": "string",
                    "description": "Filter by SAM search ID (to get solicitations from a specific search)",
                    "default": None,
                },
                "search_name": {
                    "type": "string",
                    "description": "Filter by SAM saved search name (e.g., 'IT Services Opportunities'). Case-insensitive. Resolves to search_id automatically. search_id takes precedence if both provided.",
                    "default": None,
                    "examples": ["IT Services Opportunities"],
                },
                "has_summary": {
                    "type": "boolean",
                    "description": "Filter by whether solicitation has an AI summary",
                    "default": None,
                },
                "order_by": {
                    "type": "string",
                    "description": "Field to order by (only used when no keyword search)",
                    "default": "-posted_date",
                    "enum": ["-posted_date", "posted_date", "-response_deadline", "response_deadline"],
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
            "description": "List of matching SAM.gov solicitations",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Solicitation UUID"},
                    "title": {"type": "string", "description": "Solicitation title"},
                    "solicitation_number": {"type": "string", "description": "SAM.gov solicitation number", "examples": ["W912DS-26-R-0001"]},
                    "notice_id": {"type": "string", "description": "SAM.gov notice ID"},
                    "notice_type": {"type": "string", "description": "Notice type code", "examples": ["o"]},
                    "agency_name": {"type": "string", "description": "Federal agency name"},
                    "bureau_name": {"type": "string", "description": "Bureau name", "nullable": True},
                    "posted_date": {"type": "string", "description": "Date posted (ISO format)"},
                    "response_deadline": {"type": "string", "description": "Response deadline (ISO format)", "nullable": True},
                    "naics_code": {"type": "string", "description": "NAICS industry code", "examples": ["541512"], "nullable": True},
                    "set_aside_code": {"type": "string", "description": "Set-aside type", "nullable": True},
                    "status": {"type": "string", "description": "Solicitation status"},
                    "score": {"type": "number", "description": "Relevance score", "nullable": True},
                    "detail_url": {"type": "string", "description": "Link to Curatore detail page"},
                    "sam_url": {"type": "string", "description": "Link to SAM.gov", "nullable": True},
                },
            },
        },
        tags=["search", "sam", "solicitations", "content", "hybrid"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="thin",
        required_data_sources=["sam_gov"],
        examples=[
            {
                "description": "Hybrid search with NAICS and type filters",
                "params": {
                    "keyword": "cybersecurity network security",
                    "search_mode": "hybrid",
                    "naics_codes": ["541512", "541519"],
                    "types": ["o", "k"],
                    "posted_within_days": 30,
                },
            },
            {
                "description": "Semantic search for IT opportunities with deadline filter",
                "params": {
                    "keyword": "cloud infrastructure modernization",
                    "search_mode": "semantic",
                    "naics_codes": ["541512"],
                    "response_deadline_after": "today",
                },
            },
            {
                "description": "Small business set-aside opportunities",
                "params": {
                    "keyword": "software development services",
                    "search_mode": "hybrid",
                    "set_asides": ["SBA", "8(a)"],
                    "types": ["o", "k"],
                    "posted_within_days": 14,
                },
            },
            {
                "description": "Recent presolicitations and RFIs in IT sector",
                "params": {
                    "keyword": "artificial intelligence machine learning",
                    "naics_codes": ["541512"],
                    "types": ["p", "r"],
                    "posted_within_days": 30,
                },
            },
            {
                "description": "Open IT solicitations posted this week",
                "params": {
                    "keyword": "software development",
                    "naics_codes": ["541512"],
                    "posted_within_days": 7,
                    "response_deadline_after": "today",
                },
            },
            {
                "description": "Search solicitations AND document attachments for AI content",
                "params": {
                    "keyword": "artificial intelligence",
                    "search_mode": "hybrid",
                    "include_assets": True,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Query solicitations with optional hybrid search."""
        from app.core.database.models import SamSolicitation

        keyword = params.get("keyword")
        search_mode = params.get("search_mode", "hybrid")
        semantic_weight = params.get("semantic_weight", 0.5)
        naics_codes = params.get("naics_codes")
        set_asides = params.get("set_asides")
        types = params.get("types")
        posted_within_days = params.get("posted_within_days")
        response_deadline_after = params.get("response_deadline_after")
        search_id = params.get("search_id")
        search_name = params.get("search_name")
        has_summary = params.get("has_summary")
        order_by = params.get("order_by", "-posted_date")
        include_assets = params.get("include_assets", False)
        offset = params.get("offset", 0)

        # Coerce types - Jinja2 templates render as strings
        limit_val = params.get("limit", 50)
        if isinstance(limit_val, str):
            limit_val = int(limit_val) if limit_val else 50
        limit = min(limit_val, 500)

        if isinstance(posted_within_days, str):
            posted_within_days = int(posted_within_days) if posted_within_days else None

        try:
            # Resolve search_name to search_id (case-insensitive)
            if search_name and not search_id:
                from sqlalchemy import func as sqla_func

                from app.core.database.models import SamSearch

                result = await ctx.session.execute(
                    select(SamSearch.id)
                    .where(ctx.org_filter(SamSearch.organization_id))
                    .where(SamSearch.is_active == True)
                    .where(sqla_func.lower(SamSearch.name) == search_name.lower())
                )
                row = result.first()
                if not row:
                    # Try partial match as fallback
                    result = await ctx.session.execute(
                        select(SamSearch.id)
                        .where(ctx.org_filter(SamSearch.organization_id))
                        .where(SamSearch.is_active == True)
                        .where(sqla_func.lower(SamSearch.name).contains(search_name.lower()))
                    )
                    row = result.first()

                if row:
                    search_id = str(row[0])
                else:
                    return FunctionResult.success_result(
                        data=[],
                        message=f"No SAM search found matching '{search_name}'",
                        metadata={"search_name": search_name, "total_found": 0},
                        items_processed=0,
                    )
            # If keyword is provided, use PgSearchService for hybrid search
            if keyword and keyword.strip():
                return await self._search_with_pg_service(
                    ctx=ctx,
                    keyword=keyword.strip(),
                    search_mode=search_mode,
                    semantic_weight=semantic_weight,
                    naics_codes=naics_codes,
                    set_asides=set_asides,
                    notice_types=types,
                    posted_within_days=posted_within_days,
                    response_deadline_after=response_deadline_after,
                    include_assets=include_assets,
                    limit=limit,
                    offset=offset,
                )

            # Otherwise, use direct database query with filters
            conditions = [ctx.org_filter(SamSolicitation.organization_id)]

            # NAICS codes filter (check if any code matches)
            if naics_codes:
                naics_conditions = []
                for code in naics_codes:
                    naics_conditions.append(SamSolicitation.naics_code == code)
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

            # Search ID filter
            if search_id:
                conditions.append(SamSolicitation.sam_search_id == UUID(search_id))

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

            # Apply pagination
            query = query.offset(offset).limit(limit)

            # Execute
            result = await ctx.session.execute(query)
            solicitations = result.scalars().all()

            # Format results as ContentItem instances
            results = self._format_solicitations_as_content_items(solicitations)

            return FunctionResult.success_result(
                data=results,
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

    async def _search_with_pg_service(
        self,
        ctx: FunctionContext,
        keyword: str,
        search_mode: str,
        semantic_weight: float,
        naics_codes: Optional[List[str]],
        set_asides: Optional[List[str]],
        notice_types: Optional[List[str]],
        posted_within_days: Optional[int],
        response_deadline_after: Optional[str],
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
            source_types=["sam_solicitation"],  # Only solicitations
            naics_codes=naics_codes,
            set_asides=set_asides,
            notice_types=notice_types,
            posted_within_days=posted_within_days,
            response_deadline_after=response_deadline_after,
            include_sam_assets=include_assets,
            limit=limit,
            offset=offset,
        )

        # Convert SearchHit results to ContentItem format
        results = []
        for hit in search_results.hits:
            # Determine if this is an asset or a solicitation based on source_type
            is_asset = hit.source_type not in ("SAM Solicitation", "sam_solicitation")

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
                    type="solicitation",
                    display_type="Opportunity",
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

        # Count solicitations vs assets
        solicitation_count = sum(1 for r in results if r.type == "solicitation")
        asset_count = sum(1 for r in results if r.type == "asset")

        message = f"Found {len(results)} results matching '{keyword}'"
        if include_assets and asset_count > 0:
            message = f"Found {solicitation_count} solicitations and {asset_count} documents matching '{keyword}'"

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
                "include_assets": include_assets,
                "solicitation_count": solicitation_count,
                "asset_count": asset_count,
                "result_type": "ContentItem",
            },
            items_processed=len(results),
        )

    def _format_solicitations_as_content_items(self, solicitations) -> List[ContentItem]:
        """Format solicitation records as ContentItem instances."""
        results = []
        for sol in solicitations:
            item = ContentItem(
                id=str(sol.id),
                type="solicitation",
                display_type="Opportunity",
                title=sol.title,
                text=None,
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
        return results
