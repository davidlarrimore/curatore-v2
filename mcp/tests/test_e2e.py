# End-to-End Tests
"""End-to-end tests for MCP Gateway."""

from unittest.mock import AsyncMock, patch

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
        # Verify updated endpoints
        assert data["endpoints"]["mcp"] == "/mcp"
        assert data["endpoints"]["rest"] == "/rest/tools"


class TestAuthentication:
    """Test authentication middleware."""

    def test_rest_requires_auth(self, client):
        """Test that REST endpoint requires authentication."""
        response = client.get("/rest/tools")

        assert response.status_code == 401

    def test_invalid_api_key(self, client):
        """Test with invalid API key."""
        response = client.get(
            "/rest/tools",
            headers={"Authorization": "Bearer invalid_key"},
        )

        assert response.status_code == 401


class TestRESTEndpoints:
    """Test REST convenience endpoints (relocated from /mcp/tools to /rest/tools)."""

    def test_list_tools_rest(self, client, auth_headers, sample_contracts):
        """Test REST tools list endpoint at new path."""
        with patch("app.handlers.tools_list.backend_client") as mock_client:
            with patch("app.handlers.tools_list.policy_service") as mock_policy:
                mock_client.get_contracts = AsyncMock(return_value=sample_contracts)
                mock_policy.contract_cache_ttl = 300
                # v2.0 auto-derive mode
                mock_policy.filter_allowed.return_value = [
                    c for c in sample_contracts
                    if c.get("exposure_profile", {}).get("agent", False)
                    and not c.get("side_effects", False)
                ]

                response = client.get("/rest/tools", headers=auth_headers)

                assert response.status_code == 200
                data = response.json()
                assert "tools" in data

    def test_call_tool_rest(self, client, auth_headers, sample_contract, sample_execution_result):
        """Test REST tool call endpoint at new path."""
        with patch("app.handlers.tools_call.policy_service") as mock_policy:
            with patch("app.handlers.tools_call.backend_client") as mock_client:
                mock_policy.is_allowed.return_value = True
                mock_policy.policy.is_v2 = True
                mock_policy.block_side_effects = True
                mock_policy.validate_facets = False
                mock_policy.apply_clamps.return_value = {"query": "test"}
                mock_client.get_contract = AsyncMock(return_value=sample_contract)
                mock_client.execute_function = AsyncMock(return_value=sample_execution_result)

                response = client.post(
                    "/rest/tools/search_assets/call",
                    json={"arguments": {"query": "test"}},
                    headers=auth_headers,
                )

                assert response.status_code == 200
                data = response.json()
                assert data["isError"] is False

    def test_old_mcp_tools_path_not_rest(self, client, auth_headers):
        """Test that old /mcp/tools path is no longer a REST endpoint."""
        response = client.get("/mcp/tools", headers=auth_headers)
        # The old /mcp/tools REST endpoint no longer exists — returns 404
        assert response.status_code == 404


class TestPolicyEndpoints:
    """Test policy management endpoints."""

    def test_get_policy_v2(self, client, auth_headers):
        """Test getting current v2.0 policy."""
        response = client.get("/policy", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "settings" in data
        # v2.0 uses denylist, not allowlist
        if data["version"].startswith("2"):
            assert "denylist" in data

    def test_reload_policy(self, client, auth_headers):
        """Test reloading policy."""
        response = client.post("/policy/reload", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "reloaded"
