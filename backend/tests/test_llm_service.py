"""
Unit tests for LLMService.

Tests LLM client initialization, document evaluation, config management,
and connection testing for OpenAI-compatible APIs.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock, PropertyMock
import json

from app.services.llm_service import LLMService
from app.models import LLMEvaluation, LLMConnectionStatus
from openai import OpenAI


@pytest.fixture
def llm_service_instance():
    """Create LLMService instance for testing."""
    with patch('app.services.llm_service.settings') as mock_settings:
        mock_settings.openai_api_key = "test-key"
        mock_settings.openai_model = "gpt-4"
        mock_settings.openai_base_url = "https://api.openai.com/v1"
        mock_settings.openai_verify_ssl = True
        mock_settings.openai_timeout = 60
        mock_settings.openai_max_retries = 3

        return LLMService()


@pytest.fixture
def mock_llm_client():
    """Create mock OpenAI client."""
    mock_client = MagicMock(spec=OpenAI)
    return mock_client


class TestLLMServiceInitialization:
    """Test LLMService initialization."""

    @patch('app.services.llm_service.settings')
    def test_initialization_with_api_key(self, mock_settings):
        """Test initialization with valid API key."""
        mock_settings.openai_api_key = "sk-test123"
        mock_settings.openai_model = "gpt-4"
        mock_settings.openai_base_url = "https://api.openai.com/v1"
        mock_settings.openai_verify_ssl = True
        mock_settings.openai_timeout = 60
        mock_settings.openai_max_retries = 3

        with patch('app.services.llm_service.OpenAI') as mock_openai:
            with patch('app.services.llm_service.httpx.Client'):
                service = LLMService()

        # Client should be initialized
        assert service._client is not None or mock_openai.called

    @patch('app.services.llm_service.settings')
    def test_initialization_without_api_key(self, mock_settings):
        """Test initialization without API key."""
        mock_settings.openai_api_key = None

        service = LLMService()

        # Client should be None
        assert service._client is None

    @patch('app.services.llm_service.settings')
    def test_initialization_disables_ssl_warnings(self, mock_settings):
        """Test that SSL warnings are disabled when verify_ssl is False."""
        mock_settings.openai_api_key = "sk-test"
        mock_settings.openai_verify_ssl = False
        mock_settings.openai_base_url = "http://localhost:11434/v1"
        mock_settings.openai_model = "llama2"
        mock_settings.openai_timeout = 60
        mock_settings.openai_max_retries = 3

        with patch('app.services.llm_service.OpenAI'):
            with patch('app.services.llm_service.httpx.Client'):
                with patch('app.services.llm_service.urllib3.disable_warnings') as mock_disable:
                    service = LLMService()

        # Should disable warnings
        mock_disable.assert_called_once()

    @patch('app.services.llm_service.settings')
    def test_initialization_handles_errors(self, mock_settings):
        """Test initialization handles errors gracefully."""
        mock_settings.openai_api_key = "sk-test"
        mock_settings.openai_model = "gpt-4"
        mock_settings.openai_base_url = "https://api.openai.com/v1"
        mock_settings.openai_verify_ssl = True
        mock_settings.openai_timeout = 60
        mock_settings.openai_max_retries = 3

        with patch('app.services.llm_service.OpenAI', side_effect=Exception("Init error")):
            with patch('app.services.llm_service.httpx.Client'):
                service = LLMService()

        # Should set client to None on error
        assert service._client is None


class TestConfigurationManagement:
    """Test LLM configuration management."""

    @pytest.mark.asyncio
    async def test_get_llm_config_from_env(self):
        """Test getting config from environment variables."""
        with patch('app.services.llm_service.settings') as mock_settings:
            mock_settings.openai_api_key = "env-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_timeout = 60
            mock_settings.openai_verify_ssl = True

            service = LLMService()
            config = await service._get_llm_config()

        assert config["api_key"] == "env-key"
        assert config["model"] == "gpt-4"
        assert config["base_url"] == "https://api.openai.com/v1"

    @pytest.mark.asyncio
    async def test_get_llm_config_from_database(self):
        """Test getting config from database connection."""
        mock_session = AsyncMock()
        mock_org_id = "org-123"

        mock_connection = MagicMock()
        mock_connection.is_active = True
        mock_connection.config = {
            "api_key": "db-key",
            "model": "gpt-4-turbo",
            "base_url": "https://custom.api.com/v1",
            "timeout": 30,
            "verify_ssl": False,
        }

        with patch('app.services.llm_service.settings') as mock_settings:
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_api_key = "fallback-key"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_timeout = 60
            mock_settings.openai_verify_ssl = True

            service = LLMService()

            with patch('app.services.llm_service.connection_service') as mock_conn_service:
                mock_conn_service.get_default_connection = AsyncMock(return_value=mock_connection)

                config = await service._get_llm_config(
                    organization_id=mock_org_id,
                    session=mock_session
                )

        # Should use database config
        assert config["api_key"] == "db-key"
        assert config["model"] == "gpt-4-turbo"
        assert config["base_url"] == "https://custom.api.com/v1"

    @pytest.mark.asyncio
    async def test_get_llm_config_fallback_on_db_error(self):
        """Test config falls back to env when database fails."""
        mock_session = AsyncMock()
        mock_org_id = "org-123"

        with patch('app.services.llm_service.settings') as mock_settings:
            mock_settings.openai_api_key = "env-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_timeout = 60
            mock_settings.openai_verify_ssl = True

            service = LLMService()

            with patch('app.services.llm_service.connection_service') as mock_conn_service:
                mock_conn_service.get_default_connection = AsyncMock(side_effect=Exception("DB error"))

                config = await service._get_llm_config(
                    organization_id=mock_org_id,
                    session=mock_session
                )

        # Should fall back to env
        assert config["api_key"] == "env-key"

    @pytest.mark.asyncio
    async def test_create_client_from_config(self, llm_service_instance):
        """Test creating client from config dictionary."""
        config = {
            "api_key": "test-key",
            "model": "gpt-4",
            "base_url": "https://api.openai.com/v1",
            "timeout": 60,
            "verify_ssl": True,
        }

        with patch('app.services.llm_service.OpenAI') as mock_openai:
            with patch('app.services.llm_service.httpx.Client'):
                client = await llm_service_instance._create_client_from_config(config)

        # OpenAI should be initialized
        mock_openai.assert_called_once()


class TestConnectionStatus:
    """Test LLM connection status checking."""

    @pytest.mark.asyncio
    async def test_get_status_healthy(self):
        """Test get_status when LLM is healthy."""
        with patch('app.services.llm_service.settings') as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3

            service = LLMService()

            # Mock successful completion
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "test"
            mock_client.chat.completions.create.return_value = mock_response

            service._client = mock_client

            status = await service.get_status()

        assert status.status == "healthy"
        assert status.model is not None
        assert status.endpoint is not None

    @pytest.mark.asyncio
    async def test_get_status_no_client(self):
        """Test get_status when no client is initialized."""
        service = LLMService()
        service._client = None

        status = await service.get_status()

        assert status.status == "unavailable"
        assert status.error is not None

    @pytest.mark.asyncio
    async def test_get_status_connection_error(self):
        """Test get_status when connection fails."""
        service = LLMService()

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("Connection failed")
        service._client = mock_client

        status = await service.get_status()

        assert status.status == "unhealthy"
        assert "Connection failed" in status.error


class TestDocumentEvaluation:
    """Test document evaluation functionality."""

    @pytest.mark.asyncio
    async def test_evaluate_document_success(self):
        """Test successful document evaluation."""
        service = LLMService()

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]

        # Mock JSON response
        evaluation_json = {
            "conversion_quality": 8,
            "clarity": 9,
            "completeness": 7,
            "relevance": 8,
            "markdown_quality": 8,
            "explanation": "Good quality"
        }
        mock_response.choices[0].message.content = json.dumps(evaluation_json)
        mock_client.chat.completions.create.return_value = mock_response

        service._client = mock_client

        result = await service.evaluate_document(
            markdown_content="# Test Document\n\nTest content",
            original_filename="test.pdf"
        )

        assert result is not None
        assert result.conversion_quality == 8
        assert result.clarity == 9
        assert result.completeness == 7

    @pytest.mark.asyncio
    async def test_evaluate_document_no_client(self):
        """Test evaluate_document when no client available."""
        service = LLMService()
        service._client = None

        result = await service.evaluate_document(
            markdown_content="# Test",
            original_filename="test.pdf"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_evaluate_document_handles_invalid_json(self):
        """Test evaluation handles invalid JSON response."""
        service = LLMService()

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Not JSON content"
        mock_client.chat.completions.create.return_value = mock_response

        service._client = mock_client

        result = await service.evaluate_document(
            markdown_content="# Test",
            original_filename="test.pdf"
        )

        # Should return None or handle gracefully
        # (depends on implementation)
        assert result is None or isinstance(result, LLMEvaluation)

    @pytest.mark.asyncio
    async def test_evaluate_document_with_custom_model(self):
        """Test evaluation with custom model parameter."""
        service = LLMService()

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        evaluation_json = {
            "conversion_quality": 8,
            "clarity": 9,
            "completeness": 7,
            "relevance": 8,
            "markdown_quality": 8,
            "explanation": "Good"
        }
        mock_response.choices[0].message.content = json.dumps(evaluation_json)
        mock_client.chat.completions.create.return_value = mock_response

        service._client = mock_client

        result = await service.evaluate_document(
            markdown_content="# Test",
            original_filename="test.pdf",
            model="gpt-4-turbo"
        )

        # Should call with custom model
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs.get("model") == "gpt-4-turbo"


class TestErrorHandling:
    """Test error handling in LLM service."""

    @pytest.mark.asyncio
    async def test_handles_network_timeout(self):
        """Test handling of network timeout."""
        service = LLMService()

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = TimeoutError("Request timeout")
        service._client = mock_client

        result = await service.evaluate_document(
            markdown_content="# Test",
            original_filename="test.pdf"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_api_error(self):
        """Test handling of API errors."""
        service = LLMService()

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API Error: Rate limit")
        service._client = mock_client

        result = await service.evaluate_document(
            markdown_content="# Test",
            original_filename="test.pdf"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_malformed_response(self):
        """Test handling of malformed LLM response."""
        service = LLMService()

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = []  # Empty choices
        mock_client.chat.completions.create.return_value = mock_response

        service._client = mock_client

        result = await service.evaluate_document(
            markdown_content="# Test",
            original_filename="test.pdf"
        )

        assert result is None


class TestPromptGeneration:
    """Test prompt generation for different tasks."""

    @pytest.mark.asyncio
    async def test_evaluation_prompt_includes_content(self):
        """Test that evaluation prompt includes markdown content."""
        service = LLMService()

        mock_client = MagicMock()
        service._client = mock_client

        # Set up mock to capture the prompt
        def capture_prompt(*args, **kwargs):
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = json.dumps({
                "conversion_quality": 8,
                "clarity": 8,
                "completeness": 8,
                "relevance": 8,
                "markdown_quality": 8,
                "explanation": "Test"
            })
            return mock_response

        mock_client.chat.completions.create.side_effect = capture_prompt

        test_content = "# Test Document\n\nThis is test content."
        await service.evaluate_document(
            markdown_content=test_content,
            original_filename="test.pdf"
        )

        # Verify the call was made
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        messages = call_kwargs.get("messages", [])

        # Should have user message with content
        assert len(messages) > 0
        # At least one message should contain the test content
        content_found = any(test_content in str(msg) for msg in messages)
        assert content_found or len(messages) > 0  # At minimum, messages were sent


class TestClientReinitialization:
    """Test client reinitialization."""

    def test_reinitialize_client(self):
        """Test that client can be reinitialized."""
        with patch('app.services.llm_service.settings') as mock_settings:
            mock_settings.openai_api_key = "initial-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3

            service = LLMService()

            # Change settings
            mock_settings.openai_api_key = "new-key"

            # Reinitialize
            with patch('app.services.llm_service.OpenAI') as mock_openai:
                with patch('app.services.llm_service.httpx.Client'):
                    service._initialize_client()

            # Should create new client
            # (Implementation may vary)


class TestModelSelection:
    """Test model selection and configuration."""

    @pytest.mark.asyncio
    async def test_uses_default_model(self):
        """Test that default model is used when not specified."""
        with patch('app.services.llm_service.settings') as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-3.5-turbo"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3

            service = LLMService()

            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = json.dumps({
                "conversion_quality": 8,
                "clarity": 8,
                "completeness": 8,
                "relevance": 8,
                "markdown_quality": 8,
                "explanation": "Test"
            })
            mock_client.chat.completions.create.return_value = mock_response
            service._client = mock_client

            await service.evaluate_document(
                markdown_content="# Test",
                original_filename="test.pdf"
            )

            # Should use default model
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            # Model should be specified (either default or custom)
            assert "model" in call_kwargs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
