# backend/app/cwr/tools/schema_utils.py
"""
Schema utilities for the Curatore Functions Framework.

Provides ContractView (frozen dataclass replacing ToolContract) and helpers
for converting legacy type strings to JSON Schema.

Usage:
    from app.cwr.tools.schema_utils import ContractView

    view = some_function.meta.as_contract()
    print(view.input_schema)
"""

import copy
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional

# Mapping from legacy type strings to JSON Schema types.
# Used by the migration script and param_type_to_json_schema().
TYPE_MAP: Dict[str, Dict[str, Any]] = {
    "str": {"type": "string"},
    "string": {"type": "string"},
    "int": {"type": "integer"},
    "integer": {"type": "integer"},
    "float": {"type": "number"},
    "number": {"type": "number"},
    "bool": {"type": "boolean"},
    "boolean": {"type": "boolean"},
    "list": {"type": "array"},
    "list[str]": {"type": "array", "items": {"type": "string"}},
    "list[string]": {"type": "array", "items": {"type": "string"}},
    "list[int]": {"type": "array", "items": {"type": "integer"}},
    "list[dict]": {"type": "array", "items": {"type": "object"}},
    "list[object]": {"type": "array", "items": {"type": "object"}},
    "dict": {"type": "object"},
    "object": {"type": "object"},
    "any": {},
}


def param_type_to_json_schema(type_str: str) -> Dict[str, Any]:
    """
    Convert a type string to a JSON Schema type definition.

    Args:
        type_str: Type string (e.g., "str", "list[str]", "dict")

    Returns:
        JSON Schema type definition dict
    """
    normalized = type_str.strip().lower()
    return copy.deepcopy(TYPE_MAP.get(normalized, {"type": "string"}))


@dataclass(frozen=True)
class ContractView:
    """
    Read-only view of a function's contract.

    Drop-in replacement for the deleted ToolContract dataclass.
    Produced by FunctionMeta.as_contract().
    """

    name: str
    description: str
    category: str
    version: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    side_effects: bool
    is_primitive: bool
    payload_profile: str
    exposure_profile: Dict[str, Any]
    requires_llm: bool
    requires_session: bool
    tags: List[str]
    required_data_sources: Optional[List[str]] = field(default=None)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {f.name: getattr(self, f.name) for f in fields(self)}
