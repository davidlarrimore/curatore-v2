"""
sp_get_site — Get comprehensive SharePoint site metadata via Microsoft Graph API.

Supports two input modes:
  - url: Any SharePoint URL (site is extracted automatically)
  - sync_config_id: Uses the config's folder_url
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
)
from ...context import FunctionContext
from ...content import ContentItem

logger = logging.getLogger("curatore.functions.sharepoint.sp_get_site")


class SpGetSiteFunction(BaseFunction):
    """
    Get comprehensive SharePoint site metadata.

    Example:
        result = await fn.sp_get_site(ctx,
            url="https://company.sharepoint.com/sites/IT/Shared Documents",
        )
    """

    meta = FunctionMeta(
        name="sp_get_site",
        category=FunctionCategory.DATA,
        description="Get comprehensive SharePoint site metadata from Microsoft Graph API. Returns site display name, URL, description, and timestamps.",
        input_schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Any SharePoint URL — site is extracted automatically",
                },
                "sync_config_id": {
                    "type": "string",
                    "description": "Sync config UUID — uses its folder_url",
                },
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "description": "SharePoint site metadata as a ContentItem",
            "properties": {
                "display_name": {
                    "type": "string",
                    "description": "Site display name",
                    "examples": ["IT Department"],
                },
                "name": {
                    "type": "string",
                    "description": "Site URL segment name",
                    "examples": ["IT"],
                },
                "web_url": {
                    "type": "string",
                    "description": "Full site URL",
                },
                "site_id": {
                    "type": "string",
                    "description": "Microsoft Graph site ID",
                },
                "description": {
                    "type": "string",
                    "description": "Site description",
                    "nullable": True,
                },
                "created_at": {
                    "type": "string",
                    "description": "Site creation timestamp",
                    "nullable": True,
                },
                "last_modified_at": {
                    "type": "string",
                    "description": "Site last modified timestamp",
                    "nullable": True,
                },
                "hostname": {
                    "type": "string",
                    "description": "SharePoint hostname",
                },
                "site_path": {
                    "type": "string",
                    "description": "Site path segment",
                    "examples": ["/sites/IT"],
                },
            },
        },
        tags=["data", "sharepoint", "graph-api", "site"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="full",
        examples=[
            {
                "description": "Get site info from URL",
                "params": {"url": "https://company.sharepoint.com/sites/IT/Shared Documents"},
            },
            {
                "description": "Get site info from sync config",
                "params": {"sync_config_id": "uuid"},
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Get SharePoint site metadata."""
        url = params.get("url")
        sync_config_id = params.get("sync_config_id")

        if not url and not sync_config_id:
            return FunctionResult.failed_result(
                error="Either 'url' or 'sync_config_id' is required",
            )

        try:
            # Resolve URL from sync config if needed
            if not url and sync_config_id:
                from app.core.database.models import SharePointSyncConfig
                config_uuid = UUID(sync_config_id) if isinstance(sync_config_id, str) else sync_config_id
                result = await ctx.session.execute(
                    select(SharePointSyncConfig).where(
                        SharePointSyncConfig.id == config_uuid,
                        SharePointSyncConfig.organization_id == ctx.organization_id,
                    )
                )
                config = result.scalar_one_or_none()
                if not config:
                    return FunctionResult.failed_result(
                        error=f"Sync config {sync_config_id} not found",
                    )
                url = config.folder_url

            from app.connectors.sharepoint.sharepoint_service import get_site_metadata

            meta = await get_site_metadata(
                folder_url=url,
                organization_id=ctx.organization_id,
                session=ctx.session,
            )

            if not meta:
                return FunctionResult.failed_result(
                    error=f"Could not retrieve site metadata for {url}",
                )

            item = ContentItem(
                id=meta.get("site_id") or "",
                type="sharepoint_site",
                display_type="SharePoint Site",
                title=meta.get("display_name") or meta.get("name") or "",
                text=meta.get("description"),
                fields={
                    "display_name": meta.get("display_name"),
                    "name": meta.get("name"),
                    "web_url": meta.get("web_url"),
                    "site_id": meta.get("site_id"),
                    "description": meta.get("description"),
                    "created_at": meta.get("created_at"),
                    "last_modified_at": meta.get("last_modified_at"),
                    "hostname": meta.get("hostname"),
                    "site_path": meta.get("site_path"),
                },
            )

            return FunctionResult.success_result(
                data=item,
                message=f"Retrieved site metadata: {item.title}",
                items_processed=1,
            )

        except Exception as e:
            logger.exception(f"Failed to get site metadata: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Failed to get SharePoint site metadata",
            )
