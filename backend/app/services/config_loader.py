"""
Configuration loader service for YAML-based configuration.

This service loads and caches configuration from config.yml, providing type-safe
access to service configurations with environment variable resolution and validation.

Usage:
    from app.services.config_loader import config_loader

    # Get LLM configuration
    llm_config = config_loader.get_llm_config()

    # Get specific value by dot notation
    api_key = config_loader.get("llm.api_key")

    # Reload configuration
    config_loader.reload()
"""

import os
import logging
from typing import Any, Optional, Dict, List
from pathlib import Path

from app.models.config_models import (
    AppConfig,
    LLMConfig,
    ExtractionConfig,
    ExtractionEngineConfig,
    SharePointConfig,
    EmailConfig,
    QueueConfig,
    MinIOConfig,
)

logger = logging.getLogger(__name__)


class ConfigLoader:
    """
    Configuration loader and cache manager.

    Loads config.yml from project root, validates against Pydantic models,
    resolves environment variables, and provides typed access methods.
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration loader.

        Args:
            config_path: Path to config.yml (defaults to project root)
        """
        if config_path is None:
            # Default to config.yml in project root (parent of backend/)
            backend_dir = Path(__file__).resolve().parent.parent.parent
            candidate_paths = [
                backend_dir.parent / "config.yml",
                Path("/app/config.yml"),
                Path("/config.yml"),
                Path.cwd() / "config.yml",
            ]
            config_path = str(candidate_paths[0])
            for candidate in candidate_paths:
                if candidate.exists():
                    config_path = str(candidate)
                    break

        self.config_path = config_path
        self._config: Optional[AppConfig] = None
        self._loaded = False

    def load(self) -> AppConfig:
        """
        Load and parse configuration file.

        Returns:
            Validated AppConfig instance

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If YAML is invalid or validation fails
        """
        logger.info(f"Loading configuration from: {self.config_path}")

        try:
            self._config = AppConfig.from_yaml(self.config_path)
            self._loaded = True
            logger.info("Configuration loaded successfully")
            return self._config
        except FileNotFoundError:
            logger.warning(f"Configuration file not found: {self.config_path}")
            logger.warning("Falling back to environment variables")
            self._loaded = False
            raise
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            self._loaded = False
            raise ValueError(f"Configuration error: {e}") from e

    def reload(self) -> AppConfig:
        """
        Reload configuration from file.

        Useful for hot-reloading configuration without restarting the service.

        Returns:
            Refreshed AppConfig instance
        """
        logger.info("Reloading configuration")
        self._config = None
        self._loaded = False
        return self.load()

    def is_loaded(self) -> bool:
        """
        Check if configuration is loaded.

        Returns:
            True if configuration is loaded and valid
        """
        return self._loaded and self._config is not None

    def get_config(self) -> Optional[AppConfig]:
        """
        Get the full configuration object.

        Returns:
            AppConfig instance or None if not loaded
        """
        if not self.is_loaded():
            try:
                return self.load()
            except Exception:
                return None
        return self._config

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-notation path.

        Args:
            key_path: Dot-notation path (e.g., "llm.api_key")
            default: Default value if key not found

        Returns:
            Configuration value or default

        Examples:
            >>> config_loader.get("llm.api_key")
            'sk-...'
            >>> config_loader.get("llm.timeout", 60)
            60
        """
        config = self.get_config()
        if config is None:
            return default

        # Navigate dot notation path
        obj = config
        for key in key_path.split('.'):
            if hasattr(obj, key):
                obj = getattr(obj, key)
            elif isinstance(obj, dict) and key in obj:
                obj = obj[key]
            else:
                return default

        return obj

    def validate(self) -> List[str]:
        """
        Validate configuration and return list of errors.

        Returns:
            List of validation error messages (empty if valid)

        Examples:
            >>> errors = config_loader.validate()
            >>> if errors:
            ...     print("Configuration errors:", errors)
        """
        errors = []

        try:
            config = self.get_config()
            if config is None:
                errors.append("Configuration could not be loaded")
                return errors

            # Validate required services based on usage
            if config.llm is None:
                logger.warning("LLM configuration not found (optional)")

            if config.extraction is None:
                logger.warning("Extraction configuration not found (optional)")

            if config.sharepoint is None:
                logger.warning("SharePoint configuration not found (optional)")

            if config.email is None:
                logger.warning("Email configuration not found (optional)")

            if config.minio is None:
                logger.warning("MinIO configuration not found (optional)")

            # Queue is required
            if config.queue is None:
                errors.append("Queue configuration is required")

        except Exception as e:
            errors.append(f"Validation error: {str(e)}")

        return errors

    # -------------------------------------------------------------------------
    # Typed configuration getters
    # -------------------------------------------------------------------------

    def get_llm_config(self) -> Optional[LLMConfig]:
        """
        Get typed LLM configuration.

        Returns:
            LLMConfig instance or None if not configured

        Raises:
            ValueError: If configuration is invalid
        """
        config = self.get_config()
        if config is None:
            return None
        return config.llm

    def get_extraction_config(self) -> Optional[ExtractionConfig]:
        """
        Get typed extraction configuration.

        Returns:
            ExtractionConfig instance or None if not configured

        Raises:
            ValueError: If configuration is invalid
        """
        config = self.get_config()
        if config is None:
            return None
        return config.extraction

    def get_sharepoint_config(self) -> Optional[SharePointConfig]:
        """
        Get typed SharePoint configuration.

        Returns:
            SharePointConfig instance or None if not configured

        Raises:
            ValueError: If configuration is invalid
        """
        config = self.get_config()
        if config is None:
            return None
        return config.sharepoint

    def get_email_config(self) -> Optional[EmailConfig]:
        """
        Get typed email configuration.

        Returns:
            EmailConfig instance or None if not configured

        Raises:
            ValueError: If configuration is invalid
        """
        config = self.get_config()
        if config is None:
            return None
        return config.email

    def get_queue_config(self) -> Optional[QueueConfig]:
        """
        Get typed queue configuration.

        Returns:
            QueueConfig instance (always present with defaults)

        Raises:
            ValueError: If configuration is invalid
        """
        config = self.get_config()
        if config is None:
            return None
        return config.queue

    def get_minio_config(self) -> Optional[MinIOConfig]:
        """
        Get typed MinIO configuration.

        Returns:
            MinIOConfig instance or None if not configured

        Raises:
            ValueError: If configuration is invalid
        """
        config = self.get_config()
        if config is None:
            return None
        return config.minio

    def has_llm_config(self) -> bool:
        """Check if LLM configuration is available."""
        return self.get_llm_config() is not None

    def has_extraction_config(self) -> bool:
        """Check if extraction configuration is available."""
        return self.get_extraction_config() is not None

    def has_sharepoint_config(self) -> bool:
        """Check if SharePoint configuration is available."""
        return self.get_sharepoint_config() is not None

    def has_email_config(self) -> bool:
        """Check if email configuration is available."""
        return self.get_email_config() is not None

    def has_minio_config(self) -> bool:
        """Check if MinIO configuration is available."""
        return self.get_minio_config() is not None

    # -------------------------------------------------------------------------
    # Extraction engine convenience methods
    # -------------------------------------------------------------------------

    def get_enabled_extraction_engines(self) -> List:
        """
        Get list of enabled extraction engines from config.yml.

        Returns:
            List of ExtractionEngineConfig instances that are enabled
            Empty list if no extraction config or no enabled engines
        """
        extraction_config = self.get_extraction_config()
        if extraction_config is None:
            return []

        return [engine for engine in extraction_config.engines if engine.enabled]

    def get_default_extraction_engine(self):
        """
        Get the default extraction engine from config.yml.

        Uses the top-level 'default_engine' setting to determine which engine is the default.

        Returns:
            ExtractionEngineConfig instance for the default engine
            None if no extraction config or default engine not found
        """
        extraction_config = self.get_extraction_config()
        if extraction_config is None:
            return None

        # Try to find engine matching default_engine name (case-insensitive)
        if extraction_config.default_engine:
            for engine in extraction_config.engines:
                if engine.enabled and engine.name.lower() == extraction_config.default_engine.lower():
                    return engine

        # Fallback to first enabled engine
        enabled = self.get_enabled_extraction_engines()
        return enabled[0] if enabled else None

    def has_default_engine_in_config(self) -> bool:
        """
        Check if default_engine is explicitly set in config.yml.

        Returns:
            True if extraction.default_engine is set in config.yml
            False if not set or no extraction config exists
        """
        extraction_config = self.get_extraction_config()
        if extraction_config is None:
            return False

        # Check if default_engine is set (not None and not empty string)
        return bool(extraction_config.default_engine)

    def get_extraction_engine_by_name(self, name: str):
        """
        Get a specific extraction engine by name.

        Args:
            name: Engine name to look up

        Returns:
            ExtractionEngineConfig instance or None if not found or not enabled
        """
        extraction_config = self.get_extraction_config()
        if extraction_config is None:
            return None

        for engine in extraction_config.engines:
            if engine.name == name and engine.enabled:
                return engine

        return None


# Global configuration loader instance
config_loader = ConfigLoader()


def get_config_loader() -> ConfigLoader:
    """
    Get the global configuration loader instance.

    Returns:
        ConfigLoader singleton instance

    Usage:
        >>> from app.services.config_loader import get_config_loader
        >>> loader = get_config_loader()
        >>> llm_config = loader.get_llm_config()
    """
    return config_loader
