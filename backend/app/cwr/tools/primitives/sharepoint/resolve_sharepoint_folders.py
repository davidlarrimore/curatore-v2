"""
resolve_sharepoint_folders — Resolve human-readable folder names to valid paths.

Queries the database for synced SharePoint folder paths and fuzzy-matches
against a user query. Reusable by:
  - AI Procedure Generator (as a planning tool)
  - MCP clients (Claude Desktop, Open WebUI)
  - Direct API calls via POST /api/v1/cwr/functions/resolve_sharepoint_folders/execute
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import func, select

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.sharepoint.resolve_sharepoint_folders")


class ResolveSharepointFoldersFunction(BaseFunction):
    """
    Resolve human-readable folder names to valid SharePoint folder paths.

    Queries SharePointSyncedDocument paths across active sync configs,
    extracts the folder hierarchy, and fuzzy-matches against a query string.

    Example:
        result = await fn.resolve_sharepoint_folders(ctx,
            query="Past Performances",
            site_name="Growth",
        )
    """

    meta = FunctionMeta(
        name="resolve_sharepoint_folders",
        category=FunctionCategory.DATA,
        description=(
            "Resolve human-readable SharePoint folder names to valid paths. "
            "Returns matching folders with document counts and subfolders. "
            "Use this to find the correct folder_path for search_assets()."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Human-readable folder name or partial path to resolve "
                        "(e.g., 'Past Performances', 'Reuse Material')"
                    ),
                },
                "site_name": {
                    "type": "string",
                    "description": (
                        "Filter to a specific SharePoint site by display name (e.g., 'Growth')"
                    ),
                },
                "sync_config_id": {
                    "type": "string",
                    "description": "Filter to a specific sync config by UUID",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum folder depth to return (default: 3)",
                    "default": 3,
                },
            },
            "required": [],
        },
        output_schema={
            "type": "array",
            "description": "List of matching folders sorted by relevance",
            "items": {
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "Human-readable SharePoint folder path",
                    },
                    "storage_path": {
                        "type": "string",
                        "description": "Full storage folder path for exact matching in search_assets(folder_path=..., folder_match_mode='prefix')",
                    },
                    "site_name": {
                        "type": "string",
                        "description": "SharePoint site display name",
                    },
                    "sync_config_name": {
                        "type": "string",
                        "description": "Sync config display name",
                    },
                    "sync_config_id": {
                        "type": "string",
                        "description": "Sync config UUID",
                    },
                    "document_count": {
                        "type": "integer",
                        "description": "Number of synced documents in this folder",
                    },
                    "subfolders": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Immediate child folder names",
                    },
                    "usage_hint": {
                        "type": "string",
                        "description": "How to use this path in search_assets",
                    },
                },
            },
        },
        tags=["data", "sharepoint", "folder", "resolve", "discovery"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="full",
        exposure_profile={"procedure": True, "agent": True},
        required_data_sources=["sharepoint"],
        examples=[
            {
                "description": "Find Past Performances folder on Growth site",
                "params": {"query": "Past Performances", "site_name": "Growth"},
            },
            {
                "description": "List all top-level folders for a sync config",
                "params": {"sync_config_id": "uuid", "max_depth": 1},
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Resolve folder names to validated SharePoint paths."""
        query = params.get("query", "")
        site_name = params.get("site_name", "")
        sync_config_id = params.get("sync_config_id")
        max_depth = min(params.get("max_depth", 3), 10)

        from app.core.database.models import (
            SharePointSyncConfig,
            SharePointSyncedDocument,
        )

        # Build config filter
        config_query = (
            select(SharePointSyncConfig)
            .where(SharePointSyncConfig.organization_id == ctx.requires_org_id)
            .where(SharePointSyncConfig.is_active == True)
        )
        if sync_config_id:
            config_uuid = UUID(sync_config_id) if isinstance(sync_config_id, str) else sync_config_id
            config_query = config_query.where(SharePointSyncConfig.id == config_uuid)
        if site_name:
            config_query = config_query.where(
                func.lower(SharePointSyncConfig.site_name).contains(site_name.lower())
            )

        result = await ctx.session.execute(config_query)
        configs = list(result.scalars().all())

        if not configs:
            return FunctionResult.success_result(
                data=[],
                message="No matching SharePoint sync configs found",
            )

        config_map = {c.id: c for c in configs}

        # Query all synced document paths for matching configs
        path_query = (
            select(
                SharePointSyncedDocument.sync_config_id,
                SharePointSyncedDocument.sharepoint_path,
            )
            .where(
                SharePointSyncedDocument.sync_config_id.in_([c.id for c in configs])
            )
            .where(SharePointSyncedDocument.sync_status == "synced")
            .where(SharePointSyncedDocument.sharepoint_path.isnot(None))
        )
        path_result = await ctx.session.execute(path_query)

        # Build folder tree: {config_id: {folder_path: doc_count}}
        folder_counts: Dict[Any, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        folder_children: Dict[Any, Dict[str, set]] = defaultdict(lambda: defaultdict(set))

        for row in path_result:
            cfg_id = row.sync_config_id
            path = row.sharepoint_path or ""
            parts = [p for p in path.strip("/").split("/") if p]

            # The last part is the filename, everything before is folders
            if len(parts) < 2:
                # File at root level
                folder_counts[cfg_id][""] += 1
                continue

            folder_parts = parts[:-1]  # Exclude filename

            # Count doc in its direct parent folder
            for depth in range(1, min(len(folder_parts) + 1, max_depth + 1)):
                folder_path = "/".join(folder_parts[:depth])
                if depth == len(folder_parts):
                    folder_counts[cfg_id][folder_path] += 1

            # Build full folder paths up to max_depth
            for depth in range(1, min(len(folder_parts) + 1, max_depth + 1)):
                folder_path = "/".join(folder_parts[:depth])
                folder_counts[cfg_id].setdefault(folder_path, 0)

                # Track parent -> child relationships
                if depth > 1:
                    parent_path = "/".join(folder_parts[: depth - 1])
                    folder_children[cfg_id][parent_path].add(folder_parts[depth - 1])
                elif depth == 1:
                    folder_children[cfg_id][""].add(folder_parts[0])

        # Build results
        folders: List[Dict[str, Any]] = []
        query_lower = query.lower().strip() if query else ""

        for cfg_id, paths in folder_counts.items():
            config = config_map[cfg_id]
            for folder_path, doc_count in paths.items():
                if not folder_path:
                    continue  # Skip root

                # Fuzzy match: case-insensitive contains on any path component
                if query_lower:
                    path_lower = folder_path.lower()
                    if query_lower not in path_lower:
                        continue

                children = sorted(folder_children[cfg_id].get(folder_path, set()))

                # Build storage_path from config slug + slugified folder parts
                from app.core.storage.storage_path_service import slugify as slugify_component

                slug_parts = "/".join(slugify_component(p) for p in folder_path.split("/") if p)
                storage_path = f"sharepoint/{config.slug}/{slug_parts}"

                folders.append({
                    "folder_path": folder_path,
                    "storage_path": storage_path,
                    "site_name": config.site_name or "",
                    "sync_config_name": config.name or "",
                    "sync_config_id": str(cfg_id),
                    "document_count": doc_count,
                    "subfolders": children,
                    "usage_hint": f'Use search_assets(folder_path="{storage_path}", folder_match_mode="prefix") to search documents in this folder.',
                })

        # Sort: exact match first, then by document count descending
        def _sort_key(f: Dict[str, Any]) -> tuple:
            path_lower = f["folder_path"].lower()
            # Exact match on final component gets highest priority
            final_component = path_lower.rsplit("/", 1)[-1]
            exact_match = 0 if (query_lower and final_component == query_lower) else 1
            return (exact_match, -f["document_count"])

        folders.sort(key=_sort_key)

        return FunctionResult.success_result(
            data=folders,
            message=f"Found {len(folders)} matching folders across {len(configs)} sync configs",
            items_processed=len(folders),
        )
