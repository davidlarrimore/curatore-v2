# Tools Call Handler Tests
"""Tests for MCP tools/call handler."""

import pytest
from unittest.mock import AsyncMock, patch

from app.handlers.tools_call import handle_tools_call
from app.models.mcp import MCPToolsCallResponse


class TestToolsCall:
    """Test tools/call handler."""

    @pytest.mark.asyncio
    async def test_tool_not_allowed(self):
        """Test calling a tool not in allowlist."""
        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            mock_policy.is_allowed.return_value = False

            result = await handle_tools_call("blocked_tool", {})

            assert result.isError is True
            assert "not available" in result.content[0].text

    @pytest.mark.asyncio
    async def test_tool_not_found(self, sample_contract):
        """Test calling a tool that doesn't exist in backend."""
        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            with patch("app.handlers.tools_call.backend_client") as mock_client:
                mock_policy.is_allowed.return_value = True
                mock_client.get_contract = AsyncMock(return_value=None)

                result = await handle_tools_call("nonexistent", {})

                assert result.isError is True
                assert "not found" in result.content[0].text

    @pytest.mark.asyncio
    async def test_side_effects_blocked(self, sample_contract):
        """Test that side-effect tools are blocked."""
        sample_contract["side_effects"] = True

        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            with patch("app.handlers.tools_call.backend_client") as mock_client:
                mock_policy.is_allowed.return_value = True
                mock_policy.block_side_effects = True
                mock_client.get_contract = AsyncMock(return_value=sample_contract)

                result = await handle_tools_call("send_email", {})

                assert result.isError is True
                assert "side effects" in result.content[0].text

    @pytest.mark.asyncio
    async def test_validation_error(self, sample_contract):
        """Test schema validation failure."""
        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            with patch("app.handlers.tools_call.backend_client") as mock_client:
                mock_policy.is_allowed.return_value = True
                mock_policy.block_side_effects = True
                mock_policy.apply_clamps.return_value = {}
                mock_client.get_contract = AsyncMock(return_value=sample_contract)

                # Missing required 'query' parameter
                result = await handle_tools_call("search_assets", {})

                assert result.isError is True
                assert "Invalid arguments" in result.content[0].text

    @pytest.mark.asyncio
    async def test_clamps_applied(self, sample_contract, sample_execution_result):
        """Test that policy clamps are applied."""
        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            with patch("app.handlers.tools_call.backend_client") as mock_client:
                mock_policy.is_allowed.return_value = True
                mock_policy.block_side_effects = True
                mock_policy.validate_facets = False
                # Clamp limit from 500 to 50
                mock_policy.apply_clamps.return_value = {"query": "test", "limit": 50}
                mock_client.get_contract = AsyncMock(return_value=sample_contract)
                mock_client.execute_function = AsyncMock(return_value=sample_execution_result)

                result = await handle_tools_call(
                    "search_assets",
                    {"query": "test", "limit": 500},
                )

                # Verify clamps were applied
                mock_policy.apply_clamps.assert_called_once()

                # Verify execute was called with clamped value
                call_args = mock_client.execute_function.call_args
                assert call_args.kwargs["params"]["limit"] == 50

    @pytest.mark.asyncio
    async def test_successful_execution(self, sample_contract, sample_execution_result):
        """Test successful tool execution."""
        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            with patch("app.handlers.tools_call.backend_client") as mock_client:
                mock_policy.is_allowed.return_value = True
                mock_policy.block_side_effects = True
                mock_policy.validate_facets = False
                mock_policy.apply_clamps.return_value = {"query": "test"}
                mock_client.get_contract = AsyncMock(return_value=sample_contract)
                mock_client.execute_function = AsyncMock(return_value=sample_execution_result)

                result = await handle_tools_call("search_assets", {"query": "test"})

                assert result.isError is False
                assert len(result.content) == 1
                # Result should contain the data as JSON
                assert "asset-1" in result.content[0].text

    @pytest.mark.asyncio
    async def test_execution_error(self, sample_contract):
        """Test handling execution errors from backend."""
        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            with patch("app.handlers.tools_call.backend_client") as mock_client:
                mock_policy.is_allowed.return_value = True
                mock_policy.block_side_effects = True
                mock_policy.validate_facets = False
                mock_policy.apply_clamps.return_value = {"query": "test"}
                mock_client.get_contract = AsyncMock(return_value=sample_contract)
                mock_client.execute_function = AsyncMock(
                    return_value={"status": "error", "error": "Database connection failed"}
                )

                result = await handle_tools_call("search_assets", {"query": "test"})

                assert result.isError is True
                assert "Database connection failed" in result.content[0].text

    @pytest.mark.asyncio
    async def test_facet_validation(self, sample_contract, sample_execution_result):
        """Test facet validation."""
        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            with patch("app.handlers.tools_call.backend_client") as mock_client:
                with patch("app.handlers.tools_call.facet_validator") as mock_facet:
                    mock_policy.is_allowed.return_value = True
                    mock_policy.block_side_effects = True
                    mock_policy.validate_facets = True
                    mock_policy.apply_clamps.return_value = {
                        "query": "test",
                        "facet_filters": {"invalid_facet": "value"},
                    }
                    mock_client.get_contract = AsyncMock(return_value=sample_contract)
                    mock_facet.validate_facets = AsyncMock(
                        return_value=(False, ["invalid_facet"])
                    )

                    result = await handle_tools_call(
                        "search_assets",
                        {"query": "test", "facet_filters": {"invalid_facet": "value"}},
                        org_id="test-org",
                    )

                    assert result.isError is True
                    assert "Unknown facets" in result.content[0].text
                    assert "invalid_facet" in result.content[0].text
