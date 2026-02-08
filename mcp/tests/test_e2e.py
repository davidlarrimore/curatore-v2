# End-to-End Tests
"""End-to-end tests for MCP Gateway."""

import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from app.main import app
from app.config import settings


class TestHealthEndpoints:
    """Test health and info endpoints."""

    def test_health(self, client):
        """Test health endpoint."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == settings.mcp_server_name

    def test_root(self, client):
        """Test root endpoint."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["service"] == settings.mcp_server_name
        assert "endpoints" in data


class TestAuthentication:
    """Test authentication middleware."""

    def test_mcp_requires_auth(self, client):
        """Test that MCP endpoint requires authentication."""
        response = client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        })

        assert response.status_code == 401

    def test_mcp_with_valid_auth(self, client, auth_headers):
        """Test MCP endpoint with valid auth."""
        with patch("app.handlers.tools_list.backend_client") as mock_client:
            with patch("app.handlers.tools_list.policy_service") as mock_policy:
                mock_client.get_contracts = AsyncMock(return_value=[])
                mock_policy.allowlist = []
                mock_policy.block_side_effects = True
                mock_policy.contract_cache_ttl = 300

                response = client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                    },
                    headers=auth_headers,
                )

                assert response.status_code == 200

    def test_invalid_api_key(self, client):
        """Test with invalid API key."""
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Authorization": "Bearer invalid_key"},
        )

        assert response.status_code == 401


class TestMCPProtocol:
    """Test MCP JSON-RPC protocol."""

    def test_initialize(self, client, auth_headers):
        """Test MCP initialize."""
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "test-client"},
                },
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        assert "result" in data
        assert data["result"]["protocolVersion"] == settings.mcp_protocol_version
        assert data["result"]["serverInfo"]["name"] == settings.mcp_server_name

    def test_tools_list(self, client, auth_headers, sample_contracts):
        """Test MCP tools/list."""
        with patch("app.handlers.tools_list.backend_client") as mock_client:
            with patch("app.handlers.tools_list.policy_service") as mock_policy:
                mock_client.get_contracts = AsyncMock(return_value=sample_contracts)
                mock_policy.allowlist = ["search_assets", "get_content"]
                mock_policy.block_side_effects = True
                mock_policy.contract_cache_ttl = 300

                response = client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                    },
                    headers=auth_headers,
                )

                assert response.status_code == 200
                data = response.json()
                assert "result" in data
                assert "tools" in data["result"]

                tool_names = [t["name"] for t in data["result"]["tools"]]
                assert "search_assets" in tool_names
                assert "send_email" not in tool_names  # Blocked by side_effects

    def test_tools_call(self, client, auth_headers, sample_contract, sample_execution_result):
        """Test MCP tools/call."""
        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            with patch("app.handlers.tools_call.backend_client") as mock_client:
                mock_policy.is_allowed.return_value = True
                mock_policy.block_side_effects = True
                mock_policy.validate_facets = False
                mock_policy.apply_clamps.return_value = {"query": "test"}
                mock_client.get_contract = AsyncMock(return_value=sample_contract)
                mock_client.execute_function = AsyncMock(return_value=sample_execution_result)

                response = client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "search_assets",
                            "arguments": {"query": "test"},
                        },
                    },
                    headers=auth_headers,
                )

                assert response.status_code == 200
                data = response.json()
                assert "result" in data
                assert data["result"]["isError"] is False

    def test_unknown_method(self, client, auth_headers):
        """Test unknown MCP method."""
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "unknown/method",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32601  # Method not found

    def test_invalid_json(self, client, auth_headers):
        """Test invalid JSON request."""
        response = client.post(
            "/mcp",
            content="not valid json",
            headers={**auth_headers, "Content-Type": "application/json"},
        )

        assert response.status_code == 400


class TestRESTEndpoints:
    """Test REST endpoints for testing."""

    def test_list_tools_rest(self, client, auth_headers, sample_contracts):
        """Test REST tools list endpoint."""
        with patch("app.handlers.tools_list.backend_client") as mock_client:
            with patch("app.handlers.tools_list.policy_service") as mock_policy:
                mock_client.get_contracts = AsyncMock(return_value=sample_contracts)
                mock_policy.allowlist = ["search_assets"]
                mock_policy.block_side_effects = True
                mock_policy.contract_cache_ttl = 300

                response = client.get("/mcp/tools", headers=auth_headers)

                assert response.status_code == 200
                data = response.json()
                assert "tools" in data

    def test_call_tool_rest(self, client, auth_headers, sample_contract, sample_execution_result):
        """Test REST tool call endpoint."""
        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            with patch("app.handlers.tools_call.backend_client") as mock_client:
                mock_policy.is_allowed.return_value = True
                mock_policy.block_side_effects = True
                mock_policy.validate_facets = False
                mock_policy.apply_clamps.return_value = {"query": "test"}
                mock_client.get_contract = AsyncMock(return_value=sample_contract)
                mock_client.execute_function = AsyncMock(return_value=sample_execution_result)

                response = client.post(
                    "/mcp/tools/search_assets/call",
                    json={"arguments": {"query": "test"}},
                    headers=auth_headers,
                )

                assert response.status_code == 200
                data = response.json()
                assert data["isError"] is False


class TestPolicyEndpoints:
    """Test policy management endpoints."""

    def test_get_policy(self, client, auth_headers):
        """Test getting current policy."""
        response = client.get("/policy", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "allowlist" in data
        assert "settings" in data

    def test_reload_policy(self, client, auth_headers):
        """Test reloading policy."""
        response = client.post("/policy/reload", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "reloaded"
