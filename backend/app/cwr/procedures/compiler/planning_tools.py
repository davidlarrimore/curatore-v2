"""
Planning Tools — Converts CWR functions to OpenAI tool-calling format for the
AI procedure generator's research phase.

Provides:
  - Governance-based auto-selection of read-only planning tools
  - OpenAI function-calling format converter
  - Tool executor that routes calls through the CWR function registry
  - Result truncation for large outputs
"""

import copy
import json
import logging
from typing import Any, Dict, List, Set

from app.cwr.tools.base import FunctionCategory
from app.cwr.tools.context import FunctionContext
from app.cwr.tools.registry import function_registry

logger = logging.getLogger("curatore.procedures.compiler.planning_tools")

# Planning tools are auto-selected based on governance metadata.
# Criteria: side_effects=False, requires_llm=False, category in eligible set.
PLANNING_ELIGIBLE_CATEGORIES: Set[str] = {
    FunctionCategory.SEARCH.value,
    FunctionCategory.DATA.value,
}

MAX_SINGLE_RESULT_CHARS = 4000


def _clean_schema_for_planning(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean a JSON Schema for OpenAI function-calling:
    1. Remove x-procedure-only properties
    2. Strip "default": null (confuses LLMs)
    """
    schema = copy.deepcopy(schema)
    props = schema.get("properties")
    if not isinstance(props, dict):
        return schema

    to_remove = [
        key for key, defn in props.items()
        if isinstance(defn, dict) and defn.get("x-procedure-only")
    ]
    for key in to_remove:
        del props[key]

    required = schema.get("required")
    if isinstance(required, list) and to_remove:
        schema["required"] = [r for r in required if r not in to_remove]

    for defn in props.values():
        if isinstance(defn, dict) and defn.get("default") is None and "default" in defn:
            del defn["default"]

    return schema


def get_planning_tools_openai_format() -> List[Dict[str, Any]]:
    """
    Convert eligible CWR planning tools to OpenAI function-calling format.

    Tools are auto-selected based on governance metadata:
    - side_effects=False (read-only)
    - requires_llm=False (no LLM dependency)
    - category in PLANNING_ELIGIBLE_CATEGORIES (SEARCH or DATA)

    Returns a list of tool definitions suitable for the ``tools`` parameter
    of ``chat.completions.create()``.
    """
    function_registry.initialize()
    tools: List[Dict[str, Any]] = []

    for contract in function_registry.list_contracts():
        if contract.side_effects:
            continue
        if contract.requires_llm:
            continue
        if contract.category not in PLANNING_ELIGIBLE_CATEGORIES:
            continue

        cleaned_schema = _clean_schema_for_planning(contract.input_schema)

        tools.append({
            "type": "function",
            "function": {
                "name": contract.name,
                "description": contract.description,
                "parameters": cleaned_schema,
            },
        })

    return tools


async def execute_planning_tool(
    name: str,
    args: Dict[str, Any],
    ctx: FunctionContext,
) -> Dict[str, Any]:
    """
    Execute a planning tool via the CWR function registry.

    Validates that the function is planning-eligible using governance metadata
    (side_effects=False, requires_llm=False, category in eligible set).

    Args:
        name: Function name (must pass governance eligibility checks)
        args: Function arguments from the LLM
        ctx: FunctionContext with session and organization_id

    Returns:
        Dict with ``success``, ``data`` (or ``error``), and ``summary``.
    """
    # Validate tool is planning-eligible via governance metadata
    contract = function_registry.get_contract(name)
    if contract is None:
        return {
            "success": False,
            "error": f"Function '{name}' not found in registry",
            "summary": "Error: function not found",
        }
    if contract.side_effects or contract.requires_llm:
        return {
            "success": False,
            "error": f"'{name}' is not a planning tool (has side effects or requires LLM)",
            "summary": "Error: not a planning tool",
        }
    if contract.category not in PLANNING_ELIGIBLE_CATEGORIES:
        return {
            "success": False,
            "error": f"'{name}' category '{contract.category}' not eligible for planning",
            "summary": "Error: not a planning tool",
        }

    func = function_registry.get(name)
    try:
        result = await func(ctx, **args)
        data = _serialize_result(result.data)
        summary = _build_summary(name, result)
        return {
            "success": result.status.value == "success",
            "data": data,
            "summary": summary,
            "message": result.message or "",
        }
    except Exception as e:
        logger.exception(f"Planning tool '{name}' failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "summary": f"Error executing {name}: {e}",
        }


def _serialize_result(data: Any) -> Any:
    """Serialize function result data to JSON-compatible format."""
    if data is None:
        return None
    if isinstance(data, list):
        items = []
        for item in data:
            if hasattr(item, "to_dict"):
                items.append(item.to_dict())
            elif hasattr(item, "__dict__"):
                items.append({k: v for k, v in item.__dict__.items() if not k.startswith("_")})
            else:
                items.append(item)
        return items
    if hasattr(data, "to_dict"):
        return data.to_dict()
    if hasattr(data, "__dict__"):
        return {k: v for k, v in data.__dict__.items() if not k.startswith("_")}
    return data


def _build_summary(name: str, result: Any) -> str:
    """Build a short human-readable summary of a tool result."""
    if result.status.value != "success":
        return f"{name} failed: {result.error or result.message or 'unknown error'}"

    msg = result.message or ""
    count = result.items_processed or 0

    if count > 0:
        return f"{name}: {msg}" if msg else f"{name}: {count} items"
    return f"{name}: {msg}" if msg else f"{name}: completed"


def format_tool_result_for_llm(result: Dict[str, Any]) -> str:
    """
    Format a tool result as a string for the LLM conversation.
    Truncates large results with a summary.
    """
    if not result.get("success"):
        return json.dumps({"error": result.get("error", "unknown error")})

    data = result.get("data")
    try:
        text = json.dumps(data, indent=2, default=str)
    except (TypeError, ValueError):
        text = str(data)

    if len(text) <= MAX_SINGLE_RESULT_CHARS:
        return text

    # Truncate: show count + first items
    if isinstance(data, list):
        truncated = data[:5]
        try:
            preview = json.dumps(truncated, indent=2, default=str)
        except (TypeError, ValueError):
            preview = str(truncated)
        return f"{preview}\n\n[truncated: {len(data)} total items, showing first 5]"

    return text[:MAX_SINGLE_RESULT_CHARS] + f"\n\n[truncated at {MAX_SINGLE_RESULT_CHARS} chars]"
