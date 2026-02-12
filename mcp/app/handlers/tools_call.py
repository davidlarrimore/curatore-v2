# MCP Tools Call Handler
"""Handles MCP tools/call request."""

import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from jsonschema import Draft7Validator

from app.config import settings
from app.models.mcp import (
    MCPErrorCode,
    MCPTextContent,
    MCPToolsCallResponse,
)
from app.services.backend_client import backend_client
from app.services.facet_validator import facet_validator
from app.services.policy_service import policy_service
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

    # Strip explicit null values — MCP clients often send "key": null for
    # optional parameters they don't intend to set.  Absent and null are
    # semantically equivalent for optional params, and Draft 7 validation
    # would otherwise reject null against a "type": "string" schema.
    arguments = {k: v for k, v in arguments.items() if v is not None}

    # Start progress tracking if token provided
    progress_state = None
    if progress_token:
        progress_state = progress_service.start(progress_token, name)
        progress_service.update(progress_token, progress=0, message="Validating request...")

    try:
        # 1. Quick denylist check (v2.0) or allowlist check (v1.0)
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

        # 2. Get contract for schema validation and exposure check
        contract = await backend_client.get_contract(name, api_key, correlation_id)
        if not contract:
            if progress_state:
                progress_service.fail(progress_token, f"Tool '{name}' not found")
            return _error_response(
                MCPErrorCode.TOOL_NOT_FOUND,
                f"Tool '{name}' not found",
            )

        # 2b. In v2.0 mode, verify exposure_profile allows agent access
        if policy_service.policy.is_v2:
            exposure = contract.get("exposure_profile", {})
            if not exposure.get("agent", False):
                logger.warning(f"Tool {name}: exposure_profile.agent is false")
                if progress_state:
                    progress_service.fail(progress_token, f"Tool '{name}' is not available")
                return _error_response(
                    MCPErrorCode.TOOL_NOT_FOUND,
                    f"Tool '{name}' is not available",
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
        response = _format_result(result, tool_name=name)

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


# Tools whose primary output is structured data (dicts/lists of extracted
# values, classifications, decisions, routes).  These get formatted as clean
# JSON so agents can parse the result precisely — markdown prose would lose
# the structure that is the whole point of these tools.
_STRUCTURED_OUTPUT_TOOLS: Set[str] = {
    "llm_extract",
    "llm_classify",
    "llm_decide",
    "llm_route",
}


def _format_result(
    result: Dict[str, Any],
    tool_name: str = "",
) -> MCPToolsCallResponse:
    """Format backend result as MCP response."""
    status = result.get("status", "unknown")

    if status in ("error", "failed") or result.get("error"):
        error_msg = result.get("error") or result.get("message") or "Unknown error"
        return MCPToolsCallResponse(
            content=[MCPTextContent(type="text", text=f"Error: {error_msg}")],
            isError=True,
        )

    data = result.get("data")
    message = result.get("message", "")
    metadata = result.get("metadata", {})
    items_processed = result.get("items_processed", 0)

    # Structured-output tools: return clean JSON, no prose.
    if tool_name in _STRUCTURED_OUTPUT_TOOLS and data is not None:
        text = json.dumps(data, indent=2, default=str)
        return MCPToolsCallResponse(
            content=[MCPTextContent(type="text", text=text)],
            isError=False,
        )

    parts: List[str] = []

    # Always lead with the human-readable message
    if message:
        parts.append(message)

    # Format data as readable markdown.
    # MCP TextContent.text must be human/LLM-readable text.
    if data is None:
        if not message:
            parts.append("Operation completed successfully.")
    elif isinstance(data, str):
        parts.append(data)
    elif isinstance(data, list):
        if len(data) == 0:
            if not message:
                parts.append("No results found.")
        elif _is_formattable_list(data):
            parts.append(_format_content_items(data))
        else:
            parts.append(_format_list_as_text(data))
    elif isinstance(data, dict):
        parts.append(_format_dict_as_text(data))
    else:
        parts.append(str(data))

    # Append clean metadata summary
    meta_text = _format_metadata(metadata, items_processed)
    if meta_text:
        parts.append(meta_text)

    text = "\n\n".join(parts)

    return MCPToolsCallResponse(
        content=[MCPTextContent(type="text", text=text)],
        isError=False,
    )


def _is_formattable_list(data: List[Any]) -> bool:
    """Check if a list contains dicts with id + title that we can format."""
    if not data or not isinstance(data[0], dict):
        return False
    first = data[0]
    return "id" in first and ("title" in first or "display_type" in first or "name" in first)


def _format_content_items(items: List[Dict[str, Any]]) -> str:
    """
    Format result dicts as readable markdown for LLM consumption.

    Handles both ContentItem dicts (nested fields/metadata) and flat
    search result dicts (forecasts, query_model results, etc.).
    """
    lines: List[str] = []

    for i, item in enumerate(items, 1):
        title = item.get("title") or item.get("name") or "Untitled"
        display_type = item.get("display_type") or item.get("type") or item.get("source_type") or "Item"
        item_id = item.get("id", "")

        lines.append(f"### {i}. {title}")
        lines.append(f"Type: {display_type} | ID: {item_id}")

        # Collect detail fields from both nested (ContentItem) and flat layouts
        fields = item.get("fields") or {}
        meta = item.get("metadata") or {}

        detail_parts: List[str] = []

        # Score — check both nested metadata and top-level
        score = meta.get("score") or item.get("score")
        if score is not None:
            try:
                detail_parts.append(f"Score: {float(score):.2f}")
            except (ValueError, TypeError):
                pass

        # Key fields — check both nested fields dict and top-level keys
        # NOTE: URL fields (source_url, url, detail_url, ui_link, instance_url)
        # are intentionally excluded. They contain hex strings that LLMs
        # confuse with item UUIDs, causing hallucinated IDs in follow-up calls.
        _DISPLAY_KEYS = (
            "source_type", "site_name", "content_type", "status",
            "original_filename", "folder_path",
            "created_at", "solicitation_number",
            "fiscal_year", "agency_name", "naics_code",
            "filename", "asset_id",
            # Salesforce fields
            "stage_name", "amount", "probability", "close_date",
            "opportunity_type", "role", "lead_source", "fiscal_quarter",
            "account_type", "industry", "department", "description",
            "email", "phone", "website", "custom_dates",
            # General
            "notice_type", "set_aside_code", "response_deadline",
            "posted_date", "bureau_name",
        )
        for key in _DISPLAY_KEYS:
            val = fields.get(key) or item.get(key)
            if val and key not in ("type", "id", "title", "score", "display_type", "name"):
                label = key.replace("_", " ").title()
                # Truncate long text values
                val_str = str(val)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "..."
                detail_parts.append(f"{label}: {val_str}")

        if detail_parts:
            lines.append(" | ".join(detail_parts))

        # Snippet / highlights — check nested metadata and top-level
        snippet = meta.get("snippet") or meta.get("highlights") or item.get("highlights")
        if snippet:
            # highlights can be {"content": ["..."]} or a list or a string
            if isinstance(snippet, dict):
                # Extract first content highlight
                content_highlights = snippet.get("content", [])
                if content_highlights:
                    snippet = content_highlights[0]
                else:
                    snippet = str(snippet)
            if isinstance(snippet, list):
                snippet = " ... ".join(str(s) for s in snippet[:3])
            # Strip HTML mark tags for cleaner display
            snippet_text = str(snippet)[:500].replace("<mark>", "**").replace("</mark>", "**")
            lines.append(f"> {snippet_text}")

        # Children count
        children_count = item.get("children_count", 0)
        if children_count > 0:
            lines.append(f"({children_count} attachments)")

        # Full text if present (for get_content results)
        text_content = item.get("text") or item.get("content")
        if text_content and isinstance(text_content, str):
            if len(text_content) > 4000:
                lines.append(text_content[:4000] + "\n... (truncated)")
            else:
                lines.append(text_content)

        lines.append("")  # blank line between items

    # Append a clean ID reference table so LLMs can copy exact UUIDs
    # without risk of confusing them with other hex strings in the output
    if len(items) > 1:
        lines.append("---")
        lines.append("ID Reference:")
        for i, item in enumerate(items, 1):
            item_id = item.get("id", "")
            title = item.get("title") or item.get("name") or "Untitled"
            lines.append(f"  {i}. {item_id} ({title})")

    return "\n".join(lines).rstrip()


def _format_dict_as_text(data: Dict[str, Any]) -> str:
    """
    Format a dict response as readable markdown text.

    If the dict contains a prominent list of dicts (e.g. source_types,
    items, results), formats those as numbered items.  Otherwise formats
    as key-value pairs.
    """
    # Find the most prominent list of dicts in the top-level keys
    primary_key: Optional[str] = None
    primary_list: Optional[List] = None
    best_len = 0
    for k, v in data.items():
        if isinstance(v, list) and len(v) > best_len and v and isinstance(v[0], dict):
            primary_key = k
            primary_list = v
            best_len = len(v)

    parts: List[str] = []

    if primary_list is not None:
        # Render non-list scalars as context line
        context = []
        for k, v in data.items():
            if k == primary_key or v is None:
                continue
            if isinstance(v, (str, int, float, bool)):
                context.append(f"{k.replace('_', ' ').title()}: {v}")
        if context:
            parts.append(" | ".join(context))

        # Render the primary list items
        if _is_formattable_list(primary_list):
            parts.append(_format_content_items(primary_list))
        else:
            parts.append(_format_list_as_text(primary_list))
    else:
        # Plain key-value dict
        parts.append(_format_kv(data))

    return "\n\n".join(p for p in parts if p)


def _format_list_as_text(data: List[Any]) -> str:
    """
    Format a list that doesn't match the ContentItem pattern as
    readable markdown text.
    """
    if not data:
        return "(none)"

    # Flat list of scalars
    if all(isinstance(x, (str, int, float, bool)) for x in data):
        return "\n".join(f"- {x}" for x in data)

    # List of dicts — render each as a numbered item
    if all(isinstance(x, dict) for x in data):
        lines: List[str] = []
        for i, item in enumerate(data, 1):
            name = (
                item.get("display_name")
                or item.get("name")
                or item.get("title")
                or item.get("label")
                or f"Item {i}"
            )
            lines.append(f"### {i}. {name}")
            lines.append(_format_kv(item, exclude={"display_name", "name", "title", "label"}))
            lines.append("")
        return "\n".join(lines).rstrip()

    # Mixed types
    return "\n".join(f"- {x}" for x in data)


def _format_kv(data: Dict[str, Any], exclude: Optional[set] = None) -> str:
    """
    Format a dict as readable key-value lines.

    Handles nested lists/dicts one level deep; truncates long strings.
    """
    exclude = exclude or set()
    lines: List[str] = []

    for k, v in data.items():
        if k in exclude or v is None:
            continue
        label = k.replace("_", " ").title()

        if isinstance(v, str):
            if len(v) > 300:
                v = v[:300] + "..."
            lines.append(f"{label}: {v}")
        elif isinstance(v, (int, float, bool)):
            lines.append(f"{label}: {v}")
        elif isinstance(v, list):
            if not v:
                continue
            if all(isinstance(x, (str, int, float, bool)) for x in v):
                lines.append(f"{label}: {', '.join(str(x) for x in v)}")
            elif all(isinstance(x, dict) for x in v):
                lines.append(f"{label}:")
                for item in v:
                    # Pick a display name for each sub-item
                    sub_name = (
                        item.get("name") or item.get("title") or item.get("tool")
                        or item.get("display_name") or item.get("label")
                    )
                    # Collect compact details
                    detail_parts = []
                    for sk, sv in item.items():
                        if sk in ("name", "title", "tool", "display_name", "label") or sv is None:
                            continue
                        sv_str = str(sv)
                        if len(sv_str) > 120:
                            sv_str = sv_str[:120] + "..."
                        detail_parts.append(f"{sk.replace('_', ' ')}: {sv_str}")
                    detail = f" — {', '.join(detail_parts)}" if detail_parts else ""
                    lines.append(f"  - {sub_name or '•'}{detail}")
            else:
                lines.append(f"{label}: {', '.join(str(x) for x in v)}")
        elif isinstance(v, dict):
            nested = ", ".join(
                f"{nk.replace('_', ' ').title()}: {nv}"
                for nk, nv in v.items() if nv is not None
            )
            if nested:
                lines.append(f"{label}: {nested}")
        else:
            lines.append(f"{label}: {v}")

    return "\n".join(lines)


def _format_metadata(metadata: Dict[str, Any], items_processed: int = 0) -> str:
    """Format metadata as a clean summary, omitting null/empty values."""
    if not metadata and not items_processed:
        return ""

    # Internal keys to skip
    skip_keys = {"result_type"}

    # Filter out nulls and internal keys
    clean: Dict[str, Any] = {}
    for k, v in metadata.items():
        if k in skip_keys:
            continue
        if v is None:
            continue
        if isinstance(v, dict):
            v = {nk: nv for nk, nv in v.items() if nv is not None}
            if not v:
                continue
        clean[k] = v

    if items_processed:
        clean["items_processed"] = items_processed

    if not clean:
        return ""

    # Format as readable key-value lines
    parts: List[str] = ["---"]
    for k, v in clean.items():
        label = k.replace("_", " ").title()
        if isinstance(v, dict):
            nested = ", ".join(f"{nk}={nv}" for nk, nv in v.items())
            parts.append(f"{label}: {nested}")
        elif isinstance(v, list):
            parts.append(f"{label}: {', '.join(str(x) for x in v)}")
        else:
            parts.append(f"{label}: {v}")

    return "\n".join(parts)
