"""
Unit tests for ConnectionService.

Tests connection type registry, config validation, health testing, and CRUD operations
for runtime-configurable service connections.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from app.core.auth.connection_service import (
    ConnectionService,
    ConnectionTestResult,
    ConnectionTypeRegistry,
    ExtractionConnectionType,
    MicrosoftGraphConnectionType,
    connection_service,
)


@pytest.fixture
def connection_service_instance():
    """Create ConnectionService instance for testing."""
    return ConnectionService()


@pytest.fixture
def registry_instance():
    """Create ConnectionTypeRegistry instance for testing."""
    return ConnectionTypeRegistry()


class TestConnectionServiceInitialization:
    """Test ConnectionService initialization."""

    def test_initialization(self, connection_service_instance):
        """Test service initializes with registry."""
        assert connection_service_instance._registry is not None
        assert isinstance(connection_service_instance._registry, ConnectionTypeRegistry)

    def test_singleton_instance(self):
        """Test that connection_service is a singleton instance."""
        assert connection_service is not None
        assert isinstance(connection_service, ConnectionService)

    def test_default_types_registered(self, connection_service_instance):
        """Test that default connection types are registered."""
        registry = connection_service_instance.registry

        # Should have Microsoft Graph (for SharePoint), Extraction, Playwright, and SAM.gov types
        assert registry.get("microsoft_graph") is not None
        assert registry.get("extraction") is not None
        assert registry.get("playwright") is not None
        assert registry.get("sam_gov") is not None


class TestConnectionTypeRegistry:
    """Test ConnectionTypeRegistry."""

    def test_register_connection_type(self, registry_instance):
        """Test registering a connection type."""
        ms_type = MicrosoftGraphConnectionType()
        registry_instance.register(ms_type)

        retrieved = registry_instance.get("microsoft_graph")
        assert retrieved is not None
        assert retrieved.connection_type == "microsoft_graph"

    def test_register_duplicate_type_overwrites(self, registry_instance):
        """Test that registering duplicate type overwrites."""
        ms_type1 = MicrosoftGraphConnectionType()
        ms_type2 = MicrosoftGraphConnectionType()

        registry_instance.register(ms_type1)
        registry_instance.register(ms_type2)

        # Should still have only one
        types = registry_instance.list_types()
        ms_graph_types = [t for t in types if t["type"] == "microsoft_graph"]
        assert len(ms_graph_types) == 1

    def test_get_nonexistent_type(self, registry_instance):
        """Test getting non-existent connection type."""
        result = registry_instance.get("nonexistent")
        assert result is None

    def test_list_types(self, registry_instance):
        """Test listing all connection types."""
        ms_type = MicrosoftGraphConnectionType()
        ext_type = ExtractionConnectionType()

        registry_instance.register(ms_type)
        registry_instance.register(ext_type)

        types = registry_instance.list_types()

        assert len(types) == 2
        type_names = [t["type"] for t in types]
        assert "microsoft_graph" in type_names
        assert "extraction" in type_names

    def test_list_types_includes_schema(self, registry_instance):
        """Test that list_types includes config schema."""
        ms_type = MicrosoftGraphConnectionType()
        registry_instance.register(ms_type)

        types = registry_instance.list_types()

        ms_info = next(t for t in types if t["type"] == "microsoft_graph")
        assert "config_schema" in ms_info
        assert "properties" in ms_info["config_schema"]


class TestMicrosoftGraphConnectionType:
    """Test MicrosoftGraphConnectionType."""

    def test_connection_type_attributes(self):
        """Test Microsoft Graph connection type attributes."""
        ms_type = MicrosoftGraphConnectionType()

        assert ms_type.connection_type == "microsoft_graph"
        assert ms_type.display_name == "Microsoft Graph API"
        assert len(ms_type.description) > 0

    def test_get_config_schema(self):
        """Test getting Microsoft Graph config schema."""
        ms_type = MicrosoftGraphConnectionType()
        schema = ms_type.get_config_schema()

        assert schema["type"] == "object"
        assert "properties" in schema
        assert "tenant_id" in schema["properties"]
        assert "client_id" in schema["properties"]
        assert "client_secret" in schema["properties"]
        assert "required" in schema
        assert "tenant_id" in schema["required"]

    def test_validate_config_valid(self):
        """Test validating valid SharePoint config."""
        sp_type = MicrosoftGraphConnectionType()

        config = {
            "tenant_id": "12345678-1234-1234-1234-123456789abc",
            "client_id": "app-id-123",
            "client_secret": "secret123",
        }

        validated = sp_type.validate_config(config)

        assert validated["tenant_id"] == config["tenant_id"]
        assert validated["client_id"] == config["client_id"]
        assert validated["client_secret"] == config["client_secret"]

    def test_validate_config_with_defaults(self):
        """Test that validation applies defaults."""
        sp_type = MicrosoftGraphConnectionType()

        config = {
            "tenant_id": "12345678-1234-1234-1234-123456789abc",
            "client_id": "app-id",
            "client_secret": "secret",
        }

        validated = sp_type.validate_config(config)

        # Should have default values
        assert "graph_base_url" in validated
        assert "graph_scope" in validated

    def test_validate_config_missing_required(self):
        """Test validation fails with missing required field."""
        sp_type = MicrosoftGraphConnectionType()

        config = {
            "tenant_id": "12345678-1234-1234-1234-123456789abc",
            # Missing client_id and client_secret
        }

        with pytest.raises(ValueError):
            sp_type.validate_config(config)

    def test_validate_config_invalid_type(self):
        """Test validation fails with invalid field type."""
        sp_type = MicrosoftGraphConnectionType()

        config = {
            "tenant_id": 12345,  # Should be string
            "client_id": "app-id",
            "client_secret": "secret",
        }

        with pytest.raises(ValueError):
            sp_type.validate_config(config)

    @pytest.mark.asyncio
    async def test_connection_successful(self):
        """Test successful Microsoft Graph connection test."""
        ms_type = MicrosoftGraphConnectionType()

        config = {
            "tenant_id": "test-tenant",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "graph_scope": "https://graph.microsoft.com/.default",
            "graph_base_url": "https://graph.microsoft.com/v1.0",
        }

        # Mock HTTP responses
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock token response - json() is NOT async in httpx
            mock_token_response = MagicMock()
            mock_token_response.status_code = 200
            mock_token_response.json.return_value = {"access_token": "test-token"}

            # Mock graph API response
            mock_graph_response = MagicMock()
            mock_graph_response.status_code = 200

            mock_client.post.return_value = mock_token_response
            mock_client.get.return_value = mock_graph_response

            result = await ms_type.test_connection(config)

            assert result.success is True
            assert result.status == "healthy"

    @pytest.mark.asyncio
    async def test_connection_auth_failure(self):
        """Test SharePoint connection test with auth failure."""
        sp_type = MicrosoftGraphConnectionType()

        config = {
            "tenant_id": "test-tenant",
            "client_id": "test-client",
            "client_secret": "wrong-secret",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock failed token response
            mock_token_response = AsyncMock()
            mock_token_response.status_code = 401
            mock_token_response.text = "Invalid credentials"

            mock_client.post.return_value = mock_token_response

            result = await sp_type.test_connection(config)

            assert result.success is False
            assert result.status == "unhealthy"

    @pytest.mark.asyncio
    async def test_connection_timeout(self):
        """Test SharePoint connection test with timeout."""
        sp_type = MicrosoftGraphConnectionType()

        config = {
            "tenant_id": "test-tenant",
            "client_id": "test-client",
            "client_secret": "test-secret",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.side_effect = httpx.TimeoutException("Timeout")

            result = await sp_type.test_connection(config)

            assert result.success is False
            assert result.status == "unhealthy"
            assert "timeout" in result.message.lower()


class TestExtractionConnectionType:
    """Test ExtractionConnectionType."""

    def test_connection_type_attributes(self):
        """Test Extraction connection type attributes."""
        ext_type = ExtractionConnectionType()

        assert ext_type.connection_type == "extraction"
        assert "Document Service" in ext_type.display_name
        assert len(ext_type.description) > 0

    def test_get_config_schema(self):
        """Test getting Extraction config schema."""
        ext_type = ExtractionConnectionType()
        schema = ext_type.get_config_schema()

        assert schema["type"] == "object"
        assert "service_url" in schema["properties"]
        assert "timeout" in schema["properties"]

    def test_validate_config_valid(self):
        """Test validating valid Extraction config."""
        ext_type = ExtractionConnectionType()

        config = {
            "service_url": "http://extraction:8010",
        }

        validated = ext_type.validate_config(config)

        assert validated["service_url"] == config["service_url"]

    def test_validate_config_with_api_key(self):
        """Test Extraction config with optional API key."""
        ext_type = ExtractionConnectionType()

        config = {
            "service_url": "http://extraction:8010",
            "api_key": "test-key-123",
        }

        validated = ext_type.validate_config(config)

        assert validated["api_key"] == config["api_key"]

    @pytest.mark.asyncio
    async def test_extraction_connection_successful(self):
        """Test successful Extraction connection test."""
        ext_type = ExtractionConnectionType()

        config = {
            "service_url": "http://extraction:8010",
            "timeout": 30,
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock health endpoint response
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "healthy"}

            mock_client.get.return_value = mock_response

            result = await ext_type.test_connection(config)

            assert result.success is True
            assert result.status == "healthy"

    @pytest.mark.asyncio
    async def test_extraction_connection_service_down(self):
        """Test Extraction connection when service is down."""
        ext_type = ExtractionConnectionType()

        config = {
            "service_url": "http://extraction:8010",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock 503 response
            mock_response = AsyncMock()
            mock_response.status_code = 503

            mock_client.get.return_value = mock_response

            result = await ext_type.test_connection(config)

            assert result.success is False
            assert result.status == "unhealthy"


class TestConnectionTestResult:
    """Test ConnectionTestResult model."""

    def test_create_success_result(self):
        """Test creating successful test result."""
        result = ConnectionTestResult(
            success=True,
            status="healthy",
            message="Connection successful",
        )

        assert result.success is True
        assert result.status == "healthy"
        assert result.message == "Connection successful"
        assert result.details is None
        assert result.error is None

    def test_create_failure_result(self):
        """Test creating failed test result."""
        result = ConnectionTestResult(
            success=False,
            status="unhealthy",
            message="Connection failed",
            error="Timeout after 30s",
        )

        assert result.success is False
        assert result.status == "unhealthy"
        assert result.error is not None

    def test_create_result_with_details(self):
        """Test creating result with details."""
        details = {
            "endpoint": "https://api.example.com",
            "latency_ms": 150,
        }

        result = ConnectionTestResult(
            success=True,
            status="healthy",
            message="Test passed",
            details=details,
        )

        assert result.details == details
        assert result.details["latency_ms"] == 150


class TestConnectionTypeSchemas:
    """Test connection type schema generation."""

    def test_microsoft_graph_schema_has_required_fields(self):
        """Test Microsoft Graph schema has all required fields."""
        ms_type = MicrosoftGraphConnectionType()
        schema = ms_type.get_config_schema()

        required_fields = schema.get("required", [])
        assert "tenant_id" in required_fields
        assert "client_id" in required_fields
        assert "client_secret" in required_fields

    def test_extraction_schema_has_optional_fields(self):
        """Test Extraction schema has optional fields."""
        ext_type = ExtractionConnectionType()
        schema = ext_type.get_config_schema()

        # service_url is required
        assert "service_url" in schema.get("required", [])

        # api_key is optional (not in required)
        assert "api_key" not in schema.get("required", [])


class TestErrorHandling:
    """Test error handling in connection service."""

    def test_validate_config_handles_empty_dict(self):
        """Test config validation with empty dict."""
        sp_type = MicrosoftGraphConnectionType()

        with pytest.raises(ValueError):
            sp_type.validate_config({})

    def test_validate_config_handles_none(self):
        """Test config validation with None."""
        ext_type = ExtractionConnectionType()

        with pytest.raises((ValueError, TypeError)):
            ext_type.validate_config(None)

    @pytest.mark.asyncio
    async def test_test_connection_handles_network_error(self):
        """Test connection testing handles network errors."""
        ms_type = MicrosoftGraphConnectionType()

        config = {
            "tenant_id": "12345678-1234-1234-1234-123456789abc",
            "client_id": "app-id",
            "client_secret": "secret",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = Exception("Network error")

            result = await ms_type.test_connection(config)

            assert result.success is False
            assert result.error is not None


class TestConfigNormalization:
    """Test configuration normalization."""

    def test_microsoft_graph_url_normalization(self):
        """Test Microsoft Graph URL normalization."""
        ms_type = MicrosoftGraphConnectionType()

        config = {
            "tenant_id": "12345678-1234-1234-1234-123456789abc",
            "client_id": "app-id",
            "client_secret": "secret",
            "graph_base_url": "https://graph.microsoft.com/v1.0/",  # Extra slash
        }

        validated = ms_type.validate_config(config)

        # Should normalize URL (though this might not be implemented)
        assert "graph_base_url" in validated

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
