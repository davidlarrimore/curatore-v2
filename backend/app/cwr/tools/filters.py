# backend/app/cwr/tools/filters.py
"""
CWR-wide ``where`` filter standard.

Provides a reusable operator-based condition format for filtering records by
JSONB metadata fields.  Any CWR tool that needs field-level filtering can
import ``WHERE_SCHEMA`` (a ready-made JSON Schema fragment) and
``build_jsonb_where`` (the SQLAlchemy clause builder).

Condition format::

    {"field": "sharepoint.site_name", "op": "is_empty"}
    {"field": "source.agency", "op": "eq", "value": "GSA"}

Conditions are implicitly ANDed together.
"""

from typing import Any, Dict, List

from sqlalchemy import func as sqla_func
from sqlalchemy import or_
from sqlalchemy.sql.elements import ClauseElement

# ---------------------------------------------------------------------------
# Operator catalogue
# ---------------------------------------------------------------------------

OPERATORS = frozenset({
    "eq", "neq",
    "gt", "gte", "lt", "lte",
    "in", "not_in",
    "contains",
    "is_empty", "is_not_empty",
})

UNARY_OPERATORS = frozenset({"is_empty", "is_not_empty"})

# ---------------------------------------------------------------------------
# JSON Schema for a single condition (used by contract generation)
# ---------------------------------------------------------------------------

WHERE_CONDITION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["field", "op"],
    "properties": {
        "field": {
            "type": "string",
            "description": "JSONB path as namespace.key (e.g., 'sharepoint.site_name')",
        },
        "op": {
            "type": "string",
            "enum": sorted(OPERATORS),
            "description": (
                "Comparison operator. Unary operators (is_empty, is_not_empty) "
                "do not require a value."
            ),
        },
        "value": {
            "description": (
                "Comparison value. Required for all operators except "
                "is_empty / is_not_empty. For 'in' and 'not_in', pass a list."
            ),
        },
    },
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Reusable JSON Schema fragment — import into any tool that needs ``where``
# ---------------------------------------------------------------------------

WHERE_SCHEMA: Dict[str, Any] = {
    "type": "array",
    "description": (
        "Operator-based metadata conditions. Each condition has 'field' "
        "(namespace.key JSONB path), 'op' (operator), and optional 'value'. "
        "Conditions are ANDed together. "
        "Operators: eq, neq, gt, gte, lt, lte, in, not_in, contains, "
        "is_empty, is_not_empty. "
        "Use 'is_empty' to find records where a field is null, missing, or "
        "empty string. Only applies when query='*'."
    ),
    "items": WHERE_CONDITION_SCHEMA,
    "examples": [[{"field": "sharepoint.site_name", "op": "is_empty"}]],
}

# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def validate_where(conditions: List[Dict[str, Any]]) -> List[str]:
    """
    Validate a list of ``where`` condition dicts.

    Returns a list of human-readable error strings (empty means valid).
    """
    errors: List[str] = []
    if not isinstance(conditions, list):
        return ["'where' must be a list of condition objects"]

    for idx, cond in enumerate(conditions):
        prefix = f"where[{idx}]"
        if not isinstance(cond, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        field_path = cond.get("field")
        op = cond.get("op")

        if not field_path or not isinstance(field_path, str):
            errors.append(f"{prefix}: 'field' is required and must be a string")
        elif "." not in field_path:
            errors.append(
                f"{prefix}: 'field' must be namespace.key format "
                f"(got '{field_path}')"
            )

        if not op or not isinstance(op, str):
            errors.append(f"{prefix}: 'op' is required and must be a string")
        elif op not in OPERATORS:
            errors.append(
                f"{prefix}: unknown operator '{op}'. "
                f"Valid: {', '.join(sorted(OPERATORS))}"
            )
        elif op not in UNARY_OPERATORS and "value" not in cond:
            errors.append(f"{prefix}: operator '{op}' requires a 'value'")

    return errors


# ---------------------------------------------------------------------------
# SQLAlchemy clause builder
# ---------------------------------------------------------------------------


def build_jsonb_where(
    column,
    conditions: List[Dict[str, Any]],
) -> List[ClauseElement]:
    """
    Convert ``where`` conditions to SQLAlchemy WHERE clauses against a JSONB
    column (e.g. ``Asset.source_metadata``).

    Args:
        column: SQLAlchemy JSONB column (e.g. ``Asset.source_metadata``)
        conditions: List of validated condition dicts

    Returns:
        List of clause elements to be applied with ``query.where(*clauses)``.
    """
    clauses: List[ClauseElement] = []

    for cond in conditions:
        field_path: str = cond["field"]
        op: str = cond["op"]
        value = cond.get("value")

        parts = field_path.split(".", 1)
        if len(parts) != 2:
            continue
        ns, fld = parts

        json_field = column[ns][fld]

        if op == "is_empty":
            clauses.append(
                or_(
                    column.is_(None),
                    ~column.has_key(ns),
                    ~column[ns].has_key(fld),
                    json_field.astext.is_(None),
                    json_field.astext == "",
                )
            )
        elif op == "is_not_empty":
            clauses.append(column.has_key(ns))
            clauses.append(column[ns].has_key(fld))
            clauses.append(json_field.astext.isnot(None))
            clauses.append(json_field.astext != "")
        elif op == "eq" and value is not None:
            clauses.append(json_field.astext == str(value))
        elif op == "neq" and value is not None:
            clauses.append(
                or_(
                    ~column[ns].has_key(fld),
                    json_field.astext != str(value),
                )
            )
        elif op == "gt" and value is not None:
            clauses.append(json_field.astext > str(value))
        elif op == "gte" and value is not None:
            clauses.append(json_field.astext >= str(value))
        elif op == "lt" and value is not None:
            clauses.append(json_field.astext < str(value))
        elif op == "lte" and value is not None:
            clauses.append(json_field.astext <= str(value))
        elif op == "in" and isinstance(value, list):
            clauses.append(json_field.astext.in_([str(v) for v in value]))
        elif op == "not_in" and isinstance(value, list):
            clauses.append(json_field.astext.notin_([str(v) for v in value]))
        elif op == "contains" and value is not None:
            clauses.append(
                sqla_func.lower(json_field.astext).contains(str(value).lower())
            )

    return clauses
