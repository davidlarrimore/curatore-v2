"""Tests for Typed Plan models."""

import jsonschema
import pytest
from app.cwr.procedures.compiler.plan_models import (
    TYPED_PLAN_JSON_SCHEMA,
    PlanParameter,
    PlanProcedure,
    PlanStep,
    TypedPlan,
    is_ref,
    is_template,
    parse_ref,
)


def _make_minimal_plan() -> dict:
    return {
        "procedure": {
            "name": "Test Procedure",
            "description": "A test",
        },
        "parameters": [],
        "steps": [
            {
                "name": "step1",
                "tool": "search_notices",
                "args": {"query": "*"},
            }
        ],
    }


class TestPlanProcedure:
    def test_from_dict(self):
        p = PlanProcedure.from_dict({"name": "Test", "description": "Desc", "tags": ["a"]})
        assert p.name == "Test"
        assert p.description == "Desc"
        assert p.tags == ["a"]
        assert p.slug is None

    def test_to_dict(self):
        p = PlanProcedure(name="Test", description="Desc", slug="test_slug")
        d = p.to_dict()
        assert d["name"] == "Test"
        assert d["slug"] == "test_slug"

    def test_to_dict_omits_empty(self):
        p = PlanProcedure(name="Test", description="Desc")
        d = p.to_dict()
        assert "slug" not in d
        assert "tags" not in d


class TestPlanParameter:
    def test_from_dict_defaults(self):
        p = PlanParameter.from_dict({"name": "query"})
        assert p.type == "string"
        assert p.required is False
        assert p.default is None

    def test_roundtrip(self):
        data = {"name": "limit", "type": "integer", "description": "Max", "required": True, "default": 50}
        p = PlanParameter.from_dict(data)
        d = p.to_dict()
        assert d["name"] == "limit"
        assert d["type"] == "integer"
        assert d["required"] is True
        assert d["default"] == 50


class TestPlanStep:
    def test_from_dict_minimal(self):
        s = PlanStep.from_dict({"name": "s1", "tool": "generate"})
        assert s.name == "s1"
        assert s.tool == "generate"
        assert s.args == {}
        assert s.on_error == "fail"

    def test_from_dict_with_branches(self):
        data = {
            "name": "loop",
            "tool": "foreach",
            "foreach": {"ref": "steps.search"},
            "branches": {
                "each": [{"name": "inner", "tool": "generate", "args": {}}]
            },
        }
        s = PlanStep.from_dict(data)
        assert s.branches is not None
        assert "each" in s.branches
        assert len(s.branches["each"]) == 1
        assert s.branches["each"][0].name == "inner"

    def test_roundtrip(self):
        data = {
            "name": "s1",
            "tool": "generate",
            "args": {"prompt": "hello"},
            "description": "A step",
            "on_error": "continue",
        }
        s = PlanStep.from_dict(data)
        d = s.to_dict()
        assert d["name"] == "s1"
        assert d["args"]["prompt"] == "hello"
        assert d["on_error"] == "continue"


class TestTypedPlan:
    def test_from_dict(self):
        plan = TypedPlan.from_dict(_make_minimal_plan())
        assert plan.procedure.name == "Test Procedure"
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "search_notices"

    def test_roundtrip(self):
        data = _make_minimal_plan()
        plan = TypedPlan.from_dict(data)
        d = plan.to_dict()
        assert d["procedure"]["name"] == "Test Procedure"
        assert len(d["steps"]) == 1

    def test_from_dict_with_params(self):
        data = _make_minimal_plan()
        data["parameters"] = [{"name": "query", "type": "string", "required": True}]
        plan = TypedPlan.from_dict(data)
        assert len(plan.parameters) == 1
        assert plan.parameters[0].required is True


class TestRefHelpers:
    def test_is_ref_true(self):
        assert is_ref({"ref": "steps.search"}) is True

    def test_is_ref_false_extra_keys(self):
        assert is_ref({"ref": "steps.search", "extra": True}) is False

    def test_is_ref_false_no_ref(self):
        assert is_ref({"template": "hello"}) is False
        assert is_ref("not a dict") is False

    def test_is_template_true(self):
        assert is_template({"template": "{{ steps.x }}"}) is True

    def test_is_template_false(self):
        assert is_template({"ref": "steps.x"}) is False

    def test_parse_ref_step(self):
        ns, name, field = parse_ref("steps.search_results")
        assert ns == "steps"
        assert name == "search_results"
        assert field is None

    def test_parse_ref_step_field(self):
        ns, name, field = parse_ref("steps.search_results.data")
        assert ns == "steps"
        assert name == "search_results"
        assert field == "data"

    def test_parse_ref_param(self):
        ns, name, field = parse_ref("params.query")
        assert ns == "params"
        assert name == "query"
        assert field is None

    def test_parse_ref_single(self):
        ns, name, field = parse_ref("item")
        assert ns == "item"
        assert name is None


class TestTypedPlanJsonSchema:
    def test_valid_plan_passes(self):
        plan = _make_minimal_plan()
        jsonschema.validate(instance=plan, schema=TYPED_PLAN_JSON_SCHEMA)

    def test_missing_procedure_fails(self):
        plan = {"steps": [{"name": "s1", "tool": "generate"}]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=plan, schema=TYPED_PLAN_JSON_SCHEMA)

    def test_empty_steps_fails(self):
        plan = {
            "procedure": {"name": "Test", "description": "A test"},
            "steps": [],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=plan, schema=TYPED_PLAN_JSON_SCHEMA)

    def test_step_missing_name_fails(self):
        plan = {
            "procedure": {"name": "Test", "description": "A test"},
            "steps": [{"tool": "generate"}],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=plan, schema=TYPED_PLAN_JSON_SCHEMA)

    def test_step_missing_tool_fails(self):
        plan = {
            "procedure": {"name": "Test", "description": "A test"},
            "steps": [{"name": "s1"}],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=plan, schema=TYPED_PLAN_JSON_SCHEMA)

    def test_invalid_on_error_fails(self):
        plan = {
            "procedure": {"name": "Test", "description": "A test"},
            "steps": [{"name": "s1", "tool": "generate", "on_error": "retry"}],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=plan, schema=TYPED_PLAN_JSON_SCHEMA)

    def test_additional_properties_rejected(self):
        plan = {
            "procedure": {"name": "Test", "description": "A test"},
            "steps": [{"name": "s1", "tool": "generate"}],
            "extra_field": True,
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=plan, schema=TYPED_PLAN_JSON_SCHEMA)

    def test_valid_slug_pattern(self):
        plan = _make_minimal_plan()
        plan["procedure"]["slug"] = "my_procedure_1"
        jsonschema.validate(instance=plan, schema=TYPED_PLAN_JSON_SCHEMA)

    def test_invalid_slug_pattern(self):
        plan = _make_minimal_plan()
        plan["procedure"]["slug"] = "1_starts_with_number"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=plan, schema=TYPED_PLAN_JSON_SCHEMA)
