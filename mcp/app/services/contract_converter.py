# Contract Converter Service
"""
Converts CWR ToolContracts to MCP Tool format.

The CWR ToolContract already uses JSON Schema for input_schema, which is exactly
what MCP expects. The only conversion needed is:
1. Rename input_schema → inputSchema (snake_case → camelCase)
2. Optionally enhance description with payload_profile hints
"""

import logging
from typing import Any, Dict, List

import mcp.types as types

from app.models.mcp import MCPTool

logger = logging.getLogger("mcp.services.contract_converter")


class ContractConverter:
    """
    Converts CWR ToolContracts to MCP Tool definitions.

    The CWR input_schema is already MCP-compatible JSON Schema.
    This is essentially a field rename + optional description enhancement.
    """

    @staticmethod
    def to_mcp_tool(contract: Dict[str, Any], enhance_description: bool = True) -> MCPTool:
        """
        Convert a CWR ToolContract to an MCP Tool.

        Args:
            contract: ToolContract dictionary from backend
            enhance_description: Add payload_profile hints to description

        Returns:
            MCPTool definition
        """
        name = contract.get("name", "unknown")
        description = contract.get("description", "")

        # Optionally enhance description with governance hints
        if enhance_description:
            payload_profile = contract.get("payload_profile", "full")
            if payload_profile == "thin":
                description += (
                    "\n\nNote: Returns thin payloads (IDs, titles, scores). "
                    "Use get_content for full document content."
                )
            elif payload_profile == "summary":
                description += "\n\nNote: Returns summarized content."

            if contract.get("requires_llm", False):
                description += "\n\nRequires LLM connection."

        # The input_schema is already valid JSON Schema - just rename the field
        input_schema = contract.get("input_schema", {
            "type": "object",
            "properties": {},
        })

        return MCPTool(
            name=name,
            description=description,
            inputSchema=input_schema,  # camelCase for MCP
        )

    @staticmethod
    def to_mcp_tools(
        contracts: List[Dict[str, Any]],
        enhance_description: bool = True,
    ) -> List[MCPTool]:
        """Convert multiple CWR ToolContracts to MCP Tools."""
        tools = []
        for contract in contracts:
            try:
                tool = ContractConverter.to_mcp_tool(contract, enhance_description)
                tools.append(tool)
            except Exception as e:
                logger.warning(f"Failed to convert contract {contract.get('name', 'unknown')}: {e}")
        return tools

    @staticmethod
    def to_sdk_tool(tool: MCPTool) -> types.Tool:
        """
        Convert an MCPTool to an MCP SDK types.Tool with annotations.

        Args:
            tool: MCPTool instance (internal model)

        Returns:
            MCP SDK types.Tool with ToolAnnotations
        """
        # Derive annotations from the internal _side_effects marker if present,
        # otherwise default to read-only (safe default).
        side_effects = getattr(tool, "_side_effects", False)
        return types.Tool(
            name=tool.name,
            description=tool.description,
            inputSchema=tool.inputSchema,
            annotations=types.ToolAnnotations(
                readOnlyHint=not side_effects,
                destructiveHint=False,
                idempotentHint=not side_effects,
                openWorldHint=True,
            ),
        )

    @staticmethod
    def to_sdk_tools(tools: List[MCPTool]) -> List[types.Tool]:
        """Convert a list of MCPTools to MCP SDK types.Tool list."""
        return [ContractConverter.to_sdk_tool(t) for t in tools]

    @staticmethod
    def contract_to_sdk_tool(contract: Dict[str, Any]) -> types.Tool:
        """
        Convert a raw contract dict directly to an MCP SDK types.Tool.

        Args:
            contract: ToolContract dictionary from backend

        Returns:
            MCP SDK types.Tool with ToolAnnotations
        """
        has_side_effects = contract.get("side_effects", False)
        description = contract.get("description", "")

        # Add payload_profile hints
        payload_profile = contract.get("payload_profile", "full")
        if payload_profile == "thin":
            description += (
                "\n\nNote: Returns thin payloads (IDs, titles, scores). "
                "Use get_content for full document content."
            )
        elif payload_profile == "summary":
            description += "\n\nNote: Returns summarized content."
        if contract.get("requires_llm", False):
            description += "\n\nRequires LLM connection."

        return types.Tool(
            name=contract.get("name", "unknown"),
            description=description,
            inputSchema=contract.get("input_schema", {"type": "object", "properties": {}}),
            annotations=types.ToolAnnotations(
                readOnlyHint=not has_side_effects,
                destructiveHint=False,
                idempotentHint=not has_side_effects,
                openWorldHint=True,
            ),
        )

    @staticmethod
    def filter_safe(
        contracts: List[Dict[str, Any]],
        allowlist: List[str],
        block_side_effects: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Filter contracts by allowlist and side_effects.

        Args:
            contracts: List of ToolContract dictionaries
            allowlist: List of allowed function names
            block_side_effects: Exclude contracts with side_effects=True

        Returns:
            Filtered list of contracts
        """
        result = []
        for c in contracts:
            name = c.get("name", "")

            # Check allowlist
            if allowlist and name not in allowlist:
                continue

            # Check side_effects
            if block_side_effects and c.get("side_effects", False):
                logger.debug(f"Excluding {name}: has side effects")
                continue

            result.append(c)

        return result
