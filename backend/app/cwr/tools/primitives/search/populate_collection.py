"""
Populate Collection function — add assets to a search collection from the core index.

Delegates to the existing collection_population_service.populate_from_index()
which copies chunks + embeddings from search_chunks into collection_chunks.
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
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.search.populate_collection")


class PopulateCollectionFunction(BaseFunction):
    """
    Populate a search collection with assets from the core index.

    Copies existing chunks and embeddings from the main search index into
    the specified collection's isolated vector store. This is a fast operation
    that reuses already-computed embeddings.

    Example:
        result = await fn.populate_collection(ctx,
            collection="federal-procurement-docs",
            asset_ids=["uuid1", "uuid2"],
        )
    """

    meta = FunctionMeta(
        name="populate_collection",
        category=FunctionCategory.SEARCH,
        description=(
            "Populate a search collection with assets from the core index. "
            "Copies existing chunks and embeddings into the collection's "
            "isolated vector store. Provide the collection slug or UUID "
            "and a list of asset IDs to add."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "description": (
                        "Collection slug or UUID. Use discover_data_sources("
                        "source_type='search_collection') to find available collections."
                    ),
                },
                "asset_ids": {
                    "type": "array",
                    "items": {"type": "string", "format": "uuid"},
                    "description": "List of asset UUIDs to add to the collection.",
                    "minItems": 1,
                },
            },
            "required": ["collection", "asset_ids"],
        },
        output_schema={
            "type": "object",
            "description": "Population result summary",
            "properties": {
                "collection_id": {"type": "string", "description": "Collection UUID"},
                "collection_name": {"type": "string", "description": "Collection display name"},
                "added": {"type": "integer", "description": "Number of chunks added"},
                "skipped": {"type": "integer", "description": "Number of assets skipped (no indexed chunks)"},
                "total": {"type": "integer", "description": "Total chunks in collection after population"},
            },
        },
        tags=["search", "collections", "populate", "index"],
        requires_llm=False,
        side_effects=True,
        is_primitive=True,
        payload_profile="summary",
        examples=[
            {
                "description": "Populate a collection by slug",
                "params": {
                    "collection": "federal-procurement-docs",
                    "asset_ids": [
                        "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                        "b2c3d4e5-f6a7-8901-bcde-f12345678901",
                    ],
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute collection population from core index."""
        collection_ref = params["collection"]
        raw_ids = params["asset_ids"]

        if not raw_ids:
            return FunctionResult.failed_result(
                error="Empty asset_ids",
                message="At least one asset ID is required.",
            )

        # Parse asset UUIDs
        try:
            asset_uuids = [UUID(aid) for aid in raw_ids]
        except (ValueError, AttributeError) as e:
            return FunctionResult.failed_result(
                error=f"Invalid asset ID: {e}",
                message="All asset_ids must be valid UUIDs.",
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
                    organization_id=ctx.requires_org_id,
                )
            except (ValueError, AttributeError):
                collection = await collection_service.get_collection_by_slug(
                    session=ctx.session,
                    organization_id=ctx.requires_org_id,
                    slug=collection_ref,
                )

            if not collection:
                return FunctionResult.failed_result(
                    error=f"Collection '{collection_ref}' not found",
                    message=(
                        f"No collection found with slug or ID '{collection_ref}'. "
                        "Use discover_data_sources(source_type='search_collection') "
                        "to see available collections."
                    ),
                )

            if not collection.is_active:
                return FunctionResult.failed_result(
                    error=f"Collection '{collection.name}' is inactive",
                    message="This collection is currently inactive.",
                )

            # Dry-run: return preview without writing
            if ctx.dry_run:
                return FunctionResult.success_result(
                    data={
                        "collection_id": str(collection.id),
                        "collection_name": collection.name,
                        "added": 0,
                        "skipped": 0,
                        "total": collection.item_count or 0,
                    },
                    message=(
                        f"[DRY RUN] Would populate collection '{collection.name}' "
                        f"with {len(asset_uuids)} asset(s)."
                    ),
                )

            # Populate from core index
            from app.core.search.collection_population_service import (
                collection_population_service,
            )

            result = await collection_population_service.populate_from_index(
                session=ctx.session,
                collection_id=collection.id,
                organization_id=ctx.requires_org_id,
                asset_ids=asset_uuids,
            )

            data = {
                "collection_id": str(collection.id),
                "collection_name": collection.name,
                "added": result.added,
                "skipped": result.skipped,
                "total": result.total,
            }

            return FunctionResult.success_result(
                data=data,
                message=(
                    f"Populated collection '{collection.name}': "
                    f"{result.added} chunks added, {result.skipped} assets skipped, "
                    f"{result.total} total chunks."
                ),
                metadata={
                    "collection_id": str(collection.id),
                    "collection_slug": collection.slug,
                    "asset_count": len(asset_uuids),
                },
                items_processed=result.added,
            )

        except Exception as e:
            logger.exception(f"Collection population failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Collection population failed.",
            )
