# backend/app/functions/search/search_scraped_assets.py
"""
Search Scraped Assets function - Query web scraped content.

Query and filter scraped assets from web crawl collections using hybrid search.
Returns results as ContentItem instances for unified handling.
"""

import logging
from typing import List
from uuid import UUID

from sqlalchemy import and_, desc, select

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...content import ContentItem
from ...context import FunctionContext

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
        description=(
            "Search web-scraped content within a specific collection using hybrid search. "
            "Returns page summaries with relevance scores. To read full page content, "
            "use get_content(asset_ids=[...]) with IDs from these results. "
            "Use discover_data_sources(source_type='web_scrape') to see available collections."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "collection_id": {
                    "type": "string",
                    "description": "Filter by scrape collection ID. Required unless collection_name is provided.",
                    "default": None,
                },
                "collection_name": {
                    "type": "string",
                    "description": "Filter by collection name (e.g., 'GSA AG'). Case-insensitive. Resolves to collection_id automatically. collection_id takes precedence if both provided.",
                    "default": None,
                    "examples": ["GSA Acquisition Gateway"],
                },
                "keyword": {
                    "type": "string",
                    "description": (
                        "Short keyword query (2-4 key terms work best). "
                        "Use specific terms, not full sentences. "
                        "Use collection_name or collection_id to narrow results instead of adding more query terms."
                    ),
                    "default": None,
                },
                "search_mode": {
                    "type": "string",
                    "description": "Search mode: keyword (exact matches), semantic (conceptual), or hybrid (both)",
                    "default": "hybrid",
                    "enum": ["keyword", "semantic", "hybrid"],
                },
                "semantic_weight": {
                    "type": "number",
                    "description": "Weight for semantic search in hybrid mode (0-1, default 0.5)",
                    "default": 0.5,
                },
                "asset_subtype": {
                    "type": "string",
                    "description": "Filter by asset subtype",
                    "default": None,
                    "enum": ["page", "record"],
                },
                "is_promoted": {
                    "type": "boolean",
                    "description": "Filter by promotion status",
                    "default": None,
                },
                "url_path_prefix": {
                    "type": "string",
                    "description": "Filter by URL path prefix (for hierarchical browsing)",
                    "default": None,
                },
                "crawl_depth": {
                    "type": "integer",
                    "description": "Filter by specific crawl depth",
                    "default": None,
                },
                "max_crawl_depth": {
                    "type": "integer",
                    "description": "Filter by maximum crawl depth",
                    "default": None,
                },
                "order_by": {
                    "type": "string",
                    "description": "Field to order by (only used when no keyword search)",
                    "default": "-created_at",
                    "enum": ["-created_at", "created_at", "url_path", "-crawl_depth", "crawl_depth"],
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
            },
            "required": [],
        },
        output_schema={
            "type": "array",
            "description": "List of matching scraped web pages and records",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Scraped asset UUID"},
                    "title": {"type": "string", "description": "Page title or filename"},
                    "url": {"type": "string", "description": "Full URL of the page"},
                    "url_path": {"type": "string", "description": "URL path portion"},
                    "parent_url": {"type": "string", "description": "URL of the parent page", "nullable": True},
                    "asset_subtype": {"type": "string", "description": "Asset type: page or record", "examples": ["page"]},
                    "crawl_depth": {"type": "integer", "description": "Depth from seed URL", "examples": [2]},
                    "is_promoted": {"type": "boolean", "description": "Whether asset is promoted to main collection"},
                    "score": {"type": "number", "description": "Relevance score", "nullable": True},
                    "highlights": {"type": "object", "description": "Highlighted search matches", "nullable": True},
                },
            },
        },
        tags=["search", "scrape", "web", "content", "hybrid"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="thin",
        required_data_sources=["web_scrape"],
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
        from sqlalchemy.orm import selectinload

        from app.core.database.models import ScrapeCollection, ScrapedAsset

        collection_id = params.get("collection_id")
        collection_name = params.get("collection_name")
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

        # Resolve collection_name to collection_id (case-insensitive)
        if collection_name and not collection_id:
            from sqlalchemy import func as sqla_func

            result = await ctx.session.execute(
                select(ScrapeCollection.id)
                .where(ctx.org_filter(ScrapeCollection.organization_id))
                .where(ScrapeCollection.status == "active")
                .where(sqla_func.lower(ScrapeCollection.name) == collection_name.lower())
            )
            row = result.first()
            if not row:
                # Try partial match as fallback
                result = await ctx.session.execute(
                    select(ScrapeCollection.id)
                    .where(ctx.org_filter(ScrapeCollection.organization_id))
                    .where(ScrapeCollection.status == "active")
                    .where(sqla_func.lower(ScrapeCollection.name).contains(collection_name.lower()))
                )
                row = result.first()

            if row:
                collection_id = str(row[0])
            else:
                return FunctionResult.success_result(
                    data=[],
                    message=f"No scrape collection found matching '{collection_name}'",
                    metadata={"collection_name": collection_name, "total_found": 0},
                    items_processed=0,
                )

        if not collection_id:
            return FunctionResult.failed_result(
                error="collection_id or collection_name is required",
                message="Must specify a collection_id or collection_name to search scraped assets",
            )

        try:
            collection_uuid = UUID(collection_id) if isinstance(collection_id, str) else collection_id

            # Verify collection belongs to organization
            collection_query = select(ScrapeCollection).where(
                ScrapeCollection.id == collection_uuid,
                ctx.org_filter(ScrapeCollection.organization_id),
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
            organization_id=ctx.requires_org_id,
            query=keyword,
            search_mode=search_mode,
            semantic_weight=semantic_weight,
            source_types=["web_scrape"],  # Scraped assets have source_type_filter='web_scrape'
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
