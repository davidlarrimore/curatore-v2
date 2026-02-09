# MCP Tools Call Handler
"""Handles MCP tools/call request."""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

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
from app.services.progress_service import progress_service

logger = logging.getLogger("mcp.handlers.tools_call")


def extract_progress_token(arguments: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Extract MCP _meta.progressToken from arguments.

    Per MCP spec, clients can include:
    {
        "_meta": { "progressToken": "xyz" },
        "query": "...",
        ...
    }

    Returns:
        Tuple of (progress_token, cleaned_arguments without _meta)
    """
    progress_token = None
    clean_args = arguments.copy()

    meta = clean_args.pop("_meta", None)
    if meta and isinstance(meta, dict):
        progress_token = meta.get("progressToken")

    return progress_token, clean_args


async def handle_tools_call(
    name: str,
    arguments: Dict[str, Any],
    org_id: Optional[str] = None,
    api_key: Optional[str] = None,
    correlation_id: Optional[str] = None,
    progress_token: Optional[str] = None,
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

    # Extract progress token from arguments if not provided directly
    if not progress_token:
        progress_token, arguments = extract_progress_token(arguments)

    # Start progress tracking if token provided
    progress_state = None
    if progress_token:
        progress_state = progress_service.start(progress_token, name)
        progress_service.update(progress_token, progress=0, message="Validating request...")

    try:
        # 1. Check if tool is allowed
        if not policy_service.is_allowed(name):
            logger.warning(f"Tool not allowed: {name}")
            if progress_state:
                progress_service.fail(progress_token, f"Tool '{name}' is not available")
            return _error_response(
                MCPErrorCode.TOOL_NOT_FOUND,
                f"Tool '{name}' is not available",
            )

        if progress_state:
            progress_service.update(progress_token, progress=10, message="Fetching tool contract...")

        # 2. Get contract for schema validation
        contract = await backend_client.get_contract(name, api_key, correlation_id)
        if not contract:
            if progress_state:
                progress_service.fail(progress_token, f"Tool '{name}' not found")
            return _error_response(
                MCPErrorCode.TOOL_NOT_FOUND,
                f"Tool '{name}' not found",
            )

        # Check side_effects (respects side_effects_allowlist)
        if contract.get("side_effects", False) and policy_service.block_side_effects:
            # Allow if in side_effects_allowlist
            if name not in policy_service.policy.settings.side_effects_allowlist:
                if progress_state:
                    progress_service.fail(progress_token, f"Tool '{name}' has side effects")
                return _error_response(
                    MCPErrorCode.POLICY_VIOLATION,
                    f"Tool '{name}' has side effects and is not allowed",
                )

        if progress_state:
            progress_service.update(progress_token, progress=20, message="Validating arguments...")

        # 3. Validate arguments against input schema
        input_schema = contract.get("input_schema", {})
        validation_errors = _validate_arguments(arguments, input_schema)
        if validation_errors:
            if progress_state:
                progress_service.fail(progress_token, f"Invalid arguments: {'; '.join(validation_errors)}")
            return _error_response(
                MCPErrorCode.INVALID_ARGUMENT,
                f"Invalid arguments: {'; '.join(validation_errors)}",
            )

        # 4. Apply policy clamps
        clamped_arguments = policy_service.apply_clamps(name, arguments)
        if clamped_arguments != arguments:
            logger.debug(f"Applied clamps to {name}: {arguments} → {clamped_arguments}")

        if progress_state:
            progress_service.update(progress_token, progress=30, message="Validating facets...")

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
                    if progress_state:
                        progress_service.fail(progress_token, f"Unknown facets: {', '.join(invalid_facets)}")
                    return _error_response(
                        MCPErrorCode.INVALID_ARGUMENT,
                        f"Unknown facets: {', '.join(invalid_facets)}",
                    )

        if progress_state:
            progress_service.update(progress_token, progress=40, message=f"Executing {name}...")

        # 6. Execute via backend
        logger.info(f"Executing tool: {name}")
        result = await backend_client.execute_function(
            name=name,
            params=clamped_arguments,
            api_key=api_key,
            correlation_id=correlation_id,
        )

        if progress_state:
            progress_service.update(progress_token, progress=90, message="Formatting response...")

        # 7. Convert result to MCP format
        response = _format_result(result)

        if progress_state:
            progress_service.complete(progress_token, result)

        return response

    except Exception as e:
        logger.exception(f"Error executing tool {name}: {e}")
        if progress_state:
            progress_service.fail(progress_token, str(e))
        return _error_response(
            MCPErrorCode.EXECUTION_ERROR,
            f"Execution failed: {str(e)}",
        )


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
