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
