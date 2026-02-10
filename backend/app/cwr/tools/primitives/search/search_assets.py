# backend/app/functions/search/search_assets.py
"""
Search Assets function - Full-text and semantic search for assets.

Wraps the pg_search_service to search assets using hybrid search.
Returns results as ContentItem instances for unified handling.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID
import logging

from ...base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
    OutputFieldDoc,
    OutputSchema,
)
from ...context import FunctionContext
from ...content import ContentItem

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
        description=(
            "Search document assets using full-text and semantic search. "
            "Returns document summaries with relevance scores. To read full document content, "
            "use get_content(asset_ids=[...]) with IDs from these results. "
            "This tool searches documents only — use discover_data_sources to see all available "
            "data sources and the appropriate search tool for each."
        ),
        parameters=[
            ParameterDoc(
                name="query",
                type="str",
                description=(
                    "Short keyword query (2-4 key terms work best). "
                    "Use specific names or acronyms, not full sentences. "
                    "Good: 'SOW cybersecurity', 'DISCOVER II proposal'. "
                    "Bad: 'Statement of Work for cybersecurity endpoint protection and monitoring services'. "
                    "Use filters (source_type, site_name, facet_filters) to narrow results instead of adding more query terms."
                ),
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
                name="site_name",
                type="str",
                description="Filter by SharePoint site display name (e.g., 'IT Department'). Case-insensitive. Resolves to sync_config_ids automatically.",
                required=False,
                default=None,
                example="IT Department",
            ),
            ParameterDoc(
                name="facet_filters",
                type="dict",
                description="Cross-domain facet filters (e.g., {'agency': 'GSA', 'naics_code': '541512'}). Use discover_metadata to see available facets.",
                required=False,
                default=None,
            ),
            ParameterDoc(
                name="folder_path",
                type="str",
                description="Filter by folder path. Accepts storage paths (e.g., 'sharepoint/my-site/shared-documents/opportunities') or human-friendly paths (e.g., 'Shared Documents/Opportunities') which are auto-slugified. Copy from the storage browser or asset detail page.",
                required=False,
                default=None,
                example="sharepoint/my-site/shared-documents/opportunities",
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
        returns="list[ContentItem]: Search results with document metadata",
        output_schema=OutputSchema(
            type="list[ContentItem]",
            description="List of matching documents as ContentItem objects",
            fields=[
                OutputFieldDoc(name="id", type="str", description="Asset UUID",
                              example="550e8400-e29b-41d4-a716-446655440000"),
                OutputFieldDoc(name="title", type="str", description="Full document path/title",
                              example="Opportunities/DHS/TSA/proposal.pdf"),
                OutputFieldDoc(name="original_filename", type="str", description="File name only",
                              example="proposal.pdf"),
                OutputFieldDoc(name="folder_path", type="str", description="Folder path for SharePoint",
                              example="Opportunities/DHS/TSA", nullable=True),
                OutputFieldDoc(name="source_url", type="str", description="Direct URL to document",
                              nullable=True),
                OutputFieldDoc(name="content_type", type="str", description="MIME type",
                              example="application/pdf"),
                OutputFieldDoc(name="source_type", type="str", description="Source type",
                              example="sharepoint"),
                OutputFieldDoc(name="score", type="float", description="Relevance score (0-1)",
                              example=0.85),
                OutputFieldDoc(name="snippet", type="str", description="Highlighted text excerpt",
                              nullable=True),
                OutputFieldDoc(name="site_name", type="str",
                              description="SharePoint site display name (SharePoint assets only)",
                              example="IT Department", nullable=True),
            ],
        ),
        tags=["search", "assets", "hybrid", "content"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="thin",
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
        site_name = params.get("site_name")
        facet_filters = params.get("facet_filters")
        folder_path = params.get("folder_path")
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

            # Resolve site_name to sync_config_ids (case-insensitive)
            if site_name and not sync_config_ids:
                from app.core.database.models import SharePointSyncConfig
                from sqlalchemy import select, func as sqla_func

                result = await ctx.session.execute(
                    select(SharePointSyncConfig.id)
                    .where(SharePointSyncConfig.organization_id == ctx.organization_id)
                    .where(SharePointSyncConfig.is_active == True)
                    .where(sqla_func.lower(SharePointSyncConfig.site_name) == site_name.lower())
                )
                resolved_ids = [row[0] for row in result.fetchall()]
                if not resolved_ids:
                    # Try matching on config name as fallback
                    result = await ctx.session.execute(
                        select(SharePointSyncConfig.id)
                        .where(SharePointSyncConfig.organization_id == ctx.organization_id)
                        .where(SharePointSyncConfig.is_active == True)
                        .where(sqla_func.lower(SharePointSyncConfig.name).contains(site_name.lower()))
                    )
                    resolved_ids = [row[0] for row in result.fetchall()]

                if resolved_ids:
                    sync_config_ids = resolved_ids
                    # Auto-set source_type to sharepoint when filtering by site
                    if not source_type:
                        source_types = ["sharepoint"]
                else:
                    return FunctionResult.success_result(
                        data=[],
                        message=f"No SharePoint sites found matching '{site_name}'",
                        metadata={"site_name": site_name, "total_found": 0},
                        items_processed=0,
                    )

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
                folder_path=folder_path,
                facet_filters=facet_filters,
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

                # Extract site_name from search chunk metadata
                site_name = None
                if sr.metadata:
                    site_name = sr.metadata.get("sharepoint", {}).get("site_name")

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
                        "site_name": site_name,
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
                        "site_name": site_name,
                        "facet_filters": facet_filters,
                        "folder_path": folder_path,
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
