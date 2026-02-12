# OpenAI Converter Service
"""Convert MCP tools to OpenAI function calling format."""

from typing import List

from app.models.mcp import MCPTool
from app.models.openai import OpenAIFunctionDef, OpenAITool


def mcp_to_openai_tool(mcp_tool: MCPTool) -> OpenAITool:
    """
    Convert a single MCP tool to OpenAI format.

    Args:
        mcp_tool: MCP tool definition

    Returns:
        OpenAI-compatible tool definition
    """
    return OpenAITool(
        type="function",
        function=OpenAIFunctionDef(
            name=mcp_tool.name,
            description=mcp_tool.description,
            parameters=mcp_tool.inputSchema,
            strict=True,
        ),
    )


def mcp_tools_to_openai(mcp_tools: List[MCPTool]) -> List[OpenAITool]:
    """
    Convert a list of MCP tools to OpenAI format.

    Args:
        mcp_tools: List of MCP tool definitions

    Returns:
        List of OpenAI-compatible tool definitions
    """
    return [mcp_to_openai_tool(t) for t in mcp_tools]
