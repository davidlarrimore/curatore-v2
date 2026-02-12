# backend/app/functions/search/search_forecasts.py
"""
Search Forecasts function - Query acquisition forecasts across all sources.

Searches AG, APFS, and State Department forecasts with hybrid search (keyword + semantic).
Leverages PgSearchService for consistent search modes across all search functions.
"""

import logging

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.search.search_forecasts")


class SearchForecastsFunction(BaseFunction):
    """
    Search acquisition forecasts across all sources.

    Searches the unified forecasts view which combines AG (GSA Acquisition Gateway),
    APFS (DHS), and State Department forecasts.

    Example:
        result = await fn.search_forecasts(ctx,
            query="artificial intelligence",
            source_types=["ag", "apfs"],
            fiscal_year=2026,
            limit=50,
        )
    """

    meta = FunctionMeta(
        name="search_forecasts",
        category=FunctionCategory.SEARCH,
        description=(
            "Search acquisition forecasts (planned federal procurements) using hybrid search. "
            "Returns forecast summaries with relevance scores. "
            "IMPORTANT: Forecast IDs are NOT asset IDs — do NOT pass them to get() or get_content(). "
            "To get full details for a forecast, use query_model with the appropriate model "
            "(AgForecast, ApfsForecast, or StateForecast). "
            "Use discover_data_sources to see available forecast sources and their details."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Short keyword query (2-4 key terms work best). "
                        "Use specific names or acronyms, not full descriptions. "
                        "Good: 'DISCOVER II', 'cybersecurity endpoint'. "
                        "Bad: 'Dynamic Integrated Secure Connectivity for Operational Value and End-Point Resiliency'. "
                        "Use filters (agency_name, fiscal_year, naics_code, source_types) to narrow results instead of adding more query terms."
                    ),
                    "examples": ["cybersecurity endpoint"],
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
                "source_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["ag", "apfs", "state"]},
                    "description": "Filter by forecast source: 'ag' (GSA Acquisition Gateway), 'apfs' (DHS), 'state' (State Department). Works with query to narrow results.",
                    "default": None,
                    "examples": [["ag", "apfs"]],
                },
                "fiscal_year": {
                    "type": "integer",
                    "description": "Filter by fiscal year (e.g., 2026). Combines with query and source_types to find forecasts for a specific year.",
                    "default": None,
                    "examples": [2026],
                },
                "agency_name": {
                    "type": "string",
                    "description": "Filter by agency name using partial match (e.g., 'Defense', 'Veterans'). Works with query for agency-specific searches.",
                    "default": None,
                    "examples": ["Department of Defense"],
                },
                "naics_code": {
                    "type": "string",
                    "description": "Filter by NAICS industry code (e.g., '541512' for IT Services). Combines with query to find industry-specific forecasts.",
                    "default": None,
                    "examples": ["541512"],
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 50, max: 500)",
                    "default": 50,
                },
                "offset": {
                    "type": "integer",
                    "description": "Number of results to skip for pagination",
                    "default": 0,
                },
            },
            "required": ["query"],
        },
        output_schema={
            "type": "array",
            "description": "List of matching acquisition forecasts",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Forecast UUID (NOT an asset ID -- do not pass to get() or get_content())"},
                    "title": {"type": "string", "description": "Forecast title/description"},
                    "source_type": {"type": "string", "description": "Source type", "examples": ["ag"]},
                    "agency": {"type": "string", "description": "Agency name", "nullable": True},
                    "fiscal_year": {"type": "integer", "description": "Fiscal year", "examples": [2026], "nullable": True},
                    "naics_code": {"type": "string", "description": "NAICS industry code", "nullable": True},
                    "estimated_value": {"type": "number", "description": "Estimated contract value", "nullable": True},
                    "url": {"type": "string", "description": "Source URL", "nullable": True},
                    "score": {"type": "number", "description": "Relevance score"},
                    "highlights": {"type": "object", "description": "Highlighted search matches", "nullable": True},
                    "detail_url": {"type": "string", "description": "Link to Curatore detail page"},
                },
            },
        },
        tags=["search", "forecasts", "acquisition", "hybrid"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="thin",
        examples=[
            {
                "description": "Hybrid search with source type and fiscal year",
                "params": {
                    "query": "artificial intelligence machine learning",
                    "search_mode": "hybrid",
                    "source_types": ["ag", "apfs"],
                    "fiscal_year": 2026,
                    "limit": 100,
                },
            },
            {
                "description": "Semantic search with agency filter",
                "params": {
                    "query": "cloud computing infrastructure",
                    "search_mode": "semantic",
                    "agency_name": "Department of Defense",
                    "source_types": ["ag"],
                },
            },
            {
                "description": "DHS forecasts with NAICS filter",
                "params": {
                    "query": "cybersecurity",
                    "search_mode": "hybrid",
                    "source_types": ["apfs"],
                    "naics_code": "541512",
                },
            },
            {
                "description": "Defense IT forecasts for FY2026",
                "params": {
                    "query": "information technology services",
                    "source_types": ["ag"],
                    "agency_name": "Defense",
                    "naics_code": "541512",
                    "fiscal_year": 2026,
                },
            },
            {
                "description": "State Department forecasts for consulting",
                "params": {
                    "query": "consulting advisory services",
                    "search_mode": "hybrid",
                    "source_types": ["state"],
                    "fiscal_year": 2026,
                    "limit": 50,
                },
            },
            {
                "description": "After finding forecasts, get full details with query_model",
                "params": {
                    "_note": "Use query_model(model='AgForecast', filters={'id': '<forecast_id>'}) to get full details",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute forecast search using PgSearchService."""
        query = params.get("query", "").strip()
        search_mode = params.get("search_mode", "hybrid")
        semantic_weight = params.get("semantic_weight", 0.5)
        source_types = params.get("source_types")
        fiscal_year = params.get("fiscal_year")
        agency_name = params.get("agency_name")
        naics_code = params.get("naics_code")
        limit = min(params.get("limit", 50), 500)
        offset = params.get("offset", 0)

        if not query:
            return FunctionResult.failed_result(
                error="Empty query",
                message="Search query is required",
            )

        try:
            # Use PgSearchService for hybrid search
            search_results = await ctx.search_service.search_forecasts(
                session=ctx.session,
                organization_id=ctx.organization_id,
                query=query,
                search_mode=search_mode,
                semantic_weight=semantic_weight,
                source_types=source_types,
                fiscal_year=fiscal_year,
                agency_name=agency_name,
                naics_code=naics_code,
                limit=limit,
                offset=offset,
            )

            # Convert SearchHit results to dict format
            forecasts = []
            for hit in search_results.hits:
                forecast = {
                    "id": hit.asset_id,
                    "title": hit.title,
                    "source_type": hit.source_type,
                    "url": hit.url,
                    "created_at": hit.created_at,
                    "score": hit.score,
                    "highlights": hit.highlights,
                    "keyword_score": hit.keyword_score,
                    "semantic_score": hit.semantic_score,
                }
                # Build detail URL
                forecast["detail_url"] = f"/forecasts/{hit.asset_id}"
                forecasts.append(forecast)

            return FunctionResult.success_result(
                data=forecasts,
                message=f"Found {len(forecasts)} forecasts matching '{query}'",
                metadata={
                    "total": search_results.total,
                    "limit": limit,
                    "offset": offset,
                    "has_more": offset + len(forecasts) < search_results.total,
                    "query": query,
                    "search_mode": search_mode,
                    "semantic_weight": semantic_weight,
                    "source_types": source_types,
                    "fiscal_year": fiscal_year,
                },
                items_processed=len(forecasts),
            )

        except Exception as e:
            logger.exception(f"Forecast search failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Failed to search forecasts",
            )
