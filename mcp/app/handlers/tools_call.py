# MCP Tools Call Handler
"""Handles MCP tools/call request."""

import json
import logging
from typing import Any, Dict, List, Optional

from jsonschema import Draft7Validator, ValidationError

from app.config import settings
from app.models.mcp import (
    MCPError,
    MCPErrorCode,
    MCPTextContent,
    MCPToolsCallResponse,
)
from app.services.backend_client import backend_client
from app.services.policy_service import policy_service
from app.services.facet_validator import facet_validator

logger = logging.getLogger("mcp.handlers.tools_call")


async def handle_tools_call(
    name: str,
    arguments: Dict[str, Any],
    org_id: Optional[str] = None,
    api_key: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> MCPToolsCallResponse:
    """
    Handle MCP tools/call request.

    1. Validate tool is allowed by policy
    2. Validate arguments against JSON Schema
    3. Apply policy clamps
    4. Validate facets if present
    5. Execute via backend
    6. Return result in MCP format

    Args:
        name: Tool name
        arguments: Tool arguments
        org_id: Organization ID
        api_key: API key for backend authentication
        correlation_id: Request correlation ID

    Returns:
        MCP tool call response
    """
    org_id = org_id or settings.default_org_id

    # 1. Check if tool is allowed
    if not policy_service.is_allowed(name):
        logger.warning(f"Tool not allowed: {name}")
        return _error_response(
            MCPErrorCode.TOOL_NOT_FOUND,
            f"Tool '{name}' is not available",
        )

    # 2. Get contract for schema validation
    contract = await backend_client.get_contract(name, api_key, correlation_id)
    if not contract:
        return _error_response(
            MCPErrorCode.TOOL_NOT_FOUND,
            f"Tool '{name}' not found",
        )

    # Check side_effects (shouldn't happen if policy is correct, but double-check)
    if contract.get("side_effects", False) and policy_service.block_side_effects:
        return _error_response(
            MCPErrorCode.POLICY_VIOLATION,
            f"Tool '{name}' has side effects and is not allowed",
        )

    # 3. Validate arguments against input schema
    input_schema = contract.get("input_schema", {})
    validation_errors = _validate_arguments(arguments, input_schema)
    if validation_errors:
        return _error_response(
            MCPErrorCode.INVALID_ARGUMENT,
            f"Invalid arguments: {'; '.join(validation_errors)}",
        )

    # 4. Apply policy clamps
    clamped_arguments = policy_service.apply_clamps(name, arguments)
    if clamped_arguments != arguments:
        logger.debug(f"Applied clamps to {name}: {arguments} → {clamped_arguments}")

    # 5. Validate facets if present and enabled
    if policy_service.validate_facets and org_id:
        facet_filters = clamped_arguments.get("facet_filters")
        if facet_filters:
            is_valid, invalid_facets = await facet_validator.validate_facets(
                facet_filters,
                org_id,
                api_key,
                correlation_id,
            )
            if not is_valid:
                return _error_response(
                    MCPErrorCode.INVALID_ARGUMENT,
                    f"Unknown facets: {', '.join(invalid_facets)}",
                )

    # 6. Execute via backend
    logger.info(f"Executing tool: {name}")
    result = await backend_client.execute_function(
        name=name,
        params=clamped_arguments,
        api_key=api_key,
        correlation_id=correlation_id,
    )

    # 7. Convert result to MCP format
    return _format_result(result)


def _validate_arguments(
    arguments: Dict[str, Any],
    schema: Dict[str, Any],
) -> List[str]:
    """
    Validate arguments against JSON Schema.

    Returns list of error messages, empty if valid.
    """
    if not schema:
        return []

    try:
        validator = Draft7Validator(schema)
        errors = list(validator.iter_errors(arguments))
        return [f"{e.json_path}: {e.message}" for e in errors]
    except Exception as e:
        logger.warning(f"Schema validation error: {e}")
        return []


def _error_response(code: MCPErrorCode, message: str) -> MCPToolsCallResponse:
    """Create an error response."""
    return MCPToolsCallResponse(
        content=[MCPTextContent(type="text", text=f"Error: {message}")],
        isError=True,
    )


def _format_result(result: Dict[str, Any]) -> MCPToolsCallResponse:
    """Format backend result as MCP response."""
    status = result.get("status", "unknown")

    if status == "error" or result.get("error"):
        error_msg = result.get("error", "Unknown error")
        return MCPToolsCallResponse(
            content=[MCPTextContent(type="text", text=f"Error: {error_msg}")],
            isError=True,
        )

    # Format successful result
    data = result.get("data")
    message = result.get("message", "")

    if data is None:
        text = message or "Operation completed successfully"
    elif isinstance(data, str):
        text = data
    elif isinstance(data, (list, dict)):
        # Pretty-print JSON data
        text = json.dumps(data, indent=2, default=str)
    else:
        text = str(data)

    # Include metadata if present
    metadata = result.get("metadata", {})
    items_processed = result.get("items_processed", 0)
    if items_processed:
        metadata["items_processed"] = items_processed

    if metadata:
        text += f"\n\n---\nMetadata: {json.dumps(metadata, default=str)}"

    return MCPToolsCallResponse(
        content=[MCPTextContent(type="text", text=text)],
        isError=False,
    )
