# backend/app/functions/output/bulk_update_metadata.py
"""
Bulk Update Metadata function - Update metadata for multiple assets.

Efficiently updates metadata for a batch of assets.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID
import logging

from sqlalchemy import select

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
)
from ..context import FunctionContext

logger = logging.getLogger("curatore.functions.output.bulk_update_metadata")


class BulkUpdateMetadataFunction(BaseFunction):
    """
    Update metadata for multiple assets in batch.

    Efficiently processes updates in configurable batch sizes.

    Example:
        result = await fn.bulk_update_metadata(ctx,
            updates=[
                {"asset_id": "uuid1", "content": {"tags": ["tag1"]}},
                {"asset_id": "uuid2", "content": {"tags": ["tag2"]}},
            ],
            metadata_type="tags.llm.v1",
        )
    """

    meta = FunctionMeta(
        name="bulk_update_metadata",
        category=FunctionCategory.OUTPUT,
        description="Update metadata for multiple assets in batch",
        parameters=[
            ParameterDoc(
                name="updates",
                type="list[dict]",
                description="List of updates: [{asset_id, content}, ...]",
                required=True,
            ),
            ParameterDoc(
                name="metadata_type",
                type="str",
                description="Type of metadata to update",
                required=True,
            ),
            ParameterDoc(
                name="is_canonical",
                type="bool",
                description="Set as canonical metadata",
                required=False,
                default=False,
            ),
            ParameterDoc(
                name="batch_size",
                type="int",
                description="Number of updates per batch",
                required=False,
                default=50,
            ),
        ],
        returns="dict: Summary of updates",
        tags=["output", "metadata", "bulk"],
        requires_llm=False,
        examples=[
            {
                "description": "Bulk tag update",
                "params": {
                    "updates": [
                        {"asset_id": "uuid1", "content": {"tags": ["a"]}},
                        {"asset_id": "uuid2", "content": {"tags": ["b"]}},
                    ],
                    "metadata_type": "tags.llm.v1",
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Bulk update asset metadata."""
        updates = params["updates"]
        metadata_type = params["metadata_type"]
        is_canonical = params.get("is_canonical", False)
        batch_size = params.get("batch_size", 50)

        from ...database.models import Asset, AssetMetadata

        if not updates:
            return FunctionResult.skipped_result(
                message="No updates provided",
            )

        if ctx.dry_run:
            return FunctionResult.success_result(
                data={"count": len(updates)},
                message=f"Dry run: would update {len(updates)} assets",
            )

        processed = 0
        failed = 0
        errors = []

        try:
            # Get all asset IDs to verify they exist
            asset_ids = [
                UUID(u["asset_id"]) if isinstance(u["asset_id"], str) else u["asset_id"]
                for u in updates
                if "asset_id" in u
            ]

            # Verify assets exist and belong to org
            asset_query = select(Asset.id).where(
                Asset.id.in_(asset_ids),
                Asset.organization_id == ctx.organization_id,
            )
            result = await ctx.session.execute(asset_query)
            valid_ids = {row[0] for row in result.fetchall()}

            # Process in batches
            for i in range(0, len(updates), batch_size):
                batch = updates[i:i + batch_size]

                for update in batch:
                    try:
                        asset_id = UUID(update["asset_id"]) if isinstance(update["asset_id"], str) else update["asset_id"]
                        content = update.get("content", {})

                        if asset_id not in valid_ids:
                            failed += 1
                            errors.append(f"Asset {asset_id} not found")
                            continue

                        # Mark existing canonical as superseded
                        if is_canonical:
                            existing_query = select(AssetMetadata).where(
                                AssetMetadata.asset_id == asset_id,
                                AssetMetadata.metadata_type == metadata_type,
                                AssetMetadata.is_canonical == True,
                                AssetMetadata.status == "active",
                            )
                            existing_result = await ctx.session.execute(existing_query)
                            existing = existing_result.scalar_one_or_none()
                            if existing:
                                existing.status = "superseded"

                        # Create new metadata
                        new_metadata = AssetMetadata(
                            asset_id=asset_id,
                            metadata_type=metadata_type,
                            schema_version="1.0",
                            producer_run_id=ctx.run_id,
                            is_canonical=is_canonical,
                            status="active",
                            metadata_content=content,
                        )
                        ctx.session.add(new_metadata)
                        processed += 1

                    except Exception as e:
                        failed += 1
                        errors.append(str(e))
                        logger.warning(f"Failed to update asset: {e}")

                # Flush batch
                await ctx.session.flush()

            if failed > 0 and processed > 0:
                return FunctionResult.partial_result(
                    data={
                        "processed": processed,
                        "failed": failed,
                        "errors": errors[:10],  # Limit error details
                    },
                    items_processed=processed,
                    items_failed=failed,
                    message=f"Updated {processed} assets, {failed} failed",
                )
            elif failed > 0:
                return FunctionResult.failed_result(
                    error=f"{failed} updates failed",
                    message="All updates failed",
                )
            else:
                return FunctionResult.success_result(
                    data={"processed": processed},
                    message=f"Updated {processed} assets",
                    items_processed=processed,
                )

        except Exception as e:
            logger.exception(f"Bulk update failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Bulk update failed",
                items_processed=processed,
                items_failed=failed,
            )
