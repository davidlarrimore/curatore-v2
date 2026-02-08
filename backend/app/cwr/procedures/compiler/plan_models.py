# backend/app/cwr/procedures/compiler/plan_models.py
"""
Typed Plan Models - Intermediate representation for AI-generated procedures.

The LLM emits a Typed Plan as JSON instead of raw YAML. This allows
schema-first validation, incremental repair, and clean compilation to
the final ProcedureDefinition format.

Reference syntax:
    {"ref": "steps.step_name"}           - Reference a step's output
    {"ref": "steps.step_name.field"}     - Reference a field from step output
    {"ref": "params.param_name"}         - Reference a procedure parameter

Usage:
    from app.cwr.procedures.compiler.plan_models import TypedPlan, TYPED_PLAN_JSON_SCHEMA

    plan = TypedPlan.from_dict(llm_output)
    plan_dict = plan.to_dict()
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("curatore.procedures.compiler.plan_models")


@dataclass
class PlanProcedure:
    """Top-level procedure metadata in a typed plan."""
    name: str
    description: str
    slug: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = {"name": self.name, "description": self.description}
        if self.slug:
            d["slug"] = self.slug
        if self.tags:
            d["tags"] = self.tags
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanProcedure":
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            slug=data.get("slug"),
            tags=data.get("tags", []),
        )


@dataclass
class PlanParameter:
    """A procedure parameter in a typed plan."""
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    default: Any = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
        }
        if self.default is not None:
            d["default"] = self.default
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanParameter":
        return cls(
            name=data["name"],
            type=data.get("type", "string"),
            description=data.get("description", ""),
            required=data.get("required", False),
            default=data.get("default"),
        )


@dataclass
class PlanStep:
    """
    A single step in a typed plan.

    Args can contain literal values or reference objects:
        {"ref": "steps.step_name"}
        {"ref": "steps.step_name.field"}
        {"ref": "params.param_name"}

    Complex template expressions use a "template" key:
        {"template": "{{ steps.search_results | length }}"}
    """
    name: str
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    uses: Optional[List[str]] = None  # Declared dependencies (step names)
    outputs: Optional[str] = None  # Human-readable description of output
    on_error: str = "fail"
    condition: Optional[str] = None
    foreach: Optional[Any] = None  # ref or template for iteration
    branches: Optional[Dict[str, List["PlanStep"]]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "tool": self.tool,
            "args": self.args,
        }
        if self.description:
            d["description"] = self.description
        if self.uses:
            d["uses"] = self.uses
        if self.outputs:
            d["outputs"] = self.outputs
        if self.on_error != "fail":
            d["on_error"] = self.on_error
        if self.condition is not None:
            d["condition"] = self.condition
        if self.foreach is not None:
            d["foreach"] = self.foreach
        if self.branches is not None:
            d["branches"] = {
                branch_name: [s.to_dict() for s in steps]
                for branch_name, steps in self.branches.items()
            }
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanStep":
        branches = None
        if data.get("branches"):
            branches = {
                branch_name: [PlanStep.from_dict(s) for s in steps]
                for branch_name, steps in data["branches"].items()
            }
        return cls(
            name=data["name"],
            tool=data["tool"],
            args=data.get("args", {}),
            description=data.get("description", ""),
            uses=data.get("uses"),
            outputs=data.get("outputs"),
            on_error=data.get("on_error", "fail"),
            condition=data.get("condition"),
            foreach=data.get("foreach"),
            branches=branches,
        )


@dataclass
class TypedPlan:
    """
    Complete typed plan - the intermediate representation between
    LLM output and compiled ProcedureDefinition.
    """
    procedure: PlanProcedure
    parameters: List[PlanParameter] = field(default_factory=list)
    steps: List[PlanStep] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "procedure": self.procedure.to_dict(),
            "parameters": [p.to_dict() for p in self.parameters],
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TypedPlan":
        return cls(
            procedure=PlanProcedure.from_dict(data["procedure"]),
            parameters=[PlanParameter.from_dict(p) for p in data.get("parameters", [])],
            steps=[PlanStep.from_dict(s) for s in data.get("steps", [])],
        )


def is_ref(value: Any) -> bool:
    """Check if a value is a reference object ({"ref": "..."})."""
    return isinstance(value, dict) and "ref" in value and len(value) == 1


def is_template(value: Any) -> bool:
    """Check if a value is a template object ({"template": "..."})."""
    return isinstance(value, dict) and "template" in value and len(value) == 1


def parse_ref(ref_str: str) -> tuple:
    """
    Parse a reference string into (namespace, name, field).

    Examples:
        "steps.search_results" -> ("steps", "search_results", None)
        "steps.search_results.data" -> ("steps", "search_results", "data")
        "params.query" -> ("params", "query", None)

    Returns:
        (namespace, name, field_or_none)
    """
    parts = ref_str.split(".", 2)
    if len(parts) < 2:
        return (ref_str, None, None)
    namespace = parts[0]
    name = parts[1]
    rest = parts[2] if len(parts) > 2 else None
    return (namespace, name, rest)


# ---------------------------------------------------------------------------
# JSON Schema for validating Typed Plan structure
# ---------------------------------------------------------------------------

_STEP_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["name", "tool"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "tool": {"type": "string", "minLength": 1},
        "args": {"type": "object"},
        "description": {"type": "string"},
        "uses": {"type": "array", "items": {"type": "string"}},
        "outputs": {"type": "string"},
        "on_error": {"type": "string", "enum": ["fail", "skip", "continue"]},
        "condition": {"type": "string"},
        "foreach": {},  # Can be ref object, template, or string
        "branches": {
            "type": "object",
            "additionalProperties": {
                "type": "array",
                "items": {"$ref": "#/$defs/step"},
            },
        },
    },
    "additionalProperties": False,
}

TYPED_PLAN_JSON_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["procedure", "steps"],
    "properties": {
        "procedure": {
            "type": "object",
            "required": ["name", "description"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "description": {"type": "string"},
                "slug": {"type": "string", "pattern": "^[a-z][a-z0-9_-]*$"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "parameters": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "type": {"type": "string", "enum": ["string", "integer", "boolean", "array", "object", "number"]},
                    "description": {"type": "string"},
                    "required": {"type": "boolean"},
                    "default": {},
                },
                "additionalProperties": False,
            },
        },
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/step"},
        },
    },
    "additionalProperties": False,
    "$defs": {
        "step": _STEP_SCHEMA,
    },
}
