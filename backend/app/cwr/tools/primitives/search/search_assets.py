# backend/app/functions/search/search_assets.py
"""
Search Assets function - Full-text and semantic search for assets.

Wraps the pg_search_service to search assets using hybrid search.
Returns results as ContentItem instances for unified handling.
"""

import logging
from typing import Any, Dict, List
from uuid import UUID

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...content import ContentItem
from ...context import FunctionContext
from ...filters import WHERE_SCHEMA, build_jsonb_where

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
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Short keyword query (2-4 key terms work best). "
                        "Use specific names or acronyms, not full sentences. "
                        "Good: 'SOW cybersecurity', 'DISCOVER II proposal'. "
                        "Bad: 'Statement of Work for cybersecurity endpoint protection and monitoring services'. "
                        "Use filters (source_type, site_name, facet_filters) to narrow results instead of adding more query terms. "
                        "Use '*' to list all assets matching the provided filters without text search (returns results ordered by creation date)."
                    ),
                },
                "source_type": {
                    "type": "string",
                    "description": "Filter by source type",
                    "default": None,
                    "enum": ["upload", "sharepoint", "web_scrape", "sam_gov"],
                },
                "collection_id": {
                    "type": "string",
                    "description": "Filter by scrape collection ID",
                    "default": None,
                },
                "sync_config_id": {
                    "type": "string",
                    "description": "Filter by SharePoint sync config ID",
                    "default": None,
                },
                "site_name": {
                    "type": "string",
                    "description": "Filter by SharePoint site display name (e.g., 'IT Department'). Case-insensitive. Resolves to sync_config_ids automatically.",
                    "default": None,
                    "examples": ["IT Department"],
                },
                "facet_filters": {
                    "type": "object",
                    "description": "Cross-domain facet filters (e.g., {'agency': 'GSA', 'naics_code': '541512'}). Use discover_metadata to see available facets.",
                    "default": None,
                },
                "folder_path": {
                    "type": "string",
                    "description": (
                        "Filter by storage folder path. Use the full storage path from "
                        "resolve_sharepoint_folders (e.g., 'sharepoint/growth-sharepoint/reuse-material/past-performances'). "
                        "Combined with folder_match_mode to control matching."
                    ),
                    "default": None,
                    "examples": ["sharepoint/growth-sharepoint/reuse-material/past-performances"],
                },
                "folder_match_mode": {
                    "type": "string",
                    "enum": ["prefix", "contains"],
                    "default": "prefix",
                    "description": (
                        "How to match folder_path: "
                        "'prefix' = exact prefix match on slugified storage folder (default, recommended). "
                        "'contains' = substring match anywhere in the storage folder path."
                    ),
                },
                "search_mode": {
                    "type": "string",
                    "description": "Search mode",
                    "default": "hybrid",
                    "enum": ["hybrid", "keyword", "semantic"],
                },
                "keyword_weight": {
                    "type": "number",
                    "description": "Weight for keyword search (0-1, only for hybrid mode)",
                    "default": 0.5,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 20,
                },
                "where": WHERE_SCHEMA,
            },
            "required": ["query"],
        },
        output_schema={
            "type": "array",
            "description": "List of matching documents as ContentItem objects",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Asset UUID", "examples": ["550e8400-e29b-41d4-a716-446655440000"]},
                    "title": {"type": "string", "description": "Full document path/title", "examples": ["Opportunities/DHS/TSA/proposal.pdf"]},
                    "original_filename": {"type": "string", "description": "File name only", "examples": ["proposal.pdf"]},
                    "folder_path": {"type": "string", "description": "Folder path for SharePoint", "examples": ["Opportunities/DHS/TSA"], "nullable": True},
                    "source_url": {"type": "string", "description": "Direct URL to document", "nullable": True},
                    "content_type": {"type": "string", "description": "MIME type", "examples": ["application/pdf"]},
                    "source_type": {"type": "string", "description": "Source type", "examples": ["sharepoint"]},
                    "score": {"type": "number", "description": "Relevance score (0-1)", "examples": [0.85]},
                    "snippet": {"type": "string", "description": "Highlighted text excerpt", "nullable": True},
                    "site_name": {"type": "string", "description": "SharePoint site display name (SharePoint assets only)", "examples": ["IT Department"], "nullable": True},
                },
            },
        },
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
            {
                "description": "List assets missing site_name metadata",
                "params": {
                    "query": "*",
                    "source_type": "sharepoint",
                    "where": [{"field": "sharepoint.site_name", "op": "is_empty"}],
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
        folder_match_mode = params.get("folder_match_mode", "prefix")
        search_mode = params.get("search_mode", "hybrid")
        keyword_weight = params.get("keyword_weight", 0.5)
        limit = min(params.get("limit", 20), 100)

        if not query.strip():
            return FunctionResult.failed_result(
                error="Empty query",
                message="Search query cannot be empty",
            )

        # Wildcard query: list assets by filters without full-text search
        if query.strip() == "*":
            # Allow higher limit for wildcard listing (not constrained by FTS)
            wildcard_limit = min(params.get("limit", 100), 10000)
            where_conditions = params.get("where")
            return await self._list_by_filters(
                ctx, source_type=source_type, sync_config_id=sync_config_id,
                collection_id=collection_id, site_name=site_name, limit=wildcard_limit,
                where_conditions=where_conditions, folder_path=folder_path,
                folder_match_mode=folder_match_mode,
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
                from sqlalchemy import func as sqla_func
                from sqlalchemy import select

                from app.core.database.models import SharePointSyncConfig

                result = await ctx.session.execute(
                    select(SharePointSyncConfig.id)
                    .where(ctx.org_filter(SharePointSyncConfig.organization_id))
                    .where(SharePointSyncConfig.is_active == True)
                    .where(sqla_func.lower(SharePointSyncConfig.site_name) == site_name.lower())
                )
                resolved_ids = [row[0] for row in result.fetchall()]
                if not resolved_ids:
                    # Try matching on config name as fallback
                    result = await ctx.session.execute(
                        select(SharePointSyncConfig.id)
                        .where(ctx.org_filter(SharePointSyncConfig.organization_id))
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
                folder_match_mode=folder_match_mode,
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
                result_folder = ""
                if "/" in title and sr.filename:
                    # Title contains path, extract folder portion
                    result_folder = title.rsplit("/", 1)[0] if "/" in title else ""

                # Extract site_name from search chunk metadata
                result_site_name = None
                if sr.metadata:
                    result_site_name = sr.metadata.get("sharepoint", {}).get("site_name")

                item = ContentItem(
                    id=str(sr.asset_id),
                    type="asset",
                    display_type="Document",
                    title=title,
                    text=None,  # Text not loaded by default for search results
                    text_format="markdown",
                    fields={
                        "original_filename": sr.filename,
                        "folder_path": result_folder,
                        "content_type": sr.content_type,
                        "source_type": sr.source_type,  # Display type from search service
                        "source_url": sr.url,
                        "status": "ready",  # Only indexed assets are searchable
                        "site_name": result_site_name,
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

    async def _list_by_filters(
        self,
        ctx: FunctionContext,
        source_type: str = None,
        sync_config_id: str = None,
        collection_id: str = None,
        site_name: str = None,
        limit: int = 100,
        where_conditions: List[Dict[str, Any]] = None,
        folder_path: str = None,
        folder_match_mode: str = "prefix",
    ) -> FunctionResult:
        """
        List assets by filters without full-text search.

        Used when query="*" to return all matching assets ordered by creation date.
        Queries the Asset table directly instead of search_chunks.
        """
        from sqlalchemy import func as sqla_func
        from sqlalchemy import select

        from app.core.database.models import Asset

        try:
            # Only return assets with completed extraction (status='ready').
            # This is consistent with the search-based path which only returns
            # indexed assets, and excludes unsupported/failed/pending/deleted files.
            query = select(Asset).where(
                ctx.org_filter(Asset.organization_id),
                Asset.status == "ready",
            )

            # Apply operator-based where conditions via shared filter module
            if where_conditions:
                clauses = build_jsonb_where(Asset.source_metadata, where_conditions)
                for clause in clauses:
                    query = query.where(clause)

            if source_type:
                query = query.where(Asset.source_type == source_type)

            if sync_config_id:
                sid = sync_config_id if isinstance(sync_config_id, str) else str(sync_config_id)
                query = query.where(
                    Asset.source_metadata["sync"]["config_id"].astext == sid
                )

            if collection_id:
                cid = collection_id if isinstance(collection_id, str) else str(collection_id)
                query = query.where(
                    Asset.source_metadata["scrape"]["collection_id"].astext == cid
                )

            if site_name:
                from app.core.database.models import SharePointSyncConfig
                config_result = await ctx.session.execute(
                    select(SharePointSyncConfig.id)
                    .where(ctx.org_filter(SharePointSyncConfig.organization_id))
                    .where(SharePointSyncConfig.is_active == True)
                    .where(sqla_func.lower(SharePointSyncConfig.site_name) == site_name.lower())
                )
                config_ids = [str(row[0]) for row in config_result.fetchall()]
                if not config_ids:
                    return FunctionResult.success_result(
                        data=[],
                        message=f"No SharePoint sites found matching '{site_name}'",
                        items_processed=0,
                    )
                query = query.where(
                    Asset.source_metadata["sync"]["config_id"].astext.in_(config_ids)
                )

            if folder_path:
                from app.core.storage.storage_path_service import slugify as slugify_component

                clean = folder_path.strip("/")
                slugified = "/".join(slugify_component(p) for p in clean.split("/") if p)
                storage_folder_col = Asset.source_metadata["source"]["storage_folder"].astext

                if folder_match_mode == "contains":
                    query = query.where(storage_folder_col.like(f"%{slugified}%"))
                else:
                    # Default: prefix match
                    query = query.where(storage_folder_col.like(f"{slugified}%"))

            query = query.order_by(Asset.created_at.desc()).limit(limit)

            result = await ctx.session.execute(query)
            assets = result.scalars().all()

            results = []
            for asset in assets:
                sm = asset.source_metadata or {}
                sp_meta = sm.get("sharepoint", {})
                source_meta = sm.get("source", {})

                item = ContentItem(
                    id=str(asset.id),
                    type="asset",
                    display_type="Document",
                    title=source_meta.get("original_filename") or asset.original_filename or "",
                    text=None,
                    fields={
                        "original_filename": asset.original_filename,
                        "content_type": asset.content_type,
                        "source_type": asset.source_type,
                        "source_url": source_meta.get("url"),
                        "site_name": sp_meta.get("site_name"),
                        "status": "ready" if asset.indexed_at else "pending",
                    },
                )
                results.append(item)

            return FunctionResult.success_result(
                data=results,
                message=f"Found {len(results)} assets",
                metadata={
                    "query": "*",
                    "mode": "list_by_filters",
                    "total_found": len(results),
                },
                items_processed=len(results),
            )

        except Exception as e:
            logger.exception(f"List by filters failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Failed to list assets",
            )
