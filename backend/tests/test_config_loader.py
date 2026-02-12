"""
Tests for configuration loader service.

Tests YAML configuration loading, validation, and environment variable resolution.
"""


import pytest
from app.core.models.config_models import AppConfig, LLMConfig
from app.core.shared.config_loader import ConfigLoader


class TestConfigLoader:
    """Test suite for ConfigLoader."""

    def test_load_valid_config(self, tmp_path):
        """Test loading valid configuration."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("""
version: "2.0"
llm:
  provider: openai
  api_key: test-key
  base_url: https://api.openai.com/v1
  default_model: gpt-4o-mini
queue:
  broker_url: redis://redis:6379/0
  result_backend: redis://redis:6379/1
""")

        loader = ConfigLoader(str(config_file))
        config = loader.load()

        assert config is not None
        assert config.version == "2.0"
        assert config.llm.provider == "openai"
        assert config.llm.api_key == "test-key"
        assert config.llm.default_model == "gpt-4o-mini"

    def test_load_missing_file(self, tmp_path):
        """Test loading non-existent file raises error."""
        loader = ConfigLoader(str(tmp_path / "nonexistent.yml"))

        with pytest.raises(FileNotFoundError):
            loader.load()

    def test_env_var_resolution(self, tmp_path, monkeypatch):
        """Test environment variable resolution."""
        monkeypatch.setenv("TEST_API_KEY", "secret-key-123")

        config_file = tmp_path / "config.yml"
        config_file.write_text("""
version: "2.0"
llm:
  provider: openai
  api_key: ${TEST_API_KEY}
  base_url: https://api.openai.com/v1
  default_model: gpt-4o-mini
queue:
  broker_url: redis://redis:6379/0
  result_backend: redis://redis:6379/1
""")

        loader = ConfigLoader(str(config_file))
        config = loader.load()

        assert config.llm.api_key == "secret-key-123"

    def test_env_var_missing(self, tmp_path):
        """Test missing environment variable resolves to None."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("""
version: "2.0"
llm:
  provider: openai
  api_key: ${MISSING_VAR}
  base_url: https://api.openai.com/v1
  default_model: gpt-4o-mini
queue:
  broker_url: redis://redis:6379/0
  result_backend: redis://redis:6379/1
""")

        loader = ConfigLoader(str(config_file))
        config = loader.load()

        # Missing env vars resolve to None instead of raising
        assert config.llm.api_key is None

    def test_invalid_yaml(self, tmp_path):
        """Test invalid YAML syntax raises error."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("""
version: "2.0"
llm:
  provider: openai
    api_key: test-key  # Invalid indentation
""")

        loader = ConfigLoader(str(config_file))

        with pytest.raises(ValueError):
            loader.load()

    def test_schema_validation_failure(self, tmp_path):
        """Test schema validation catches invalid values."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("""
version: "2.0"
llm:
  provider: invalid_provider  # Not in allowed values
  api_key: test-key
  base_url: https://api.openai.com/v1
  default_model: gpt-4o-mini
""")

        loader = ConfigLoader(str(config_file))

        with pytest.raises(ValueError):
            loader.load()

    def test_get_llm_config(self, tmp_path):
        """Test getting LLM configuration."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("""
version: "2.0"
llm:
  provider: openai
  api_key: test-key
  base_url: https://api.openai.com/v1
  default_model: gpt-4o-mini
queue:
  broker_url: redis://redis:6379/0
  result_backend: redis://redis:6379/1
""")

        loader = ConfigLoader(str(config_file))
        llm_config = loader.get_llm_config()

        assert llm_config is not None
        assert llm_config.provider == "openai"
        assert llm_config.api_key == "test-key"
        assert llm_config.timeout == 60  # Default value

    def test_get_llm_config_none_when_not_configured(self, tmp_path):
        """Test getting LLM config returns None when not configured."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("""
version: "2.0"
queue:
  broker_url: redis://redis:6379/0
  result_backend: redis://redis:6379/1
""")

        loader = ConfigLoader(str(config_file))
        llm_config = loader.get_llm_config()

        assert llm_config is None

    def test_get_value_by_path(self, tmp_path):
        """Test getting value by dot-notation path."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("""
version: "2.0"
llm:
  provider: openai
  api_key: test-key
  base_url: https://api.openai.com/v1
  default_model: gpt-4o-mini
  timeout: 120
queue:
  broker_url: redis://redis:6379/0
  result_backend: redis://redis:6379/1
""")

        loader = ConfigLoader(str(config_file))
        loader.load()

        assert loader.get("llm.api_key") == "test-key"
        assert loader.get("llm.timeout") == 120
        assert loader.get("queue.broker_url") == "redis://redis:6379/0"
        assert loader.get("nonexistent.path", "default") == "default"

    def test_reload_config(self, tmp_path):
        """Test reloading configuration."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("""
version: "2.0"
llm:
  provider: openai
  api_key: old-key
  base_url: https://api.openai.com/v1
  default_model: gpt-4o-mini
queue:
  broker_url: redis://redis:6379/0
  result_backend: redis://redis:6379/1
""")

        loader = ConfigLoader(str(config_file))
        config = loader.load()
        assert config.llm.api_key == "old-key"

        # Update file
        config_file.write_text("""
version: "2.0"
llm:
  provider: openai
  api_key: new-key
  base_url: https://api.openai.com/v1
  default_model: gpt-4o-mini
queue:
  broker_url: redis://redis:6379/0
  result_backend: redis://redis:6379/1
""")

        # Reload
        config = loader.reload()
        assert config.llm.api_key == "new-key"

    def test_validate_config(self, tmp_path):
        """Test configuration validation."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("""
version: "2.0"
llm:
  provider: openai
  api_key: test-key
  base_url: https://api.openai.com/v1
  default_model: gpt-4o-mini
queue:
  broker_url: redis://redis:6379/0
  result_backend: redis://redis:6379/1
""")

        loader = ConfigLoader(str(config_file))
        loader.load()
        errors = loader.validate()

        assert isinstance(errors, list)
        assert len(errors) == 0  # No errors for valid config

    def test_optional_service_configs(self, tmp_path):
        """Test that optional service configs can be omitted."""
        config_file = tmp_path / "config.yml"
        config_file.write_text("""
version: "2.0"
queue:
  broker_url: redis://redis:6379/0
  result_backend: redis://redis:6379/1
""")

        loader = ConfigLoader(str(config_file))
        config = loader.load()

        assert config.llm is None
        assert config.extraction is None
        assert config.email is None
        assert config.queue is not None


class TestConfigModels:
    """Test suite for configuration models."""

    def test_llm_config_defaults(self):
        """Test LLM config default values."""
        config = LLMConfig(
            provider="openai",
            api_key="test",
            base_url="https://api.openai.com/v1",
            default_model="gpt-4o-mini"
        )

        assert config.timeout == 60
        assert config.max_retries == 3
        assert config.verify_ssl is True

    def test_llm_config_validation(self):
        """Test LLM config validation."""
        # Valid config
        config = LLMConfig(
            provider="openai",
            api_key="test",
            base_url="https://api.openai.com/v1",
            default_model="gpt-4o-mini",
            timeout=120
        )
        assert config.timeout == 120

        # Invalid timeout (too large)
        with pytest.raises(ValueError):
            LLMConfig(
                provider="openai",
                api_key="test",
                base_url="https://api.openai.com/v1",
                default_model="gpt-4o-mini",
                timeout=700  # > 600 max
            )

    def test_app_config_from_yaml(self, tmp_path, monkeypatch):
        """Test AppConfig.from_yaml() class method."""
        monkeypatch.setenv("TEST_KEY", "secret-123")

        config_file = tmp_path / "config.yml"
        config_file.write_text("""
version: "2.0"
llm:
  provider: openai
  api_key: ${TEST_KEY}
  base_url: https://api.openai.com/v1
  default_model: gpt-4o-mini
queue:
  broker_url: redis://redis:6379/0
  result_backend: redis://redis:6379/1
""")

        config = AppConfig.from_yaml(str(config_file))

        assert config.version == "2.0"
        assert config.llm.api_key == "secret-123"
