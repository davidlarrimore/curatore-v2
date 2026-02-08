# Contract Converter Tests
"""Tests for ToolContract to MCP Tool conversion."""

import pytest
from app.services.contract_converter import ContractConverter
from app.models.mcp import MCPTool


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
