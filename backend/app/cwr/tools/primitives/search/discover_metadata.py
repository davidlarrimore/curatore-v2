# backend/app/cwr/tools/primitives/search/discover_metadata.py
"""
Discover Metadata function — returns available metadata facets, namespaces,
and field definitions so users can understand what filters are available.
"""

import logging
from typing import Any, Dict

from ...base import (
    BaseFunction,
    FunctionCategory,
    FunctionMeta,
    FunctionResult,
)
from ...context import FunctionContext

logger = logging.getLogger("curatore.functions.search.discover_metadata")


class DiscoverMetadataFunction(BaseFunction):
    """
    Discover available metadata facets and fields for search filtering.

    Returns facet definitions (cross-domain filter abstractions) and
    optionally namespace/field details. Helps users understand what
    filters are available when searching.

    Example:
        result = await fn.discover_metadata(ctx)
        result = await fn.discover_metadata(ctx, include_fields=True)
    """

    meta = FunctionMeta(
        name="discover_metadata",
        category=FunctionCategory.SEARCH,
        description=(
            "Discover available metadata facets and fields for filtering search results. "
            "Returns cross-domain facet definitions and optionally namespace/field details."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "include_fields": {
                    "type": "boolean",
                    "description": "Include detailed field definitions per namespace (more verbose)",
                    "default": False,
                },
                "namespace": {
                    "type": "string",
                    "description": "Filter to a specific namespace (e.g., 'sam', 'sharepoint', 'forecast')",
                    "default": None,
                },
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "description": "Metadata catalog with facets and optional field details",
            "properties": {
                "facets": {"type": "array", "items": {"type": "object"}, "description": "Cross-domain facet definitions with operators and content type mappings"},
                "namespaces": {"type": "array", "items": {"type": "object"}, "description": "Namespace definitions (only if include_fields=True)", "nullable": True},
                "usage_hint": {"type": "string", "description": "How to use facets in search queries"},
            },
        },
        tags=["search", "discovery", "metadata", "facets"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="full",
        examples=[
            {
                "description": "Discover available search facets",
                "params": {},
            },
            {
                "description": "Get detailed fields for SAM namespace",
                "params": {"include_fields": True, "namespace": "sam"},
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute metadata discovery."""
        from app.core.metadata.registry_service import metadata_registry_service

        include_fields = params.get("include_fields", False)
        namespace_filter = params.get("namespace")

        try:
            # Get facet definitions
            facets_raw = metadata_registry_service.get_facet_definitions()
            facets = []
            for name, defn in facets_raw.items():
                facets.append({
                    "name": name,
                    "display_name": defn.get("display_name", name),
                    "data_type": defn.get("data_type", "string"),
                    "description": defn.get("description"),
                    "operators": defn.get("operators", ["eq", "in"]),
                    "content_types": list(defn.get("mappings", {}).keys()),
                })

            result_data: Dict[str, Any] = {
                "facets": facets,
                "usage_hint": (
                    'Use facet_filters in search functions: '
                    '{"agency": "GSA", "naics_code": "541512"}. '
                    "Facets work across content types automatically."
                ),
            }

            # Optionally include field details
            if include_fields:
                namespaces_raw = metadata_registry_service.get_namespaces()
                fields_raw = metadata_registry_service.get_all_fields()

                ns_list = []
                for ns_key, ns_def in namespaces_raw.items():
                    if namespace_filter and ns_key != namespace_filter:
                        continue

                    ns_fields = fields_raw.get(ns_key, {})
                    field_list = []
                    for fname, fdef in ns_fields.items():
                        field_entry = {
                            "name": fname,
                            "data_type": fdef.get("data_type", "string"),
                            "facetable": fdef.get("facetable", False),
                            "description": fdef.get("description"),
                            "examples": fdef.get("examples", [])[:5],
                        }
                        # Expose full value list for facetable fields with defined values
                        if fdef.get("facetable") and len(fdef.get("examples", [])) > 3:
                            field_entry["allowed_values"] = fdef.get("examples", [])
                        field_list.append(field_entry)

                    ns_list.append({
                        "namespace": ns_key,
                        "display_name": ns_def.get("display_name", ns_key),
                        "description": ns_def.get("description"),
                        "fields": field_list,
                    })

                result_data["namespaces"] = ns_list

            return FunctionResult.success_result(
                data=result_data,
                message=f"Found {len(facets)} facets",
                metadata={
                    "include_fields": include_fields,
                    "namespace_filter": namespace_filter,
                },
            )

        except Exception as e:
            logger.exception(f"Metadata discovery failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Metadata discovery failed",
            )
