# OpenAI-Compatible Models
"""Pydantic models for OpenAI function calling format."""

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


class OpenAIFunctionDef(BaseModel):
    """OpenAI function definition format."""

    name: str = Field(..., description="Function name")
    description: str = Field(..., description="Function description")
    parameters: Dict[str, Any] = Field(..., description="JSON Schema for parameters")
    strict: bool = Field(default=True, description="Strict mode for validation")


class OpenAITool(BaseModel):
    """OpenAI tool wrapper."""

    type: Literal["function"] = "function"
    function: OpenAIFunctionDef


class OpenAIToolsResponse(BaseModel):
    """Response containing OpenAI-compatible tools."""

    tools: List[OpenAITool] = Field(..., description="List of available tools")
    total: int = Field(..., description="Total number of tools")
