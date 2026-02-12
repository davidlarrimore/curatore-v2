# Tools List Handler Tests
"""Tests for MCP tools/list handler."""

from unittest.mock import AsyncMock, patch

import pytest
from app.handlers.tools_list import clear_cache, handle_tools_list


class TestToolsList:
    """Test tools/list handler."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Clear cache before each test."""
        clear_cache()

    @pytest.mark.asyncio
    async def test_list_tools_empty(self):
        """Test listing tools with empty backend response."""
        with patch("app.handlers.tools_list.backend_client") as mock_client:
            with patch("app.handlers.tools_list.policy_service") as mock_policy:
                mock_client.get_contracts = AsyncMock(return_value=[])
                mock_policy.contract_cache_ttl = 300
                mock_policy.filter_allowed.return_value = []

                result = await handle_tools_list()

                assert result.tools == []

    @pytest.mark.asyncio
    async def test_list_tools_filtered(self, sample_contracts):
        """Test that tools are filtered by policy (v2.0 auto-derive)."""
        with patch("app.handlers.tools_list.backend_client") as mock_client:
            with patch("app.handlers.tools_list.policy_service") as mock_policy:
                mock_client.get_contracts = AsyncMock(return_value=sample_contracts)
                mock_policy.contract_cache_ttl = 300
                # Simulate v2.0 filtering: agent=True and no side_effects
                mock_policy.filter_allowed.return_value = [
                    c for c in sample_contracts
                    if c.get("exposure_profile", {}).get("agent", False)
                    and not c.get("side_effects", False)
                ]

                result = await handle_tools_list()

                # send_email is excluded (agent=False + side_effects=True)
                tool_names = [t.name for t in result.tools]
                assert "search_assets" in tool_names
                assert "get_content" in tool_names
                assert "send_email" not in tool_names

    @pytest.mark.asyncio
    async def test_list_tools_caching(self, sample_contracts):
        """Test that contracts are cached."""
        with patch("app.handlers.tools_list.backend_client") as mock_client:
            with patch("app.handlers.tools_list.policy_service") as mock_policy:
                mock_client.get_contracts = AsyncMock(return_value=sample_contracts)
                mock_policy.contract_cache_ttl = 300
                mock_policy.filter_allowed.return_value = [sample_contracts[0]]

                # First call
                await handle_tools_list()
                # Second call
                await handle_tools_list()

                # Backend should only be called once due to caching
                assert mock_client.get_contracts.call_count == 1

    @pytest.mark.asyncio
    async def test_list_tools_schema_preserved(self, sample_contract):
        """Test that input schema is preserved correctly."""
        with patch("app.handlers.tools_list.backend_client") as mock_client:
            with patch("app.handlers.tools_list.policy_service") as mock_policy:
                mock_client.get_contracts = AsyncMock(return_value=[sample_contract])
                mock_policy.contract_cache_ttl = 300
                mock_policy.filter_allowed.return_value = [sample_contract]

                result = await handle_tools_list()

                assert len(result.tools) == 1
                tool = result.tools[0]

                # Check inputSchema matches input_schema from contract
                assert tool.inputSchema == sample_contract["input_schema"]
                assert tool.inputSchema["type"] == "object"
                assert "query" in tool.inputSchema["properties"]
