"""Integration tests for the v2 AI Procedure Generator."""

import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from dataclasses import dataclass, field as dc_field
from typing import Dict, Any, List, Optional

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

        # Mock _call_llm to return valid plan
        plan = _valid_plan_json()
        service._call_llm = AsyncMock(return_value=json.dumps(plan))

        result = await service.generate_procedure(
            prompt="Search SAM.gov notices and summarize them",
            profile="workflow_standard",
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

        async def mock_call_llm(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps(invalid_plan)
            return json.dumps(valid_plan)

        service._call_llm = mock_call_llm

        result = await service.generate_procedure(
            prompt="Search notices",
            profile="workflow_standard",
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
        service._call_llm = AsyncMock(return_value=json.dumps(invalid_plan))

        result = await service.generate_procedure(
            prompt="Do something",
            profile="workflow_standard",
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

        # First return with fences, then clean JSON
        plan = _valid_plan_json()
        fenced = f"```json\n{json.dumps(plan)}\n```"
        call_count = 0

        async def mock_call_llm(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return fenced
            return json.dumps(plan)

        service._call_llm = mock_call_llm

        result = await service.generate_procedure(
            prompt="Search notices",
            profile="workflow_standard",
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

    def test_refine_with_yaml(self):
        service = ProcedureGeneratorService()
        prompt = service._build_user_prompt("Add a logging step", current_yaml="name: Test\nsteps:\n  - name: s1")
        assert "existing procedure definition" in prompt
        assert "name: Test" in prompt

    def test_refine_with_plan(self):
        service = ProcedureGeneratorService()
        plan = _valid_plan_json()
        prompt = service._build_user_prompt("Add email step", current_plan=plan)
        assert "existing Typed Plan" in prompt
        assert "Test Procedure" in prompt
