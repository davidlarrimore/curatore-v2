# MCP Initialize Handler
"""Handles MCP initialize request."""

import logging
from typing import Any, Dict

from app.config import settings
from app.models.mcp import MCPInitializeResponse

logger = logging.getLogger("mcp.handlers.initialize")


async def handle_initialize(params: Dict[str, Any]) -> MCPInitializeResponse:
    """
    Handle MCP initialize request.

    Args:
        params: Initialize request parameters

    Returns:
        Initialize response with server capabilities
    """
    client_version = params.get("protocolVersion", "unknown")
    client_info = params.get("clientInfo", {})

    logger.info(
        f"MCP client connecting: {client_info.get('name', 'unknown')} "
        f"(protocol: {client_version})"
    )

    return MCPInitializeResponse(
        protocolVersion=settings.mcp_protocol_version,
        capabilities={"tools": {}, "resources": {}},
        serverInfo={
            "name": settings.mcp_server_name,
            "version": settings.mcp_server_version,
        },
    )
