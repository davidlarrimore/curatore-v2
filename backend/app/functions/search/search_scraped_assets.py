# backend/app/functions/search/search_scraped_assets.py
"""
Search Scraped Assets function - Query web scraped content.

Query and filter scraped assets from web crawl collections.
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
        description="Search scraped assets with filters, returns ContentItem list",
        parameters=[
            ParameterDoc(
                name="collection_id",
                type="str",
                description="Filter by scrape collection ID (required)",
                required=True,
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
                name="keyword",
                type="str",
                description="Search in URL or metadata title",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="order_by",
                type="str",
                description="Field to order by",
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
        ],
        returns="list[ContentItem]: Matching scraped assets as ContentItem instances",
        tags=["search", "scrape", "web", "content"],
        requires_llm=False,
        examples=[
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
        """Query scraped assets."""
        from ...database.models import ScrapedAsset, Asset, ScrapeCollection

        collection_id = params.get("collection_id")
        asset_subtype = params.get("asset_subtype")
        is_promoted = params.get("is_promoted")
        url_path_prefix = params.get("url_path_prefix")
        crawl_depth = params.get("crawl_depth")
        max_crawl_depth = params.get("max_crawl_depth")
        keyword = params.get("keyword")
        order_by = params.get("order_by", "-created_at")

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

            # Build query
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

            # Keyword search
            if keyword:
                keyword_pattern = f"%{keyword}%"
                conditions.append(
                    or_(
                        ScrapedAsset.url.ilike(keyword_pattern),
                        ScrapedAsset.scrape_metadata["title"].astext.ilike(keyword_pattern),
                    )
                )

            # Build query with eager loading
            query = (
                select(ScrapedAsset)
                .where(and_(*conditions))
                .options(selectinload(ScrapedAsset.asset))
            )

            # Need to import selectinload
            from sqlalchemy.orm import selectinload

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

            # Apply limit
            query = query.limit(limit)

            # Execute
            result = await ctx.session.execute(query)
            scraped_assets = result.scalars().all()

            # Format results as ContentItem instances
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
                    text=None,  # Text not loaded by default
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
                    parent_id=str(sa.collection_id),
                    parent_type="scrape_collection",
                )
                results.append(item)

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
