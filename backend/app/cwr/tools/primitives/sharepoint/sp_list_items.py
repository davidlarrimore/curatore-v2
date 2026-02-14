"""
sp_list_items — Browse SharePoint folder contents via Microsoft Graph API.

Supports two input modes:
  - folder_url: Direct SharePoint folder URL
  - sync_config_id: Uses the config's folder_url
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
from ...content import ContentItem
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.sharepoint.sp_list_items")


class SpListItemsFunction(BaseFunction):
    """
    Browse SharePoint folder contents.

    Example:
        result = await fn.sp_list_items(ctx,
            sync_config_id="uuid",
            recursive=True,
            file_extensions=["pdf", "docx"],
            limit=50,
        )
    """

    meta = FunctionMeta(
        name="sp_list_items",
        category=FunctionCategory.DATA,
        description="Browse SharePoint folder contents via Microsoft Graph API. Returns file/folder items with comprehensive metadata.",
        input_schema={
            "type": "object",
            "properties": {
                "folder_url": {
                    "type": "string",
                    "description": "SharePoint folder URL",
                },
                "sync_config_id": {
                    "type": "string",
                    "description": "Sync config UUID — uses its folder_url",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Recurse into subfolders",
                    "default": False,
                },
                "include_folders": {
                    "type": "boolean",
                    "description": "Include folder items in results",
                    "default": False,
                },
                "file_extensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by extension (e.g. ['pdf', 'docx'])",
                    "default": None,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum items to return (capped at 500)",
                    "default": 100,
                },
            },
            "required": [],
        },
        output_schema={
            "type": "array",
            "description": "List of SharePoint items as ContentItem objects",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "File or folder name",
                    },
                    "item_type": {
                        "type": "string",
                        "description": "'file' or 'folder'",
                    },
                    "size": {
                        "type": "integer",
                        "description": "File size in bytes",
                        "nullable": True,
                    },
                    "extension": {
                        "type": "string",
                        "description": "File extension",
                        "nullable": True,
                    },
                    "folder": {
                        "type": "string",
                        "description": "Parent folder path",
                    },
                    "web_url": {
                        "type": "string",
                        "description": "Direct SharePoint link",
                    },
                    "drive_id": {
                        "type": "string",
                        "description": "Graph drive ID",
                    },
                    "mime": {
                        "type": "string",
                        "description": "MIME type",
                        "nullable": True,
                    },
                    "created": {
                        "type": "string",
                        "description": "Created timestamp",
                        "nullable": True,
                    },
                    "modified": {
                        "type": "string",
                        "description": "Modified timestamp",
                        "nullable": True,
                    },
                    "created_by": {
                        "type": "string",
                        "description": "Creator display name",
                        "nullable": True,
                    },
                    "last_modified_by": {
                        "type": "string",
                        "description": "Modifier display name",
                        "nullable": True,
                    },
                    "etag": {
                        "type": "string",
                        "description": "Change detection tag",
                        "nullable": True,
                    },
                },
            },
        },
        tags=["data", "sharepoint", "graph-api", "browse"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="full",
        required_data_sources=["sharepoint"],
        examples=[
            {
                "description": "List files in sync config folder",
                "params": {"sync_config_id": "uuid", "limit": 50},
            },
            {
                "description": "List PDFs recursively",
                "params": {
                    "folder_url": "https://company.sharepoint.com/sites/IT/Shared Documents",
                    "recursive": True,
                    "file_extensions": ["pdf"],
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Browse SharePoint folder contents."""
        folder_url = params.get("folder_url")
        sync_config_id = params.get("sync_config_id")
        recursive = params.get("recursive", False)
        include_folders = params.get("include_folders", False)
        file_extensions = params.get("file_extensions")
        limit = min(params.get("limit", 100), 500)

        if not folder_url and not sync_config_id:
            return FunctionResult.failed_result(
                error="Either 'folder_url' or 'sync_config_id' is required",
            )

        try:
            # Resolve folder_url from sync config if needed
            if not folder_url and sync_config_id:
                from app.core.database.models import SharePointSyncConfig
                config_uuid = UUID(sync_config_id) if isinstance(sync_config_id, str) else sync_config_id
                result = await ctx.session.execute(
                    select(SharePointSyncConfig).where(
                        SharePointSyncConfig.id == config_uuid,
                        SharePointSyncConfig.organization_id == ctx.requires_org_id,
                    )
                )
                config = result.scalar_one_or_none()
                if not config:
                    return FunctionResult.failed_result(
                        error=f"Sync config {sync_config_id} not found",
                    )
                folder_url = config.folder_url

            from app.connectors.sharepoint.sharepoint_service import sharepoint_inventory

            inventory = await sharepoint_inventory(
                folder_url=folder_url,
                recursive=recursive,
                include_folders=include_folders,
                page_size=200,
                max_items=limit,
                organization_id=ctx.requires_org_id,
                session=ctx.session,
            )

            raw_items = inventory.get("items", [])
            folder_info = inventory.get("folder", {})

            # Apply file_extensions filter if provided
            if file_extensions:
                ext_set = {e.lower().lstrip(".") for e in file_extensions}
                raw_items = [
                    item for item in raw_items
                    if item.get("type") == "folder" or item.get("extension", "").lower() in ext_set
                ]

            # Convert to ContentItems
            items = []
            for item in raw_items:
                is_folder = item.get("type") == "folder"
                content_item = ContentItem(
                    id=item.get("id", ""),
                    type="sharepoint_item",
                    display_type="SharePoint Folder" if is_folder else "SharePoint File",
                    title=item.get("name", ""),
                    fields={
                        "name": item.get("name"),
                        "item_type": item.get("type"),
                        "size": item.get("size"),
                        "extension": item.get("extension"),
                        "folder": item.get("folder"),
                        "web_url": item.get("web_url"),
                        "drive_id": item.get("drive_id"),
                        "mime": item.get("mime"),
                        "created": item.get("created"),
                        "modified": item.get("modified"),
                        "created_by": item.get("created_by"),
                        "created_by_email": item.get("created_by_email"),
                        "last_modified_by": item.get("last_modified_by"),
                        "last_modified_by_email": item.get("last_modified_by_email"),
                        "etag": item.get("etag"),
                        "quick_xor_hash": item.get("quick_xor_hash"),
                        "description": item.get("description"),
                    },
                )
                items.append(content_item)

            return FunctionResult.success_result(
                data=items,
                message=f"Found {len(items)} items in SharePoint folder",
                metadata={"folder": folder_info},
                items_processed=len(items),
            )

        except Exception as e:
            logger.exception(f"Failed to list SharePoint items: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Failed to list SharePoint folder contents",
            )
