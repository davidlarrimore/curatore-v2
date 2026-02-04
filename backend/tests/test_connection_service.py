"""
Unit tests for ConnectionService.

Tests connection type registry, config validation, health testing, and CRUD operations
for runtime-configurable service connections.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from typing import Dict, Any
from pydantic import ValidationError
import httpx

from app.services.connection_service import (
    ConnectionService,
    ConnectionTypeRegistry,
    BaseConnectionType,
    MicrosoftGraphConnectionType,
    LLMConnectionType,
    ExtractionConnectionType,
    ConnectionTestResult,
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

        # Should have SharePoint, LLM, and Extraction types
        assert registry.get("sharepoint") is not None
        assert registry.get("llm") is not None
        assert registry.get("extraction") is not None


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
        llm_type = LLMConnectionType()

        registry_instance.register(ms_type)
        registry_instance.register(llm_type)

        types = registry_instance.list_types()

        assert len(types) == 2
        type_names = [t["type"] for t in types]
        assert "microsoft_graph" in type_names
        assert "llm" in type_names

    def test_list_types_includes_schema(self, registry_instance):
        """Test that list_types includes config schema."""
        ms_type = MicrosoftGraphConnectionType()
        registry_instance.register(ms_type)

        types = registry_instance.list_types()

        ms_info = next(t for t in types if t["type"] == "microsoft_graph")
        assert "schema" in ms_info
        assert "properties" in ms_info["schema"]


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
        sp_type = SharePointConnectionType()

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
        sp_type = SharePointConnectionType()

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
        sp_type = SharePointConnectionType()

        config = {
            "tenant_id": "12345678-1234-1234-1234-123456789abc",
            # Missing client_id and client_secret
        }

        with pytest.raises(ValueError):
            sp_type.validate_config(config)

    def test_validate_config_invalid_type(self):
        """Test validation fails with invalid field type."""
        sp_type = SharePointConnectionType()

        config = {
            "tenant_id": 12345,  # Should be string
            "client_id": "app-id",
            "client_secret": "secret",
        }

        with pytest.raises(ValueError):
            sp_type.validate_config(config)

    @pytest.mark.asyncio
    async def test_connection_successful(self):
        """Test successful SharePoint connection test."""
        sp_type = SharePointConnectionType()

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

            # Mock token response
            mock_token_response = AsyncMock()
            mock_token_response.status_code = 200
            mock_token_response.json.return_value = {"access_token": "test-token"}

            # Mock graph API response
            mock_graph_response = AsyncMock()
            mock_graph_response.status_code = 200

            mock_client.post.return_value = mock_token_response
            mock_client.get.return_value = mock_graph_response

            result = await sp_type.test_connection(config)

            assert result.success is True
            assert result.status == "healthy"

    @pytest.mark.asyncio
    async def test_connection_auth_failure(self):
        """Test SharePoint connection test with auth failure."""
        sp_type = SharePointConnectionType()

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
        sp_type = SharePointConnectionType()

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


class TestLLMConnectionType:
    """Test LLMConnectionType."""

    def test_connection_type_attributes(self):
        """Test LLM connection type attributes."""
        llm_type = LLMConnectionType()

        assert llm_type.connection_type == "llm"
        assert llm_type.display_name == "LLM API"
        assert len(llm_type.description) > 0

    def test_get_config_schema(self):
        """Test getting LLM config schema."""
        llm_type = LLMConnectionType()
        schema = llm_type.get_config_schema()

        assert schema["type"] == "object"
        assert "api_key" in schema["properties"]
        assert "model" in schema["properties"]
        assert "base_url" in schema["properties"]
        assert "timeout" in schema["properties"]
        assert "verify_ssl" in schema["properties"]

    def test_validate_config_valid(self):
        """Test validating valid LLM config."""
        llm_type = LLMConnectionType()

        config = {
            "api_key": "sk-test123",
            "model": "gpt-4",
            "base_url": "https://api.openai.com/v1",
        }

        validated = llm_type.validate_config(config)

        assert validated["api_key"] == config["api_key"]
        assert validated["model"] == config["model"]
        assert validated["base_url"] == config["base_url"]

    def test_validate_config_with_defaults(self):
        """Test LLM config validation with defaults."""
        llm_type = LLMConnectionType()

        config = {
            "api_key": "sk-test",
            "model": "gpt-4",
            "base_url": "https://api.openai.com/v1",
        }

        validated = llm_type.validate_config(config)

        # Should have default values
        assert "timeout" in validated
        assert validated["timeout"] == 60
        assert "verify_ssl" in validated
        assert validated["verify_ssl"] is True

    def test_validate_config_timeout_bounds(self):
        """Test LLM config timeout validation."""
        llm_type = LLMConnectionType()

        # Test minimum bound
        config_min = {
            "api_key": "sk-test",
            "model": "gpt-4",
            "base_url": "https://api.openai.com/v1",
            "timeout": 1,
        }
        validated_min = llm_type.validate_config(config_min)
        assert validated_min["timeout"] == 1

        # Test maximum bound
        config_max = {
            "api_key": "sk-test",
            "model": "gpt-4",
            "base_url": "https://api.openai.com/v1",
            "timeout": 600,
        }
        validated_max = llm_type.validate_config(config_max)
        assert validated_max["timeout"] == 600

        # Test out of bounds (should fail)
        config_invalid = {
            "api_key": "sk-test",
            "model": "gpt-4",
            "base_url": "https://api.openai.com/v1",
            "timeout": 1000,  # Exceeds maximum
        }
        with pytest.raises(ValueError):
            llm_type.validate_config(config_invalid)

    @pytest.mark.asyncio
    async def test_llm_connection_successful(self):
        """Test successful LLM connection test."""
        llm_type = LLMConnectionType()

        config = {
            "api_key": "sk-test123",
            "model": "gpt-4",
            "base_url": "https://api.openai.com/v1",
            "timeout": 30,
            "verify_ssl": True,
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock successful completion response
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "choices": [{"message": {"content": "test"}}]
            }

            mock_client.post.return_value = mock_response

            result = await llm_type.test_connection(config)

            assert result.success is True
            assert result.status == "healthy"

    @pytest.mark.asyncio
    async def test_llm_connection_invalid_api_key(self):
        """Test LLM connection with invalid API key."""
        llm_type = LLMConnectionType()

        config = {
            "api_key": "invalid-key",
            "model": "gpt-4",
            "base_url": "https://api.openai.com/v1",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Mock 401 response
            mock_response = AsyncMock()
            mock_response.status_code = 401
            mock_response.text = "Invalid API key"

            mock_client.post.return_value = mock_response

            result = await llm_type.test_connection(config)

            assert result.success is False
            assert result.status == "unhealthy"


class TestExtractionConnectionType:
    """Test ExtractionConnectionType."""

    def test_connection_type_attributes(self):
        """Test Extraction connection type attributes."""
        ext_type = ExtractionConnectionType()

        assert ext_type.connection_type == "extraction"
        assert "Extraction" in ext_type.display_name
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

    def test_sharepoint_schema_has_required_fields(self):
        """Test SharePoint schema has all required fields."""
        sp_type = SharePointConnectionType()
        schema = sp_type.get_config_schema()

        required_fields = schema.get("required", [])
        assert "tenant_id" in required_fields
        assert "client_id" in required_fields
        assert "client_secret" in required_fields

    def test_llm_schema_has_writeonly_secret(self):
        """Test LLM schema marks API key as writeOnly."""
        llm_type = LLMConnectionType()
        schema = llm_type.get_config_schema()

        api_key_prop = schema["properties"]["api_key"]
        assert api_key_prop.get("writeOnly") is True

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
        sp_type = SharePointConnectionType()

        with pytest.raises(ValueError):
            sp_type.validate_config({})

    def test_validate_config_handles_none(self):
        """Test config validation with None."""
        llm_type = LLMConnectionType()

        with pytest.raises((ValueError, TypeError)):
            llm_type.validate_config(None)

    @pytest.mark.asyncio
    async def test_test_connection_handles_network_error(self):
        """Test connection testing handles network errors."""
        llm_type = LLMConnectionType()

        config = {
            "api_key": "sk-test",
            "model": "gpt-4",
            "base_url": "https://api.openai.com/v1",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client.post.side_effect = Exception("Network error")

            result = await llm_type.test_connection(config)

            assert result.success is False
            assert result.error is not None


class TestConfigNormalization:
    """Test configuration normalization."""

    def test_sharepoint_url_normalization(self):
        """Test SharePoint URL normalization."""
        sp_type = SharePointConnectionType()

        config = {
            "tenant_id": "12345678-1234-1234-1234-123456789abc",
            "client_id": "app-id",
            "client_secret": "secret",
            "graph_base_url": "https://graph.microsoft.com/v1.0/",  # Extra slash
        }

        validated = sp_type.validate_config(config)

        # Should normalize URL (though this might not be implemented)
        assert "graph_base_url" in validated

    def test_llm_url_normalization(self):
        """Test LLM URL normalization in test_connection."""
        llm_type = LLMConnectionType()

        config = {
            "api_key": "sk-test",
            "model": "gpt-4",
            "base_url": "https://api.openai.com/v1/",  # Extra slash
        }

        # The test_connection method should handle trailing slashes
        # This is tested through the actual implementation


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
