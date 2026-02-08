# backend/tests/test_procedure_validator.py
"""
Tests for the ProcedureValidator class.

Covers:
- Schema validation (required fields, slug format, step structure)
- Function existence and parameter validation
- Flow control branch validation (if_branch, switch_branch, foreach, parallel)
- Template reference validation (forward refs, param refs)
"""

import pytest
from app.cwr.contracts.validation import ProcedureValidator, ValidationErrorCode
from app.cwr.tools import initialize_functions


@pytest.fixture(autouse=True, scope="module")
def _init_functions():
    """Ensure functions are registered before tests run."""
    initialize_functions()


@pytest.fixture
def validator():
    return ProcedureValidator()


def _minimal_procedure(**overrides):
    """Create a minimal valid procedure definition."""
    base = {
        "name": "Test Procedure",
        "slug": "test-procedure",
        "steps": [
            {
                "name": "step_one",
                "function": "search_assets",
                "params": {"query": "test"},
            }
        ],
    }
    base.update(overrides)
    return base


# =============================================================================
# SCHEMA VALIDATION TESTS
# =============================================================================


class TestSchemaValidation:
    """Tests for schema-level validation."""

    def test_valid_minimal_procedure(self, validator):
        definition = _minimal_procedure()
        result = validator.validate(definition)
        assert result.valid, f"Expected valid, got errors: {[e.to_dict() for e in result.errors]}"

    def test_missing_name_field(self, validator):
        definition = _minimal_procedure(name="")
        result = validator.validate(definition)
        assert not result.valid
        codes = [e.code for e in result.errors]
        assert ValidationErrorCode.MISSING_REQUIRED_FIELD in codes

    def test_missing_slug_field(self, validator):
        definition = _minimal_procedure(slug="")
        result = validator.validate(definition)
        assert not result.valid
        codes = [e.code for e in result.errors]
        assert ValidationErrorCode.MISSING_REQUIRED_FIELD in codes

    def test_missing_steps_field(self, validator):
        definition = _minimal_procedure(steps=[])
        result = validator.validate(definition)
        assert not result.valid
        codes = [e.code for e in result.errors]
        assert ValidationErrorCode.EMPTY_STEPS in codes

    def test_invalid_slug_format_uppercase(self, validator):
        definition = _minimal_procedure(slug="Test-Procedure")
        result = validator.validate(definition)
        assert not result.valid
        codes = [e.code for e in result.errors]
        assert ValidationErrorCode.INVALID_SLUG_FORMAT in codes

    def test_invalid_slug_format_spaces(self, validator):
        definition = _minimal_procedure(slug="test procedure")
        result = validator.validate(definition)
        assert not result.valid
        codes = [e.code for e in result.errors]
        assert ValidationErrorCode.INVALID_SLUG_FORMAT in codes

    def test_valid_slug_with_hyphens_and_underscores(self, validator):
        definition = _minimal_procedure(slug="test-procedure_v2")
        result = validator.validate(definition)
        assert result.valid

    def test_empty_steps_list(self, validator):
        definition = _minimal_procedure(steps=[])
        result = validator.validate(definition)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.EMPTY_STEPS for e in result.errors)

    def test_duplicate_step_names(self, validator):
        definition = _minimal_procedure(steps=[
            {"name": "step_one", "function": "search_assets", "params": {"query": "a"}},
            {"name": "step_one", "function": "search_assets", "params": {"query": "b"}},
        ])
        result = validator.validate(definition)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.DUPLICATE_STEP_NAME for e in result.errors)

    def test_invalid_on_error_policy(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "step_one",
                "function": "search_assets",
                "params": {"query": "test"},
                "on_error": "explode",
            },
        ])
        result = validator.validate(definition)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.INVALID_ON_ERROR_POLICY for e in result.errors)

    def test_valid_on_error_policies(self, validator):
        for policy in ["fail", "skip", "continue"]:
            definition = _minimal_procedure(steps=[
                {
                    "name": "step_one",
                    "function": "search_assets",
                    "params": {"query": "test"},
                    "on_error": policy,
                },
            ])
            result = validator.validate(definition)
            assert result.valid, f"Policy '{policy}' should be valid"


# =============================================================================
# FUNCTION VALIDATION TESTS
# =============================================================================


class TestFunctionValidation:
    """Tests for function existence and parameter validation."""

    def test_unknown_function_error(self, validator):
        definition = _minimal_procedure(steps=[
            {"name": "step_one", "function": "nonexistent_function", "params": {}},
        ])
        result = validator.validate(definition)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.UNKNOWN_FUNCTION for e in result.errors)

    def test_missing_required_param(self, validator):
        definition = _minimal_procedure(steps=[
            {"name": "step_one", "function": "search_assets", "params": {}},
        ])
        result = validator.validate(definition)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.MISSING_REQUIRED_PARAM for e in result.errors)

    def test_type_mismatch_int_as_string(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "step_one",
                "function": "search_assets",
                "params": {"query": "test", "limit": "not-an-int"},
            },
        ])
        result = validator.validate(definition)
        type_errors = [e for e in result.errors if e.code == ValidationErrorCode.INVALID_PARAM_TYPE]
        assert len(type_errors) > 0

    def test_type_mismatch_list_as_string(self, validator):
        """Functions expecting list params should reject strings."""
        definition = _minimal_procedure(steps=[
            {
                "name": "step_one",
                "function": "llm_classify",
                "params": {
                    "data": "some text",
                    "categories": "not-a-list",  # Should be list
                },
            },
        ])
        result = validator.validate(definition)
        type_errors = [e for e in result.errors if e.code == ValidationErrorCode.INVALID_PARAM_TYPE]
        assert len(type_errors) > 0

    def test_template_bypasses_type_check(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "step_one",
                "function": "search_assets",
                "params": {
                    "query": "{{ params.q }}",
                    "limit": "{{ params.limit }}",
                },
            },
        ])
        result = validator.validate(definition)
        type_errors = [e for e in result.errors if e.code == ValidationErrorCode.INVALID_PARAM_TYPE]
        assert len(type_errors) == 0

    def test_template_bypasses_enum_check(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "step_one",
                "function": "search_assets",
                "params": {
                    "query": "test",
                    "mode": "{{ params.search_mode }}",
                },
            },
        ])
        result = validator.validate(definition)
        # Template should bypass enum check
        enum_errors = [e for e in result.errors if e.code == ValidationErrorCode.INVALID_PARAM_TYPE and "allowed values" in e.message]
        assert len(enum_errors) == 0

    def test_valid_params_pass(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "step_one",
                "function": "search_assets",
                "params": {"query": "test", "limit": 5},
            },
        ])
        result = validator.validate(definition)
        assert result.valid

    def test_none_params_treated_as_empty(self, validator):
        """Steps with params=None should be handled gracefully."""
        definition = _minimal_procedure(steps=[
            {"name": "step_one", "function": "search_assets", "params": None},
        ])
        result = validator.validate(definition)
        # Should get missing_required_param but not crash
        assert not result.valid
        assert any(e.code == ValidationErrorCode.MISSING_REQUIRED_PARAM for e in result.errors)


# =============================================================================
# FLOW CONTROL VALIDATION TESTS
# =============================================================================


class TestFlowControlValidation:
    """Tests for flow control branch validation."""

    def test_if_branch_valid(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "decide",
                "function": "if_branch",
                "params": {"condition": "true"},
                "branches": {
                    "then": [
                        {"name": "do_then", "function": "log", "params": {"message": "yes"}},
                    ],
                },
            },
        ])
        result = validator.validate(definition)
        assert result.valid, f"Errors: {[e.to_dict() for e in result.errors]}"

    def test_if_branch_missing_then(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "decide",
                "function": "if_branch",
                "params": {"condition": "true"},
                "branches": {
                    "else": [
                        {"name": "do_else", "function": "log", "params": {"message": "no"}},
                    ],
                },
            },
        ])
        result = validator.validate(definition)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.MISSING_REQUIRED_BRANCH for e in result.errors)

    def test_if_branch_with_else(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "decide",
                "function": "if_branch",
                "params": {"condition": "true"},
                "branches": {
                    "then": [
                        {"name": "do_then", "function": "log", "params": {"message": "yes"}},
                    ],
                    "else": [
                        {"name": "do_else", "function": "log", "params": {"message": "no"}},
                    ],
                },
            },
        ])
        result = validator.validate(definition)
        assert result.valid

    def test_switch_branch_valid(self, validator):
        definition = _minimal_procedure(
            parameters=[{"name": "category", "type": "string", "required": True}],
            steps=[
            {
                "name": "route",
                "function": "switch_branch",
                "params": {"value": "{{ params.category }}"},
                "branches": {
                    "sales": [
                        {"name": "handle_sales", "function": "log", "params": {"message": "sales"}},
                    ],
                    "support": [
                        {"name": "handle_support", "function": "log", "params": {"message": "support"}},
                    ],
                },
            },
        ])
        result = validator.validate(definition)
        assert result.valid, f"Errors: {[e.to_dict() for e in result.errors]}"

    def test_switch_branch_empty_cases(self, validator):
        """Switch branch with only a default branch (no cases) should fail."""
        definition = _minimal_procedure(steps=[
            {
                "name": "route",
                "function": "switch_branch",
                "params": {"value": "test"},
                "branches": {
                    "default": [
                        {"name": "fallback", "function": "log", "params": {"message": "default"}},
                    ],
                },
            },
        ])
        result = validator.validate(definition)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.INSUFFICIENT_BRANCHES for e in result.errors)

    def test_foreach_valid(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "iterate",
                "function": "foreach",
                "params": {"items": "{{ steps.step_one }}"},
                "branches": {
                    "each": [
                        {"name": "process", "function": "log", "params": {"message": "{{ item }}"}},
                    ],
                },
            },
        ])
        # Need a prior step for the reference
        definition["steps"].insert(0, {
            "name": "step_one",
            "function": "search_assets",
            "params": {"query": "test"},
        })
        result = validator.validate(definition)
        assert result.valid, f"Errors: {[e.to_dict() for e in result.errors]}"

    def test_foreach_missing_each(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "iterate",
                "function": "foreach",
                "params": {"items": ["a", "b"]},
                "branches": {
                    "wrong_name": [
                        {"name": "process", "function": "log", "params": {"message": "hi"}},
                    ],
                },
            },
        ])
        result = validator.validate(definition)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.MISSING_REQUIRED_BRANCH for e in result.errors)

    def test_missing_branches_entirely(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "decide",
                "function": "if_branch",
                "params": {"condition": "true"},
                # No branches at all
            },
        ])
        result = validator.validate(definition)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.MISSING_REQUIRED_BRANCH for e in result.errors)

    def test_empty_branch_steps(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "decide",
                "function": "if_branch",
                "params": {"condition": "true"},
                "branches": {
                    "then": [],  # Empty branch
                },
            },
        ])
        result = validator.validate(definition)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.EMPTY_BRANCH for e in result.errors)

    def test_parallel_needs_at_least_two_branches(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "par",
                "function": "parallel",
                "params": {},
                "branches": {
                    "only_one": [
                        {"name": "a", "function": "log", "params": {"message": "a"}},
                    ],
                },
            },
        ])
        result = validator.validate(definition)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.INSUFFICIENT_BRANCHES for e in result.errors)


# =============================================================================
# TEMPLATE REFERENCE TESTS
# =============================================================================


class TestTemplateReferences:
    """Tests for template reference validation."""

    def test_valid_step_reference(self, validator):
        definition = _minimal_procedure(steps=[
            {"name": "search", "function": "search_assets", "params": {"query": "test"}},
            {
                "name": "summarize",
                "function": "llm_summarize",
                "params": {"data": "{{ steps.search }}"},
            },
        ])
        result = validator.validate(definition)
        ref_errors = [e for e in result.errors if e.code == ValidationErrorCode.INVALID_STEP_REFERENCE]
        assert len(ref_errors) == 0

    def test_forward_reference_error(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "summarize",
                "function": "llm_summarize",
                "params": {"data": "{{ steps.future_step }}"},
            },
            {"name": "future_step", "function": "search_assets", "params": {"query": "test"}},
        ])
        result = validator.validate(definition)
        ref_errors = [e for e in result.errors if e.code == ValidationErrorCode.INVALID_STEP_REFERENCE]
        assert len(ref_errors) > 0

    def test_invalid_param_reference(self, validator):
        definition = _minimal_procedure(
            parameters=[],
            steps=[
                {
                    "name": "search",
                    "function": "search_assets",
                    "params": {"query": "{{ params.undefined_param }}"},
                },
            ],
        )
        result = validator.validate(definition)
        ref_errors = [e for e in result.errors if e.code == ValidationErrorCode.INVALID_PARAM_REFERENCE]
        assert len(ref_errors) > 0

    def test_valid_param_reference(self, validator):
        definition = _minimal_procedure(
            parameters=[{"name": "search_query"}],
            steps=[
                {
                    "name": "search",
                    "function": "search_assets",
                    "params": {"query": "{{ params.search_query }}"},
                },
            ],
        )
        result = validator.validate(definition)
        ref_errors = [e for e in result.errors if e.code == ValidationErrorCode.INVALID_PARAM_REFERENCE]
        assert len(ref_errors) == 0

    def test_self_reference_error(self, validator):
        definition = _minimal_procedure(steps=[
            {
                "name": "search",
                "function": "search_assets",
                "params": {"query": "{{ steps.search }}"},
            },
        ])
        result = validator.validate(definition)
        circular_errors = [e for e in result.errors if e.code == ValidationErrorCode.CIRCULAR_DEPENDENCY]
        assert len(circular_errors) > 0


# =============================================================================
# PARAMETER DEFINITION VALIDATION
# =============================================================================


class TestParameterDefinitionValidation:
    """Tests for procedure-level parameter definitions."""

    def test_duplicate_parameter_names(self, validator):
        definition = _minimal_procedure(
            parameters=[
                {"name": "query"},
                {"name": "query"},
            ],
        )
        result = validator.validate(definition)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.DUPLICATE_PARAMETER_NAME for e in result.errors)

    def test_contradictory_required_with_default(self, validator):
        definition = _minimal_procedure(
            parameters=[
                {"name": "query", "required": True, "default": "hello"},
            ],
        )
        result = validator.validate(definition)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.CONTRADICTORY_PARAMETER for e in result.errors)

    def test_missing_parameter_name(self, validator):
        definition = _minimal_procedure(
            parameters=[
                {"type": "str", "description": "no name provided"},
            ],
        )
        result = validator.validate(definition)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.MISSING_PARAMETER_NAME for e in result.errors)


# =============================================================================
# VALIDATION RESULT SERIALIZATION
# =============================================================================


class TestValidationResultSerialization:
    """Tests for serialization of validation results."""

    def test_to_dict_on_valid(self, validator):
        definition = _minimal_procedure()
        result = validator.validate(definition)
        d = result.to_dict()
        assert d["valid"] is True
        assert d["error_count"] == 0
        assert d["warning_count"] >= 0

    def test_to_dict_on_invalid(self, validator):
        definition = _minimal_procedure(name="", slug="")
        result = validator.validate(definition)
        d = result.to_dict()
        assert d["valid"] is False
        assert d["error_count"] > 0
        assert len(d["errors"]) > 0
        # Each error should have code, message, path
        error = d["errors"][0]
        assert "code" in error
        assert "message" in error
        assert "path" in error
