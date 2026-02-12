# Contract Converter Service
"""
Converts CWR ToolContracts to MCP Tool format.

The CWR ToolContract already uses JSON Schema for input_schema, which is exactly
what MCP expects. The conversion includes:
1. Rename input_schema → inputSchema (snake_case → camelCase)
2. Strip properties marked with x-procedure-only (internal to procedure runtime)
3. Optionally enhance description with payload_profile hints
"""

import copy
import logging
from typing import Any, Dict, List

import mcp.types as types

from app.models.mcp import MCPTool

logger = logging.getLogger("mcp.services.contract_converter")


def _clean_schema_for_mcp(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep-copy a JSON Schema and clean it for MCP/agent exposure:

    1. Remove properties marked ``"x-procedure-only": true`` (CWR
       procedure-runtime params like ``items`` that confuse agents).
    2. Strip ``"default": null`` from remaining properties.  The backend
       Python schemas use ``"default": None`` to indicate "optional, no
       default", but that serialises as ``"default": null`` in JSON Schema.
       LLMs see the literal ``null`` and faithfully send it back, which
       then fails Draft 7 type validation (e.g. null vs string).
    """
    schema = copy.deepcopy(schema)
    props = schema.get("properties")
    if not isinstance(props, dict):
        return schema

    # 1. Remove procedure-only properties
    to_remove = [
        key for key, defn in props.items()
        if isinstance(defn, dict) and defn.get("x-procedure-only")
    ]

    for key in to_remove:
        del props[key]

    # Also remove from required list if present
    required = schema.get("required")
    if isinstance(required, list) and to_remove:
        schema["required"] = [r for r in required if r not in to_remove]

    # 2. Strip "default": null from remaining properties
    for defn in props.values():
        if isinstance(defn, dict) and defn.get("default") is None and "default" in defn:
            del defn["default"]

    return schema


class ContractConverter:
    """
    Converts CWR ToolContracts to MCP Tool definitions.

    The CWR input_schema is already MCP-compatible JSON Schema.
    This converter renames fields, strips procedure-only parameters,
    and optionally enhances descriptions.
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

        # The input_schema is already valid JSON Schema — strip procedure-only
        # params and rename the field for MCP.
        input_schema = contract.get("input_schema", {
            "type": "object",
            "properties": {},
        })
        input_schema = _clean_schema_for_mcp(input_schema)

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

        input_schema = contract.get("input_schema", {"type": "object", "properties": {}})
        input_schema = _clean_schema_for_mcp(input_schema)

        return types.Tool(
            name=contract.get("name", "unknown"),
            description=description,
            inputSchema=input_schema,
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
