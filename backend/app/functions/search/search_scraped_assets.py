# backend/app/functions/search/search_scraped_assets.py
"""
Search Scraped Assets function - Query web scraped content.

Query and filter scraped assets from web crawl collections using hybrid search.
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

logger = logging.getLogger("curatore.functions.search.search_scraped_assets")


class SearchScrapedAssetsFunction(BaseFunction):
    """
    Search scraped assets from web crawl collections.

    Queries scraped pages and records with various filters.
    Returns ContentItem instances for unified handling.

    Example:
        result = await fn.search_scraped_assets(ctx,
            collection_id="uuid",
            asset_subtype="record",
        )
    """

    meta = FunctionMeta(
        name="search_scraped_assets",
        category=FunctionCategory.SEARCH,
        description="Search scraped assets with hybrid search and filters, returns ContentItem list",
        parameters=[
            ParameterDoc(
                name="collection_id",
                type="str",
                description="Filter by scrape collection ID (required)",
                required=True,
            ),
            ParameterDoc(
                name="keyword",
                type="str",
                description="Search query for content (uses hybrid search)",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="search_mode",
                type="str",
                description="Search mode: keyword (exact matches), semantic (conceptual), or hybrid (both)",
                required=False,
                default="hybrid",
                enum_values=["keyword", "semantic", "hybrid"],
            ),
            ParameterDoc(
                name="semantic_weight",
                type="float",
                description="Weight for semantic search in hybrid mode (0-1, default 0.5)",
                required=False,
                default=0.5,
            ),
            ParameterDoc(
                name="asset_subtype",
                type="str",
                description="Filter by asset subtype",
                required=False,
                default=None,
                enum_values=["page", "record"],
            ),
            ParameterDoc(
                name="is_promoted",
                type="bool",
                description="Filter by promotion status",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="url_path_prefix",
                type="str",
                description="Filter by URL path prefix (for hierarchical browsing)",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="crawl_depth",
                type="int",
                description="Filter by specific crawl depth",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="max_crawl_depth",
                type="int",
                description="Filter by maximum crawl depth",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="order_by",
                type="str",
                description="Field to order by (only used when no keyword search)",
                required=False,
                default="-created_at",
                enum_values=["-created_at", "created_at", "url_path", "-crawl_depth", "crawl_depth"],
            ),
            ParameterDoc(
                name="limit",
                type="int",
                description="Maximum number of results",
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
        returns="list[ContentItem]: Matching scraped assets as ContentItem instances",
        tags=["search", "scrape", "web", "content", "hybrid"],
        requires_llm=False,
        examples=[
            {
                "description": "Hybrid search in collection",
                "params": {
                    "collection_id": "uuid",
                    "keyword": "procurement opportunities",
                    "search_mode": "hybrid",
                    "limit": 50,
                },
            },
            {
                "description": "Semantic search for related content",
                "params": {
                    "collection_id": "uuid",
                    "keyword": "federal contracts IT services",
                    "search_mode": "semantic",
                },
            },
            {
                "description": "Get promoted records from collection",
                "params": {
                    "collection_id": "uuid",
                    "asset_subtype": "record",
                    "is_promoted": True,
                },
            },
            {
                "description": "Browse by path",
                "params": {
                    "collection_id": "uuid",
                    "url_path_prefix": "/opportunities/",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Query scraped assets with optional hybrid search."""
        from ...database.models import ScrapedAsset, Asset, ScrapeCollection
        from sqlalchemy.orm import selectinload

        collection_id = params.get("collection_id")
        keyword = params.get("keyword")
        search_mode = params.get("search_mode", "hybrid")
        semantic_weight = params.get("semantic_weight", 0.5)
        asset_subtype = params.get("asset_subtype")
        is_promoted = params.get("is_promoted")
        url_path_prefix = params.get("url_path_prefix")
        crawl_depth = params.get("crawl_depth")
        max_crawl_depth = params.get("max_crawl_depth")
        order_by = params.get("order_by", "-created_at")
        offset = params.get("offset", 0)

        # Coerce types
        limit_val = params.get("limit", 50)
        if isinstance(limit_val, str):
            limit_val = int(limit_val) if limit_val else 50
        limit = min(limit_val, 500)

        if not collection_id:
            return FunctionResult.failed_result(
                error="collection_id is required",
                message="Must specify a collection_id to search scraped assets",
            )

        try:
            collection_uuid = UUID(collection_id) if isinstance(collection_id, str) else collection_id

            # Verify collection belongs to organization
            collection_query = select(ScrapeCollection).where(
                ScrapeCollection.id == collection_uuid,
                ScrapeCollection.organization_id == ctx.organization_id,
            )
            collection_result = await ctx.session.execute(collection_query)
            collection = collection_result.scalar_one_or_none()

            if not collection:
                return FunctionResult.failed_result(
                    error="Collection not found",
                    message=f"Collection {collection_id} not found or not accessible",
                )

            # If keyword is provided, use PgSearchService for hybrid search
            if keyword and keyword.strip():
                return await self._search_with_pg_service(
                    ctx=ctx,
                    collection_id=collection_uuid,
                    collection_name=collection.name,
                    keyword=keyword.strip(),
                    search_mode=search_mode,
                    semantic_weight=semantic_weight,
                    limit=limit,
                    offset=offset,
                )

            # Otherwise, use direct database query with filters
            conditions = [ScrapedAsset.collection_id == collection_uuid]

            # Asset subtype filter
            if asset_subtype:
                conditions.append(ScrapedAsset.asset_subtype == asset_subtype)

            # Promotion filter
            if is_promoted is not None:
                conditions.append(ScrapedAsset.is_promoted == is_promoted)

            # URL path prefix filter
            if url_path_prefix:
                conditions.append(ScrapedAsset.url_path.startswith(url_path_prefix))

            # Crawl depth filters
            if crawl_depth is not None:
                conditions.append(ScrapedAsset.crawl_depth == crawl_depth)
            if max_crawl_depth is not None:
                conditions.append(ScrapedAsset.crawl_depth <= max_crawl_depth)

            # Build query with eager loading
            query = (
                select(ScrapedAsset)
                .where(and_(*conditions))
                .options(selectinload(ScrapedAsset.asset))
            )

            # Apply ordering
            if order_by:
                desc_order = order_by.startswith("-")
                field_name = order_by.lstrip("-")
                field_map = {
                    "created_at": ScrapedAsset.created_at,
                    "url_path": ScrapedAsset.url_path,
                    "crawl_depth": ScrapedAsset.crawl_depth,
                }
                if field_name in field_map:
                    order_col = field_map[field_name]
                    query = query.order_by(desc(order_col) if desc_order else order_col)

            # Apply pagination
            query = query.offset(offset).limit(limit)

            # Execute
            result = await ctx.session.execute(query)
            scraped_assets = result.scalars().all()

            # Format results as ContentItem instances
            results = self._format_scraped_assets_as_content_items(scraped_assets, collection_uuid)

            return FunctionResult.success_result(
                data=results,
                message=f"Found {len(results)} scraped assets",
                metadata={
                    "collection_id": str(collection_uuid),
                    "collection_name": collection.name,
                    "filters": {
                        "asset_subtype": asset_subtype,
                        "is_promoted": is_promoted,
                        "url_path_prefix": url_path_prefix,
                        "crawl_depth": crawl_depth,
                        "max_crawl_depth": max_crawl_depth,
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
                message="Scraped asset query failed",
            )

    async def _search_with_pg_service(
        self,
        ctx: FunctionContext,
        collection_id: UUID,
        collection_name: str,
        keyword: str,
        search_mode: str,
        semantic_weight: float,
        limit: int,
        offset: int,
    ) -> FunctionResult:
        """Use PgSearchService for hybrid search within a collection."""
        # Search using the main search service with collection filter
        search_results = await ctx.search_service.search(
            session=ctx.session,
            organization_id=ctx.organization_id,
            query=keyword,
            search_mode=search_mode,
            semantic_weight=semantic_weight,
            source_types=["asset"],  # Scraped assets are stored as assets
            collection_ids=[collection_id],
            limit=limit,
            offset=offset,
        )

        # Convert SearchHit results to ContentItem format
        results = []
        for hit in search_results.hits:
            item = ContentItem(
                id=hit.asset_id,
                type="scraped_asset",
                display_type="Web Page",
                title=hit.title or hit.filename,
                text=None,
                text_format="markdown",
                fields={
                    "url": hit.url,
                    "source_type": hit.source_type,
                    "content_type": hit.content_type,
                    "created_at": hit.created_at,
                },
                metadata={
                    "score": hit.score,
                    "keyword_score": hit.keyword_score,
                    "semantic_score": hit.semantic_score,
                    "highlights": hit.highlights,
                    "search_mode": search_mode,
                },
                parent_id=str(collection_id),
                parent_type="scrape_collection",
            )
            results.append(item)

        return FunctionResult.success_result(
            data=results,
            message=f"Found {len(results)} scraped assets matching '{keyword}'",
            metadata={
                "collection_id": str(collection_id),
                "collection_name": collection_name,
                "total": search_results.total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(results) < search_results.total,
                "keyword": keyword,
                "search_mode": search_mode,
                "semantic_weight": semantic_weight,
                "result_type": "ContentItem",
            },
            items_processed=len(results),
        )

    def _format_scraped_assets_as_content_items(self, scraped_assets, collection_uuid: UUID) -> List[ContentItem]:
        """Format scraped asset records as ContentItem instances."""
        results = []
        for sa in scraped_assets:
            # Determine display type and title
            if sa.asset_subtype == "record":
                display_type = "Captured Document"
            else:
                display_type = "Web Page"

            # Get title from metadata or asset
            title = None
            if sa.scrape_metadata and "title" in sa.scrape_metadata:
                title = sa.scrape_metadata["title"]
            elif sa.asset:
                title = sa.asset.original_filename
            if not title:
                title = sa.url.split("/")[-1] or sa.url

            item = ContentItem(
                id=str(sa.id),
                type="scraped_asset",
                display_type=display_type,
                title=title,
                text=None,
                text_format="markdown",
                fields={
                    "url": sa.url,
                    "url_path": sa.url_path,
                    "parent_url": sa.parent_url,
                    "asset_subtype": sa.asset_subtype,
                    "crawl_depth": sa.crawl_depth,
                    "is_promoted": sa.is_promoted,
                },
                metadata={
                    "scrape_metadata": sa.scrape_metadata,
                    "promoted_at": sa.promoted_at.isoformat() if sa.promoted_at else None,
                    "asset_id": str(sa.asset_id) if sa.asset_id else None,
                    "asset_status": sa.asset.status if sa.asset else None,
                },
                parent_id=str(collection_uuid),
                parent_type="scrape_collection",
            )
            results.append(item)
        return results
