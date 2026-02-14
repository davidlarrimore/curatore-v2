# backend/app/cwr/tools/primitives/search/discover_data_sources.py
"""
Discover Data Sources function — returns a two-level catalog:
1. Source type knowledge (from YAML registry + DB overrides)
2. Live instances (from org config tables)

Gives AI clients a curated understanding of what data is available
and how to search it.
"""

import logging
from typing import Any, Dict, List

from sqlalchemy import func, select

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.search.discover_data_sources")


class DiscoverDataSourcesFunction(BaseFunction):
    """
    Discover available data sources and what they contain.

    Returns a two-level catalog combining curated knowledge about each
    source type (what SAM.gov IS, what SharePoint contains, etc.) with
    live instance details (configured searches, sync folders, collections).

    Example:
        result = await fn.discover_data_sources(ctx)
        result = await fn.discover_data_sources(ctx, source_type="sharepoint")
    """

    meta = FunctionMeta(
        name="discover_data_sources",
        category=FunctionCategory.SEARCH,
        description=(
            "Discover what data sources are available, what they contain, "
            "and how to search them. Call this first to understand what data is available "
            "before choosing a search tool. Returns source type descriptions, capabilities, "
            "example questions, recommended search tools with usage guidance, "
            "and live configuration details (configured sites, searches, collections)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "source_type": {
                    "type": "string",
                    "description": "Filter to a specific source type",
                    "default": None,
                    "enum": [
                        "sam_gov", "sharepoint", "forecast_ag", "forecast_apfs",
                        "forecast_state", "salesforce", "web_scrape",
                        "search_collection",
                    ],
                },
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "description": "Two-level data source catalog",
            "properties": {
                "source_types": {"type": "array", "items": {"type": "object"}, "description": "Source type definitions with instances"},
                "total_source_types": {"type": "integer", "description": "Number of source types returned"},
                "total_instances": {"type": "integer", "description": "Total configured instances across all types"},
            },
        },
        tags=["search", "discovery", "metadata", "data-sources"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="full",
        examples=[
            {
                "description": "Discover all available data sources",
                "params": {},
            },
            {
                "description": "Get SharePoint sources only",
                "params": {"source_type": "sharepoint"},
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute data source discovery."""
        from app.core.database.models import (
            Asset,
            Connection,
            ForecastSync,
            SamSearch,
            ScrapeCollection,
            SearchCollection,
            SharePointSyncConfig,
        )
        from app.core.metadata.registry_service import metadata_registry_service

        source_type_filter = params.get("source_type")

        try:
            # Get the curated catalog (YAML baseline + org overrides)
            catalog = await metadata_registry_service.get_data_source_catalog(
                ctx.session, ctx.organization_id
            )

            # Filter if requested
            if source_type_filter:
                catalog = {k: v for k, v in catalog.items() if k == source_type_filter}

            # Remove inactive source types
            catalog = {k: v for k, v in catalog.items() if v.get("is_active", True)}

            # Build response with live instances
            source_types = []
            total_instances = 0

            for key, defn in catalog.items():
                try:
                    instances = await self._get_instances(
                        ctx, key,
                        Asset=Asset,
                        SharePointSyncConfig=SharePointSyncConfig,
                        SamSearch=SamSearch,
                        ScrapeCollection=ScrapeCollection,
                        SearchCollection=SearchCollection,
                        ForecastSync=ForecastSync,
                        Connection=Connection,
                    )
                except Exception as inst_err:
                    logger.warning(f"Failed to fetch instances for {key}: {inst_err}")
                    instances = []
                total_instances += len(instances)

                entry = {
                    "type": key,
                    "display_name": defn.get("display_name", key),
                    "description": defn.get("description"),
                    "capabilities": defn.get("capabilities", []),
                    "example_questions": defn.get("example_questions", []),
                    "search_tools": defn.get("search_tools", []),
                    "instances": instances,
                }
                if defn.get("note"):
                    entry["note"] = defn["note"]

                source_types.append(entry)

            result_data = {
                "source_types": source_types,
                "total_source_types": len(source_types),
                "total_instances": total_instances,
            }

            return FunctionResult.success_result(
                data=result_data,
                message=f"Found {len(source_types)} source types with {total_instances} configured instances",
                metadata={"source_type_filter": source_type_filter},
            )

        except Exception as e:
            logger.exception(f"Discovery failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Data source discovery failed",
            )

    async def _get_instances(
        self,
        ctx: FunctionContext,
        source_type: str,
        **models,
    ) -> List[Dict[str, Any]]:
        """Fetch live configuration instances for a source type."""
        instances = []

        if source_type == "sam_gov":
            SamSearch = models["SamSearch"]
            result = await ctx.session.execute(
                select(SamSearch)
                .where(ctx.org_filter(SamSearch.organization_id))
                .where(SamSearch.is_active == True)
            )
            for s in result.scalars():
                # Summarize search config filters
                config = s.search_config or {}
                filter_parts = []
                if config.get("naics_codes"):
                    filter_parts.append(f"NAICS: {', '.join(config['naics_codes'][:5])}")
                if config.get("agencies"):
                    filter_parts.append(f"Agencies: {', '.join(config['agencies'][:3])}")
                if config.get("notice_types"):
                    filter_parts.append(f"Types: {', '.join(config['notice_types'][:5])}")
                if config.get("set_asides"):
                    filter_parts.append(f"Set-asides: {', '.join(config['set_asides'][:3])}")

                instances.append({
                    "type": "sam_search",
                    "id": str(s.id),
                    "name": s.name,
                    "description": (s.description or "")[:200] or None,
                    "filters_summary": " | ".join(filter_parts) if filter_parts else None,
                    "last_pull_at": s.last_pull_at.isoformat() if s.last_pull_at else None,
                    "status": s.status or "active",
                })

        elif source_type == "sharepoint":
            SharePointSyncConfig = models["SharePointSyncConfig"]
            Asset = models["Asset"]
            from app.core.database.models import SharePointSyncedDocument

            # Get configs
            result = await ctx.session.execute(
                select(SharePointSyncConfig)
                .where(ctx.org_filter(SharePointSyncConfig.organization_id))
                .where(SharePointSyncConfig.is_active == True)
            )
            configs = list(result.scalars())

            # Get actual asset counts per sync_config_id in one query
            if configs:
                config_id_col = Asset.source_metadata["sync"]["config_id"].astext
                count_result = await ctx.session.execute(
                    select(
                        config_id_col.label("config_id"),
                        func.count(Asset.id).label("total"),
                        func.count(Asset.indexed_at).label("indexed"),
                    )
                    .where(Asset.source_type == "sharepoint")
                    .where(ctx.org_filter(Asset.organization_id))
                    .where(
                        config_id_col.in_([str(c.id) for c in configs])
                    )
                    .group_by(config_id_col)
                )
                asset_counts = {
                    row.config_id: {"total": row.total, "indexed": row.indexed}
                    for row in count_result
                }
            else:
                asset_counts = {}

            # Get top-level folder paths per sync config (first 2 levels of depth)
            folder_paths_by_config = {}
            if configs:
                path_result = await ctx.session.execute(
                    select(
                        SharePointSyncedDocument.sync_config_id,
                        SharePointSyncedDocument.sharepoint_path,
                    )
                    .where(
                        SharePointSyncedDocument.sync_config_id.in_(
                            [c.id for c in configs]
                        )
                    )
                    .where(SharePointSyncedDocument.sync_status == "synced")
                    .where(SharePointSyncedDocument.sharepoint_path.isnot(None))
                )
                for row in path_result:
                    cfg_id = str(row.sync_config_id)
                    path = row.sharepoint_path or ""
                    # Extract top-level folders (first 2 levels)
                    parts = [p for p in path.strip("/").split("/") if p]
                    if len(parts) >= 1:
                        folder_paths_by_config.setdefault(cfg_id, set()).add(parts[0])
                    if len(parts) >= 2:
                        folder_paths_by_config.setdefault(cfg_id, set()).add(
                            f"{parts[0]}/{parts[1]}"
                        )

            for c in configs:
                site_name = getattr(c, "site_name", None)
                counts = asset_counts.get(str(c.id), {"total": 0, "indexed": 0})
                available_folders = sorted(
                    folder_paths_by_config.get(str(c.id), set())
                )
                inst = {
                    "type": "sharepoint_sync",
                    "id": str(c.id),
                    "name": c.name,
                    "slug": c.slug,
                    "site_name": site_name,
                    "description": (c.description or "")[:200] or None,
                    "folder_name": c.folder_name or c.folder_url or "",
                    "stats": {
                        "total_documents": counts["total"],
                        "searchable_documents": counts["indexed"],
                    },
                    "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
                }
                if available_folders:
                    inst["available_folders"] = available_folders
                    inst["folder_path_hint"] = (
                        "Use these paths with search_assets(folder_path='...') "
                        "to filter by folder. Prefix-matches subfolders too."
                    )
                instances.append(inst)

        elif source_type in ("forecast_ag", "forecast_apfs", "forecast_state"):
            ForecastSync = models["ForecastSync"]
            # Map source_type key to ForecastSync.source_type value
            fs_type_map = {
                "forecast_ag": "ag",
                "forecast_apfs": "apfs",
                "forecast_state": "state",
            }
            fs_type = fs_type_map[source_type]
            result = await ctx.session.execute(
                select(ForecastSync)
                .where(ctx.org_filter(ForecastSync.organization_id))
                .where(ForecastSync.source_type == fs_type)
                .where(ForecastSync.is_active == True)
            )
            for f in result.scalars():
                instances.append({
                    "type": "forecast_sync",
                    "id": str(f.id),
                    "name": f.name,
                    "source_type": f.source_type,
                    "last_sync_at": f.last_sync_at.isoformat() if f.last_sync_at else None,
                    "status": f.status or "active",
                })

        elif source_type == "salesforce":
            Connection = models["Connection"]
            result = await ctx.session.execute(
                select(Connection)
                .where(ctx.org_filter(Connection.organization_id))
                .where(Connection.connection_type == "salesforce")
                .where(Connection.is_active == True)
            )
            for c in result.scalars():
                config = c.config or {}
                instances.append({
                    "type": "salesforce_connection",
                    "id": str(c.id),
                    "name": c.name,
                    "instance_url": config.get("instance_url", ""),
                })

        elif source_type == "search_collection":
            SearchCollection = models["SearchCollection"]
            result = await ctx.session.execute(
                select(SearchCollection)
                .where(ctx.org_filter(SearchCollection.organization_id))
                .where(SearchCollection.is_active == True)
            )
            for c in result.scalars():
                instances.append({
                    "type": "search_collection",
                    "id": str(c.id),
                    "name": c.name,
                    "slug": c.slug,
                    "description": (c.description or "")[:200] or None,
                    "collection_type": c.collection_type,
                    "item_count": c.item_count,
                    "source_type": c.source_type,
                })

        elif source_type == "web_scrape":
            ScrapeCollection = models["ScrapeCollection"]
            Asset = models["Asset"]

            result = await ctx.session.execute(
                select(ScrapeCollection)
                .where(ctx.org_filter(ScrapeCollection.organization_id))
                .where(ScrapeCollection.status == "active")
            )
            collections = list(result.scalars())

            # Get actual asset counts per collection
            if collections:
                coll_id_col = Asset.source_metadata["scrape"]["collection_id"].astext
                count_result = await ctx.session.execute(
                    select(
                        coll_id_col.label("coll_id"),
                        func.count(Asset.id).label("total"),
                        func.count(Asset.indexed_at).label("indexed"),
                    )
                    .where(Asset.source_type.in_(["web_scrape", "web_scrape_document"]))
                    .where(ctx.org_filter(Asset.organization_id))
                    .where(
                        coll_id_col.in_([str(c.id) for c in collections])
                    )
                    .group_by(coll_id_col)
                )
                asset_counts = {
                    row.coll_id: {"total": row.total, "indexed": row.indexed}
                    for row in count_result
                }
            else:
                asset_counts = {}

            for c in collections:
                counts = asset_counts.get(str(c.id), {"total": 0, "indexed": 0})
                instances.append({
                    "type": "scrape_collection",
                    "id": str(c.id),
                    "name": c.name,
                    "description": (c.description or "")[:200] or None,
                    "root_url": c.root_url,
                    "stats": {
                        "total_documents": counts["total"],
                        "searchable_documents": counts["indexed"],
                    },
                    "last_crawl_at": c.last_crawl_at.isoformat() if c.last_crawl_at else None,
                })

        return instances
