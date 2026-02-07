# backend/app/functions/output/update_metadata.py
"""
Update Metadata function - Update asset metadata.

Updates the metadata for a single asset.
"""

from typing import Any, Dict, Optional
from uuid import UUID
import logging

from sqlalchemy import select

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
    OutputFieldDoc,
    OutputSchema,
)
from ..context import FunctionContext

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
        parameters=[
            ParameterDoc(
                name="asset_id",
                type="str",
                description="Asset ID to update",
                required=True,
            ),
            ParameterDoc(
                name="metadata_type",
                type="str",
                description="Type of metadata (e.g., 'tags.llm.v1', 'summary.short.v1')",
                required=True,
                example="tags.llm.v1",
            ),
            ParameterDoc(
                name="content",
                type="dict",
                description="Metadata content",
                required=True,
            ),
            ParameterDoc(
                name="is_canonical",
                type="bool",
                description="Set as canonical metadata for this type",
                required=False,
                default=False,
            ),
            ParameterDoc(
                name="schema_version",
                type="str",
                description="Schema version for this metadata type",
                required=False,
                default="1.0",
            ),
        ],
        returns="dict: Updated metadata record",
        output_schema=OutputSchema(
            type="dict",
            description="Result of metadata update operation",
            fields=[
                OutputFieldDoc(name="asset_id", type="str",
                              description="UUID of the updated asset"),
                OutputFieldDoc(name="metadata_type", type="str",
                              description="Type of metadata that was updated",
                              example="tags.llm.v1"),
                OutputFieldDoc(name="is_canonical", type="bool",
                              description="Whether this is the canonical metadata for this type"),
                OutputFieldDoc(name="content", type="dict",
                              description="The metadata content that was saved"),
            ],
        ),
        tags=["output", "metadata", "assets"],
        requires_llm=False,
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
        is_canonical = params.get("is_canonical", False)
        schema_version = params.get("schema_version", "1.0")

        from ...database.models import Asset, AssetMetadata

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

            # Check for existing metadata of this type
            existing_query = select(AssetMetadata).where(
                AssetMetadata.asset_id == asset_uuid,
                AssetMetadata.metadata_type == metadata_type,
                AssetMetadata.is_canonical == True,
                AssetMetadata.status == "active",
            )
            existing_result = await ctx.session.execute(existing_query)
            existing = existing_result.scalar_one_or_none()

            if existing and is_canonical:
                # Mark existing as superseded
                existing.status = "superseded"

            # Create new metadata record
            new_metadata = AssetMetadata(
                asset_id=asset_uuid,
                metadata_type=metadata_type,
                schema_version=schema_version,
                producer_run_id=ctx.run_id,
                is_canonical=is_canonical,
                status="active",
                metadata_content=content,
            )
            ctx.session.add(new_metadata)

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
