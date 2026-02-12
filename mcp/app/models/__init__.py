# MCP Gateway Models
"""Pydantic models for MCP protocol, OpenAI compatibility, and policy configuration."""

from .mcp import (
    MCPContent,
    MCPError,
    MCPErrorCode,
    MCPTextContent,
    MCPTool,
    MCPToolCall,
    MCPToolResult,
)
from .openai import (
    OpenAIFunctionDef,
    OpenAITool,
    OpenAIToolsResponse,
)
from .policy import (
    ClampConfig,
    Policy,
    PolicySettings,
    ToolClamps,
)

__all__ = [
    # MCP models
    "MCPError",
    "MCPErrorCode",
    "MCPTool",
    "MCPToolCall",
    "MCPToolResult",
    "MCPContent",
    "MCPTextContent",
    # OpenAI models
    "OpenAIFunctionDef",
    "OpenAITool",
    "OpenAIToolsResponse",
    # Policy models
    "ClampConfig",
    "ToolClamps",
    "PolicySettings",
    "Policy",
]
