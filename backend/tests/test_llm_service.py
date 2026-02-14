"""
Unit tests for LLMService and LLMAdapter.

Tests LLM client initialization, document evaluation, config management,
and connection testing for OpenAI-compatible APIs.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.connectors.adapters.llm_adapter import LLMAdapter
from app.core.llm.llm_service import LLMService
from app.core.models import LLMEvaluation
from openai import OpenAI

# ============================================================================
# Patch targets — initialization logic lives in llm_adapter
# ============================================================================
_ADAPTER_MOD = "app.connectors.adapters.llm_adapter"
_SERVICE_MOD = "app.core.llm.llm_service"


@pytest.fixture
def llm_service_instance():
    """Create LLMService instance for testing."""
    with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
         patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader:
        mock_settings.openai_api_key = "test-key"
        mock_settings.openai_model = "gpt-4"
        mock_settings.openai_base_url = "https://api.openai.com/v1"
        mock_settings.openai_verify_ssl = True
        mock_settings.openai_timeout = 60
        mock_settings.openai_max_retries = 3
        mock_config_loader.get_llm_config.return_value = None

        adapter = LLMAdapter()
        return LLMService(adapter=adapter)


@pytest.fixture
def mock_llm_client():
    """Create mock OpenAI client."""
    mock_client = MagicMock(spec=OpenAI)
    return mock_client


class TestLLMServiceInitialization:
    """Test LLMService initialization."""

    def test_initialization_with_api_key(self):
        """Test initialization with valid API key."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader:
            mock_settings.openai_api_key = "sk-test123"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3
            mock_config_loader.get_llm_config.return_value = None

            with patch(f"{_ADAPTER_MOD}.OpenAI") as mock_openai:
                with patch(f"{_ADAPTER_MOD}.httpx.Client"):
                    adapter = LLMAdapter()
                    service = LLMService(adapter=adapter)

            # Client should be initialized
            assert service._client is not None or mock_openai.called

    def test_initialization_without_api_key(self):
        """Test initialization without API key."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader:
            mock_settings.openai_api_key = None
            mock_config_loader.get_llm_config.return_value = None

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)

            # Client should be None
            assert service._client is None

    def test_initialization_disables_ssl_warnings(self):
        """Test that SSL warnings are disabled when verify_ssl is False."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader:
            mock_settings.openai_api_key = "sk-test"
            mock_settings.openai_verify_ssl = False
            mock_settings.openai_base_url = "http://localhost:11434/v1"
            mock_settings.openai_model = "llama2"
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3
            mock_config_loader.get_llm_config.return_value = None

            with patch(f"{_ADAPTER_MOD}.OpenAI"):
                with patch(f"{_ADAPTER_MOD}.httpx.Client"):
                    with patch(f"{_ADAPTER_MOD}.urllib3.disable_warnings") as mock_disable:
                        adapter = LLMAdapter()
                        service = LLMService(adapter=adapter)

            # Should disable warnings
            mock_disable.assert_called_once()

    def test_initialization_handles_errors(self):
        """Test initialization handles errors gracefully."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader:
            mock_settings.openai_api_key = "sk-test"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3
            mock_config_loader.get_llm_config.return_value = None

            with patch(f"{_ADAPTER_MOD}.OpenAI", side_effect=Exception("Init error")):
                with patch(f"{_ADAPTER_MOD}.httpx.Client"):
                    adapter = LLMAdapter()
                    service = LLMService(adapter=adapter)

            # Should set client to None on error
            assert service._client is None


class TestConfigurationManagement:
    """Test LLM configuration management."""

    @pytest.mark.asyncio
    async def test_get_llm_config_from_env(self):
        """Test getting config from environment variables."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader:
            mock_settings.openai_api_key = "env-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_timeout = 60
            mock_settings.openai_verify_ssl = True
            mock_config_loader.get_llm_config.return_value = None

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)
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

        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader:
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_api_key = "fallback-key"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_timeout = 60
            mock_settings.openai_verify_ssl = True
            mock_config_loader.get_llm_config.return_value = None

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)

            with patch('app.core.auth.connection_service.connection_service') as mock_conn_service:
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

        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader:
            mock_settings.openai_api_key = "env-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_timeout = 60
            mock_settings.openai_verify_ssl = True
            mock_config_loader.get_llm_config.return_value = None

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)

            with patch('app.core.auth.connection_service.connection_service') as mock_conn_service:
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

        with patch(f"{_ADAPTER_MOD}.OpenAI") as mock_openai:
            with patch(f"{_ADAPTER_MOD}.httpx.Client"):
                client = await llm_service_instance._create_client_from_config(config)

        # OpenAI should be initialized
        mock_openai.assert_called_once()


class TestConnectionStatus:
    """Test LLM connection status checking."""

    @pytest.mark.asyncio
    async def test_get_status_healthy(self):
        """Test test_connection when LLM is healthy."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3
            mock_config_loader.get_llm_config.return_value = None

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)

            # Mock successful completion
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "OK"
            mock_client.chat.completions.create.return_value = mock_response

            service._client = mock_client

            status = await service.test_connection()

        assert status.connected is True
        assert status.model is not None
        assert status.endpoint is not None

    @pytest.mark.asyncio
    async def test_get_status_no_client(self):
        """Test test_connection when no client is initialized."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader:
            mock_settings.openai_api_key = None
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_config_loader.get_llm_config.return_value = None

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)
            service._client = None

            status = await service.test_connection()

        assert status.connected is False
        assert status.error is not None

    @pytest.mark.asyncio
    async def test_get_status_connection_error(self):
        """Test test_connection when connection fails."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3
            mock_config_loader.get_llm_config.return_value = None

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)

            mock_client = MagicMock()
            mock_client.models.list.side_effect = Exception("Connection failed")
            adapter._client = mock_client

            status = await service.test_connection()

        assert status.connected is False
        assert "Connection failed" in status.error


class TestDocumentEvaluation:
    """Test document evaluation functionality."""

    @pytest.mark.asyncio
    async def test_evaluate_document_success(self):
        """Test successful document evaluation."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader, \
             patch(f"{_SERVICE_MOD}.llm_routing_service") as mock_routing:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3
            mock_config_loader.get_llm_config.return_value = None

            mock_task_config = MagicMock()
            mock_task_config.model = "gpt-4"
            mock_task_config.temperature = 0
            mock_routing.get_config_for_task = AsyncMock(return_value=mock_task_config)

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)

            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]

            # Mock JSON response matching the actual evaluate_document schema
            evaluation_json = {
                "clarity_score": 9,
                "clarity_feedback": "Well-structured",
                "completeness_score": 7,
                "completeness_feedback": "Mostly complete",
                "relevance_score": 8,
                "relevance_feedback": "Relevant",
                "markdown_score": 8,
                "markdown_feedback": "Good formatting",
                "overall_feedback": "Good quality",
                "pass_recommendation": "Pass"
            }
            mock_response.choices[0].message.content = json.dumps(evaluation_json)
            mock_client.chat.completions.create.return_value = mock_response

            service._client = mock_client

            result = await service.evaluate_document(
                markdown_text="# Test Document\n\nTest content"
            )

        assert result is not None
        assert result.clarity_score == 9
        assert result.completeness_score == 7

    @pytest.mark.asyncio
    async def test_evaluate_document_no_client(self):
        """Test evaluate_document when no client available."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader, \
             patch(f"{_SERVICE_MOD}.llm_routing_service") as mock_routing:
            mock_settings.openai_api_key = None
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_config_loader.get_llm_config.return_value = None

            mock_task_config = MagicMock()
            mock_task_config.model = "gpt-4"
            mock_routing.get_config_for_task = AsyncMock(return_value=mock_task_config)

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)
            service._client = None

            result = await service.evaluate_document(
                markdown_text="# Test"
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_evaluate_document_handles_invalid_json(self):
        """Test evaluation handles invalid JSON response."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader, \
             patch(f"{_SERVICE_MOD}.llm_routing_service") as mock_routing:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3
            mock_config_loader.get_llm_config.return_value = None

            mock_task_config = MagicMock()
            mock_task_config.model = "gpt-4"
            mock_routing.get_config_for_task = AsyncMock(return_value=mock_task_config)

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)

            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "Not JSON content"
            mock_client.chat.completions.create.return_value = mock_response

            service._client = mock_client

            result = await service.evaluate_document(
                markdown_text="# Test"
            )

        # Should return None or handle gracefully
        assert result is None or isinstance(result, LLMEvaluation)

    @pytest.mark.asyncio
    async def test_evaluate_document_with_custom_model(self):
        """Test evaluation uses task-specific model from routing."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader, \
             patch(f"{_SERVICE_MOD}.llm_routing_service") as mock_routing:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3
            mock_config_loader.get_llm_config.return_value = None

            mock_task_config = MagicMock()
            mock_task_config.model = "gpt-4-turbo"
            mock_task_config.temperature = 0
            mock_routing.get_config_for_task = AsyncMock(return_value=mock_task_config)

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)

            mock_client = MagicMock()
            evaluation_json = {
                "clarity_score": 8,
                "clarity_feedback": "Good",
                "completeness_score": 7,
                "completeness_feedback": "Good",
                "relevance_score": 8,
                "relevance_feedback": "Good",
                "markdown_score": 8,
                "markdown_feedback": "Good",
                "overall_feedback": "Good",
                "pass_recommendation": "Pass"
            }
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = json.dumps(evaluation_json)
            mock_client.chat.completions.create.return_value = mock_response

            service._client = mock_client

            result = await service.evaluate_document(
                markdown_text="# Test"
            )

        # Should call with model from routing config
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs.get("model") == "gpt-4-turbo"


class TestErrorHandling:
    """Test error handling in LLM service."""

    @pytest.mark.asyncio
    async def test_handles_network_timeout(self):
        """Test handling of network timeout."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader, \
             patch(f"{_SERVICE_MOD}.llm_routing_service") as mock_routing:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3
            mock_config_loader.get_llm_config.return_value = None

            mock_task_config = MagicMock()
            mock_task_config.model = "gpt-4"
            mock_routing.get_config_for_task = AsyncMock(return_value=mock_task_config)

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)

            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = TimeoutError("Request timeout")
            service._client = mock_client

            result = await service.evaluate_document(
                markdown_text="# Test"
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_api_error(self):
        """Test handling of API errors."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader, \
             patch(f"{_SERVICE_MOD}.llm_routing_service") as mock_routing:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3
            mock_config_loader.get_llm_config.return_value = None

            mock_task_config = MagicMock()
            mock_task_config.model = "gpt-4"
            mock_routing.get_config_for_task = AsyncMock(return_value=mock_task_config)

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)

            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = Exception("API Error: Rate limit")
            service._client = mock_client

            result = await service.evaluate_document(
                markdown_text="# Test"
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_malformed_response(self):
        """Test handling of malformed LLM response."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader, \
             patch(f"{_SERVICE_MOD}.llm_routing_service") as mock_routing:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3
            mock_config_loader.get_llm_config.return_value = None

            mock_task_config = MagicMock()
            mock_task_config.model = "gpt-4"
            mock_routing.get_config_for_task = AsyncMock(return_value=mock_task_config)

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)

            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = []  # Empty choices
            mock_client.chat.completions.create.return_value = mock_response

            service._client = mock_client

            result = await service.evaluate_document(
                markdown_text="# Test"
            )

        assert result is None


class TestPromptGeneration:
    """Test prompt generation for different tasks."""

    @pytest.mark.asyncio
    async def test_evaluation_prompt_includes_content(self):
        """Test that evaluation prompt includes markdown content."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader, \
             patch(f"{_SERVICE_MOD}.llm_routing_service") as mock_routing:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3
            mock_config_loader.get_llm_config.return_value = None

            mock_task_config = MagicMock()
            mock_task_config.model = "gpt-4"
            mock_task_config.temperature = 0
            mock_routing.get_config_for_task = AsyncMock(return_value=mock_task_config)

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)

            mock_client = MagicMock()

            # Set up mock to capture the prompt
            def capture_prompt(*args, **kwargs):
                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = json.dumps({
                    "clarity_score": 8,
                    "clarity_feedback": "Good",
                    "completeness_score": 8,
                    "completeness_feedback": "Good",
                    "relevance_score": 8,
                    "relevance_feedback": "Good",
                    "markdown_score": 8,
                    "markdown_feedback": "Good",
                    "overall_feedback": "Test",
                    "pass_recommendation": "Pass"
                })
                return mock_response

            mock_client.chat.completions.create.side_effect = capture_prompt
            service._client = mock_client

            test_content = "# Test Document\n\nThis is test content."
            await service.evaluate_document(
                markdown_text=test_content
            )

            # Verify the call was made (inside context so mock is still valid)
            mock_client.chat.completions.create.assert_called_once()
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            messages = call_kwargs.get("messages", [])

            # Should have user message with content
            assert len(messages) > 0
            # At least one message should contain the test content
            content_found = any(
                test_content in msg.get("content", "")
                for msg in messages
                if isinstance(msg, dict)
            )
            assert content_found


class TestClientReinitialization:
    """Test client reinitialization."""

    def test_reinitialize_client(self):
        """Test that client can be reinitialized."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader:
            mock_settings.openai_api_key = "initial-key"
            mock_settings.openai_model = "gpt-4"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3
            mock_config_loader.get_llm_config.return_value = None

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)

            # Change settings
            mock_settings.openai_api_key = "new-key"

            # Reinitialize
            with patch(f"{_ADAPTER_MOD}.OpenAI") as mock_openai:
                with patch(f"{_ADAPTER_MOD}.httpx.Client"):
                    service._initialize_client()

            # Should create new client
            mock_openai.assert_called()


class TestModelSelection:
    """Test model selection and configuration."""

    @pytest.mark.asyncio
    async def test_uses_default_model(self):
        """Test that default model is used when not specified."""
        with patch(f"{_ADAPTER_MOD}.settings") as mock_settings, \
             patch(f"{_ADAPTER_MOD}.config_loader") as mock_config_loader, \
             patch(f"{_SERVICE_MOD}.llm_routing_service") as mock_routing:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-3.5-turbo"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_verify_ssl = True
            mock_settings.openai_timeout = 60
            mock_settings.openai_max_retries = 3
            mock_config_loader.get_llm_config.return_value = None

            mock_task_config = MagicMock()
            mock_task_config.model = "gpt-3.5-turbo"
            mock_task_config.temperature = 0
            mock_routing.get_config_for_task = AsyncMock(return_value=mock_task_config)

            adapter = LLMAdapter()
            service = LLMService(adapter=adapter)

            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = json.dumps({
                "clarity_score": 8,
                "clarity_feedback": "Good",
                "completeness_score": 8,
                "completeness_feedback": "Good",
                "relevance_score": 8,
                "relevance_feedback": "Good",
                "markdown_score": 8,
                "markdown_feedback": "Good",
                "overall_feedback": "Test",
                "pass_recommendation": "Pass"
            })
            mock_client.chat.completions.create.return_value = mock_response
            service._client = mock_client

            await service.evaluate_document(
                markdown_text="# Test"
            )

            # Should use default model
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            # Model should be specified
            assert "model" in call_kwargs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
