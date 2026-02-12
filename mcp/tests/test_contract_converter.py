# Contract Converter Tests
"""Tests for ToolContract to MCP Tool conversion."""

import mcp.types as types
from app.models.mcp import MCPTool
from app.services.contract_converter import ContractConverter


class TestContractConverter:
    """Test contract conversion."""

    def test_to_mcp_tool_basic(self, sample_contract):
        """Test basic contract conversion."""
        tool = ContractConverter.to_mcp_tool(sample_contract)

        assert isinstance(tool, MCPTool)
        assert tool.name == "search_assets"
        assert "Search organization assets" in tool.description
        assert tool.inputSchema == sample_contract["input_schema"]

    def test_to_mcp_tool_thin_payload_hint(self, sample_contract):
        """Test that thin payload profile adds hint to description."""
        sample_contract["payload_profile"] = "thin"
        tool = ContractConverter.to_mcp_tool(sample_contract, enhance_description=True)

        assert "thin payloads" in tool.description.lower()
        assert "get_content" in tool.description

    def test_to_mcp_tool_no_enhancement(self, sample_contract):
        """Test conversion without description enhancement."""
        sample_contract["payload_profile"] = "thin"
        tool = ContractConverter.to_mcp_tool(sample_contract, enhance_description=False)

        assert "thin payloads" not in tool.description.lower()

    def test_to_mcp_tool_requires_llm_hint(self, sample_contract):
        """Test that requires_llm adds hint to description."""
        sample_contract["requires_llm"] = True
        tool = ContractConverter.to_mcp_tool(sample_contract)

        assert "Requires LLM" in tool.description

    def test_to_mcp_tools(self, sample_contracts):
        """Test converting multiple contracts."""
        tools = ContractConverter.to_mcp_tools(sample_contracts)

        assert len(tools) == 3
        assert all(isinstance(t, MCPTool) for t in tools)

    def test_filter_safe_allowlist(self, sample_contracts):
        """Test filtering by allowlist."""
        allowlist = ["search_assets", "get_content"]
        filtered = ContractConverter.filter_safe(
            sample_contracts,
            allowlist=allowlist,
            block_side_effects=False,
        )

        assert len(filtered) == 2
        names = [c["name"] for c in filtered]
        assert "search_assets" in names
        assert "get_content" in names
        assert "send_email" not in names

    def test_filter_safe_side_effects(self, sample_contracts):
        """Test filtering by side_effects."""
        filtered = ContractConverter.filter_safe(
            sample_contracts,
            allowlist=[],  # Empty allowlist = all allowed
            block_side_effects=True,
        )

        # send_email has side_effects=True, should be excluded
        names = [c["name"] for c in filtered]
        assert "send_email" not in names

    def test_filter_safe_combined(self, sample_contracts):
        """Test combined allowlist and side_effects filtering."""
        allowlist = ["search_assets", "send_email"]  # send_email in allowlist but has side effects
        filtered = ContractConverter.filter_safe(
            sample_contracts,
            allowlist=allowlist,
            block_side_effects=True,
        )

        # Only search_assets should remain
        assert len(filtered) == 1
        assert filtered[0]["name"] == "search_assets"

    def test_input_schema_preserved(self, sample_contract):
        """Test that input_schema is preserved exactly."""
        tool = ContractConverter.to_mcp_tool(sample_contract)

        # inputSchema should match input_schema exactly
        assert tool.inputSchema == sample_contract["input_schema"]
        assert tool.inputSchema["type"] == "object"
        assert "query" in tool.inputSchema["properties"]
        assert tool.inputSchema["required"] == ["query"]


class TestSDKToolConversion:
    """Test conversion to MCP SDK types.Tool."""

    def test_to_sdk_tool_basic(self, sample_contract):
        """Test converting MCPTool to SDK types.Tool."""
        mcp_tool = ContractConverter.to_mcp_tool(sample_contract)
        sdk_tool = ContractConverter.to_sdk_tool(mcp_tool)

        assert isinstance(sdk_tool, types.Tool)
        assert sdk_tool.name == "search_assets"
        assert "Search organization assets" in sdk_tool.description
        assert sdk_tool.inputSchema == sample_contract["input_schema"]

    def test_to_sdk_tool_annotations_read_only(self, sample_contract):
        """Test that non-side-effect tools get readOnlyHint=True."""
        mcp_tool = ContractConverter.to_mcp_tool(sample_contract)
        sdk_tool = ContractConverter.to_sdk_tool(mcp_tool)

        assert sdk_tool.annotations is not None
        assert sdk_tool.annotations.readOnlyHint is True
        assert sdk_tool.annotations.destructiveHint is False
        assert sdk_tool.annotations.idempotentHint is True
        assert sdk_tool.annotations.openWorldHint is True

    def test_to_sdk_tools_multiple(self, sample_contracts):
        """Test converting multiple MCPTools to SDK types."""
        mcp_tools = ContractConverter.to_mcp_tools(sample_contracts)
        sdk_tools = ContractConverter.to_sdk_tools(mcp_tools)

        assert len(sdk_tools) == 3
        assert all(isinstance(t, types.Tool) for t in sdk_tools)

    def test_contract_to_sdk_tool_direct(self, sample_contract):
        """Test converting raw contract dict directly to SDK types.Tool."""
        sdk_tool = ContractConverter.contract_to_sdk_tool(sample_contract)

        assert isinstance(sdk_tool, types.Tool)
        assert sdk_tool.name == "search_assets"
        assert sdk_tool.annotations is not None
        assert sdk_tool.annotations.readOnlyHint is True

    def test_contract_to_sdk_tool_with_side_effects(self):
        """Test that side-effect contracts get readOnlyHint=False."""
        contract = {
            "name": "confirm_email",
            "description": "Send confirmation email",
            "input_schema": {"type": "object", "properties": {}},
            "side_effects": True,
        }
        sdk_tool = ContractConverter.contract_to_sdk_tool(contract)

        assert sdk_tool.annotations.readOnlyHint is False
        assert sdk_tool.annotations.idempotentHint is False

    def test_contract_to_sdk_tool_payload_hints(self, sample_contract):
        """Test that payload_profile hints are added to description."""
        sample_contract["payload_profile"] = "thin"
        sdk_tool = ContractConverter.contract_to_sdk_tool(sample_contract)

        assert "thin payloads" in sdk_tool.description.lower()

    def test_contract_to_sdk_tool_llm_hint(self, sample_contract):
        """Test that requires_llm hint is added to description."""
        sample_contract["requires_llm"] = True
        sdk_tool = ContractConverter.contract_to_sdk_tool(sample_contract)

        assert "Requires LLM" in sdk_tool.description


class TestProcedureOnlyStripping:
    """Test that x-procedure-only properties are stripped for MCP exposure."""

    def _make_contract_with_items(self):
        """Create a contract with x-procedure-only items property."""
        return {
            "name": "llm_summarize",
            "description": "Summarize text",
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to summarize",
                    },
                    "style": {
                        "type": "string",
                        "default": "paragraph",
                    },
                    "items": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Collection of items (procedure only)",
                        "x-procedure-only": True,
                    },
                    "chunk_size": {
                        "type": "integer",
                        "default": 8000,
                        "x-procedure-only": True,
                    },
                },
                "required": ["text"],
            },
            "side_effects": False,
            "requires_llm": True,
        }

    def test_to_mcp_tool_strips_procedure_only(self):
        """Test that to_mcp_tool removes x-procedure-only properties."""
        contract = self._make_contract_with_items()
        tool = ContractConverter.to_mcp_tool(contract)

        assert "text" in tool.inputSchema["properties"]
        assert "style" in tool.inputSchema["properties"]
        assert "items" not in tool.inputSchema["properties"]
        assert "chunk_size" not in tool.inputSchema["properties"]

    def test_contract_to_sdk_tool_strips_procedure_only(self):
        """Test that contract_to_sdk_tool removes x-procedure-only properties."""
        contract = self._make_contract_with_items()
        sdk_tool = ContractConverter.contract_to_sdk_tool(contract)

        assert "text" in sdk_tool.inputSchema["properties"]
        assert "items" not in sdk_tool.inputSchema["properties"]
        assert "chunk_size" not in sdk_tool.inputSchema["properties"]

    def test_stripping_does_not_mutate_original(self):
        """Test that stripping creates a copy and doesn't modify the original."""
        contract = self._make_contract_with_items()
        original_props = set(contract["input_schema"]["properties"].keys())

        ContractConverter.to_mcp_tool(contract)

        # Original contract should be unchanged
        assert set(contract["input_schema"]["properties"].keys()) == original_props
        assert "items" in contract["input_schema"]["properties"]

    def test_required_list_cleaned(self):
        """Test that required list is updated when procedure-only props removed."""
        contract = self._make_contract_with_items()
        # Add items to required (unusual but should be handled)
        contract["input_schema"]["required"] = ["text", "items"]

        tool = ContractConverter.to_mcp_tool(contract)

        assert tool.inputSchema["required"] == ["text"]

    def test_no_procedure_only_passes_through(self, sample_contract):
        """Test that contracts without x-procedure-only pass through unchanged."""
        tool = ContractConverter.to_mcp_tool(sample_contract)

        assert tool.inputSchema["properties"] == sample_contract["input_schema"]["properties"]
        assert tool.inputSchema["required"] == sample_contract["input_schema"]["required"]

    def test_null_defaults_stripped(self):
        """Test that 'default': null is stripped from properties."""
        contract = {
            "name": "llm_summarize",
            "description": "Summarize text",
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to summarize",
                    },
                    "focus": {
                        "type": "string",
                        "description": "What to focus on",
                        "default": None,
                    },
                    "model": {
                        "type": "string",
                        "description": "Model to use",
                        "default": None,
                    },
                    "style": {
                        "type": "string",
                        "description": "Summary style",
                        "default": "paragraph",
                    },
                },
                "required": ["text"],
            },
            "side_effects": False,
        }
        tool = ContractConverter.to_mcp_tool(contract)

        # "default": null should be removed
        assert "default" not in tool.inputSchema["properties"]["focus"]
        assert "default" not in tool.inputSchema["properties"]["model"]
        # Real defaults should be preserved
        assert tool.inputSchema["properties"]["style"]["default"] == "paragraph"
        # Non-default fields should be unaffected
        assert "default" not in tool.inputSchema["properties"]["text"]

    def test_null_defaults_not_mutate_original(self):
        """Test that stripping null defaults doesn't modify the original contract."""
        contract = {
            "name": "test",
            "description": "Test",
            "input_schema": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "default": None,
                    },
                },
            },
            "side_effects": False,
        }
        ContractConverter.to_mcp_tool(contract)

        # Original should still have "default": None
        assert "default" in contract["input_schema"]["properties"]["focus"]
        assert contract["input_schema"]["properties"]["focus"]["default"] is None
