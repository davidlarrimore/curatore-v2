# backend/app/functions/search/search_assets.py
"""
Search Assets function - Full-text and semantic search for assets.

Wraps the pg_search_service to search assets using hybrid search.
Returns results as ContentItem instances for unified handling.
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
from ..content import ContentItem

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
        description="""Search assets (documents, files) using full-text and semantic search.

Returns a list of ContentItem objects. Each item has these fields accessible in templates:
- id: Asset UUID
- title: Full path/title of the document
- type: Always "asset"
- display_type: Always "Document"
- original_filename: The file name (e.g., "report.pdf")
- folder_path: Folder path for SharePoint files (e.g., "Opportunities/DHS/Project")
- source_url: Direct URL to the file (SharePoint web URL for SharePoint files)
- content_type: MIME type (e.g., "application/pdf")
- source_type: Source type ("sharepoint", "upload", "web_scrape", "sam_gov")
- score: Search relevance score
- snippet: Text snippet with search term highlights""",
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
        returns="""list[ContentItem]: Search results. Template fields:
- {{ item.title }} - Full document path/title
- {{ item.original_filename }} - File name only
- {{ item.folder_path }} - Folder path (SharePoint)
- {{ item.source_url }} - Direct link to document
- {{ item.content_type }} - MIME type
- {{ item.source_type }} - Source ("sharepoint", "upload", etc.)
- {{ item.score }} - Relevance score
- {{ item.snippet }} - Highlighted excerpt""",
        tags=["search", "assets", "hybrid", "content"],
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
            # Build source_types filter
            # The search service treats values like "sharepoint", "upload", "web_scrape", "sam_gov"
            # as asset source_type_filter values (filters: source_type='asset' AND source_type_filter=X)
            if source_type:
                # Filter to specific asset type (e.g., "sharepoint")
                source_types = [source_type]
            else:
                # All asset types - list all known asset source filters
                source_types = ["upload", "sharepoint", "web_scrape", "sam_gov"]

            # Build optional filters
            collection_ids = None
            if collection_id:
                cid = UUID(collection_id) if isinstance(collection_id, str) else collection_id
                collection_ids = [cid]

            sync_config_ids = None
            if sync_config_id:
                sid = UUID(sync_config_id) if isinstance(sync_config_id, str) else sync_config_id
                sync_config_ids = [sid]

            # Execute search
            # PgSearchService uses semantic_weight (0-1), so convert from keyword_weight
            semantic_weight = 1 - keyword_weight
            search_results = await ctx.search_service.search(
                session=ctx.session,
                organization_id=ctx.organization_id,
                query=query,
                search_mode=search_mode,
                semantic_weight=semantic_weight,
                source_types=source_types,
                collection_ids=collection_ids,
                sync_config_ids=sync_config_ids,
                limit=limit,
            )

            # Format results as ContentItem instances
            results = []
            for sr in search_results.hits:
                # Extract snippet from highlights if available
                snippet = None
                if sr.highlights and "content" in sr.highlights and sr.highlights["content"]:
                    snippet = sr.highlights["content"][0]

                # Parse folder_path from title (title often contains full path like "Folder/SubFolder/file.pdf")
                title = sr.title or sr.filename or ""
                folder_path = ""
                if "/" in title and sr.filename:
                    # Title contains path, extract folder portion
                    folder_path = title.rsplit("/", 1)[0] if "/" in title else ""

                item = ContentItem(
                    id=str(sr.asset_id),
                    type="asset",
                    display_type="Document",
                    title=title,
                    text=None,  # Text not loaded by default for search results
                    text_format="markdown",
                    fields={
                        "original_filename": sr.filename,
                        "folder_path": folder_path,
                        "content_type": sr.content_type,
                        "source_type": sr.source_type,  # Display type from search service
                        "source_url": sr.url,
                        "status": "ready",  # Only indexed assets are searchable
                    },
                    metadata={
                        "score": sr.score,
                        "snippet": snippet,
                        "search_mode": search_mode,
                    },
                )
                results.append(item)

            return FunctionResult.success_result(
                data=results,  # List of ContentItem
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
                    "result_type": "ContentItem",
                },
                items_processed=len(results),
            )

        except Exception as e:
            logger.exception(f"Search failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Search failed",
            )
