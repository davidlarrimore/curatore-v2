# MCP SDK Server Tests
"""Tests for MCP SDK server handlers."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.server import sdk_list_tools, sdk_call_tool, sdk_list_resources
from app.server import ctx_org_id, ctx_api_key, ctx_correlation_id


class TestSDKListTools:
    """Test SDK list_tools handler."""

    @pytest.mark.asyncio
    async def test_list_tools_delegates_to_handler(self, sample_contracts):
        """Test that SDK list_tools delegates to existing handler."""
        with patch("app.server.handle_tools_list") as mock_handler:
            mock_response = MagicMock()
            mock_response.tools = []
            mock_handler.return_value = mock_response

            ctx_api_key.set("test-key")
            ctx_correlation_id.set("test-corr")

            result = await sdk_list_tools()

            mock_handler.assert_called_once_with("test-key", "test-corr")
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_tools_converts_to_sdk_types(self, sample_contracts):
        """Test that tools are converted to SDK types.Tool."""
        from app.models.mcp import MCPTool

        with patch("app.server.handle_tools_list") as mock_handler:
            mock_response = MagicMock()
            mock_response.tools = [
                MCPTool(
                    name="search_assets",
                    description="Search assets",
                    inputSchema={"type": "object", "properties": {}},
                ),
            ]
            mock_handler.return_value = mock_response

            ctx_api_key.set("test-key")
            result = await sdk_list_tools()

            assert len(result) == 1
            # Should be mcp.types.Tool instances
            assert result[0].name == "search_assets"
            assert result[0].description == "Search assets"
            assert result[0].annotations is not None


class TestSDKCallTool:
    """Test SDK call_tool handler."""

    @pytest.mark.asyncio
    async def test_call_tool_delegates_to_handler(self, sample_execution_result):
        """Test that SDK call_tool delegates to existing handler."""
        from app.models.mcp import MCPTextContent, MCPToolsCallResponse

        with patch("app.server.handle_tools_call") as mock_handler:
            mock_handler.return_value = MCPToolsCallResponse(
                content=[MCPTextContent(type="text", text="Search results")],
                isError=False,
            )

            ctx_org_id.set("test-org")
            ctx_api_key.set("test-key")
            ctx_correlation_id.set("test-corr")

            result = await sdk_call_tool("search_assets", {"query": "test"})

            mock_handler.assert_called_once_with(
                name="search_assets",
                arguments={"query": "test"},
                org_id="test-org",
                api_key="test-key",
                correlation_id="test-corr",
            )
            assert len(result) == 1
            assert result[0].text == "Search results"

    @pytest.mark.asyncio
    async def test_call_tool_empty_arguments(self):
        """Test calling a tool with no arguments."""
        from app.models.mcp import MCPTextContent, MCPToolsCallResponse

        with patch("app.server.handle_tools_call") as mock_handler:
            mock_handler.return_value = MCPToolsCallResponse(
                content=[MCPTextContent(type="text", text="OK")],
                isError=False,
            )

            result = await sdk_call_tool("discover_data_sources", {})

            call_args = mock_handler.call_args
            assert call_args.kwargs["arguments"] == {}

    @pytest.mark.asyncio
    async def test_call_tool_error_response(self):
        """Test that errors are propagated as TextContent."""
        from app.models.mcp import MCPTextContent, MCPToolsCallResponse

        with patch("app.server.handle_tools_call") as mock_handler:
            mock_handler.return_value = MCPToolsCallResponse(
                content=[MCPTextContent(type="text", text="Error: not found")],
                isError=True,
            )

            result = await sdk_call_tool("missing_tool", {})

            assert len(result) == 1
            assert "Error" in result[0].text


class TestSDKListResources:
    """Test SDK list_resources handler."""

    @pytest.mark.asyncio
    async def test_list_resources_delegates_to_handler(self):
        """Test that SDK list_resources delegates to existing handler."""
        with patch("app.server.handle_resources_list") as mock_handler:
            mock_handler.return_value = {
                "resources": [
                    {
                        "uri": "curatore://data-sources/sam",
                        "name": "SAM.gov",
                        "description": "Federal procurement data",
                        "mimeType": "text/plain",
                    },
                ]
            }

            ctx_api_key.set("test-key")
            ctx_correlation_id.set("test-corr")

            result = await sdk_list_resources()

            mock_handler.assert_called_once_with("test-key", "test-corr")
            assert len(result) == 1
            assert result[0].name == "SAM.gov"
            assert str(result[0].uri) == "curatore://data-sources/sam"

    @pytest.mark.asyncio
    async def test_list_resources_empty(self):
        """Test empty resources list."""
        with patch("app.server.handle_resources_list") as mock_handler:
            mock_handler.return_value = {"resources": []}

            result = await sdk_list_resources()

            assert result == []
