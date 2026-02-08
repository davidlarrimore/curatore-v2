"""Tests for the Plan Validator."""

import pytest
from unittest.mock import MagicMock
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

from app.cwr.contracts.validation import ValidationErrorCode
from app.cwr.procedures.compiler.plan_validator import PlanValidator


# ---------------------------------------------------------------------------
# Helpers to build mock contract packs
# ---------------------------------------------------------------------------

@dataclass
class MockContract:
    name: str
    description: str = ""
    category: str = "search"
    input_schema: Dict[str, Any] = field(default_factory=dict)
    side_effects: bool = False
    payload_profile: str = "full"
    requires_llm: bool = False
    tags: List[str] = field(default_factory=list)

    def to_dict(self):
        return {"name": self.name, "category": self.category}


@dataclass
class MockProfile:
    name: MagicMock = field(default_factory=lambda: MagicMock(value="workflow_standard"))
    blocked_tools: frozenset = field(default_factory=frozenset)
    require_side_effect_confirmation: bool = False
    allowed_categories: frozenset = field(default_factory=lambda: frozenset({"search", "llm", "flow", "notify", "output"}))
    allow_side_effects: bool = True
    max_search_limit: int = 100
    max_llm_tokens: int = 4096


class MockContractPack:
    def __init__(self, contracts=None, profile=None):
        self.contracts = contracts or []
        self.profile = profile or MockProfile()

    def get_tool_names(self):
        return sorted(c.name for c in self.contracts)

    def get_contract(self, name):
        for c in self.contracts:
            if c.name == name:
                return c
        return None


def _make_pack(tools=None, blocked_tools=None, require_confirmation=False):
    """Create a mock contract pack with common tools."""
    if tools is None:
        tools = [
            MockContract(
                name="search_notices",
                category="search",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                        "posted_within_days": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            ),
            MockContract(
                name="generate",
                category="llm",
                input_schema={
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "max_tokens": {"type": "integer"},
                    },
                    "required": ["prompt"],
                },
                requires_llm=True,
            ),
            MockContract(
                name="send_email",
                category="notify",
                input_schema={
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["to", "subject", "body"],
                },
                side_effects=True,
            ),
            MockContract(
                name="foreach",
                category="flow",
                input_schema={"type": "object", "properties": {}, "required": []},
            ),
            MockContract(
                name="if_branch",
                category="flow",
                input_schema={
                    "type": "object",
                    "properties": {"condition": {"type": "string"}},
                    "required": ["condition"],
                },
            ),
        ]

    profile = MockProfile(
        blocked_tools=frozenset(blocked_tools or []),
        require_side_effect_confirmation=require_confirmation,
    )
    return MockContractPack(contracts=tools, profile=profile)


def _make_plan(steps, parameters=None):
    return {
        "procedure": {"name": "Test", "description": "Test procedure"},
        "parameters": parameters or [],
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# Layer 1: Schema Validation
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_valid_plan_passes(self):
        pack = _make_pack()
        validator = PlanValidator(pack)
        plan = _make_plan([{"name": "s1", "tool": "search_notices", "args": {"query": "*"}}])
        result = validator.validate(plan)
        assert result.valid

    def test_missing_procedure_fails(self):
        pack = _make_pack()
        validator = PlanValidator(pack)
        plan = {"steps": [{"name": "s1", "tool": "generate"}]}
        result = validator.validate(plan)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.INVALID_FIELD_TYPE for e in result.errors)

    def test_empty_steps_fails(self):
        pack = _make_pack()
        validator = PlanValidator(pack)
        plan = {"procedure": {"name": "Test", "description": "A"}, "steps": []}
        result = validator.validate(plan)
        assert not result.valid


# ---------------------------------------------------------------------------
# Layer 2: Tool Existence + Arg Validation
# ---------------------------------------------------------------------------

class TestToolValidation:
    def test_unknown_tool_rejected(self):
        pack = _make_pack()
        validator = PlanValidator(pack)
        plan = _make_plan([{"name": "s1", "tool": "nonexistent_tool", "args": {}}])
        result = validator.validate(plan)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.UNKNOWN_FUNCTION for e in result.errors)

    def test_missing_required_arg(self):
        pack = _make_pack()
        validator = PlanValidator(pack)
        plan = _make_plan([{"name": "s1", "tool": "search_notices", "args": {}}])
        result = validator.validate(plan)
        assert not result.valid
        assert any(e.code == ValidationErrorCode.MISSING_REQUIRED_PARAM for e in result.errors)

    def test_ref_satisfies_required(self):
        pack = _make_pack()
        validator = PlanValidator(pack)
        plan = _make_plan(
            parameters=[{"name": "q", "type": "string"}],
            steps=[{"name": "s1", "tool": "search_notices", "args": {"query": {"ref": "params.q"}}}],
        )
        result = validator.validate(plan)
        # Should not have MISSING_REQUIRED_PARAM
        required_errors = [e for e in result.errors if e.code == ValidationErrorCode.MISSING_REQUIRED_PARAM]
        assert len(required_errors) == 0

    def test_wrong_type_arg(self):
        pack = _make_pack()
        validator = PlanValidator(pack)
        plan = _make_plan([
            {"name": "s1", "tool": "search_notices", "args": {"query": "*", "limit": "not_an_int"}}
        ])
        result = validator.validate(plan)
        assert any(e.code == ValidationErrorCode.INVALID_PARAM_TYPE for e in result.errors)


# ---------------------------------------------------------------------------
# Layer 3: Reference Validation
# ---------------------------------------------------------------------------

class TestReferenceValidation:
    def test_valid_step_ref(self):
        pack = _make_pack()
        validator = PlanValidator(pack)
        plan = _make_plan([
            {"name": "search", "tool": "search_notices", "args": {"query": "*"}},
            {"name": "summarize", "tool": "generate", "args": {"prompt": {"ref": "steps.search"}}},
        ])
        result = validator.validate(plan)
        ref_errors = [e for e in result.errors if e.code in (
            ValidationErrorCode.INVALID_STEP_REFERENCE,
            ValidationErrorCode.INVALID_PARAM_REFERENCE,
        )]
        assert len(ref_errors) == 0

    def test_forward_ref_rejected(self):
        pack = _make_pack()
        validator = PlanValidator(pack)
        plan = _make_plan([
            {"name": "first", "tool": "generate", "args": {"prompt": {"ref": "steps.second"}}},
            {"name": "second", "tool": "search_notices", "args": {"query": "*"}},
        ])
        result = validator.validate(plan)
        assert any(e.code == ValidationErrorCode.INVALID_STEP_REFERENCE for e in result.errors)

    def test_self_ref_rejected(self):
        pack = _make_pack()
        validator = PlanValidator(pack)
        plan = _make_plan([
            {"name": "loop", "tool": "generate", "args": {"prompt": {"ref": "steps.loop"}}},
        ])
        result = validator.validate(plan)
        assert any(e.code == ValidationErrorCode.CIRCULAR_DEPENDENCY for e in result.errors)

    def test_undefined_param_ref_rejected(self):
        pack = _make_pack()
        validator = PlanValidator(pack)
        plan = _make_plan([
            {"name": "s1", "tool": "search_notices", "args": {"query": {"ref": "params.undefined"}}},
        ])
        result = validator.validate(plan)
        assert any(e.code == ValidationErrorCode.INVALID_PARAM_REFERENCE for e in result.errors)

    def test_valid_param_ref(self):
        pack = _make_pack()
        validator = PlanValidator(pack)
        plan = _make_plan(
            parameters=[{"name": "query"}],
            steps=[{"name": "s1", "tool": "search_notices", "args": {"query": {"ref": "params.query"}}}],
        )
        result = validator.validate(plan)
        ref_errors = [e for e in result.errors if e.code == ValidationErrorCode.INVALID_PARAM_REFERENCE]
        assert len(ref_errors) == 0

    def test_inline_template_forward_ref(self):
        pack = _make_pack()
        validator = PlanValidator(pack)
        plan = _make_plan([
            {"name": "first", "tool": "generate", "args": {
                "prompt": "Use {{ steps.second }} here",
            }},
            {"name": "second", "tool": "search_notices", "args": {"query": "*"}},
        ])
        result = validator.validate(plan)
        assert any(e.code == ValidationErrorCode.INVALID_STEP_REFERENCE for e in result.errors)


# ---------------------------------------------------------------------------
# Layer 4: Side-Effect Policy
# ---------------------------------------------------------------------------

class TestSideEffectPolicy:
    def test_blocked_tool_rejected(self):
        pack = _make_pack(blocked_tools=["send_email"])
        validator = PlanValidator(pack)
        plan = _make_plan([
            {"name": "email", "tool": "send_email", "args": {
                "to": "test@test.com", "subject": "Test", "body": "Hi",
            }},
        ])
        result = validator.validate(plan)
        assert any(e.code == ValidationErrorCode.TOOL_BLOCKED_BY_PROFILE for e in result.errors)

    def test_admin_requires_confirmation(self):
        pack = _make_pack(require_confirmation=True)
        validator = PlanValidator(pack)
        plan = _make_plan([
            {"name": "email", "tool": "send_email", "args": {
                "to": "test@test.com", "subject": "Test", "body": "Hi",
            }},
        ])
        result = validator.validate(plan)
        assert any(e.code == ValidationErrorCode.MISSING_SIDE_EFFECT_CONFIRMATION for e in result.errors)

    def test_admin_with_confirmation_passes(self):
        pack = _make_pack(require_confirmation=True)
        validator = PlanValidator(pack)
        plan = _make_plan([
            {"name": "email", "tool": "send_email", "args": {
                "to": "test@test.com", "subject": "Test", "body": "Hi",
                "confirm_side_effects": True,
            }},
        ])
        result = validator.validate(plan)
        confirmation_errors = [e for e in result.errors if e.code == ValidationErrorCode.MISSING_SIDE_EFFECT_CONFIRMATION]
        assert len(confirmation_errors) == 0


# ---------------------------------------------------------------------------
# Branch Validation (recursive)
# ---------------------------------------------------------------------------

class TestBranchValidation:
    def test_unknown_tool_in_branch_detected(self):
        pack = _make_pack()
        validator = PlanValidator(pack)
        plan = _make_plan([
            {"name": "search", "tool": "search_notices", "args": {"query": "*"}},
            {
                "name": "loop",
                "tool": "foreach",
                "foreach": {"ref": "steps.search"},
                "branches": {
                    "each": [
                        {"name": "inner", "tool": "nonexistent", "args": {}}
                    ]
                },
            },
        ])
        result = validator.validate(plan)
        assert any(e.code == ValidationErrorCode.UNKNOWN_FUNCTION for e in result.errors)
        assert any("branches" in e.path for e in result.errors if e.code == ValidationErrorCode.UNKNOWN_FUNCTION)
