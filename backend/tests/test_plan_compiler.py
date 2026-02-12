"""Tests for the Plan Compiler."""

from app.cwr.governance.generation_profiles import GENERATION_PROFILES, GenerationProfileName, get_profile
from app.cwr.procedures.compiler.plan_compiler import PlanCompiler


def _make_plan(steps=None, parameters=None, tags=None, slug=None):
    return {
        "procedure": {
            "name": "Test Procedure",
            "description": "A test procedure",
            **({"slug": slug} if slug else {}),
            **({"tags": tags} if tags else {}),
        },
        "parameters": parameters or [],
        "steps": steps or [
            {"name": "step1", "tool": "search_notices", "args": {"query": "*", "limit": 50}}
        ],
    }


class TestSlugGeneration:
    def test_auto_slug_from_name(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        result = compiler.compile(_make_plan())
        assert result["slug"] == "test_procedure"

    def test_explicit_slug_preserved(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        result = compiler.compile(_make_plan(slug="custom_slug"))
        assert result["slug"] == "custom_slug"

    def test_slug_strips_special_chars(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan()
        plan["procedure"]["name"] = "My Amazing! Procedure #1"
        result = compiler.compile(plan)
        assert result["slug"] == "my_amazing_procedure_1"

    def test_slug_leading_number_prefixed(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan()
        plan["procedure"]["name"] = "123 Numbers First"
        result = compiler.compile(plan)
        assert result["slug"].startswith("p_")


class TestRefResolution:
    def test_ref_to_template(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan(steps=[
            {"name": "search", "tool": "search_notices", "args": {"query": "*"}},
            {"name": "summarize", "tool": "generate", "args": {
                "prompt": {"ref": "steps.search"},
            }},
        ])
        result = compiler.compile(plan)
        assert result["steps"][1]["params"]["prompt"] == "{{ steps.search }}"

    def test_ref_field_to_template(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan(steps=[
            {"name": "search", "tool": "search_notices", "args": {"query": "*"}},
            {"name": "use_field", "tool": "generate", "args": {
                "text": {"ref": "steps.search.data"},
            }},
        ])
        result = compiler.compile(plan)
        assert result["steps"][1]["params"]["text"] == "{{ steps.search.data }}"

    def test_param_ref_to_template(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan(
            parameters=[{"name": "query", "type": "string"}],
            steps=[
                {"name": "search", "tool": "search_notices", "args": {
                    "query": {"ref": "params.query"},
                }},
            ],
        )
        result = compiler.compile(plan)
        assert result["steps"][0]["params"]["query"] == "{{ params.query }}"

    def test_template_object_resolved(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan(steps=[
            {"name": "search", "tool": "search_notices", "args": {"query": "*"}},
            {"name": "summarize", "tool": "generate", "args": {
                "prompt": {"template": "Found {{ steps.search | length }} items"},
            }},
        ])
        result = compiler.compile(plan)
        assert result["steps"][1]["params"]["prompt"] == "Found {{ steps.search | length }} items"

    def test_nested_refs_in_dict(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan(steps=[
            {"name": "search", "tool": "search_notices", "args": {"query": "*"}},
            {"name": "email", "tool": "send_email", "args": {
                "to": "test@test.com",
                "attachments": [{"filename": {"ref": "steps.search.filename"}}],
            }},
        ])
        result = compiler.compile(plan)
        assert result["steps"][1]["params"]["attachments"][0]["filename"] == "{{ steps.search.filename }}"


class TestParameterTypeMapping:
    def test_string_to_str(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan(parameters=[
            {"name": "query", "type": "string"},
        ])
        result = compiler.compile(plan)
        assert result["parameters"][0]["type"] == "str"

    def test_integer_to_int(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan(parameters=[
            {"name": "limit", "type": "integer"},
        ])
        result = compiler.compile(plan)
        assert result["parameters"][0]["type"] == "int"

    def test_boolean_to_bool(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan(parameters=[
            {"name": "flag", "type": "boolean"},
        ])
        result = compiler.compile(plan)
        assert result["parameters"][0]["type"] == "bool"

    def test_array_to_list(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan(parameters=[
            {"name": "items", "type": "array"},
        ])
        result = compiler.compile(plan)
        assert result["parameters"][0]["type"] == "list"


class TestPolicyClamps:
    def test_search_limit_clamped(self):
        profile = GENERATION_PROFILES[GenerationProfileName.SAFE_READONLY]
        compiler = PlanCompiler(profile)
        plan = _make_plan(steps=[
            {"name": "search", "tool": "search_notices", "args": {"query": "*", "limit": 500}},
        ])
        result = compiler.compile(plan)
        assert result["steps"][0]["params"]["limit"] == profile.max_search_limit

    def test_llm_tokens_clamped(self):
        profile = GENERATION_PROFILES[GenerationProfileName.SAFE_READONLY]
        compiler = PlanCompiler(profile)
        plan = _make_plan(steps=[
            {"name": "gen", "tool": "generate", "args": {"prompt": "hi", "max_tokens": 10000}},
        ])
        result = compiler.compile(plan)
        assert result["steps"][0]["params"]["max_tokens"] == profile.max_llm_tokens

    def test_within_limits_unchanged(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan(steps=[
            {"name": "search", "tool": "search_notices", "args": {"query": "*", "limit": 10}},
        ])
        result = compiler.compile(plan)
        assert result["steps"][0]["params"]["limit"] == 10


class TestToolToFunctionMapping:
    def test_tool_becomes_function(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan(steps=[
            {"name": "s1", "tool": "search_notices", "args": {"query": "*"}},
        ])
        result = compiler.compile(plan)
        assert result["steps"][0]["function"] == "search_notices"
        assert "tool" not in result["steps"][0]


class TestBranchCompilation:
    def test_foreach_branches_compiled(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan(steps=[
            {"name": "search", "tool": "search_notices", "args": {"query": "*"}},
            {
                "name": "loop",
                "tool": "foreach",
                "foreach": {"ref": "steps.search"},
                "branches": {
                    "each": [
                        {"name": "inner", "tool": "generate", "args": {
                            "prompt": {"ref": "steps.search"},
                        }}
                    ]
                },
            },
        ])
        result = compiler.compile(plan)
        loop_step = result["steps"][1]
        assert loop_step["foreach"] == "{{ steps.search }}"
        assert "each" in loop_step["branches"]
        inner = loop_step["branches"]["each"][0]
        assert inner["function"] == "generate"
        assert inner["params"]["prompt"] == "{{ steps.search }}"

    def test_if_branch_condition(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        plan = _make_plan(steps=[
            {"name": "search", "tool": "search_notices", "args": {"query": "*"}},
            {
                "name": "check",
                "tool": "if_branch",
                "args": {"condition": "steps.search"},
                "branches": {
                    "then": [{"name": "do_thing", "tool": "generate", "args": {"prompt": "yes"}}],
                    "else": [{"name": "skip", "tool": "log", "args": {"message": "no results"}}],
                },
            },
        ])
        result = compiler.compile(plan)
        assert "then" in result["steps"][1]["branches"]
        assert "else" in result["steps"][1]["branches"]


class TestOutputStructure:
    def test_output_has_required_fields(self):
        profile = get_profile("workflow_standard")
        compiler = PlanCompiler(profile)
        result = compiler.compile(_make_plan(tags=["test"]))
        assert "name" in result
        assert "slug" in result
        assert "description" in result
        assert "version" in result
        assert "parameters" in result
        assert "steps" in result
        assert "on_error" in result
        assert result["tags"] == ["test"]
