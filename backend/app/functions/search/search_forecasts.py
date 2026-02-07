# backend/app/functions/search/search_forecasts.py
"""
Search Forecasts function - Query acquisition forecasts across all sources.

Searches AG, APFS, and State Department forecasts with hybrid search (keyword + semantic).
Leverages PgSearchService for consistent search modes across all search functions.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID
import logging

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
    OutputFieldDoc,
    OutputSchema,
)
from ..context import FunctionContext

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
        description="Search acquisition forecasts from AG, APFS, and State Department sources using hybrid search",
        parameters=[
            ParameterDoc(
                name="query",
                type="str",
                description="Search query for title, description, and agency name. Combines with all filters below for refined results.",
                required=True,
                example="artificial intelligence",
            ),
            ParameterDoc(
                name="search_mode",
                type="str",
                description="Search mode: 'keyword' for exact term matches, 'semantic' for conceptual similarity, 'hybrid' combines both for best results.",
                required=False,
                default="hybrid",
                enum_values=["keyword", "semantic", "hybrid"],
            ),
            ParameterDoc(
                name="semantic_weight",
                type="float",
                description="Balance between keyword and semantic search in hybrid mode. 0.0 = keyword only, 1.0 = semantic only, 0.5 = equal weight.",
                required=False,
                default=0.5,
            ),
            ParameterDoc(
                name="source_types",
                type="list[str]",
                description="Filter by forecast source: 'ag' (GSA Acquisition Gateway), 'apfs' (DHS), 'state' (State Department). Works with query to narrow results.",
                required=False,
                default=None,
                enum_values=["ag", "apfs", "state"],
                example=["ag", "apfs"],
            ),
            ParameterDoc(
                name="fiscal_year",
                type="int",
                description="Filter by fiscal year (e.g., 2026). Combines with query and source_types to find forecasts for a specific year.",
                required=False,
                default=None,
                example=2026,
            ),
            ParameterDoc(
                name="agency_name",
                type="str",
                description="Filter by agency name using partial match (e.g., 'Defense', 'Veterans'). Works with query for agency-specific searches.",
                required=False,
                default=None,
                example="Department of Defense",
            ),
            ParameterDoc(
                name="naics_code",
                type="str",
                description="Filter by NAICS industry code (e.g., '541512' for IT Services). Combines with query to find industry-specific forecasts.",
                required=False,
                default=None,
                example="541512",
            ),
            ParameterDoc(
                name="limit",
                type="int",
                description="Maximum number of results (default: 50, max: 500)",
                required=False,
                default=50,
            ),
            ParameterDoc(
                name="offset",
                type="int",
                description="Number of results to skip for pagination",
                required=False,
                default=0,
            ),
        ],
        returns="list[dict]: List of forecast records with search scores and highlights",
        output_schema=OutputSchema(
            type="list[dict]",
            description="List of matching acquisition forecasts",
            fields=[
                OutputFieldDoc(name="id", type="str", description="Forecast UUID"),
                OutputFieldDoc(name="title", type="str", description="Forecast title/description"),
                OutputFieldDoc(name="source_type", type="str", description="Source type",
                              example="ag"),
                OutputFieldDoc(name="agency", type="str", description="Agency name", nullable=True),
                OutputFieldDoc(name="fiscal_year", type="int", description="Fiscal year",
                              example=2026, nullable=True),
                OutputFieldDoc(name="naics_code", type="str", description="NAICS industry code",
                              nullable=True),
                OutputFieldDoc(name="estimated_value", type="float",
                              description="Estimated contract value", nullable=True),
                OutputFieldDoc(name="url", type="str", description="Source URL", nullable=True),
                OutputFieldDoc(name="score", type="float", description="Relevance score"),
                OutputFieldDoc(name="highlights", type="dict",
                              description="Highlighted search matches", nullable=True),
                OutputFieldDoc(name="detail_url", type="str",
                              description="Link to Curatore detail page"),
            ],
        ),
        tags=["search", "forecasts", "acquisition", "hybrid"],
        requires_llm=False,
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
