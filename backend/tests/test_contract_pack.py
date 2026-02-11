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
class MockContractView:
    """Mock for ContractView (replacement for ToolContract)."""
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


@dataclass
class MockFunctionMeta:
    name: str
    description: str = ""
    category: MagicMock = dc_field(default_factory=lambda: MagicMock(value="search"))
    side_effects: bool = False
    exposure_profile: Optional[Dict[str, bool]] = None
    input_schema: Dict[str, Any] = dc_field(default_factory=dict)
    output_schema: Optional[Dict] = None
    payload_profile: str = "full"
    requires_llm: bool = False
    requires_session: bool = False
    tags: List[str] = dc_field(default_factory=list)
    version: str = "1.0"
    is_primitive: bool = True

    def as_contract(self):
        """Produce a MockContractView, same as FunctionMeta.as_contract()."""
        return MockContractView(
            name=self.name,
            description=self.description,
            category=self.category.value,
            side_effects=self.side_effects,
            payload_profile=self.payload_profile,
            requires_llm=self.requires_llm,
            input_schema=self.input_schema or {},
            output_schema=self.output_schema or {},
            tags=self.tags,
            is_primitive=self.is_primitive,
            exposure_profile=self.exposure_profile,
            requires_session=self.requires_session,
            version=self.version,
        )


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
            MockContractView(name="search_notices"),
            MockContractView(name="generate"),
        ]
        profile = get_profile("workflow_standard")
        pack = ToolContractPack(profile=profile, contracts=contracts)
        names = pack.get_tool_names()
        assert names == ["generate", "search_notices"]

    def test_get_contract(self):
        contracts = [
            MockContractView(name="search_notices"),
            MockContractView(name="generate"),
        ]
        profile = get_profile("workflow_standard")
        pack = ToolContractPack(profile=profile, contracts=contracts)
        assert pack.get_contract("search_notices") is not None
        assert pack.get_contract("nonexistent") is None

    def test_to_prompt_json_valid(self):
        contracts = [
            MockContractView(
                name="search_notices",
                description="Search notices",
                category="search",
                input_schema={"type": "object"},
                output_schema={
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                        },
                    },
                },
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
        assert "output_schema" in parsed[0]
        assert parsed[0]["output_schema"]["type"] == "array"
        assert "item_fields" in parsed[0]["output_schema"]
        assert parsed[0]["output_schema"]["item_fields"]["id"] == "string"

    def test_to_dict(self):
        contracts = [MockContractView(name="search_notices")]
        profile = get_profile("workflow_standard")
        pack = ToolContractPack(profile=profile, contracts=contracts)
        d = pack.to_dict()
        assert d["profile"] == "workflow_standard"
        assert d["tool_count"] == 1


class TestGetToolContractPack:
    @patch("app.cwr.contracts.contract_pack.function_registry")
    @patch("app.cwr.contracts.contract_pack.check_exposure")
    def test_safe_readonly_excludes_side_effects(self, mock_exposure, mock_registry):
        metas = _make_mock_metas()
        mock_registry.list_all.return_value = metas
        mock_registry.initialize.return_value = None
        mock_exposure.side_effect = lambda meta, ctx: meta.exposure_profile.get(ctx, False)

        profile = get_profile("safe_readonly")
        pack = get_tool_contract_pack(profile=profile)

        names = pack.get_tool_names()
        assert "send_email" not in names
        assert "webhook" not in names
        assert "update_metadata" not in names
        assert "create_artifact" not in names

    @patch("app.cwr.contracts.contract_pack.function_registry")
    @patch("app.cwr.contracts.contract_pack.check_exposure")
    def test_workflow_standard_excludes_blocked(self, mock_exposure, mock_registry):
        metas = _make_mock_metas()
        mock_registry.list_all.return_value = metas
        mock_registry.initialize.return_value = None
        mock_exposure.side_effect = lambda meta, ctx: meta.exposure_profile.get(ctx, False)

        profile = get_profile("workflow_standard")
        pack = get_tool_contract_pack(profile=profile)

        names = pack.get_tool_names()
        assert "webhook" not in names
        assert "update_metadata" not in names
        # send_email should be allowed (notify category, allowed)
        assert "send_email" in names

    @patch("app.cwr.contracts.contract_pack.function_registry")
    @patch("app.cwr.contracts.contract_pack.check_exposure")
    def test_admin_full_includes_all_exposed(self, mock_exposure, mock_registry):
        metas = _make_mock_metas()
        mock_registry.list_all.return_value = metas
        mock_registry.initialize.return_value = None
        mock_exposure.side_effect = lambda meta, ctx: meta.exposure_profile.get(ctx, False)

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
    def test_exposure_profile_filters(self, mock_exposure, mock_registry):
        metas = _make_mock_metas()
        mock_registry.list_all.return_value = metas
        mock_registry.initialize.return_value = None
        mock_exposure.side_effect = lambda meta, ctx: meta.exposure_profile.get(ctx, False)

        profile = get_profile("admin_full")
        pack = get_tool_contract_pack(profile=profile)

        # agent_only_tool has procedure: False, so it should be excluded
        assert "agent_only_tool" not in pack.get_tool_names()


class TestCompactOutputSchema:
    """Tests for ToolContractPack._compact_output_schema()."""

    def test_string_schema(self):
        result = ToolContractPack._compact_output_schema({"type": "string"})
        assert result == {"type": "string"}

    def test_object_with_properties(self):
        schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "The ID"},
                "title": {"type": "string", "description": "The title"},
                "count": {"type": "integer"},
            },
        }
        result = ToolContractPack._compact_output_schema(schema)
        assert result == {
            "type": "object",
            "fields": {"id": "string", "title": "string", "count": "integer"},
        }

    def test_object_without_properties(self):
        result = ToolContractPack._compact_output_schema({"type": "object"})
        assert result == {"type": "object"}

    def test_array_of_objects(self):
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "score": {"type": "number"},
                },
            },
        }
        result = ToolContractPack._compact_output_schema(schema)
        assert result == {
            "type": "array",
            "item_fields": {"id": "string", "score": "number"},
        }

    def test_array_of_strings(self):
        schema = {"type": "array", "items": {"type": "string"}}
        result = ToolContractPack._compact_output_schema(schema)
        assert result == {"type": "array", "items": "string"}

    def test_empty_schema(self):
        assert ToolContractPack._compact_output_schema({}) == {}

    def test_no_type(self):
        assert ToolContractPack._compact_output_schema({"description": "foo"}) == {}

    def test_variants_stripped(self):
        schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "variants": {"type": "object", "description": "Variant data"},
            },
        }
        result = ToolContractPack._compact_output_schema(schema)
        assert result == {"type": "object", "fields": {"id": "string"}}
        assert "variants" not in result.get("fields", {})

    def test_generic_array(self):
        result = ToolContractPack._compact_output_schema({"type": "array"})
        assert result == {"type": "array"}
