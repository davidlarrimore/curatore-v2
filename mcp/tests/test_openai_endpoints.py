# OpenAI-Compatible Endpoint Tests
"""Tests for OpenAI-compatible tool endpoints."""

import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from app.main import app
from app.config import settings


class TestOpenAIToolsList:
    """Test OpenAI tools list endpoint."""

    def test_list_openai_tools(self, client, auth_headers, sample_contracts):
        """Test listing tools in OpenAI format."""
        with patch("app.handlers.tools_list.backend_client") as mock_client:
            with patch("app.handlers.tools_list.policy_service") as mock_policy:
                mock_client.get_contracts = AsyncMock(return_value=sample_contracts)
                mock_policy.allowlist = ["search_assets", "get_content"]
                mock_policy.block_side_effects = True
                mock_policy.contract_cache_ttl = 300

                response = client.get("/openai/tools", headers=auth_headers)

                assert response.status_code == 200
                data = response.json()

                # Check response structure
                assert "tools" in data
                assert "total" in data
                assert data["total"] == len(data["tools"])

                # Check tool format matches OpenAI spec
                for tool in data["tools"]:
                    assert tool["type"] == "function"
                    assert "function" in tool
                    func = tool["function"]
                    assert "name" in func
                    assert "description" in func
                    assert "parameters" in func
                    assert func["strict"] is True

    def test_openai_tools_filtered_by_policy(self, client, auth_headers, sample_contracts):
        """Test that side-effect tools are filtered out."""
        with patch("app.handlers.tools_list.backend_client") as mock_client:
            with patch("app.handlers.tools_list.policy_service") as mock_policy:
                mock_client.get_contracts = AsyncMock(return_value=sample_contracts)
                mock_policy.allowlist = ["search_assets", "get_content", "send_email"]
                mock_policy.block_side_effects = True
                mock_policy.contract_cache_ttl = 300

                response = client.get("/openai/tools", headers=auth_headers)

                assert response.status_code == 200
                data = response.json()

                tool_names = [t["function"]["name"] for t in data["tools"]]
                assert "search_assets" in tool_names
                assert "get_content" in tool_names
                assert "send_email" not in tool_names  # Has side effects

    def test_openai_tools_requires_auth(self, client):
        """Test that OpenAI endpoint requires authentication."""
        response = client.get("/openai/tools")
        assert response.status_code == 401

    def test_openai_tools_parameters_schema(self, client, auth_headers, sample_contracts):
        """Test that parameters match input schema."""
        with patch("app.handlers.tools_list.backend_client") as mock_client:
            with patch("app.handlers.tools_list.policy_service") as mock_policy:
                mock_client.get_contracts = AsyncMock(return_value=sample_contracts)
                mock_policy.allowlist = ["search_assets"]
                mock_policy.block_side_effects = True
                mock_policy.contract_cache_ttl = 300

                response = client.get("/openai/tools", headers=auth_headers)

                assert response.status_code == 200
                data = response.json()

                # Find search_assets tool
                search_tool = next(
                    (t for t in data["tools"] if t["function"]["name"] == "search_assets"),
                    None,
                )
                assert search_tool is not None

                params = search_tool["function"]["parameters"]
                assert params["type"] == "object"
                assert "query" in params["properties"]
                assert "limit" in params["properties"]
                assert "query" in params["required"]


class TestOpenAIToolsCall:
    """Test OpenAI tool call endpoint."""

    def test_call_openai_tool(self, client, auth_headers, sample_contract, sample_execution_result):
        """Test calling a tool via OpenAI endpoint."""
        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            with patch("app.handlers.tools_call.backend_client") as mock_client:
                mock_policy.is_allowed.return_value = True
                mock_policy.block_side_effects = True
                mock_policy.validate_facets = False
                mock_policy.apply_clamps.return_value = {"query": "test"}
                mock_client.get_contract = AsyncMock(return_value=sample_contract)
                mock_client.execute_function = AsyncMock(return_value=sample_execution_result)

                # OpenAI sends arguments directly in body
                response = client.post(
                    "/openai/tools/search_assets",
                    json={"query": "test"},
                    headers=auth_headers,
                )

                assert response.status_code == 200
                data = response.json()
                assert data["isError"] is False

    def test_call_openai_tool_with_wrapped_arguments(
        self, client, auth_headers, sample_contract, sample_execution_result
    ):
        """Test calling a tool with MCP-style wrapped arguments."""
        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            with patch("app.handlers.tools_call.backend_client") as mock_client:
                mock_policy.is_allowed.return_value = True
                mock_policy.block_side_effects = True
                mock_policy.validate_facets = False
                mock_policy.apply_clamps.return_value = {"query": "test"}
                mock_client.get_contract = AsyncMock(return_value=sample_contract)
                mock_client.execute_function = AsyncMock(return_value=sample_execution_result)

                # Also support MCP-style wrapped arguments
                response = client.post(
                    "/openai/tools/search_assets",
                    json={"arguments": {"query": "test"}},
                    headers=auth_headers,
                )

                assert response.status_code == 200
                data = response.json()
                assert data["isError"] is False

    def test_call_openai_tool_not_allowed(self, client, auth_headers):
        """Test calling a tool not in allowlist."""
        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            mock_policy.is_allowed.return_value = False

            response = client.post(
                "/openai/tools/blocked_tool",
                json={"query": "test"},
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["isError"] is True

    def test_call_openai_tool_requires_auth(self, client):
        """Test that OpenAI call endpoint requires authentication."""
        response = client.post("/openai/tools/search_assets", json={"query": "test"})
        assert response.status_code == 401

    def test_call_openai_tool_empty_body(
        self, client, auth_headers, sample_contract, sample_execution_result
    ):
        """Test calling a tool with empty body."""
        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            with patch("app.handlers.tools_call.backend_client") as mock_client:
                mock_policy.is_allowed.return_value = True
                mock_policy.block_side_effects = True
                mock_policy.validate_facets = False
                mock_policy.apply_clamps.return_value = {}
                mock_client.get_contract = AsyncMock(return_value=sample_contract)
                mock_client.execute_function = AsyncMock(return_value=sample_execution_result)

                response = client.post(
                    "/openai/tools/search_assets",
                    json={},
                    headers=auth_headers,
                )

                # Will fail validation since query is required
                assert response.status_code == 200


class TestOpenAIConverter:
    """Test OpenAI converter functions."""

    def test_mcp_to_openai_tool(self):
        """Test converting single MCP tool to OpenAI format."""
        from app.models.mcp import MCPTool
        from app.services.openai_converter import mcp_to_openai_tool

        mcp_tool = MCPTool(
            name="test_tool",
            description="A test tool",
            inputSchema={
                "type": "object",
                "properties": {"arg1": {"type": "string"}},
                "required": ["arg1"],
            },
        )

        openai_tool = mcp_to_openai_tool(mcp_tool)

        assert openai_tool.type == "function"
        assert openai_tool.function.name == "test_tool"
        assert openai_tool.function.description == "A test tool"
        assert openai_tool.function.parameters == mcp_tool.inputSchema
        assert openai_tool.function.strict is True

    def test_mcp_tools_to_openai(self):
        """Test converting multiple MCP tools to OpenAI format."""
        from app.models.mcp import MCPTool
        from app.services.openai_converter import mcp_tools_to_openai

        mcp_tools = [
            MCPTool(name="tool1", description="Tool 1", inputSchema={"type": "object"}),
            MCPTool(name="tool2", description="Tool 2", inputSchema={"type": "object"}),
        ]

        openai_tools = mcp_tools_to_openai(mcp_tools)

        assert len(openai_tools) == 2
        assert openai_tools[0].function.name == "tool1"
        assert openai_tools[1].function.name == "tool2"


class TestRootEndpointIncludesOpenAI:
    """Test that root endpoint includes OpenAI endpoints."""

    def test_root_includes_openai_endpoint(self, client):
        """Test root endpoint lists OpenAI endpoints."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "endpoints" in data
        assert "openai" in data["endpoints"]
        assert data["endpoints"]["openai"] == "/openai/tools"
