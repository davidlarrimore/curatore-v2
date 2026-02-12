"""Integration tests for the v2 AI Procedure Generator."""

import json
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.cwr.procedures.compiler.ai_generator import ProcedureGeneratorService

# ---------------------------------------------------------------------------
# Helper: Create a valid plan JSON that the mock LLM will return
# ---------------------------------------------------------------------------

def _valid_plan_json():
    return {
        "procedure": {
            "name": "Test Procedure",
            "description": "A test procedure",
            "tags": ["test"],
        },
        "parameters": [
            {"name": "query", "type": "string", "description": "Search query", "required": False, "default": "*"},
        ],
        "steps": [
            {
                "name": "search",
                "tool": "search_notices",
                "description": "Search for notices",
                "args": {
                    "query": {"ref": "params.query"},
                    "limit": 50,
                },
            },
            {
                "name": "summarize",
                "tool": "llm_generate",
                "description": "Summarize results",
                "args": {
                    "prompt": {"template": "Summarize: {{ steps.search }}"},
                    "max_tokens": 2000,
                },
            },
        ],
    }


def _invalid_plan_json_unknown_tool():
    plan = _valid_plan_json()
    plan["steps"][1]["tool"] = "nonexistent_tool"
    return plan


def _mock_llm_response(content: str, tool_calls=None):
    """Create a mock OpenAI-compatible response object."""
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls
    if hasattr(message, "model_dump"):
        message.model_dump.return_value = {
            "role": "assistant",
            "content": content,
            "tool_calls": None,
        }

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


@dataclass
class MockToolContract:
    name: str
    description: str = ""
    category: str = "search"
    input_schema: Dict[str, Any] = dc_field(default_factory=lambda: {"type": "object", "properties": {}, "required": []})
    output_schema: Dict[str, Any] = dc_field(default_factory=dict)
    side_effects: bool = False
    payload_profile: str = "full"
    requires_llm: bool = False
    tags: List[str] = dc_field(default_factory=list)
    is_primitive: bool = True
    exposure_profile: Optional[Dict] = None
    requires_session: bool = False
    version: str = "1.0"

    def to_dict(self):
        return {"name": self.name, "category": self.category}


@dataclass
class MockContractPack:
    profile: Any = dc_field(default_factory=lambda: MagicMock(
        name=MagicMock(value="workflow_standard"),
        blocked_tools=frozenset(),
        require_side_effect_confirmation=False,
        allowed_categories=frozenset({"search", "llm", "flow", "notify", "output"}),
        allow_side_effects=True,
        max_search_limit=100,
        max_llm_tokens=4096,
    ))
    contracts: List[MockToolContract] = dc_field(default_factory=list)

    def get_tool_names(self):
        return sorted(c.name for c in self.contracts)

    def get_contract(self, name):
        for c in self.contracts:
            if c.name == name:
                return c
        return None

    def to_prompt_json(self):
        return json.dumps([{"name": c.name} for c in self.contracts])


def _make_default_pack():
    return MockContractPack(contracts=[
        MockToolContract(
            name="search_notices",
            category="search",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": [],
            },
        ),
        MockToolContract(
            name="llm_generate",
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
        MockToolContract(
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
    ])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProcedureGeneratorService:
    """Test the v2 ProcedureGeneratorService with mocked LLM."""

    @pytest.mark.asyncio
    @patch("app.cwr.procedures.compiler.ai_generator.get_tool_contract_pack")
    @patch("app.cwr.procedures.compiler.ai_generator.llm_service")
    @patch("app.cwr.procedures.compiler.ai_generator.config_loader")
    async def test_successful_generation(self, mock_config, mock_llm, mock_get_pack):
        """Test successful plan generation and compilation."""
        mock_llm.is_available = True
        mock_llm._client = MagicMock()
        mock_config.get_task_type_config.return_value = MagicMock(model="test", temperature=0.2)

        pack = _make_default_pack()
        mock_get_pack.return_value = pack

        service = ProcedureGeneratorService()

        # Mock _call_llm to return valid plan wrapped in response object
        plan = _valid_plan_json()
        service._call_llm = AsyncMock(return_value=_mock_llm_response(json.dumps(plan)))

        result = await service.generate_procedure(
            prompt="Search SAM.gov notices and summarize them",
            profile="workflow_standard",
            use_planning_tools=False,
        )

        assert result["success"] is True
        assert result["yaml"] is not None
        assert result["procedure"] is not None
        assert result["plan_json"] is not None
        assert result["profile_used"] == "workflow_standard"
        assert result["diagnostics"] is not None

    @pytest.mark.asyncio
    @patch("app.cwr.procedures.compiler.ai_generator.get_tool_contract_pack")
    @patch("app.cwr.procedures.compiler.ai_generator.llm_service")
    @patch("app.cwr.procedures.compiler.ai_generator.config_loader")
    async def test_plan_repair_after_invalid(self, mock_config, mock_llm, mock_get_pack):
        """Test that the service repairs a plan after first attempt fails."""
        mock_llm.is_available = True
        mock_llm._client = MagicMock()
        mock_config.get_task_type_config.return_value = MagicMock(model="test", temperature=0.2)

        pack = _make_default_pack()
        mock_get_pack.return_value = pack

        service = ProcedureGeneratorService()

        # First call returns invalid plan (unknown tool), second returns valid
        invalid_plan = _invalid_plan_json_unknown_tool()
        valid_plan = _valid_plan_json()
        call_count = 0

        async def mock_call_llm(messages, tools=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_llm_response(json.dumps(invalid_plan))
            return _mock_llm_response(json.dumps(valid_plan))

        service._call_llm = mock_call_llm

        result = await service.generate_procedure(
            prompt="Search notices",
            profile="workflow_standard",
            use_planning_tools=False,
        )

        assert result["success"] is True
        assert result["attempts"] >= 2

    @pytest.mark.asyncio
    @patch("app.cwr.procedures.compiler.ai_generator.get_tool_contract_pack")
    @patch("app.cwr.procedures.compiler.ai_generator.llm_service")
    @patch("app.cwr.procedures.compiler.ai_generator.config_loader")
    async def test_max_attempts_exceeded(self, mock_config, mock_llm, mock_get_pack):
        """Test failure when all plan attempts are exhausted."""
        mock_llm.is_available = True
        mock_llm._client = MagicMock()
        mock_config.get_task_type_config.return_value = MagicMock(model="test", temperature=0.2)

        pack = _make_default_pack()
        mock_get_pack.return_value = pack

        service = ProcedureGeneratorService()

        # Always return invalid plan
        invalid_plan = _invalid_plan_json_unknown_tool()
        service._call_llm = AsyncMock(return_value=_mock_llm_response(json.dumps(invalid_plan)))

        result = await service.generate_procedure(
            prompt="Do something",
            profile="workflow_standard",
            use_planning_tools=False,
        )

        assert result["success"] is False
        assert result["error"] is not None
        assert "Failed to generate valid plan" in result["error"]
        assert len(result["validation_errors"]) > 0

    @pytest.mark.asyncio
    @patch("app.cwr.procedures.compiler.ai_generator.get_tool_contract_pack")
    @patch("app.cwr.procedures.compiler.ai_generator.llm_service")
    @patch("app.cwr.procedures.compiler.ai_generator.config_loader")
    async def test_json_parse_recovery(self, mock_config, mock_llm, mock_get_pack):
        """Test recovery from JSON parse errors (markdown fences)."""
        mock_llm.is_available = True
        mock_llm._client = MagicMock()
        mock_config.get_task_type_config.return_value = MagicMock(model="test", temperature=0.2)

        pack = _make_default_pack()
        mock_get_pack.return_value = pack

        service = ProcedureGeneratorService()

        # Return fenced JSON (should be stripped by parser)
        plan = _valid_plan_json()
        fenced = f"```json\n{json.dumps(plan)}\n```"

        service._call_llm = AsyncMock(return_value=_mock_llm_response(fenced))

        result = await service.generate_procedure(
            prompt="Search notices",
            profile="workflow_standard",
            use_planning_tools=False,
        )

        # Should succeed on first attempt since fence stripping works
        assert result["success"] is True

    @pytest.mark.asyncio
    @patch("app.cwr.procedures.compiler.ai_generator.llm_service")
    async def test_llm_unavailable(self, mock_llm):
        """Test graceful error when LLM is unavailable."""
        mock_llm.is_available = False

        service = ProcedureGeneratorService()
        result = await service.generate_procedure(
            prompt="Search notices",
        )

        assert result["success"] is False
        assert "not available" in result["error"]


class TestParseJSON:
    """Test JSON parsing resilience."""

    def test_clean_json(self):
        service = ProcedureGeneratorService()
        plan = _valid_plan_json()
        result = service._parse_plan_json(json.dumps(plan))
        assert result is not None
        assert result["procedure"]["name"] == "Test Procedure"

    def test_fenced_json(self):
        service = ProcedureGeneratorService()
        plan = _valid_plan_json()
        fenced = f"```json\n{json.dumps(plan)}\n```"
        result = service._parse_plan_json(fenced)
        assert result is not None

    def test_triple_backtick_json(self):
        service = ProcedureGeneratorService()
        plan = _valid_plan_json()
        fenced = f"```\n{json.dumps(plan)}\n```"
        result = service._parse_plan_json(fenced)
        assert result is not None

    def test_embedded_json(self):
        service = ProcedureGeneratorService()
        plan = _valid_plan_json()
        text = f"Here's the plan:\n{json.dumps(plan)}\nDone!"
        result = service._parse_plan_json(text)
        assert result is not None

    def test_garbage_returns_none(self):
        service = ProcedureGeneratorService()
        result = service._parse_plan_json("This is not JSON at all")
        assert result is None

    def test_array_returns_none(self):
        service = ProcedureGeneratorService()
        result = service._parse_plan_json("[1, 2, 3]")
        assert result is None


class TestUserPromptBuilding:
    def test_generate_mode(self):
        service = ProcedureGeneratorService()
        prompt = service._build_user_prompt("Create a search procedure")
        assert "Create a Typed Plan JSON" in prompt

    def test_refine_with_plan(self):
        service = ProcedureGeneratorService()
        plan = _valid_plan_json()
        prompt = service._build_user_prompt("Add email step", current_plan=plan)
        assert "existing Typed Plan" in prompt
        assert "Test Procedure" in prompt


class TestPlanningToolsGovernance:
    """Test governance-based planning tool selection."""

    def test_planning_tools_exclude_side_effects(self):
        """Planning tools must exclude functions with side_effects=True."""
        from app.cwr.procedures.compiler.planning_tools import (
            PLANNING_ELIGIBLE_CATEGORIES,
            get_planning_tools_openai_format,
        )
        from app.cwr.tools.registry import function_registry

        function_registry.initialize()
        tools = get_planning_tools_openai_format()
        tool_names = {t["function"]["name"] for t in tools}

        # Verify no tool with side_effects=True is included
        for name in tool_names:
            contract = function_registry.get_contract(name)
            assert contract is not None, f"Tool '{name}' not found in registry"
            assert contract.side_effects is False, f"Tool '{name}' has side_effects=True"
            assert contract.requires_llm is False, f"Tool '{name}' requires LLM"
            assert contract.category in PLANNING_ELIGIBLE_CATEGORIES, (
                f"Tool '{name}' has ineligible category '{contract.category}'"
            )

    def test_planning_tools_include_core_search_tools(self):
        """Core search/data tools should be auto-selected as planning tools."""
        from app.cwr.procedures.compiler.planning_tools import get_planning_tools_openai_format

        tools = get_planning_tools_openai_format()
        tool_names = {t["function"]["name"] for t in tools}

        expected_core = {
            "discover_data_sources",
            "discover_metadata",
            "search_assets",
            "search_notices",
            "search_solicitations",
        }
        for name in expected_core:
            assert name in tool_names, f"Expected planning tool '{name}' not found"

    def test_planning_tools_exclude_llm_functions(self):
        """LLM functions (generate, summarize, etc.) must not be planning tools."""
        from app.cwr.procedures.compiler.planning_tools import get_planning_tools_openai_format

        tools = get_planning_tools_openai_format()
        tool_names = {t["function"]["name"] for t in tools}

        llm_tools = {"llm_generate", "llm_summarize", "llm_classify", "llm_extract"}
        for name in llm_tools:
            assert name not in tool_names, f"LLM tool '{name}' should not be a planning tool"

    @pytest.mark.asyncio
    async def test_execute_rejects_side_effect_tool(self):
        """execute_planning_tool should reject tools with side effects."""
        from app.cwr.procedures.compiler.planning_tools import execute_planning_tool
        from app.cwr.tools.context import FunctionContext

        ctx = FunctionContext(session=MagicMock(), organization_id=MagicMock())
        result = await execute_planning_tool("send_email", {}, ctx)
        assert result["success"] is False
        assert "side effects" in result["error"] or "not eligible" in result["error"] or "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_rejects_unknown_tool(self):
        """execute_planning_tool should reject unknown function names."""
        from app.cwr.procedures.compiler.planning_tools import execute_planning_tool
        from app.cwr.tools.context import FunctionContext

        ctx = FunctionContext(session=MagicMock(), organization_id=MagicMock())
        result = await execute_planning_tool("nonexistent_function_xyz", {}, ctx)
        assert result["success"] is False
        assert "not found" in result["error"]


class TestClarificationDetection:
    """Test the _is_clarification_response method."""

    def test_detects_question_without_json(self):
        """A response with questions and no JSON is a clarification."""
        service = ProcedureGeneratorService()
        content = (
            "I found multiple folders that could match your request:\n\n"
            "1. Reuse Material/Past Performances (Growth site, 42 documents)\n"
            "2. Past Performances (IT Department site, 15 documents)\n\n"
            "Which folder would you like the procedure to target?"
        )
        assert service._is_clarification_response(content) is True

    def test_rejects_json_with_questions(self):
        """A response with both JSON and questions is NOT a clarification."""
        service = ProcedureGeneratorService()
        content = '{"procedure": {"name": "Test?"}, "steps": []}'
        assert service._is_clarification_response(content) is False

    def test_rejects_pure_json(self):
        """A pure JSON response is not a clarification."""
        service = ProcedureGeneratorService()
        content = json.dumps(_valid_plan_json())
        assert service._is_clarification_response(content) is False

    def test_rejects_empty_content(self):
        """Empty content is not a clarification."""
        service = ProcedureGeneratorService()
        assert service._is_clarification_response("") is False
        assert service._is_clarification_response(None) is False

    def test_rejects_statement_without_questions(self):
        """A statement without question marks is not a clarification."""
        service = ProcedureGeneratorService()
        content = "I could not find any matching folders for the specified path."
        assert service._is_clarification_response(content) is False

    @pytest.mark.asyncio
    @patch("app.cwr.procedures.compiler.ai_generator.get_tool_contract_pack")
    @patch("app.cwr.procedures.compiler.ai_generator.llm_service")
    @patch("app.cwr.procedures.compiler.ai_generator.config_loader")
    async def test_clarification_returned_in_result(self, mock_config, mock_llm, mock_get_pack):
        """When the AI asks for clarification, result should include needs_clarification."""
        mock_llm.is_available = True
        mock_llm._client = MagicMock()
        mock_config.get_task_type_config.return_value = MagicMock(model="test", temperature=0.2)

        pack = _make_default_pack()
        mock_get_pack.return_value = pack

        service = ProcedureGeneratorService()

        clarification_text = "Which folder did you mean? I found two matches."
        service._call_llm = AsyncMock(return_value=_mock_llm_response(clarification_text))

        result = await service.generate_procedure(
            prompt="Classify documents in Past Performances",
            profile="workflow_standard",
            use_planning_tools=False,
        )

        assert result["success"] is False
        assert result.get("needs_clarification") is True
        assert result.get("clarification_message") == clarification_text
        assert result.get("error") is None
