# MCP Gateway Models
"""Pydantic models for MCP protocol, OpenAI compatibility, and policy configuration."""

from .mcp import (
    MCPError,
    MCPErrorCode,
    MCPTool,
    MCPToolCall,
    MCPToolResult,
    MCPContent,
    MCPTextContent,
)
from .openai import (
    OpenAIFunctionDef,
    OpenAITool,
    OpenAIToolsResponse,
)
from .policy import (
    ClampConfig,
    ToolClamps,
    PolicySettings,
    Policy,
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
