# MCP Resources List Handler
"""Handles MCP resources/list request by exposing data source catalog."""

import logging
import time
from typing import Any, Dict, List, Optional

from app.services.backend_client import backend_client

logger = logging.getLogger("mcp.handlers.resources_list")

# Cache for resources (5-minute TTL)
_resources_cache: Dict[str, Any] = {"data": None, "timestamp": 0}
_CACHE_TTL = 300  # 5 minutes


async def handle_resources_list(
    api_key: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Handle MCP resources/list request.

    Returns data source catalog as MCP Resources. Each source type becomes
    a resource with curated descriptions including capabilities and usage hints.

    Args:
        api_key: API key for backend authentication
        correlation_id: Request correlation ID

    Returns:
        Dict with "resources" key containing list of MCP Resource objects
    """
    now = time.time()

    # Check cache
    if _resources_cache["data"] and (now - _resources_cache["timestamp"]) < _CACHE_TTL:
        return _resources_cache["data"]

    try:
        # Call discover_data_sources via backend
        result = await backend_client.execute_function(
            name="discover_data_sources",
            params={},
            api_key=api_key,
            correlation_id=correlation_id,
        )

        resources = _convert_to_mcp_resources(result)
        response = {"resources": resources}

        # Update cache
        _resources_cache["data"] = response
        _resources_cache["timestamp"] = now

        logger.info(f"Built {len(resources)} MCP resources from data source catalog")
        return response

    except Exception as e:
        logger.warning(f"Failed to build resources list: {e}")
        # Return cached data if available, otherwise empty
        if _resources_cache["data"]:
            return _resources_cache["data"]
        return {"resources": []}


def _convert_to_mcp_resources(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert discover_data_sources result to MCP Resource objects."""
    resources = []

    # Extract from function result wrapper
    data = result.get("data") or result.get("result", {}).get("data", {})
    if not data:
        return resources

    source_types = data.get("source_types", [])

    for source_type in source_types:
        st_key = source_type.get("type", "unknown")
        display_name = source_type.get("display_name", st_key)
        description = source_type.get("description", "")
        capabilities = source_type.get("capabilities", [])
        example_questions = source_type.get("example_questions", [])
        search_tools = source_type.get("search_tools", [])
        instances = source_type.get("instances", [])

        # Build rich description with capabilities and usage hints
        desc_parts = [description.strip()] if description else []

        if capabilities:
            desc_parts.append("\nCapabilities:")
            for cap in capabilities[:5]:
                desc_parts.append(f"  - {cap}")

        if search_tools:
            desc_parts.append("\nSearch tools:")
            for tool in search_tools:
                tool_name = tool.get("tool", "")
                use_for = tool.get("use_for", "")
                desc_parts.append(f"  - {tool_name}: {use_for}")

        if example_questions:
            desc_parts.append("\nExample questions:")
            for q in example_questions[:3]:
                desc_parts.append(f"  - {q}")

        if instances:
            desc_parts.append(f"\nConfigured instances ({len(instances)}):")
            for inst in instances[:10]:
                inst_name = inst.get("name", inst.get("id", "unknown"))
                inst_desc = inst.get("description", "")
                line = f"  - {inst_name}"
                if inst_desc:
                    line += f": {inst_desc}"
                desc_parts.append(line)

        full_description = "\n".join(desc_parts)

        resource = {
            "uri": f"curatore://data-sources/{st_key}",
            "name": display_name,
            "description": full_description,
            "mimeType": "text/plain",
        }
        resources.append(resource)

    return resources


def invalidate_cache():
    """Clear the resources cache."""
    _resources_cache["data"] = None
    _resources_cache["timestamp"] = 0
