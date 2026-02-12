# backend/app/functions/output/update_metadata.py
"""
Update Metadata function - Update asset metadata.

Updates the metadata for a single asset.
"""

import logging
from uuid import UUID

from sqlalchemy import select

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.output.update_metadata")


class UpdateMetadataFunction(BaseFunction):
    """
    Update metadata for a single asset.

    Creates or updates an AssetMetadata record.

    Example:
        result = await fn.update_metadata(ctx,
            asset_id="uuid",
            metadata_type="tags.llm.v1",
            content={"tags": ["contract", "federal"]},
        )
    """

    meta = FunctionMeta(
        name="update_metadata",
        category=FunctionCategory.OUTPUT,
        description="Update metadata for a single asset",
        input_schema={
            "type": "object",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "Asset ID to update",
                },
                "metadata_type": {
                    "type": "string",
                    "description": "Type of metadata (e.g., 'tags.llm.v1', 'summary.short.v1')",
                    "examples": ["tags.llm.v1"],
                },
                "content": {
                    "type": "object",
                    "description": "Metadata content",
                },
                "is_canonical": {
                    "type": "boolean",
                    "description": "Set as canonical metadata for this type",
                    "default": True,
                },
                "schema_version": {
                    "type": "string",
                    "description": "Schema version for this metadata type",
                    "default": "1.0",
                },
            },
            "required": ["asset_id", "metadata_type", "content"],
        },
        output_schema={
            "type": "object",
            "description": "Result of metadata update operation",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "UUID of the updated asset",
                },
                "metadata_type": {
                    "type": "string",
                    "description": "Type of metadata that was updated",
                    "examples": ["tags.llm.v1"],
                },
                "is_canonical": {
                    "type": "boolean",
                    "description": "Whether this is the canonical metadata for this type",
                },
                "content": {
                    "type": "object",
                    "description": "The metadata content that was saved",
                },
            },
        },
        tags=["output", "metadata", "assets"],
        requires_llm=False,
        side_effects=True,
        is_primitive=True,
        payload_profile="full",
        examples=[
            {
                "description": "Add tags to asset",
                "params": {
                    "asset_id": "uuid",
                    "metadata_type": "tags.llm.v1",
                    "content": {"tags": ["important", "reviewed"]},
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Update asset metadata."""
        asset_id = params["asset_id"]
        metadata_type = params["metadata_type"]
        content = params["content"]
        is_canonical = params.get("is_canonical", True)
        schema_version = params.get("schema_version", "1.0")

        from app.core.database.models import Asset, AssetMetadata

        try:
            # Convert to UUID
            asset_uuid = UUID(asset_id) if isinstance(asset_id, str) else asset_id

            # Verify asset exists and belongs to org
            asset_query = select(Asset).where(
                Asset.id == asset_uuid,
                Asset.organization_id == ctx.organization_id,
            )
            result = await ctx.session.execute(asset_query)
            asset = result.scalar_one_or_none()

            if not asset:
                return FunctionResult.failed_result(
                    error="Asset not found",
                    message=f"Asset {asset_id} not found or not accessible",
                )

            if ctx.dry_run:
                return FunctionResult.success_result(
                    data={"asset_id": str(asset_uuid), "metadata_type": metadata_type},
                    message="Dry run: would update metadata",
                )

            # Upsert: find existing canonical metadata of this type
            existing_query = select(AssetMetadata).where(
                AssetMetadata.asset_id == asset_uuid,
                AssetMetadata.metadata_type == metadata_type,
                AssetMetadata.is_canonical == True,
            )
            existing_result = await ctx.session.execute(existing_query)
            existing = existing_result.scalar_one_or_none()

            if existing:
                # Merge and update in place
                merged_content = {**(existing.metadata_content or {}), **content}
                existing.metadata_content = merged_content
                existing.producer_run_id = ctx.run_id
                existing.schema_version = schema_version
            else:
                # Create new metadata record
                new_metadata = AssetMetadata(
                    asset_id=asset_uuid,
                    metadata_type=metadata_type,
                    schema_version=schema_version,
                    producer_run_id=ctx.run_id,
                    is_canonical=is_canonical,
                    metadata_content=content,
                )
                ctx.session.add(new_metadata)

            # Propagate canonical metadata to search_chunks for searchability
            if is_canonical:
                from app.core.search.pg_index_service import pg_index_service
                await ctx.session.flush()
                await pg_index_service.propagate_asset_metadata(ctx.session, asset_uuid)

            return FunctionResult.success_result(
                data={
                    "asset_id": str(asset_uuid),
                    "metadata_type": metadata_type,
                    "is_canonical": is_canonical,
                    "content": content,
                },
                message=f"Updated {metadata_type} metadata for asset",
                items_processed=1,
            )

        except Exception as e:
            logger.exception(f"Failed to update metadata: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Failed to update metadata",
            )
