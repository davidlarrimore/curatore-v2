# MCP SDK Server
"""MCP Server using official SDK with Streamable HTTP transport."""

import logging
from contextvars import ContextVar
from typing import Optional

import mcp.types as types
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from app.handlers import handle_resources_list, handle_tools_call, handle_tools_list
from app.services.contract_converter import ContractConverter

logger = logging.getLogger("mcp.server")

# Auth context — set by ASGI middleware before SDK handlers run
ctx_org_id: ContextVar[Optional[str]] = ContextVar("ctx_org_id", default=None)
ctx_api_key: ContextVar[Optional[str]] = ContextVar("ctx_api_key", default=None)
ctx_correlation_id: ContextVar[Optional[str]] = ContextVar("ctx_correlation_id", default=None)

server = Server("curatore-mcp")

# Session manager for Streamable HTTP transport
session_manager = StreamableHTTPSessionManager(
    app=server,
    json_response=True,
    stateless=True,
)


@server.list_tools()
async def sdk_list_tools() -> list[types.Tool]:
    """List available tools via SDK transport."""
    api_key = ctx_api_key.get()
    correlation_id = ctx_correlation_id.get()
    result = await handle_tools_list(api_key, correlation_id)
    return ContractConverter.to_sdk_tools(result.tools)


@server.call_tool()
async def sdk_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Execute a tool via SDK transport."""
    result = await handle_tools_call(
        name=name,
        arguments=arguments or {},
        org_id=ctx_org_id.get(),
        api_key=ctx_api_key.get(),
        correlation_id=ctx_correlation_id.get(),
    )
    return [
        types.TextContent(type="text", text=block.text)
        for block in result.content
    ]


@server.list_resources()
async def sdk_list_resources() -> list[types.Resource]:
    """List available resources via SDK transport."""
    api_key = ctx_api_key.get()
    correlation_id = ctx_correlation_id.get()
    result = await handle_resources_list(api_key, correlation_id)
    return [
        types.Resource(
            uri=r["uri"],
            name=r["name"],
            description=r.get("description"),
            mimeType=r.get("mimeType"),
        )
        for r in result.get("resources", [])
    ]


@server.read_resource()
async def sdk_read_resource(uri: types.AnyUrl) -> str:
    """Read a specific resource by URI. Returns description text."""
    api_key = ctx_api_key.get()
    correlation_id = ctx_correlation_id.get()
    result = await handle_resources_list(api_key, correlation_id)

    uri_str = str(uri)
    for r in result.get("resources", []):
        if r["uri"] == uri_str:
            return r.get("description", "")

    raise ValueError(f"Resource not found: {uri_str}")


@server.list_resource_templates()
async def sdk_list_resource_templates() -> list[types.ResourceTemplate]:
    """List resource templates (none currently)."""
    return []
