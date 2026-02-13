"""
Search Collection function — search within a specific named collection.

Provides collection-scoped search using the existing pg_search_service,
filtering results to only chunks belonging to the specified collection.
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

logger = logging.getLogger("curatore.functions.search.search_collection")


class SearchCollectionFunction(BaseFunction):
    """
    Search within a specific named search collection.

    Runs hybrid search (keyword + semantic) scoped to a single collection.
    Use discover_data_sources(source_type='search_collection') first to discover available collections and their
    slugs/IDs.

    Example:
        result = await fn.search_collection(ctx,
            collection="federal-procurement-docs",
            query="cybersecurity requirements",
        )
    """

    meta = FunctionMeta(
        name="search_collection",
        category=FunctionCategory.SEARCH,
        description=(
            "Search within a specific named collection. Runs hybrid keyword + semantic "
            "search scoped to one collection. Use discover_data_sources(source_type='search_collection') to discover available "
            "collections first. Provide the collection slug or ID."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "description": (
                        "Collection slug or UUID. Use the slug from discover_data_sources(source_type='search_collection') "
                        "for convenience, or the full UUID."
                    ),
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Search query (2-4 key terms work best). "
                        "Use '*' to list all items in the collection."
                    ),
                },
                "search_mode": {
                    "type": "string",
                    "description": "Search mode",
                    "default": "hybrid",
                    "enum": ["hybrid", "keyword", "semantic"],
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 20,
                },
            },
            "required": ["collection", "query"],
        },
        output_schema={
            "type": "array",
            "description": "List of matching documents within the collection",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Asset UUID"},
                    "title": {"type": "string", "description": "Document title"},
                    "content_type": {"type": "string", "description": "MIME type"},
                    "source_type": {"type": "string", "description": "Source type"},
                    "score": {"type": "number", "description": "Relevance score (0-1)"},
                    "snippet": {"type": "string", "description": "Text excerpt", "nullable": True},
                },
            },
        },
        tags=["search", "collections", "hybrid", "content"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="thin",
        examples=[
            {
                "description": "Search a collection by slug",
                "params": {
                    "collection": "federal-procurement-docs",
                    "query": "cybersecurity requirements",
                    "limit": 10,
                },
            },
            {
                "description": "List all items in a collection",
                "params": {
                    "collection": "sam-gov-notices",
                    "query": "*",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute collection-scoped search."""
        collection_ref = params["collection"]
        query = params["query"]
        search_mode = params.get("search_mode", "hybrid")
        limit = min(params.get("limit", 20), 100)

        if not query.strip():
            return FunctionResult.failed_result(
                error="Empty query",
                message="Search query cannot be empty",
            )

        try:
            from app.core.search.collection_service import collection_service

            # Resolve collection by slug or UUID
            collection = None
            try:
                collection_uuid = UUID(collection_ref)
                collection = await collection_service.get_collection(
                    session=ctx.session,
                    collection_id=collection_uuid,
                    organization_id=ctx.organization_id,
                )
            except (ValueError, AttributeError):
                # Not a UUID, try as slug
                collection = await collection_service.get_collection_by_slug(
                    session=ctx.session,
                    organization_id=ctx.organization_id,
                    slug=collection_ref,
                )

            if not collection:
                return FunctionResult.failed_result(
                    error=f"Collection '{collection_ref}' not found",
                    message=(
                        f"No collection found with slug or ID '{collection_ref}'. "
                        "Use discover_data_sources(source_type='search_collection') to see available collections."
                    ),
                )

            if not collection.is_active:
                return FunctionResult.failed_result(
                    error=f"Collection '{collection.name}' is inactive",
                    message="This collection is currently inactive.",
                )

            # Execute search via the collection's store adapter
            from app.core.search.collection_stores.pgvector_store import (
                PgVectorCollectionStore,
            )
            from app.core.search.embedding_service import embedding_service

            store = PgVectorCollectionStore(ctx.session)

            # For wildcard queries, use keyword mode with empty query
            effective_query = query if query.strip() != "*" else ""
            effective_mode = search_mode if query.strip() != "*" else "keyword"

            # Get embedding for semantic/hybrid modes
            query_embedding = []
            if effective_mode in ("semantic", "hybrid") and effective_query:
                query_embedding = await embedding_service.get_embedding(
                    effective_query
                )

            chunk_results = await store.search(
                collection_id=collection.id,
                query=effective_query,
                query_embedding=query_embedding,
                search_mode=effective_mode,
                limit=limit,
            )

            results = []
            for cr in chunk_results:
                snippet = cr.highlight if cr.highlight else None

                item = ContentItem(
                    id=cr.source_asset_id or cr.id,
                    type="asset",
                    display_type="Document",
                    title=cr.title or "",
                    text=None,
                    fields={
                        "content_type": cr.metadata.get("source_content_type") if cr.metadata else None,
                        "source_type": cr.metadata.get("source_source_type") if cr.metadata else None,
                    },
                    metadata={
                        "score": cr.score,
                        "snippet": snippet,
                        "search_mode": search_mode,
                        "collection_slug": collection.slug,
                        "collection_name": collection.name,
                    },
                )
                results.append(item)

            return FunctionResult.success_result(
                data=results,
                message=f"Found {len(results)} results in collection '{collection.name}'",
                metadata={
                    "collection_id": str(collection.id),
                    "collection_slug": collection.slug,
                    "collection_name": collection.name,
                    "query": query,
                    "search_mode": search_mode,
                    "total_found": len(results),
                },
                items_processed=len(results),
            )

        except Exception as e:
            logger.exception(f"Collection search failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Collection search failed",
            )
