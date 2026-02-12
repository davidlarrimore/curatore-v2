# backend/app/cwr/procedures/compiler/plan_compiler.py
"""
Plan Compiler - Converts a validated TypedPlan dict into a ProcedureDefinition-compatible dict.

Handles:
- Slug generation from procedure name
- Ref object resolution to Jinja2 template strings
- Template object resolution
- Policy clamps (search limit, LLM tokens)
- Parameter type mapping (string -> str, integer -> int, etc.)
- Branch compilation (recursive)

Usage:
    from app.cwr.procedures.compiler.plan_compiler import PlanCompiler

    compiler = PlanCompiler(profile)
    procedure_dict = compiler.compile(plan_dict)
"""

import logging
import re
from typing import Any, Dict

from app.cwr.governance.generation_profiles import GenerationProfile

logger = logging.getLogger("curatore.procedures.compiler.plan_compiler")

# Mapping from plan type names to procedure definition type names
_TYPE_MAP = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}


class PlanCompiler:
    """
    Compiles a validated plan dict into a ProcedureDefinition-compatible dict.

    The output dict can be passed to ProcedureDefinition.from_dict() or
    used directly with the procedure executor.
    """

    def __init__(self, profile: GenerationProfile):
        self._profile = profile

    def compile(self, plan_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compile a typed plan dict into a procedure definition dict.

        Args:
            plan_dict: Validated plan dict (matches TYPED_PLAN_JSON_SCHEMA)

        Returns:
            Dict compatible with ProcedureDefinition.from_dict()
        """
        procedure = plan_dict["procedure"]
        parameters = plan_dict.get("parameters", [])
        steps = plan_dict.get("steps", [])

        # Generate slug from name if missing
        slug = procedure.get("slug") or self._slugify(procedure["name"])

        # Build procedure dict
        result: Dict[str, Any] = {
            "name": procedure["name"],
            "slug": slug,
            "description": procedure.get("description", ""),
            "version": "1.0.0",
            "parameters": [self._compile_parameter(p) for p in parameters],
            "steps": [self._compile_step(s) for s in steps],
            "outputs": [],
            "triggers": [],
            "on_error": "fail",
            "tags": procedure.get("tags", []),
        }

        return result

    def _slugify(self, name: str) -> str:
        """Generate a slug from a procedure name."""
        slug = name.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "_", slug)
        slug = slug.strip("_")
        # Ensure starts with letter
        if slug and not slug[0].isalpha():
            slug = "p_" + slug
        return slug or "generated_procedure"

    def _compile_parameter(self, param: Dict[str, Any]) -> Dict[str, Any]:
        """Compile a plan parameter to a procedure parameter."""
        param_type = param.get("type", "string")
        mapped_type = _TYPE_MAP.get(param_type, param_type)

        result = {
            "name": param["name"],
            "type": mapped_type,
            "description": param.get("description", ""),
            "required": param.get("required", False),
        }

        if "default" in param and param["default"] is not None:
            result["default"] = param["default"]

        return result

    def _compile_step(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """Compile a plan step to a procedure step definition."""
        result: Dict[str, Any] = {
            "name": step["name"],
            "function": step["tool"],  # tool -> function mapping
            "params": self._compile_args(step.get("args", {})),
            "on_error": step.get("on_error", "fail"),
            "description": step.get("description", ""),
        }

        # Condition
        condition = step.get("condition")
        if condition is not None:
            result["condition"] = self._resolve_value(condition)

        # Foreach
        foreach = step.get("foreach")
        if foreach is not None:
            result["foreach"] = self._resolve_value(foreach)

        # Branches (recursive)
        branches = step.get("branches")
        if branches:
            result["branches"] = {
                branch_name: [self._compile_step(s) for s in branch_steps]
                for branch_name, branch_steps in branches.items()
            }

        # Apply policy clamps
        self._apply_clamps(result)

        return result

    def _compile_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Compile step args, resolving refs and templates to Jinja2 strings."""
        return {
            key: self._resolve_value(value)
            for key, value in args.items()
        }

    def _resolve_value(self, value: Any) -> Any:
        """
        Recursively resolve refs and templates to Jinja2 template strings.

        {"ref": "steps.search_results"} -> "{{ steps.search_results }}"
        {"ref": "steps.search_results.data"} -> "{{ steps.search_results.data }}"
        {"ref": "params.query"} -> "{{ params.query }}"
        {"template": "{{ steps.data | length }}"} -> "{{ steps.data | length }}"
        """
        if isinstance(value, dict):
            if "ref" in value and len(value) == 1:
                return "{{ " + value["ref"] + " }}"
            elif "template" in value and len(value) == 1:
                return value["template"]
            else:
                return {k: self._resolve_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._resolve_value(item) for item in value]
        else:
            return value

    def _apply_clamps(self, step: Dict[str, Any]) -> None:
        """Apply profile policy clamps to a compiled step."""
        params = step.get("params", {})
        func = step.get("function", "")

        # Clamp search limit
        if "limit" in params and isinstance(params["limit"], (int, float)):
            if params["limit"] > self._profile.max_search_limit:
                logger.info(
                    f"Clamping step '{step.get('name')}' limit from {params['limit']} "
                    f"to {self._profile.max_search_limit}"
                )
                params["limit"] = self._profile.max_search_limit

        # Clamp LLM max_tokens
        if "max_tokens" in params and isinstance(params["max_tokens"], (int, float)):
            if params["max_tokens"] > self._profile.max_llm_tokens:
                logger.info(
                    f"Clamping step '{step.get('name')}' max_tokens from {params['max_tokens']} "
                    f"to {self._profile.max_llm_tokens}"
                )
                params["max_tokens"] = self._profile.max_llm_tokens
