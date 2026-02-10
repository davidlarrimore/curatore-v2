"""
sp_get_item — Get metadata for a single SharePoint drive item via Microsoft Graph API.

Supports two input modes:
  - drive_id + item_id: Direct Graph API IDs
  - asset_id: Looks up drive_id/item_id from Asset.source_metadata.sharepoint
"""

from typing import Any, Dict, Optional
from uuid import UUID
import logging

from sqlalchemy import select

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

logger = logging.getLogger("curatore.functions.sharepoint.sp_get_item")


class SpGetItemFunction(BaseFunction):
    """
    Get metadata for a single SharePoint drive item.

    Example:
        result = await fn.sp_get_item(ctx,
            asset_id="uuid",  # Refreshes SP metadata for a local asset
        )
    """

    meta = FunctionMeta(
        name="sp_get_item",
        category=FunctionCategory.DATA,
        description="Get metadata for a single SharePoint drive item from Microsoft Graph API. Supports lookup by Graph IDs or Curatore asset_id.",
        parameters=[
            ParameterDoc(
                name="drive_id",
                type="str",
                description="Microsoft Graph drive ID",
                required=False,
            ),
            ParameterDoc(
                name="item_id",
                type="str",
                description="Microsoft Graph item ID",
                required=False,
            ),
            ParameterDoc(
                name="asset_id",
                type="str",
                description="Curatore asset UUID — looks up drive_id/item_id from source_metadata.sharepoint",
                required=False,
            ),
        ],
        returns="ContentItem: SharePoint item metadata",
        output_schema=OutputSchema(
            type="ContentItem",
            description="SharePoint item metadata as a ContentItem",
            fields=[
                OutputFieldDoc(name="name", type="str", description="File or folder name"),
                OutputFieldDoc(name="item_type", type="str", description="'file' or 'folder'"),
                OutputFieldDoc(name="size", type="int", description="File size in bytes", nullable=True),
                OutputFieldDoc(name="extension", type="str", description="File extension", nullable=True),
                OutputFieldDoc(name="folder", type="str", description="Parent folder path"),
                OutputFieldDoc(name="web_url", type="str", description="Direct SharePoint link"),
                OutputFieldDoc(name="drive_id", type="str", description="Graph drive ID"),
                OutputFieldDoc(name="mime", type="str", description="MIME type", nullable=True),
                OutputFieldDoc(name="created", type="str", description="Created timestamp", nullable=True),
                OutputFieldDoc(name="modified", type="str", description="Modified timestamp", nullable=True),
                OutputFieldDoc(name="created_by", type="str", description="Creator display name", nullable=True),
                OutputFieldDoc(name="last_modified_by", type="str", description="Modifier display name", nullable=True),
                OutputFieldDoc(name="etag", type="str", description="Change detection tag", nullable=True),
            ],
        ),
        tags=["data", "sharepoint", "graph-api", "item"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="full",
        examples=[
            {
                "description": "Get item by Graph IDs",
                "params": {"drive_id": "drive-id", "item_id": "item-id"},
            },
            {
                "description": "Refresh SP metadata for a local asset",
                "params": {"asset_id": "uuid"},
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Get single SharePoint item metadata."""
        drive_id = params.get("drive_id")
        item_id = params.get("item_id")
        asset_id = params.get("asset_id")

        # Validate input modes
        has_graph_ids = drive_id and item_id
        has_asset_id = bool(asset_id)

        if not has_graph_ids and not has_asset_id:
            return FunctionResult.failed_result(
                error="Either ('drive_id' + 'item_id') or 'asset_id' is required",
            )

        try:
            # Resolve Graph IDs from asset if needed
            if not has_graph_ids and has_asset_id:
                from app.core.database.models import Asset
                asset_uuid = UUID(asset_id) if isinstance(asset_id, str) else asset_id
                result = await ctx.session.execute(
                    select(Asset).where(
                        Asset.id == asset_uuid,
                        Asset.organization_id == ctx.organization_id,
                    )
                )
                asset = result.scalar_one_or_none()
                if not asset:
                    return FunctionResult.failed_result(
                        error=f"Asset {asset_id} not found",
                    )

                sp_meta = (asset.source_metadata or {}).get("sharepoint", {})
                drive_id = sp_meta.get("drive_id")
                item_id = sp_meta.get("item_id")

                if not drive_id or not item_id:
                    return FunctionResult.failed_result(
                        error=f"Asset {asset_id} has no SharePoint drive_id/item_id in source_metadata",
                    )

            from app.connectors.sharepoint.sharepoint_service import get_item_metadata

            item_data = await get_item_metadata(
                drive_id=drive_id,
                item_id=item_id,
                organization_id=ctx.organization_id,
                session=ctx.session,
            )

            if not item_data:
                return FunctionResult.failed_result(
                    error=f"Could not retrieve item metadata for drive={drive_id} item={item_id}",
                )

            is_folder = item_data.get("type") == "folder"
            content_item = ContentItem(
                id=item_data.get("id", ""),
                type="sharepoint_item",
                display_type="SharePoint Folder" if is_folder else "SharePoint File",
                title=item_data.get("name", ""),
                fields={
                    "name": item_data.get("name"),
                    "item_type": item_data.get("type"),
                    "size": item_data.get("size"),
                    "extension": item_data.get("extension"),
                    "folder": item_data.get("folder"),
                    "web_url": item_data.get("web_url"),
                    "drive_id": item_data.get("drive_id"),
                    "mime": item_data.get("mime"),
                    "created": item_data.get("created"),
                    "modified": item_data.get("modified"),
                    "created_by": item_data.get("created_by"),
                    "created_by_email": item_data.get("created_by_email"),
                    "last_modified_by": item_data.get("last_modified_by"),
                    "last_modified_by_email": item_data.get("last_modified_by_email"),
                    "etag": item_data.get("etag"),
                    "quick_xor_hash": item_data.get("quick_xor_hash"),
                    "description": item_data.get("description"),
                },
            )

            return FunctionResult.success_result(
                data=content_item,
                message=f"Retrieved item metadata: {content_item.title}",
                items_processed=1,
            )

        except Exception as e:
            logger.exception(f"Failed to get SharePoint item metadata: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Failed to get SharePoint item metadata",
            )
