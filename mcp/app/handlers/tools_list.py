# MCP Tools List Handler
"""Handles MCP tools/list request."""

import logging
import time
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models.mcp import MCPTool, MCPToolsListResponse
from app.services.backend_client import backend_client
from app.services.contract_converter import ContractConverter
from app.services.policy_service import policy_service

logger = logging.getLogger("mcp.handlers.tools_list")

# In-memory cache for contracts
_contract_cache: List[Dict[str, Any]] = []
_cache_timestamp: float = 0


async def _get_contracts(
    api_key: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get contracts from cache or backend."""
    global _contract_cache, _cache_timestamp

    cache_ttl = policy_service.contract_cache_ttl
    if _contract_cache and (time.time() - _cache_timestamp) < cache_ttl:
        return _contract_cache

    # Fetch from backend (filter side_effects=False at source)
    contracts = await backend_client.get_contracts(
        side_effects=False,
        api_key=api_key,
        correlation_id=correlation_id,
    )

    _contract_cache = contracts
    _cache_timestamp = time.time()
    logger.debug(f"Cached {len(contracts)} contracts")

    return contracts


async def handle_tools_list(
    api_key: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> MCPToolsListResponse:
    """
    Handle MCP tools/list request.

    Fetches tool contracts from backend, filters by policy, and
    converts to MCP tool format.

    Args:
        api_key: API key for backend authentication
        correlation_id: Request correlation ID

    Returns:
        List of MCP tools
    """
    # Get all contracts (cached)
    contracts = await _get_contracts(api_key, correlation_id)

    # Filter by policy allowlist and side_effects
    allowed_contracts = ContractConverter.filter_safe(
        contracts,
        allowlist=policy_service.allowlist,
        block_side_effects=policy_service.block_side_effects,
    )

    # Convert to MCP tool format
    tools = ContractConverter.to_mcp_tools(allowed_contracts)

    logger.info(f"Returning {len(tools)} tools")
    return MCPToolsListResponse(tools=tools)


def clear_cache():
    """Clear the contract cache."""
    global _contract_cache, _cache_timestamp
    _contract_cache = []
    _cache_timestamp = 0
