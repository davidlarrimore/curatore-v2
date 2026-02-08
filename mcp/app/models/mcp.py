# MCP Protocol Models
"""Pydantic models for MCP (Model Context Protocol) messages."""

from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class MCPErrorCode(str, Enum):
    """MCP error codes."""

    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class MCPError(BaseModel):
    """MCP error response."""

    code: MCPErrorCode
    message: str
    data: Optional[Dict[str, Any]] = None


class MCPTool(BaseModel):
    """MCP tool definition."""

    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    inputSchema: Dict[str, Any] = Field(..., description="JSON Schema for tool input")


class MCPToolCall(BaseModel):
    """MCP tool call request."""

    name: str = Field(..., description="Tool name to call")
    arguments: Dict[str, Any] = Field(
        default_factory=dict, description="Tool arguments"
    )


class MCPTextContent(BaseModel):
    """MCP text content block."""

    type: str = Field(default="text", const=True)
    text: str = Field(..., description="Text content")


class MCPContent(BaseModel):
    """MCP content wrapper - can contain multiple content blocks."""

    content: List[MCPTextContent] = Field(
        default_factory=list, description="Content blocks"
    )
    isError: bool = Field(default=False, description="Whether this is an error")


class MCPToolResult(BaseModel):
    """MCP tool execution result."""

    content: List[MCPTextContent] = Field(..., description="Result content blocks")
    isError: bool = Field(default=False, description="Whether execution resulted in error")


class MCPInitializeRequest(BaseModel):
    """MCP initialize request."""

    protocolVersion: str = Field(..., description="Client protocol version")
    capabilities: Dict[str, Any] = Field(
        default_factory=dict, description="Client capabilities"
    )
    clientInfo: Dict[str, Any] = Field(
        default_factory=dict, description="Client information"
    )


class MCPInitializeResponse(BaseModel):
    """MCP initialize response."""

    protocolVersion: str = Field(..., description="Server protocol version")
    capabilities: Dict[str, Any] = Field(
        default_factory=dict, description="Server capabilities"
    )
    serverInfo: Dict[str, Any] = Field(
        default_factory=dict, description="Server information"
    )


class MCPToolsListResponse(BaseModel):
    """MCP tools/list response."""

    tools: List[MCPTool] = Field(..., description="Available tools")


class MCPToolsCallRequest(BaseModel):
    """MCP tools/call request."""

    name: str = Field(..., description="Tool name")
    arguments: Dict[str, Any] = Field(
        default_factory=dict, description="Tool arguments"
    )


class MCPToolsCallResponse(BaseModel):
    """MCP tools/call response."""

    content: List[MCPTextContent] = Field(..., description="Result content")
    isError: bool = Field(default=False, description="Error flag")


# JSON-RPC wrapper models
class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 request."""

    jsonrpc: str = Field(default="2.0", const=True)
    id: Union[str, int, None] = Field(default=None, description="Request ID")
    method: str = Field(..., description="Method name")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Method params")


class JSONRPCResponse(BaseModel):
    """JSON-RPC 2.0 response."""

    jsonrpc: str = Field(default="2.0", const=True)
    id: Union[str, int, None] = Field(default=None, description="Request ID")
    result: Optional[Any] = Field(default=None, description="Result")
    error: Optional[Dict[str, Any]] = Field(default=None, description="Error")


class JSONRPCError(BaseModel):
    """JSON-RPC 2.0 error object."""

    code: int = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    data: Optional[Any] = Field(default=None, description="Additional error data")
