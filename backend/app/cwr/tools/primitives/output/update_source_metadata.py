"""
update_source_metadata — Update Asset.source_metadata (generic, any asset type).

Updates a specific namespace within source_metadata using shallow merge,
then optionally propagates to search_chunks.metadata for searchability.

This is NOT SharePoint-specific — it works for any asset type and namespace.
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.output.update_source_metadata")


class UpdateSourceMetadataFunction(BaseFunction):
    """
    Update Asset.source_metadata for a specific namespace.

    Performs a shallow merge — provided keys overwrite existing ones,
    unprovided keys are preserved.

    Example:
        result = await fn.update_source_metadata(ctx,
            asset_id="uuid",
            namespace="sharepoint",
            fields={"site_name": "IT Department"},
        )
    """

    meta = FunctionMeta(
        name="update_source_metadata",
        category=FunctionCategory.OUTPUT,
        description="Update Asset.source_metadata for a specific namespace with shallow merge, then propagate to search index.",
        input_schema={
            "type": "object",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "Asset UUID",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace to update (e.g. 'sharepoint', 'sam', 'salesforce', 'forecast', 'source', 'file')",
                },
                "fields": {
                    "type": "object",
                    "description": "Fields to merge into namespace (shallow merge — provided keys overwrite, unprovided keys preserved)",
                },
                "propagate_to_search": {
                    "type": "boolean",
                    "description": "Propagate changes to search_chunks.metadata",
                    "default": True,
                },
            },
            "required": ["asset_id", "namespace", "fields"],
        },
        output_schema={
            "type": "object",
            "description": "Result of source metadata update operation",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "UUID of the updated asset",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace that was updated",
                },
                "fields_updated": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of field keys that were updated",
                },
                "propagated": {
                    "type": "boolean",
                    "description": "Whether changes were propagated to search index",
                },
            },
        },
        tags=["output", "metadata", "source-metadata", "assets"],
        requires_llm=False,
        side_effects=True,
        is_primitive=True,
        payload_profile="full",
        examples=[
            {
                "description": "Update SharePoint site name on an asset",
                "params": {
                    "asset_id": "uuid",
                    "namespace": "sharepoint",
                    "fields": {"site_name": "IT Department"},
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Update Asset.source_metadata."""
        asset_id = params["asset_id"]
        namespace = params["namespace"]
        fields = params["fields"]
        propagate_to_search = params.get("propagate_to_search", True)

        from app.core.database.models import Asset

        try:
            asset_uuid = UUID(asset_id) if isinstance(asset_id, str) else asset_id

            # Verify asset exists and belongs to org
            result = await ctx.session.execute(
                select(Asset).where(
                    Asset.id == asset_uuid,
                    ctx.org_filter(Asset.organization_id),
                )
            )
            asset = result.scalar_one_or_none()

            if not asset:
                return FunctionResult.failed_result(
                    error="Asset not found",
                    message=f"Asset {asset_id} not found or not accessible",
                )

            if ctx.dry_run:
                return FunctionResult.success_result(
                    data={
                        "asset_id": str(asset_uuid),
                        "namespace": namespace,
                        "fields_updated": list(fields.keys()),
                        "propagated": False,
                    },
                    message=f"Dry run: would update {namespace} with {len(fields)} fields",
                )

            # Deep merge: preserve existing namespace fields, overwrite with provided ones
            source_metadata = dict(asset.source_metadata or {})
            existing_ns = dict(source_metadata.get(namespace) or {})
            existing_ns.update(fields)
            source_metadata[namespace] = existing_ns
            asset.source_metadata = source_metadata
            flag_modified(asset, "source_metadata")
            await ctx.session.flush()

            # Propagate to search_chunks.metadata
            propagated = False
            if propagate_to_search:
                from app.core.search.pg_index_service import pg_index_service
                propagated = await pg_index_service.propagate_source_metadata(
                    ctx.session, asset_uuid
                )

            return FunctionResult.success_result(
                data={
                    "asset_id": str(asset_uuid),
                    "namespace": namespace,
                    "fields_updated": list(fields.keys()),
                    "propagated": propagated,
                },
                message=f"Updated {namespace}.{', '.join(fields.keys())} for asset",
                items_processed=1,
            )

        except Exception as e:
            logger.exception(f"Failed to update source metadata: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Failed to update source metadata",
            )
