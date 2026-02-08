"""Tests for the Tool Contract Pack."""

import json
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass, field as dc_field
from typing import List, Optional, Dict, Any

from app.cwr.governance.generation_profiles import (
    get_profile,
    GenerationProfileName,
    GENERATION_PROFILES,
)
from app.cwr.contracts.contract_pack import ToolContractPack, get_tool_contract_pack


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class MockFunctionMeta:
    name: str
    description: str = ""
    category: MagicMock = dc_field(default_factory=lambda: MagicMock(value="search"))
    side_effects: bool = False
    exposure_profile: Optional[Dict[str, bool]] = None
    parameters: List = dc_field(default_factory=list)
    output_schema: Optional[Dict] = None
    output_variants: Optional[Dict] = None
    payload_profile: str = "full"
    requires_llm: bool = False
    requires_session: bool = False
    tags: List[str] = dc_field(default_factory=list)
    version: str = "1.0"
    is_primitive: bool = True


@dataclass
class MockToolContract:
    name: str
    description: str = ""
    category: str = "search"
    input_schema: Dict[str, Any] = dc_field(default_factory=dict)
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


def _make_mock_registry(metas):
    """Create a mock function registry."""
    registry = MagicMock()
    registry.list_all.return_value = metas
    registry.initialize.return_value = None
    return registry


def _make_mock_metas():
    """Create a set of mock function metas covering all categories."""
    return [
        MockFunctionMeta(
            name="search_notices",
            category=MagicMock(value="search"),
            side_effects=False,
            exposure_profile={"procedure": True},
        ),
        MockFunctionMeta(
            name="generate",
            category=MagicMock(value="llm"),
            side_effects=False,
            requires_llm=True,
            exposure_profile={"procedure": True},
        ),
        MockFunctionMeta(
            name="send_email",
            category=MagicMock(value="notify"),
            side_effects=True,
            exposure_profile={"procedure": True},
        ),
        MockFunctionMeta(
            name="webhook",
            category=MagicMock(value="notify"),
            side_effects=True,
            exposure_profile={"procedure": True},
        ),
        MockFunctionMeta(
            name="update_metadata",
            category=MagicMock(value="output"),
            side_effects=True,
            exposure_profile={"procedure": True},
        ),
        MockFunctionMeta(
            name="create_artifact",
            category=MagicMock(value="output"),
            side_effects=True,
            exposure_profile={"procedure": True},
        ),
        MockFunctionMeta(
            name="foreach",
            category=MagicMock(value="flow"),
            side_effects=False,
            exposure_profile={"procedure": True},
        ),
        MockFunctionMeta(
            name="agent_only_tool",
            category=MagicMock(value="search"),
            side_effects=False,
            exposure_profile={"procedure": False, "agent": True},
        ),
    ]


class TestToolContractPack:
    def test_get_tool_names(self):
        contracts = [
            MockToolContract(name="search_notices"),
            MockToolContract(name="generate"),
        ]
        profile = get_profile("workflow_standard")
        pack = ToolContractPack(profile=profile, contracts=contracts)
        names = pack.get_tool_names()
        assert names == ["generate", "search_notices"]

    def test_get_contract(self):
        contracts = [
            MockToolContract(name="search_notices"),
            MockToolContract(name="generate"),
        ]
        profile = get_profile("workflow_standard")
        pack = ToolContractPack(profile=profile, contracts=contracts)
        assert pack.get_contract("search_notices") is not None
        assert pack.get_contract("nonexistent") is None

    def test_to_prompt_json_valid(self):
        contracts = [
            MockToolContract(
                name="search_notices",
                description="Search notices",
                category="search",
                input_schema={"type": "object"},
                payload_profile="full",
            ),
        ]
        profile = get_profile("workflow_standard")
        pack = ToolContractPack(profile=profile, contracts=contracts)
        json_str = pack.to_prompt_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "search_notices"
        assert "input_schema" in parsed[0]

    def test_to_dict(self):
        contracts = [MockToolContract(name="search_notices")]
        profile = get_profile("workflow_standard")
        pack = ToolContractPack(profile=profile, contracts=contracts)
        d = pack.to_dict()
        assert d["profile"] == "workflow_standard"
        assert d["tool_count"] == 1


class TestGetToolContractPack:
    @patch("app.cwr.contracts.contract_pack.function_registry")
    @patch("app.cwr.contracts.contract_pack.check_exposure")
    @patch("app.cwr.contracts.contract_pack.ContractGenerator")
    def test_safe_readonly_excludes_side_effects(self, mock_gen, mock_exposure, mock_registry):
        metas = _make_mock_metas()
        mock_registry.list_all.return_value = metas
        mock_registry.initialize.return_value = None
        mock_exposure.side_effect = lambda meta, ctx: meta.exposure_profile.get(ctx, False)
        mock_gen.generate.side_effect = lambda meta: MockToolContract(
            name=meta.name,
            category=meta.category.value,
            side_effects=meta.side_effects,
        )

        profile = get_profile("safe_readonly")
        pack = get_tool_contract_pack(profile=profile)

        names = pack.get_tool_names()
        assert "send_email" not in names
        assert "webhook" not in names
        assert "update_metadata" not in names
        assert "create_artifact" not in names

    @patch("app.cwr.contracts.contract_pack.function_registry")
    @patch("app.cwr.contracts.contract_pack.check_exposure")
    @patch("app.cwr.contracts.contract_pack.ContractGenerator")
    def test_workflow_standard_excludes_blocked(self, mock_gen, mock_exposure, mock_registry):
        metas = _make_mock_metas()
        mock_registry.list_all.return_value = metas
        mock_registry.initialize.return_value = None
        mock_exposure.side_effect = lambda meta, ctx: meta.exposure_profile.get(ctx, False)
        mock_gen.generate.side_effect = lambda meta: MockToolContract(
            name=meta.name,
            category=meta.category.value,
            side_effects=meta.side_effects,
        )

        profile = get_profile("workflow_standard")
        pack = get_tool_contract_pack(profile=profile)

        names = pack.get_tool_names()
        assert "webhook" not in names
        assert "update_metadata" not in names
        # send_email should be allowed (notify category, allowed)
        assert "send_email" in names

    @patch("app.cwr.contracts.contract_pack.function_registry")
    @patch("app.cwr.contracts.contract_pack.check_exposure")
    @patch("app.cwr.contracts.contract_pack.ContractGenerator")
    def test_admin_full_includes_all_exposed(self, mock_gen, mock_exposure, mock_registry):
        metas = _make_mock_metas()
        mock_registry.list_all.return_value = metas
        mock_registry.initialize.return_value = None
        mock_exposure.side_effect = lambda meta, ctx: meta.exposure_profile.get(ctx, False)
        mock_gen.generate.side_effect = lambda meta: MockToolContract(
            name=meta.name,
            category=meta.category.value,
            side_effects=meta.side_effects,
        )

        profile = get_profile("admin_full")
        pack = get_tool_contract_pack(profile=profile)

        names = pack.get_tool_names()
        assert "webhook" in names
        assert "update_metadata" in names
        assert "send_email" in names
        # Agent-only tool should be excluded
        assert "agent_only_tool" not in names

    @patch("app.cwr.contracts.contract_pack.function_registry")
    @patch("app.cwr.contracts.contract_pack.check_exposure")
    @patch("app.cwr.contracts.contract_pack.ContractGenerator")
    def test_exposure_profile_filters(self, mock_gen, mock_exposure, mock_registry):
        metas = _make_mock_metas()
        mock_registry.list_all.return_value = metas
        mock_registry.initialize.return_value = None
        mock_exposure.side_effect = lambda meta, ctx: meta.exposure_profile.get(ctx, False)
        mock_gen.generate.side_effect = lambda meta: MockToolContract(
            name=meta.name,
            category=meta.category.value,
        )

        profile = get_profile("admin_full")
        pack = get_tool_contract_pack(profile=profile)

        # agent_only_tool has procedure: False, so it should be excluded
        assert "agent_only_tool" not in pack.get_tool_names()
