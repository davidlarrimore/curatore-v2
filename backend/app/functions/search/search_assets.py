# backend/app/functions/search/search_assets.py
"""
Search Assets function - Full-text and semantic search for assets.

Wraps the pg_search_service to search assets using hybrid search.
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
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.search.search_assets")


class SearchAssetsFunction(BaseFunction):
    """
    Search assets using full-text and semantic search.

    Wraps the PostgreSQL hybrid search service for searching asset content.

    Example:
        result = await fn.search_assets(ctx,
            query="machine learning applications",
            source_type="sharepoint",
            limit=20,
        )
    """

    meta = FunctionMeta(
        name="search_assets",
        category=FunctionCategory.SEARCH,
        description="Search assets using full-text and semantic search",
        parameters=[
            ParameterDoc(
                name="query",
                type="str",
                description="Search query",
                required=True,
            ),
            ParameterDoc(
                name="source_type",
                type="str",
                description="Filter by source type",
                required=False,
                default=None,
                enum_values=["upload", "sharepoint", "web_scrape", "sam_gov"],
            ),
            ParameterDoc(
                name="collection_id",
                type="str",
                description="Filter by scrape collection ID",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="sync_config_id",
                type="str",
                description="Filter by SharePoint sync config ID",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="search_mode",
                type="str",
                description="Search mode",
                required=False,
                default="hybrid",
                enum_values=["hybrid", "keyword", "semantic"],
            ),
            ParameterDoc(
                name="keyword_weight",
                type="float",
                description="Weight for keyword search (0-1, only for hybrid mode)",
                required=False,
                default=0.5,
            ),
            ParameterDoc(
                name="limit",
                type="int",
                description="Maximum number of results",
                required=False,
                default=20,
            ),
        ],
        returns="list[dict]: Search results with scores and snippets",
        tags=["search", "assets", "hybrid"],
        requires_llm=False,
        examples=[
            {
                "description": "Search SharePoint assets",
                "params": {
                    "query": "quarterly report",
                    "source_type": "sharepoint",
                    "limit": 10,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute asset search."""
        query = params["query"]
        source_type = params.get("source_type")
        collection_id = params.get("collection_id")
        sync_config_id = params.get("sync_config_id")
        search_mode = params.get("search_mode", "hybrid")
        keyword_weight = params.get("keyword_weight", 0.5)
        limit = min(params.get("limit", 20), 100)

        if not query.strip():
            return FunctionResult.failed_result(
                error="Empty query",
                message="Search query cannot be empty",
            )

        try:
            # Build filters
            filters = {
                "source_types": ["asset"],  # Only search assets
            }
            if source_type:
                filters["source_type_filters"] = [source_type]
            if collection_id:
                filters["collection_id"] = UUID(collection_id) if isinstance(collection_id, str) else collection_id
            if sync_config_id:
                filters["sync_config_id"] = UUID(sync_config_id) if isinstance(sync_config_id, str) else sync_config_id

            # Execute search
            search_results = await ctx.search_service.search(
                session=ctx.session,
                organization_id=ctx.organization_id,
                query=query,
                search_mode=search_mode,
                keyword_weight=keyword_weight,
                limit=limit,
                **filters,
            )

            # Format results
            results = []
            for sr in search_results.results:
                results.append({
                    "asset_id": str(sr.source_id),
                    "title": sr.title,
                    "filename": sr.filename,
                    "score": sr.score,
                    "snippet": sr.snippet,
                    "source_type": sr.source_type_filter,
                    "content_type": sr.content_type,
                })

            return FunctionResult.success_result(
                data=results,
                message=f"Found {len(results)} assets",
                metadata={
                    "query": query,
                    "search_mode": search_mode,
                    "total_found": len(results),
                    "filters_applied": {
                        "source_type": source_type,
                        "collection_id": str(collection_id) if collection_id else None,
                        "sync_config_id": str(sync_config_id) if sync_config_id else None,
                    },
                },
                items_processed=len(results),
            )

        except Exception as e:
            logger.exception(f"Search failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Search failed",
            )
