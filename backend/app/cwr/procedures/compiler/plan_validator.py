# backend/app/cwr/procedures/compiler/plan_validator.py
"""
Plan Validator - Validates a TypedPlan against schema, tool contracts,
reference integrity, and side-effect policies.

Four validation layers:
1. Schema - jsonschema validation against TYPED_PLAN_JSON_SCHEMA
2. Tool args - each step's tool exists in pack, args match input_schema
3. References - all {"ref": "..."} resolve, no forward refs, no circular deps
4. Side-effect policy - blocked tools rejected, admin requires confirmation

Usage:
    from app.cwr.procedures.compiler.plan_validator import PlanValidator

    validator = PlanValidator(contract_pack)
    result = validator.validate(plan_dict)
"""

import logging
from typing import Any, Dict, List, Optional, Set

import jsonschema

from app.cwr.contracts.contract_pack import ToolContractPack
from app.cwr.contracts.validation import ValidationError, ValidationErrorCode, ValidationResult
from app.cwr.procedures.compiler.plan_models import (
    TYPED_PLAN_JSON_SCHEMA,
    is_ref,
    is_template,
    parse_ref,
)

logger = logging.getLogger("curatore.procedures.compiler.plan_validator")


class PlanValidator:
    """
    Validates a typed plan dict against schema, contracts, references,
    and side-effect policy.
    """

    def __init__(self, contract_pack: ToolContractPack):
        self._pack = contract_pack
        self._profile = contract_pack.profile

    def validate(self, plan_dict: Dict[str, Any]) -> ValidationResult:
        """
        Run all validation layers on a plan dict.

        Args:
            plan_dict: Raw plan dictionary (as parsed from LLM JSON output)

        Returns:
            ValidationResult with errors and warnings
        """
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []

        # Layer 1: JSON Schema validation
        schema_errors = self._validate_schema(plan_dict)
        errors.extend(schema_errors)
        if schema_errors:
            # Schema failures prevent further validation
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        steps = plan_dict.get("steps", [])
        parameters = plan_dict.get("parameters", [])

        # Layer 2: Tool existence and arg validation
        tool_errors = self._validate_tools(steps)
        errors.extend(tool_errors)

        # Layer 3: Reference validation
        param_names = {p["name"] for p in parameters}
        ref_errors = self._validate_references(steps, param_names)
        errors.extend(ref_errors)

        # Layer 4: Side-effect policy
        policy_errors, policy_warnings = self._validate_side_effect_policy(steps)
        errors.extend(policy_errors)
        warnings.extend(policy_warnings)

        # Layer 5: Facet validation (warnings only)
        facet_warnings = self._validate_facets(steps)
        warnings.extend(facet_warnings)

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Layer 1: Schema
    # ------------------------------------------------------------------

    def _validate_schema(self, plan_dict: Dict[str, Any]) -> List[ValidationError]:
        """Validate plan dict against TYPED_PLAN_JSON_SCHEMA."""
        errors = []
        try:
            jsonschema.validate(instance=plan_dict, schema=TYPED_PLAN_JSON_SCHEMA)
        except jsonschema.ValidationError as e:
            path = ".".join(str(p) for p in e.absolute_path) or "root"
            errors.append(ValidationError(
                code=ValidationErrorCode.INVALID_FIELD_TYPE,
                message=f"Schema error at '{path}': {e.message}",
                path=path,
                details={"schema_path": list(e.absolute_schema_path)},
            ))
        except jsonschema.SchemaError as e:
            errors.append(ValidationError(
                code=ValidationErrorCode.INVALID_FIELD_TYPE,
                message=f"Internal schema error: {e.message}",
                path="root",
            ))
        return errors

    # ------------------------------------------------------------------
    # Layer 2: Tool existence + arg validation
    # ------------------------------------------------------------------

    def _validate_tools(self, steps: List[Dict], base_path: str = "steps") -> List[ValidationError]:
        """Validate that each step's tool exists and args match input_schema."""
        errors: List[ValidationError] = []

        for idx, step in enumerate(steps):
            step_path = f"{base_path}[{idx}]"
            tool_name = step.get("tool", "")
            args = step.get("args", {})

            contract = self._pack.get_contract(tool_name)
            if not contract:
                available = self._pack.get_tool_names()
                errors.append(ValidationError(
                    code=ValidationErrorCode.UNKNOWN_FUNCTION,
                    message=f"Unknown or unavailable tool: '{tool_name}'",
                    path=f"{step_path}.tool",
                    details={"tool": tool_name, "available": available},
                ))
                # Can't validate args without contract
            else:
                arg_errors = self._validate_step_args(contract, args, step_path)
                errors.extend(arg_errors)

            # Recursively validate branches
            branches = step.get("branches")
            if branches and isinstance(branches, dict):
                for branch_name, branch_steps in branches.items():
                    if isinstance(branch_steps, list):
                        branch_errors = self._validate_tools(
                            branch_steps,
                            base_path=f"{step_path}.branches.{branch_name}",
                        )
                        errors.extend(branch_errors)

        return errors

    def _validate_step_args(
        self,
        contract: Any,
        args: Dict[str, Any],
        step_path: str,
    ) -> List[ValidationError]:
        """Validate step args against the tool's input_schema."""
        errors: List[ValidationError] = []
        input_schema = contract.input_schema
        properties = input_schema.get("properties", {})
        required_params = set(input_schema.get("required", []))

        # Check required params
        provided = set(args.keys())
        for param_name in required_params:
            if param_name not in provided:
                val = args.get(param_name)
                # Template refs satisfy the requirement
                if is_ref(val) or is_template(val):
                    continue
                errors.append(ValidationError(
                    code=ValidationErrorCode.MISSING_REQUIRED_PARAM,
                    message=f"Missing required arg '{param_name}' for tool '{contract.name}'",
                    path=f"{step_path}.args.{param_name}",
                    details={"tool": contract.name, "parameter": param_name},
                ))

        # Type-check literal values (skip refs and templates)
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        for arg_name, arg_val in args.items():
            if arg_name not in properties:
                continue  # Extra args allowed (functions may accept **kwargs)
            if is_ref(arg_val) or is_template(arg_val):
                continue
            if isinstance(arg_val, str) and "{{" in arg_val:
                continue  # Legacy template string

            prop_schema = properties[arg_name]
            expected_type = prop_schema.get("type")
            if not expected_type:
                continue

            python_type = type_map.get(expected_type)
            if python_type and not isinstance(arg_val, python_type):
                errors.append(ValidationError(
                    code=ValidationErrorCode.INVALID_PARAM_TYPE,
                    message=f"Arg '{arg_name}' for '{contract.name}' expects '{expected_type}' but got '{type(arg_val).__name__}'",
                    path=f"{step_path}.args.{arg_name}",
                    details={
                        "tool": contract.name,
                        "parameter": arg_name,
                        "expected_type": expected_type,
                        "actual_type": type(arg_val).__name__,
                    },
                ))

            # Enum validation
            enum_values = prop_schema.get("enum")
            if enum_values and arg_val not in enum_values:
                errors.append(ValidationError(
                    code=ValidationErrorCode.INVALID_PARAM_TYPE,
                    message=f"Arg '{arg_name}' value '{arg_val}' not in allowed values: {enum_values}",
                    path=f"{step_path}.args.{arg_name}",
                    details={
                        "tool": contract.name,
                        "parameter": arg_name,
                        "value": arg_val,
                        "allowed_values": enum_values,
                    },
                ))

        return errors

    # ------------------------------------------------------------------
    # Layer 3: Reference resolution
    # ------------------------------------------------------------------

    def _validate_references(
        self,
        steps: List[Dict],
        param_names: Set[str],
    ) -> List[ValidationError]:
        """Validate all refs resolve and there are no forward references."""
        errors: List[ValidationError] = []
        seen_steps: Set[str] = set()

        self._validate_refs_in_steps(steps, param_names, seen_steps, "steps", errors)
        return errors

    def _validate_refs_in_steps(
        self,
        steps: List[Dict],
        param_names: Set[str],
        seen_steps: Set[str],
        base_path: str,
        errors: List[ValidationError],
        extra_context: Optional[Set[str]] = None,
    ) -> None:
        """Recursively validate references in a step list."""
        local_seen = set(seen_steps)
        extra_context = extra_context or set()

        for idx, step in enumerate(steps):
            step_name = step.get("name", "")
            step_path = f"{base_path}[{idx}]"
            tool_name = step.get("tool", "")

            # Validate refs in args
            self._check_refs_in_value(
                step.get("args", {}), local_seen, param_names,
                f"{step_path}.args", step_name, errors, extra_context,
            )

            # Validate refs in condition
            if step.get("condition"):
                self._check_refs_in_value(
                    step["condition"], local_seen, param_names,
                    f"{step_path}.condition", step_name, errors, extra_context,
                )

            # Validate refs in foreach
            if step.get("foreach"):
                self._check_refs_in_value(
                    step["foreach"], local_seen, param_names,
                    f"{step_path}.foreach", step_name, errors, extra_context,
                )

            # Validate branches recursively
            branches = step.get("branches")
            if branches and isinstance(branches, dict):
                branch_extra = set(extra_context)
                if tool_name == "foreach":
                    branch_extra.add("item")
                    branch_extra.add("item_index")

                for branch_name, branch_steps in branches.items():
                    if isinstance(branch_steps, list):
                        self._validate_refs_in_steps(
                            branch_steps, param_names, local_seen,
                            f"{step_path}.branches.{branch_name}",
                            errors, branch_extra,
                        )

            local_seen.add(step_name)

    def _check_refs_in_value(
        self,
        value: Any,
        seen_steps: Set[str],
        param_names: Set[str],
        path: str,
        current_step: str,
        errors: List[ValidationError],
        extra_context: Set[str],
    ) -> None:
        """Check reference objects within a value tree."""
        if is_ref(value):
            ref_str = value["ref"]
            namespace, name, _ = parse_ref(ref_str)

            if namespace == "steps":
                if name == current_step:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.CIRCULAR_DEPENDENCY,
                        message=f"Step '{current_step}' references itself via ref '{ref_str}'",
                        path=path,
                        details={"step": current_step, "reference": ref_str},
                    ))
                elif name and name not in seen_steps:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.INVALID_STEP_REFERENCE,
                        message=f"Step '{current_step}' references unknown or future step '{name}' via ref '{ref_str}'",
                        path=path,
                        details={
                            "step": current_step,
                            "reference": ref_str,
                            "available_steps": sorted(seen_steps),
                        },
                    ))
            elif namespace == "params":
                if name and name not in param_names:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.INVALID_PARAM_REFERENCE,
                        message=f"Step '{current_step}' references undefined parameter '{name}' via ref '{ref_str}'",
                        path=path,
                        details={
                            "step": current_step,
                            "reference": ref_str,
                            "defined_params": sorted(param_names),
                        },
                    ))
            # else: unknown namespace, could be 'item', 'item_index' etc.
            # only flag if not in extra_context
            elif namespace not in extra_context and namespace not in ("item", "item_index"):
                pass  # Allow unknown namespaces for extensibility

        elif is_template(value):
            # Template strings use {{ }} syntax, validated at compile time
            pass

        elif isinstance(value, str) and "{{" in value:
            # Legacy inline template - check for step/param refs
            import re
            for match in re.finditer(r"steps\.([a-zA-Z_][a-zA-Z0-9_]*)", value):
                ref_step = match.group(1)
                if ref_step == current_step:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.CIRCULAR_DEPENDENCY,
                        message=f"Step '{current_step}' references itself in template",
                        path=path,
                        details={"step": current_step, "reference": ref_step},
                    ))
                elif ref_step not in seen_steps:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.INVALID_STEP_REFERENCE,
                        message=f"Step '{current_step}' references unknown or future step '{ref_step}'",
                        path=path,
                        details={
                            "step": current_step,
                            "reference": ref_step,
                            "available_steps": sorted(seen_steps),
                        },
                    ))

            for match in re.finditer(r"params\.([a-zA-Z_][a-zA-Z0-9_]*)", value):
                ref_param = match.group(1)
                if ref_param not in param_names:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.INVALID_PARAM_REFERENCE,
                        message=f"Step '{current_step}' references undefined parameter '{ref_param}'",
                        path=path,
                        details={
                            "step": current_step,
                            "reference": ref_param,
                            "defined_params": sorted(param_names),
                        },
                    ))

        elif isinstance(value, dict):
            for key, val in value.items():
                self._check_refs_in_value(
                    val, seen_steps, param_names,
                    f"{path}.{key}", current_step, errors, extra_context,
                )

        elif isinstance(value, list):
            for i, item in enumerate(value):
                self._check_refs_in_value(
                    item, seen_steps, param_names,
                    f"{path}[{i}]", current_step, errors, extra_context,
                )

    # ------------------------------------------------------------------
    # Layer 4: Side-effect policy
    # ------------------------------------------------------------------

    def _validate_side_effect_policy(
        self, steps: List[Dict], base_path: str = "steps"
    ) -> tuple:
        """Validate side-effect policy for the profile."""
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []

        for idx, step in enumerate(steps):
            step_path = f"{base_path}[{idx}]"
            tool_name = step.get("tool", "")

            contract = self._pack.get_contract(tool_name)
            if not contract:
                continue

            # Check if tool is blocked by profile
            if tool_name in self._profile.blocked_tools:
                errors.append(ValidationError(
                    code=ValidationErrorCode.TOOL_BLOCKED_BY_PROFILE,
                    message=f"Tool '{tool_name}' is blocked by profile '{self._profile.name.value}'",
                    path=f"{step_path}.tool",
                    details={
                        "tool": tool_name,
                        "profile": self._profile.name.value,
                    },
                ))

            # Admin profile requires confirmation on side-effect steps
            if (
                contract.side_effects
                and self._profile.require_side_effect_confirmation
            ):
                args = step.get("args", {})
                if not args.get("confirm_side_effects"):
                    errors.append(ValidationError(
                        code=ValidationErrorCode.MISSING_SIDE_EFFECT_CONFIRMATION,
                        message=f"Side-effect tool '{tool_name}' requires 'confirm_side_effects: true' under admin_full profile",
                        path=f"{step_path}.args.confirm_side_effects",
                        details={
                            "tool": tool_name,
                            "profile": self._profile.name.value,
                        },
                    ))

            # Recursively check branches
            branches = step.get("branches")
            if branches and isinstance(branches, dict):
                for branch_name, branch_steps in branches.items():
                    if isinstance(branch_steps, list):
                        be, bw = self._validate_side_effect_policy(
                            branch_steps,
                            base_path=f"{step_path}.branches.{branch_name}",
                        )
                        errors.extend(be)
                        warnings.extend(bw)

        return errors, warnings

    # ------------------------------------------------------------------
    # Layer 5: Facet validation (warnings)
    # ------------------------------------------------------------------

    def _validate_facets(self, steps: List[Dict], base_path: str = "steps") -> List[ValidationError]:
        """Validate facet_filters in step args against known facets."""
        warnings: List[ValidationError] = []

        for idx, step in enumerate(steps):
            step_path = f"{base_path}[{idx}]"
            args = step.get("args", {})
            facet_filters = args.get("facet_filters")

            if not facet_filters or not isinstance(facet_filters, dict):
                continue

            try:
                from app.core.metadata.registry_service import metadata_registry_service
                known_facets = metadata_registry_service.get_facet_definitions()
            except Exception:
                continue

            if not known_facets:
                continue

            for facet_name in facet_filters.keys():
                if isinstance(facet_name, str) and "{{" in facet_name:
                    continue
                if is_ref(facet_filters[facet_name]):
                    continue
                if facet_name not in known_facets:
                    warnings.append(ValidationError(
                        code=ValidationErrorCode.INVALID_FACET_FILTER,
                        message=f"Unknown facet filter '{facet_name}'. Available: {', '.join(sorted(known_facets.keys()))}",
                        path=f"{step_path}.args.facet_filters.{facet_name}",
                        details={
                            "unknown_facet": facet_name,
                            "available_facets": sorted(known_facets.keys()),
                        },
                    ))

            # Recurse into branches
            branches = step.get("branches")
            if branches and isinstance(branches, dict):
                for branch_name, branch_steps in branches.items():
                    if isinstance(branch_steps, list):
                        warnings.extend(self._validate_facets(
                            branch_steps,
                            base_path=f"{step_path}.branches.{branch_name}",
                        ))

        return warnings
