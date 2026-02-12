# backend/app/procedures/validator.py
"""
Procedure Validator - Validate procedure definitions before saving.

Provides comprehensive validation of procedure definitions including:
- Schema validation (required fields, valid types)
- Function existence checks
- Parameter validation against function signatures
- Template variable reference validation
- Step dependency validation

Returns structured error codes and messages for frontend display.
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("curatore.procedures.validator")


class ValidationErrorCode(str, Enum):
    """Error codes for procedure validation failures."""
    # Schema errors
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_FIELD_TYPE = "INVALID_FIELD_TYPE"
    INVALID_SLUG_FORMAT = "INVALID_SLUG_FORMAT"
    EMPTY_STEPS = "EMPTY_STEPS"
    DUPLICATE_STEP_NAME = "DUPLICATE_STEP_NAME"

    # Parameter errors
    DUPLICATE_PARAMETER_NAME = "DUPLICATE_PARAMETER_NAME"
    CONTRADICTORY_PARAMETER = "CONTRADICTORY_PARAMETER"
    MISSING_PARAMETER_NAME = "MISSING_PARAMETER_NAME"

    # Function errors
    UNKNOWN_FUNCTION = "UNKNOWN_FUNCTION"
    MISSING_REQUIRED_PARAM = "MISSING_REQUIRED_PARAM"
    UNKNOWN_FUNCTION_PARAM = "UNKNOWN_FUNCTION_PARAM"
    INVALID_PARAM_TYPE = "INVALID_PARAM_TYPE"

    # Template/reference errors
    INVALID_STEP_REFERENCE = "INVALID_STEP_REFERENCE"
    INVALID_PARAM_REFERENCE = "INVALID_PARAM_REFERENCE"
    CIRCULAR_DEPENDENCY = "CIRCULAR_DEPENDENCY"
    INVALID_TEMPLATE_SYNTAX = "INVALID_TEMPLATE_SYNTAX"

    # Policy errors
    INVALID_ON_ERROR_POLICY = "INVALID_ON_ERROR_POLICY"

    # Flow control errors
    MISSING_REQUIRED_BRANCH = "MISSING_REQUIRED_BRANCH"
    EMPTY_BRANCH = "EMPTY_BRANCH"
    INSUFFICIENT_BRANCHES = "INSUFFICIENT_BRANCHES"
    INVALID_BRANCH_STRUCTURE = "INVALID_BRANCH_STRUCTURE"

    # Profile/policy errors (v2 generation profiles)
    TOOL_BLOCKED_BY_PROFILE = "TOOL_BLOCKED_BY_PROFILE"
    MISSING_SIDE_EFFECT_CONFIRMATION = "MISSING_SIDE_EFFECT_CONFIRMATION"

    # Semantic warnings (non-blocking but suspicious)
    FUNCTION_MISMATCH_WARNING = "FUNCTION_MISMATCH_WARNING"
    INVALID_FACET_FILTER = "INVALID_FACET_FILTER"
    INVALID_OUTPUT_FIELD_REFERENCE = "INVALID_OUTPUT_FIELD_REFERENCE"


@dataclass
class ValidationError:
    """A single validation error."""
    code: ValidationErrorCode
    message: str
    path: str  # JSON path to the error location (e.g., "steps[0].params.query")
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "path": self.path,
            "details": self.details,
        }


@dataclass
class ValidationResult:
    """Result of procedure validation."""
    valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


def resolve_output_fields(output_schema: Dict[str, Any]) -> tuple:
    """
    Extract the output type and set of valid field names from an output_schema.

    Returns:
        (schema_type, fields) where:
        - schema_type is "string", "object", "array", or None (can't validate)
        - fields is a set of field names, empty set for string, or None if generic
    """
    if not output_schema:
        return (None, None)

    schema_type = output_schema.get("type")
    if not schema_type:
        return (None, None)

    if schema_type == "string":
        return ("string", set())  # String output has no fields

    if schema_type == "object":
        props = output_schema.get("properties")
        if props:
            return ("object", set(props.keys()))
        return (None, None)  # Generic object, can't validate

    if schema_type == "array":
        items = output_schema.get("items", {})
        if items.get("type") == "object":
            item_props = items.get("properties")
            if item_props:
                return ("array", set(item_props.keys()))
        return ("array", None)  # Known array, but can't validate item fields

    return (None, None)


class ProcedureValidator:
    """
    Validates procedure definitions.

    Performs comprehensive validation including:
    - Schema structure
    - Function existence and parameters
    - Template syntax and references
    - Step dependencies
    - Semantic mismatch warnings (step name vs function)
    """

    # Valid on_error policies
    VALID_ON_ERROR_POLICIES = {"fail", "skip", "continue"}

    # Slug pattern: lowercase letters, numbers, underscores, hyphens
    SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")

    # Flow control functions and their branch requirements
    FLOW_FUNCTIONS = {
        "if_branch": {
            "required_branches": ["then"],
            "optional_branches": ["else"],
            "min_branches": 1,
            "description": "requires 'branches.then' (else is optional)",
        },
        "switch_branch": {
            "required_branches": [],  # Any non-default branches
            "optional_branches": ["default"],
            "min_branches": 1,  # At least one case (not counting default)
            "description": "requires at least one case branch (default is optional)",
        },
        "parallel": {
            "required_branches": [],  # Any branch names
            "optional_branches": [],
            "min_branches": 2,  # At least 2 branches for parallel
            "description": "requires at least 2 branches",
        },
        "foreach": {
            "required_branches": ["each"],
            "optional_branches": [],
            "min_branches": 1,
            "description": "requires 'branches.each'",
        },
    }

    # Template variable pattern: {{ xxx }}
    TEMPLATE_PATTERN = re.compile(r"\{\{\s*([^}]+)\s*\}\}")

    # Step reference pattern in templates: steps.step_name or steps.step_name.xxx
    STEP_REF_PATTERN = re.compile(r"steps\.([a-zA-Z_][a-zA-Z0-9_]*)")

    # Param reference pattern in templates: params.param_name or params.param_name.xxx
    PARAM_REF_PATTERN = re.compile(r"params\.([a-zA-Z_][a-zA-Z0-9_]*)")

    # Output field reference pattern: steps.step_name.field_name
    OUTPUT_FIELD_REF_PATTERN = re.compile(r"steps\.([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)")

    # Mapping of keywords in step names to expected functions
    # Used to detect when step name suggests a different function than what's used
    STEP_NAME_FUNCTION_HINTS = {
        # Forecast-related keywords -> should use search_forecasts
        "forecast": {
            "expected": "search_forecasts",
            "wrong_functions": ["search_assets", "search_solicitations", "search_notices"],
            "suggestion": "For acquisition forecasts (AG, APFS, State Dept), use search_forecasts instead of search_assets",
        },
        # SAM solicitation keywords -> should use search_solicitations
        "solicitation": {
            "expected": "search_solicitations",
            "wrong_functions": ["search_assets", "search_forecasts"],
            "suggestion": "For SAM.gov solicitations, use search_solicitations instead",
        },
        # SAM notice keywords -> should use search_notices
        "notice": {
            "expected": "search_notices",
            "wrong_functions": ["search_assets", "search_forecasts", "search_solicitations"],
            "suggestion": "For SAM.gov notices, use search_notices instead",
        },
        # Salesforce keywords -> should use search_salesforce
        "salesforce": {
            "expected": "search_salesforce",
            "wrong_functions": ["search_assets", "search_forecasts"],
            "suggestion": "For Salesforce data, use search_salesforce instead",
        },
        "account": {
            "expected": "search_salesforce",
            "wrong_functions": ["search_assets"],
            "suggestion": "For Salesforce accounts, use search_salesforce instead",
        },
        "opportunity": {
            "expected": "search_salesforce",
            "wrong_functions": ["search_assets"],
            "suggestion": "For Salesforce opportunities, use search_salesforce instead",
        },
        # Scrape keywords -> should use search_scraped_assets
        "scrape": {
            "expected": "search_scraped_assets",
            "wrong_functions": ["search_assets"],
            "suggestion": "For scraped web content, use search_scraped_assets instead",
        },
    }

    # Keywords that suggest email content generation - should NOT use generate_document
    EMAIL_CONTENT_HINTS = ["email", "html", "body", "message", "notification", "mail"]

    def __init__(self):
        self._function_registry = None

    def _get_function_registry(self):
        """Lazy load function registry to avoid circular imports."""
        if self._function_registry is None:
            from app.cwr.tools.registry import function_registry
            function_registry.initialize()
            self._function_registry = function_registry
        return self._function_registry

    def validate(self, definition: Dict[str, Any]) -> ValidationResult:
        """
        Validate a procedure definition.

        Args:
            definition: Procedure definition dict

        Returns:
            ValidationResult with any errors/warnings
        """
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []

        # Schema validation
        errors.extend(self._validate_schema(definition))

        # If schema is invalid, skip further validation
        if errors:
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        # Function validation
        steps = definition.get("steps", [])
        step_names = set()

        for idx, step in enumerate(steps):
            step_path = f"steps[{idx}]"
            step_name = step.get("name", "")

            # Check for duplicate step names
            if step_name in step_names:
                errors.append(ValidationError(
                    code=ValidationErrorCode.DUPLICATE_STEP_NAME,
                    message=f"Duplicate step name: '{step_name}'",
                    path=f"{step_path}.name",
                    details={"step_name": step_name},
                ))
            step_names.add(step_name)

            # Validate function exists
            func_name = step.get("function", "")
            # Defensive: handle params being None explicitly
            step_params = step.get("params")
            if step_params is None:
                step_params = {}
            func_errors = self._validate_function(func_name, step_params, step_path)
            errors.extend(func_errors)

            # Log unknown functions for debugging
            if func_errors:
                for err in func_errors:
                    if err.code == ValidationErrorCode.UNKNOWN_FUNCTION:
                        logger.warning(f"Validation found unknown function '{func_name}' in step '{step_name}'")

            # Validate on_error policy
            on_error = step.get("on_error", "fail")
            if on_error not in self.VALID_ON_ERROR_POLICIES:
                errors.append(ValidationError(
                    code=ValidationErrorCode.INVALID_ON_ERROR_POLICY,
                    message=f"Invalid on_error policy: '{on_error}'. Must be one of: {', '.join(self.VALID_ON_ERROR_POLICIES)}",
                    path=f"{step_path}.on_error",
                    details={"value": on_error, "valid_values": list(self.VALID_ON_ERROR_POLICIES)},
                ))

            # Validate flow function branches
            if func_name in self.FLOW_FUNCTIONS:
                branch_errors = self._validate_flow_branches(step, step_path)
                errors.extend(branch_errors)

        # Collect defined parameter names for template validation
        defined_params = set()
        for param in definition.get("parameters", []):
            if isinstance(param, dict) and param.get("name"):
                defined_params.add(param["name"])

        # Template reference validation
        ref_errors = self._validate_template_references(steps, defined_params)
        errors.extend(ref_errors)

        # Output field reference validation
        output_errors, output_warnings = self._validate_output_field_refs(steps, defined_params)
        errors.extend(output_errors)
        warnings.extend(output_warnings)

        # Facet filter validation
        for idx, step in enumerate(steps):
            step_path = f"steps[{idx}]"
            facet_warnings = self._validate_facet_filters(step, step_path)
            warnings.extend(facet_warnings)

        # Semantic mismatch warnings (step name vs function)
        mismatch_warnings = self._check_function_mismatches(steps, definition)
        warnings.extend(mismatch_warnings)

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _validate_schema(self, definition: Dict[str, Any]) -> List[ValidationError]:
        """Validate the schema structure."""
        errors = []

        # Required fields
        if not definition.get("name"):
            errors.append(ValidationError(
                code=ValidationErrorCode.MISSING_REQUIRED_FIELD,
                message="Procedure name is required",
                path="name",
            ))

        if not definition.get("slug"):
            errors.append(ValidationError(
                code=ValidationErrorCode.MISSING_REQUIRED_FIELD,
                message="Procedure slug is required",
                path="slug",
            ))
        elif not self.SLUG_PATTERN.match(definition["slug"]):
            errors.append(ValidationError(
                code=ValidationErrorCode.INVALID_SLUG_FORMAT,
                message="Slug must start with a lowercase letter and contain only lowercase letters, numbers, underscores, and hyphens",
                path="slug",
                details={"value": definition["slug"], "pattern": "^[a-z][a-z0-9_-]*$"},
            ))

        # Steps validation
        steps = definition.get("steps")
        if not steps:
            errors.append(ValidationError(
                code=ValidationErrorCode.EMPTY_STEPS,
                message="At least one step is required",
                path="steps",
            ))
        elif not isinstance(steps, list):
            errors.append(ValidationError(
                code=ValidationErrorCode.INVALID_FIELD_TYPE,
                message="Steps must be an array",
                path="steps",
                details={"expected": "array", "received": type(steps).__name__},
            ))
        else:
            for idx, step in enumerate(steps):
                step_path = f"steps[{idx}]"

                if not isinstance(step, dict):
                    errors.append(ValidationError(
                        code=ValidationErrorCode.INVALID_FIELD_TYPE,
                        message="Step must be an object",
                        path=step_path,
                        details={"expected": "object", "received": type(step).__name__},
                    ))
                    continue

                if not step.get("name"):
                    errors.append(ValidationError(
                        code=ValidationErrorCode.MISSING_REQUIRED_FIELD,
                        message="Step name is required",
                        path=f"{step_path}.name",
                    ))

                if not step.get("function"):
                    errors.append(ValidationError(
                        code=ValidationErrorCode.MISSING_REQUIRED_FIELD,
                        message="Step function is required",
                        path=f"{step_path}.function",
                    ))

        # Validate on_error at procedure level
        on_error = definition.get("on_error", "fail")
        if on_error not in self.VALID_ON_ERROR_POLICIES:
            errors.append(ValidationError(
                code=ValidationErrorCode.INVALID_ON_ERROR_POLICY,
                message=f"Invalid on_error policy: '{on_error}'",
                path="on_error",
                details={"value": on_error, "valid_values": list(self.VALID_ON_ERROR_POLICIES)},
            ))

        # Validate parameters
        parameters = definition.get("parameters", [])
        if parameters:
            if not isinstance(parameters, list):
                errors.append(ValidationError(
                    code=ValidationErrorCode.INVALID_FIELD_TYPE,
                    message="Parameters must be an array",
                    path="parameters",
                    details={"expected": "array", "received": type(parameters).__name__},
                ))
            else:
                param_names = set()
                for idx, param in enumerate(parameters):
                    param_path = f"parameters[{idx}]"

                    if not isinstance(param, dict):
                        errors.append(ValidationError(
                            code=ValidationErrorCode.INVALID_FIELD_TYPE,
                            message="Parameter must be an object",
                            path=param_path,
                            details={"expected": "object", "received": type(param).__name__},
                        ))
                        continue

                    # Check parameter name is present
                    param_name = param.get("name")
                    if not param_name:
                        errors.append(ValidationError(
                            code=ValidationErrorCode.MISSING_PARAMETER_NAME,
                            message="Parameter name is required",
                            path=f"{param_path}.name",
                        ))
                        continue

                    # Check for duplicate parameter names
                    if param_name in param_names:
                        errors.append(ValidationError(
                            code=ValidationErrorCode.DUPLICATE_PARAMETER_NAME,
                            message=f"Duplicate parameter name: '{param_name}'",
                            path=f"{param_path}.name",
                            details={"parameter_name": param_name},
                        ))
                    param_names.add(param_name)

                    # Check for contradictory required + default
                    is_required = param.get("required", False)
                    has_default = param.get("default") is not None
                    if is_required and has_default:
                        errors.append(ValidationError(
                            code=ValidationErrorCode.CONTRADICTORY_PARAMETER,
                            message=f"Parameter '{param_name}' cannot be both required and have a default value. If it has a default, set required: false.",
                            path=f"{param_path}",
                            details={
                                "parameter_name": param_name,
                                "required": is_required,
                                "default": param.get("default"),
                                "fix": "Set 'required: false' since the parameter has a default value",
                            },
                        ))

        return errors

    # Type string to JSON Schema type mapping for validation
    _JSON_SCHEMA_TYPES: Dict[str, type] = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    def _validate_function(
        self,
        func_name: str,
        params: Dict[str, Any],
        step_path: str,
    ) -> List[ValidationError]:
        """Validate function exists and parameters are valid using tool contracts."""
        errors = []
        registry = self._get_function_registry()

        # Log available functions for debugging (only on first call)
        available_funcs = registry.list_names()
        logger.debug(f"Validating function '{func_name}' - registry has {len(available_funcs)} functions")

        # Check function exists
        contract = registry.get_contract(func_name)
        if not contract:
            logger.warning(
                f"UNKNOWN_FUNCTION: '{func_name}' not found. "
                f"Available functions ({len(available_funcs)}): {available_funcs[:10]}..."
            )
            errors.append(ValidationError(
                code=ValidationErrorCode.UNKNOWN_FUNCTION,
                message=f"Unknown function: '{func_name}'",
                path=f"{step_path}.function",
                details={"function": func_name, "available": available_funcs},
            ))
            return errors  # Can't validate params if function doesn't exist

        # Use contract's input JSON Schema for validation
        input_schema = contract.input_schema
        properties = input_schema.get("properties", {})
        required_params = set(input_schema.get("required", []))

        # Check for missing required parameters
        provided_params = set(params.keys())
        for param_name in required_params:
            if param_name not in provided_params:
                param_value = params.get(param_name)
                # Allow if it's a template
                if not (isinstance(param_value, str) and "{{" in param_value):
                    errors.append(ValidationError(
                        code=ValidationErrorCode.MISSING_REQUIRED_PARAM,
                        message=f"Missing required parameter '{param_name}' for function '{func_name}'",
                        path=f"{step_path}.params.{param_name}",
                        details={"function": func_name, "parameter": param_name},
                    ))

        # Type validation using JSON Schema types
        for param_name, value in params.items():
            if param_name not in properties:
                continue  # Unknown params allowed (functions may accept **kwargs)

            # Skip template strings - they're resolved at runtime
            if isinstance(value, str) and "{{" in value:
                continue

            # Skip None for optional parameters (they're treated as absent at runtime)
            if value is None and param_name not in required_params:
                continue

            prop_schema = properties[param_name]
            expected_type = prop_schema.get("type")
            if not expected_type:
                continue

            python_type = self._JSON_SCHEMA_TYPES.get(expected_type)
            if python_type and not isinstance(value, python_type):
                errors.append(ValidationError(
                    code=ValidationErrorCode.INVALID_PARAM_TYPE,
                    message=f"Parameter '{param_name}' for function '{func_name}' expects type '{expected_type}' but got '{type(value).__name__}'",
                    path=f"{step_path}.params.{param_name}",
                    details={
                        "function": func_name,
                        "parameter": param_name,
                        "expected_type": expected_type,
                        "actual_type": type(value).__name__,
                    },
                ))

            # Enum validation from JSON Schema
            # For arrays, enum is inside "items"; for scalars, enum is at top level
            if expected_type == "array":
                items_schema = prop_schema.get("items", {})
                enum_values = items_schema.get("enum")
                if enum_values and isinstance(value, list):
                    for item in value:
                        if item not in enum_values:
                            errors.append(ValidationError(
                                code=ValidationErrorCode.INVALID_PARAM_TYPE,
                                message=f"Parameter '{param_name}' for function '{func_name}' contains invalid value '{item}' not in allowed values: {enum_values}",
                                path=f"{step_path}.params.{param_name}",
                                details={
                                    "function": func_name,
                                    "parameter": param_name,
                                    "value": item,
                                    "allowed_values": enum_values,
                                },
                            ))
            else:
                enum_values = prop_schema.get("enum")
                if enum_values and value not in enum_values:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.INVALID_PARAM_TYPE,
                        message=f"Parameter '{param_name}' for function '{func_name}' value '{value}' not in allowed values: {enum_values}",
                        path=f"{step_path}.params.{param_name}",
                        details={
                            "function": func_name,
                            "parameter": param_name,
                            "value": value,
                            "allowed_values": enum_values,
                        },
                    ))

        return errors

    def _validate_flow_branches(
        self,
        step: Dict[str, Any],
        step_path: str,
    ) -> List[ValidationError]:
        """
        Validate branches for a flow control function.

        Each flow function has specific branch requirements:
        - if_branch: requires 'branches.then' with ≥1 step; 'branches.else' is optional
        - switch_branch: requires ≥1 named case in 'branches'; 'branches.default' is optional
        - parallel: requires ≥2 named branches, each with ≥1 step
        - foreach: requires 'branches.each' with ≥1 step
        """
        errors = []
        func_name = step.get("function", "")
        branches = step.get("branches")
        step_name = step.get("name", "")

        flow_config = self.FLOW_FUNCTIONS.get(func_name)
        if not flow_config:
            return errors  # Not a flow function

        # Check if branches field exists
        if not branches:
            errors.append(ValidationError(
                code=ValidationErrorCode.MISSING_REQUIRED_BRANCH,
                message=f"Flow function '{func_name}' requires a 'branches' field. {flow_config['description']}",
                path=f"{step_path}.branches",
                details={
                    "function": func_name,
                    "step_name": step_name,
                    "required_branches": flow_config["required_branches"],
                },
            ))
            return errors

        if not isinstance(branches, dict):
            errors.append(ValidationError(
                code=ValidationErrorCode.INVALID_BRANCH_STRUCTURE,
                message="'branches' must be an object mapping branch names to step lists",
                path=f"{step_path}.branches",
                details={"expected": "object", "received": type(branches).__name__},
            ))
            return errors

        # Check for required branches
        for required_branch in flow_config["required_branches"]:
            if required_branch not in branches:
                errors.append(ValidationError(
                    code=ValidationErrorCode.MISSING_REQUIRED_BRANCH,
                    message=f"Flow function '{func_name}' requires branch '{required_branch}'",
                    path=f"{step_path}.branches.{required_branch}",
                    details={
                        "function": func_name,
                        "missing_branch": required_branch,
                    },
                ))
            elif not branches[required_branch]:
                errors.append(ValidationError(
                    code=ValidationErrorCode.EMPTY_BRANCH,
                    message=f"Branch '{required_branch}' must contain at least one step",
                    path=f"{step_path}.branches.{required_branch}",
                    details={
                        "function": func_name,
                        "branch": required_branch,
                    },
                ))

        # Check minimum branch count (for switch_branch and parallel)
        if func_name == "switch_branch":
            # Count non-default branches
            non_default_branches = [k for k in branches.keys() if k != "default"]
            if len(non_default_branches) < 1:
                errors.append(ValidationError(
                    code=ValidationErrorCode.INSUFFICIENT_BRANCHES,
                    message="switch_branch requires at least one case branch (not counting 'default')",
                    path=f"{step_path}.branches",
                    details={
                        "function": func_name,
                        "branch_count": len(non_default_branches),
                        "min_required": 1,
                    },
                ))

        elif func_name == "parallel":
            if len(branches) < 2:
                errors.append(ValidationError(
                    code=ValidationErrorCode.INSUFFICIENT_BRANCHES,
                    message=f"parallel requires at least 2 branches for concurrent execution (found {len(branches)})",
                    path=f"{step_path}.branches",
                    details={
                        "function": func_name,
                        "branch_count": len(branches),
                        "min_required": 2,
                    },
                ))

        # Validate each branch has steps and validate nested steps
        for branch_name, branch_steps in branches.items():
            branch_path = f"{step_path}.branches.{branch_name}"

            # Skip if already reported as missing required
            if branch_name in flow_config["required_branches"] and not branch_steps:
                continue  # Already reported above

            if not isinstance(branch_steps, list):
                errors.append(ValidationError(
                    code=ValidationErrorCode.INVALID_BRANCH_STRUCTURE,
                    message=f"Branch '{branch_name}' must be a list of steps",
                    path=branch_path,
                    details={"expected": "array", "received": type(branch_steps).__name__},
                ))
                continue

            if not branch_steps:
                errors.append(ValidationError(
                    code=ValidationErrorCode.EMPTY_BRANCH,
                    message=f"Branch '{branch_name}' must contain at least one step",
                    path=branch_path,
                    details={"branch": branch_name},
                ))
                continue

            # Recursively validate nested steps
            nested_step_names = set()
            for nested_idx, nested_step in enumerate(branch_steps):
                nested_path = f"{branch_path}[{nested_idx}]"

                if not isinstance(nested_step, dict):
                    errors.append(ValidationError(
                        code=ValidationErrorCode.INVALID_FIELD_TYPE,
                        message="Step must be an object",
                        path=nested_path,
                        details={"expected": "object", "received": type(nested_step).__name__},
                    ))
                    continue

                nested_name = nested_step.get("name", "")
                nested_func = nested_step.get("function", "")

                # Check required fields
                if not nested_name:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.MISSING_REQUIRED_FIELD,
                        message="Step name is required",
                        path=f"{nested_path}.name",
                    ))

                if not nested_func:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.MISSING_REQUIRED_FIELD,
                        message="Step function is required",
                        path=f"{nested_path}.function",
                    ))
                else:
                    # Validate function exists
                    nested_params = nested_step.get("params") or {}
                    func_errors = self._validate_function(nested_func, nested_params, nested_path)
                    errors.extend(func_errors)

                # Check for duplicate step names within branch
                if nested_name in nested_step_names:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.DUPLICATE_STEP_NAME,
                        message=f"Duplicate step name '{nested_name}' in branch '{branch_name}'",
                        path=f"{nested_path}.name",
                        details={"step_name": nested_name, "branch": branch_name},
                    ))
                nested_step_names.add(nested_name)

                # Validate on_error policy
                nested_on_error = nested_step.get("on_error", "fail")
                if nested_on_error not in self.VALID_ON_ERROR_POLICIES:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.INVALID_ON_ERROR_POLICY,
                        message=f"Invalid on_error policy: '{nested_on_error}'",
                        path=f"{nested_path}.on_error",
                        details={"value": nested_on_error, "valid_values": list(self.VALID_ON_ERROR_POLICIES)},
                    ))

                # Recursively validate nested flow functions
                if nested_func in self.FLOW_FUNCTIONS:
                    nested_branch_errors = self._validate_flow_branches(nested_step, nested_path)
                    errors.extend(nested_branch_errors)

        return errors

    def _check_function_mismatches(
        self,
        steps: List[Dict[str, Any]],
        definition: Dict[str, Any],
    ) -> List[ValidationError]:
        """
        Check for semantic mismatches between step names and functions.

        This catches common mistakes like naming a step "search_forecasts"
        but using `function: search_assets` which won't search forecasts.

        Also catches misuse of generate_document for email body content.

        Returns warnings (not errors) since the procedure may still be technically valid.
        """
        warnings = []

        # Also check procedure name and description for hints
        proc_name = (definition.get("name") or "").lower()
        proc_desc = (definition.get("description") or "").lower()
        proc_context = f"{proc_name} {proc_desc}"

        for idx, step in enumerate(steps):
            step_name = (step.get("name") or "").lower()
            func_name = step.get("function", "")
            step_path = f"steps[{idx}]"

            # Check for generate_document used for email content
            # This is a common mistake - generate_document creates files (PDF, DOCX, CSV),
            # not HTML strings for email bodies
            if func_name == "generate_document":
                # Check if step name suggests email content
                if any(hint in step_name for hint in self.EMAIL_CONTENT_HINTS):
                    warnings.append(ValidationError(
                        code=ValidationErrorCode.FUNCTION_MISMATCH_WARNING,
                        message=f"Step '{step.get('name')}' uses generate_document but name suggests email content. For HTML emails, use send_email with html: true instead.",
                        path=f"{step_path}.function",
                        details={
                            "step_name": step.get("name"),
                            "current_function": func_name,
                            "suggested_function": "send_email",
                            "suggestion": "For HTML emails, use send_email with html: true. generate_document creates files (PDF, DOCX, CSV) - not HTML strings.",
                        },
                    ))
                # Also check params for format: html which is invalid for generate_document
                step_params = step.get("params") or {}
                if step_params.get("format") == "html":
                    warnings.append(ValidationError(
                        code=ValidationErrorCode.FUNCTION_MISMATCH_WARNING,
                        message=f"Step '{step.get('name')}' uses generate_document with format: html, but generate_document only supports pdf, docx, csv. For HTML emails, use send_email with html: true.",
                        path=f"{step_path}.params.format",
                        details={
                            "step_name": step.get("name"),
                            "current_function": func_name,
                            "invalid_format": "html",
                            "valid_formats": ["pdf", "docx", "csv"],
                            "suggested_function": "send_email",
                            "suggestion": "For HTML emails, use send_email with html: true. generate_document only creates PDF, DOCX, or CSV files.",
                        },
                    ))

            # Check each keyword mapping for search function mismatches
            for keyword, hint in self.STEP_NAME_FUNCTION_HINTS.items():
                # Check if keyword appears in step name or procedure context
                keyword_in_step = keyword in step_name
                keyword_in_context = keyword in proc_context

                # Only warn if keyword is in the step name specifically
                # (procedure context is used for stronger signals)
                if keyword_in_step and func_name in hint["wrong_functions"]:
                    # Strong signal: step name contains keyword but uses wrong function
                    warnings.append(ValidationError(
                        code=ValidationErrorCode.FUNCTION_MISMATCH_WARNING,
                        message=f"Step '{step.get('name')}' appears to want {hint['expected']} but uses '{func_name}'. {hint['suggestion']}",
                        path=f"{step_path}.function",
                        details={
                            "step_name": step.get("name"),
                            "current_function": func_name,
                            "expected_function": hint["expected"],
                            "keyword_matched": keyword,
                            "suggestion": hint["suggestion"],
                        },
                    ))
                elif keyword_in_context and keyword_in_step and func_name != hint["expected"]:
                    # Weaker signal: keyword in both step name and procedure context
                    # but function doesn't match expected (could be intentional)
                    if func_name in hint["wrong_functions"]:
                        warnings.append(ValidationError(
                            code=ValidationErrorCode.FUNCTION_MISMATCH_WARNING,
                            message=f"Procedure is about '{keyword}' but step '{step.get('name')}' uses '{func_name}'. Consider using {hint['expected']}.",
                            path=f"{step_path}.function",
                            details={
                                "step_name": step.get("name"),
                                "current_function": func_name,
                                "expected_function": hint["expected"],
                                "keyword_matched": keyword,
                                "suggestion": hint["suggestion"],
                            },
                        ))

        return warnings

    def _validate_facet_filters(
        self,
        step: Dict[str, Any],
        step_path: str,
    ) -> List[ValidationError]:
        """
        Validate facet_filters parameter against known facet definitions.

        Checks if step params contain a facet_filters dict, and if so, validates
        each facet name against the metadata registry. Unknown facets produce
        warnings (not errors) since facets can be org-dependent.

        Args:
            step: Step definition dict
            step_path: Path for error reporting

        Returns:
            List of validation warnings for unknown facets
        """
        warnings = []
        step_params = step.get("params") or {}
        facet_filters = step_params.get("facet_filters")

        if not facet_filters or not isinstance(facet_filters, dict):
            return warnings

        # Skip if values are template expressions (resolved at runtime)
        if isinstance(facet_filters, str) and "{{" in facet_filters:
            return warnings

        # Try to get known facet definitions from the registry
        try:
            from app.core.metadata.registry_service import metadata_registry_service
            known_facets = metadata_registry_service.get_facet_definitions()
        except Exception:
            # Registry not available — can't validate, skip silently
            return warnings

        if not known_facets:
            return warnings

        for facet_name in facet_filters.keys():
            # Skip template expressions
            if isinstance(facet_name, str) and "{{" in facet_name:
                continue

            if facet_name not in known_facets:
                warnings.append(ValidationError(
                    code=ValidationErrorCode.INVALID_FACET_FILTER,
                    message=f"Step '{step.get('name')}' uses unknown facet filter '{facet_name}'. Available facets: {', '.join(sorted(known_facets.keys()))}",
                    path=f"{step_path}.params.facet_filters.{facet_name}",
                    details={
                        "step_name": step.get("name"),
                        "unknown_facet": facet_name,
                        "available_facets": sorted(known_facets.keys()),
                    },
                ))

        return warnings

    def _validate_template_references(
        self, steps: List[Dict[str, Any]], defined_params: set
    ) -> List[ValidationError]:
        """Validate template references to prior steps and defined parameters."""
        errors = []

        # Track step names we've seen (for forward reference detection)
        seen_steps = set()

        self._validate_template_refs_in_steps(
            steps, defined_params, seen_steps, "steps", errors
        )

        return errors

    def _validate_template_refs_in_steps(
        self,
        steps: List[Dict[str, Any]],
        defined_params: set,
        seen_steps: set,
        base_path: str,
        errors: List[ValidationError],
        extra_context: Optional[set] = None,
    ) -> None:
        """
        Recursively validate template references in a list of steps.

        Args:
            steps: List of step dictionaries
            defined_params: Set of defined parameter names
            seen_steps: Set of step names seen before this list (shared across siblings)
            base_path: Base path for error reporting
            errors: List to append errors to
            extra_context: Additional context variables (e.g., 'item', 'item_index' for foreach)
        """
        # Track steps seen within this scope
        local_seen = set(seen_steps)  # Copy to not affect sibling branches
        extra_context = extra_context or set()

        for idx, step in enumerate(steps):
            step_name = step.get("name", "")
            step_path = f"{base_path}[{idx}]"
            func_name = step.get("function", "")

            # Check all string values in params for template references
            self._check_template_refs_in_value(
                step.get("params", {}),
                local_seen,
                defined_params,
                f"{step_path}.params",
                step_name,
                errors,
                extra_context,
            )

            # Check condition
            condition = step.get("condition")
            if condition:
                self._check_template_refs_in_value(
                    condition,
                    local_seen,
                    defined_params,
                    f"{step_path}.condition",
                    step_name,
                    errors,
                    extra_context,
                )

            # Check foreach (legacy single-step foreach)
            foreach = step.get("foreach")
            if foreach:
                self._check_template_refs_in_value(
                    foreach,
                    local_seen,
                    defined_params,
                    f"{step_path}.foreach",
                    step_name,
                    errors,
                    extra_context,
                )

            # Validate branches recursively
            branches = step.get("branches")
            if branches and isinstance(branches, dict):
                # Determine extra context for branch steps
                branch_extra_context = set(extra_context)
                if func_name == "foreach":
                    # foreach branches have access to 'item' and 'item_index'
                    branch_extra_context.add("item")
                    branch_extra_context.add("item_index")

                for branch_name, branch_steps in branches.items():
                    if isinstance(branch_steps, list):
                        # Each branch sees steps from before the flow step, plus steps within the branch
                        self._validate_template_refs_in_steps(
                            branch_steps,
                            defined_params,
                            local_seen,  # Branch can see steps before the flow step
                            f"{step_path}.branches.{branch_name}",
                            errors,
                            branch_extra_context,
                        )

            # Add this step to seen steps (available for subsequent steps at this level)
            local_seen.add(step_name)

    def _check_template_refs_in_value(
        self,
        value: Any,
        seen_steps: set,
        defined_params: set,
        path: str,
        current_step: str,
        errors: List[ValidationError],
        extra_context: Optional[set] = None,
    ) -> None:
        """
        Recursively check template references in a value.

        Args:
            value: The value to check
            seen_steps: Set of step names that have executed before this point
            defined_params: Set of defined parameter names
            path: Path for error reporting
            current_step: Name of the current step
            errors: List to append errors to
            extra_context: Additional valid context variables (e.g., 'item', 'item_index')
        """
        extra_context = extra_context or set()

        if isinstance(value, str):
            # Find all step references in template
            for match in self.STEP_REF_PATTERN.finditer(value):
                ref_step = match.group(1)

                # Check if referencing current step (self-reference)
                if ref_step == current_step:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.CIRCULAR_DEPENDENCY,
                        message=f"Step '{current_step}' cannot reference itself",
                        path=path,
                        details={"step": current_step, "reference": ref_step},
                    ))

                # Check if referencing a step that hasn't been executed yet
                elif ref_step not in seen_steps:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.INVALID_STEP_REFERENCE,
                        message=f"Step '{current_step}' references unknown or future step '{ref_step}'",
                        path=path,
                        details={
                            "step": current_step,
                            "reference": ref_step,
                            "available_steps": list(seen_steps),
                        },
                    ))

            # Find all param references in template
            for match in self.PARAM_REF_PATTERN.finditer(value):
                ref_param = match.group(1)

                # Check if referencing an undefined parameter
                if ref_param not in defined_params:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.INVALID_PARAM_REFERENCE,
                        message=f"Step '{current_step}' references undefined parameter '{ref_param}'",
                        path=path,
                        details={
                            "step": current_step,
                            "reference": ref_param,
                            "defined_params": list(defined_params),
                        },
                    ))

            # Validate template syntax
            for match in self.TEMPLATE_PATTERN.finditer(value):
                expr = match.group(1).strip()
                # Basic syntax check - must start with valid identifier
                # Also allow extra context variables like 'item' and 'item_index'
                first_word = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)", expr)
                if not first_word:
                    errors.append(ValidationError(
                        code=ValidationErrorCode.INVALID_TEMPLATE_SYNTAX,
                        message=f"Invalid template expression: '{expr}'",
                        path=path,
                        details={"expression": expr},
                    ))
                # Note: We don't validate 'item' and 'item_index' references here
                # because they're injected by the executor at runtime for foreach branches

        elif isinstance(value, dict):
            for key, val in value.items():
                self._check_template_refs_in_value(val, seen_steps, defined_params, f"{path}.{key}", current_step, errors, extra_context)

        elif isinstance(value, list):
            for i, item in enumerate(value):
                self._check_template_refs_in_value(item, seen_steps, defined_params, f"{path}[{i}]", current_step, errors, extra_context)

    def _validate_output_field_refs(
        self,
        steps: List[Dict[str, Any]],
        defined_params: set,
        base_path: str = "steps",
    ) -> Tuple[List[ValidationError], List[ValidationError]]:
        """
        Validate output field references in procedure steps.

        Checks {{ steps.X.field }} references against the function's output_schema.
        String-field-ref → error. Array-field-ref / unknown-object-field → warning.
        Generic schema → skip.

        Returns:
            (errors, warnings)
        """
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []

        # Build step_name -> function_name map
        step_func_map: Dict[str, str] = {}
        for step in steps:
            sname = step.get("name", "")
            sfunc = step.get("function", "")
            if sname and sfunc:
                step_func_map[sname] = sfunc

        registry = self._get_function_registry()

        for idx, step in enumerate(steps):
            step_path = f"{base_path}[{idx}]"
            step_name = step.get("name", "")

            # Check params, condition, foreach for output field refs
            for section_key in ("params", "condition", "foreach"):
                value = step.get(section_key)
                if value is not None:
                    section_path = f"{step_path}.{section_key}"
                    self._check_output_field_refs_in_value(
                        value, step_func_map, registry,
                        section_path, step_name, errors, warnings,
                    )

            # Recurse into branches
            branches = step.get("branches")
            if branches and isinstance(branches, dict):
                for branch_name, branch_steps in branches.items():
                    if isinstance(branch_steps, list):
                        branch_errors, branch_warnings = self._validate_output_field_refs(
                            branch_steps, defined_params,
                            base_path=f"{step_path}.branches.{branch_name}",
                        )
                        errors.extend(branch_errors)
                        warnings.extend(branch_warnings)

        return errors, warnings

    def _check_output_field_refs_in_value(
        self,
        value: Any,
        step_func_map: Dict[str, str],
        registry: Any,
        path: str,
        current_step: str,
        errors: List[ValidationError],
        warnings: List[ValidationError],
    ) -> None:
        """Recursively check for output field references in a value tree."""
        if isinstance(value, str) and "{{" in value:
            for match in self.OUTPUT_FIELD_REF_PATTERN.finditer(value):
                step_ref = match.group(1)
                field_ref = match.group(2)
                self._check_single_output_field_ref(
                    step_ref, field_ref, f"steps.{step_ref}.{field_ref}",
                    step_func_map, registry, path, current_step, errors, warnings,
                )
        elif isinstance(value, dict):
            for key, val in value.items():
                self._check_output_field_refs_in_value(
                    val, step_func_map, registry,
                    f"{path}.{key}", current_step, errors, warnings,
                )
        elif isinstance(value, list):
            for i, item in enumerate(value):
                self._check_output_field_refs_in_value(
                    item, step_func_map, registry,
                    f"{path}[{i}]", current_step, errors, warnings,
                )

    def _check_single_output_field_ref(
        self,
        step_name: str,
        field_name: str,
        ref_str: str,
        step_func_map: Dict[str, str],
        registry: Any,
        path: str,
        current_step: str,
        errors: List[ValidationError],
        warnings: List[ValidationError],
    ) -> None:
        """Check a single steps.X.field reference against the function's output_schema."""
        func_name = step_func_map.get(step_name)
        if not func_name:
            return  # Step not found at this level; skip

        contract = registry.get_contract(func_name)
        if not contract:
            return  # Function not found; function validation handles this

        schema_type, output_fields = resolve_output_fields(contract.output_schema)
        if schema_type is None:
            return  # Generic schema, can't validate

        if schema_type == "string":
            errors.append(ValidationError(
                code=ValidationErrorCode.INVALID_OUTPUT_FIELD_REFERENCE,
                message=f"Step '{current_step}' references field '{field_name}' on step '{step_name}' "
                        f"(function '{func_name}'), but it returns a string. "
                        f"Use the step result directly: {{{{ steps.{step_name} }}}}",
                path=path,
                details={
                    "step": current_step,
                    "referenced_step": step_name,
                    "function": func_name,
                    "field": field_name,
                    "output_type": "string",
                    "ref": ref_str,
                },
            ))
        elif schema_type == "array":
            available = sorted(output_fields) if output_fields else []
            msg = (
                f"Step '{current_step}' references field '{field_name}' on step '{step_name}' "
                f"(function '{func_name}'), but it returns an array. Use foreach to iterate, "
                f"then access item.{field_name}."
            )
            if available:
                msg += f" Available item fields: {available}"
            warnings.append(ValidationError(
                code=ValidationErrorCode.INVALID_OUTPUT_FIELD_REFERENCE,
                message=msg,
                path=path,
                details={
                    "step": current_step,
                    "referenced_step": step_name,
                    "function": func_name,
                    "field": field_name,
                    "output_type": "array",
                    "available_fields": available,
                    "ref": ref_str,
                },
            ))
        elif schema_type == "object" and output_fields is not None and field_name not in output_fields:
            warnings.append(ValidationError(
                code=ValidationErrorCode.INVALID_OUTPUT_FIELD_REFERENCE,
                message=f"Step '{current_step}' references field '{field_name}' on step '{step_name}' "
                        f"(function '{func_name}'), but that field is not in the output schema. "
                        f"Available fields: {sorted(output_fields)}",
                path=path,
                details={
                    "step": current_step,
                    "referenced_step": step_name,
                    "function": func_name,
                    "field": field_name,
                    "output_type": "object",
                    "available_fields": sorted(output_fields),
                    "ref": ref_str,
                },
            ))


# Global validator instance
procedure_validator = ProcedureValidator()


def validate_procedure(definition: Dict[str, Any]) -> ValidationResult:
    """Validate a procedure definition."""
    return procedure_validator.validate(definition)
