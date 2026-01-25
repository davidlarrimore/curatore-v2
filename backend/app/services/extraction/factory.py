"""
Extraction engine factory.

This module provides a factory for creating extraction engine instances
based on configuration from config.yml or database connections.
"""

from typing import Optional, Dict, Any
import logging

from .base import BaseExtractionEngine
from .extraction_service import ExtractionServiceEngine
from .docling import DoclingEngine
from .tika import TikaEngine

logger = logging.getLogger(__name__)


class ExtractionEngineFactory:
    """
    Factory for creating extraction engine instances.

    This factory instantiates the appropriate extraction engine class
    based on the engine_type configuration parameter.
    """

    # Registry of available engine types
    _engines = {
        "extraction-service": ExtractionServiceEngine,
        "docling": DoclingEngine,
        "tika": TikaEngine,
        # Future engines will be registered here:
        # "unstructured": UnstructuredEngine,
    }

    @classmethod
    def create_engine(
        cls,
        engine_type: str,
        name: str,
        service_url: str,
        timeout: int = 300,
        verify_ssl: bool = True,
        api_key: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> BaseExtractionEngine:
        """
        Create an extraction engine instance.

        Args:
            engine_type: Type of engine (e.g., 'extraction-service', 'docling', 'tika')
            name: Unique name/identifier for this engine instance
            service_url: Base URL of the extraction service
            timeout: Request timeout in seconds (default: 300)
            verify_ssl: Whether to verify SSL certificates (default: True)
            api_key: Optional API key for authentication
            options: Engine-specific options

        Returns:
            Instantiated extraction engine

        Raises:
            ValueError: If engine_type is not supported
        """
        # Get engine class from registry
        engine_class = cls._engines.get(engine_type)

        if not engine_class:
            available = ", ".join(cls._engines.keys())
            raise ValueError(
                f"Unsupported engine type: {engine_type}. "
                f"Available engines: {available}"
            )

        # Instantiate engine with provided configuration
        try:
            engine = engine_class(
                name=name,
                service_url=service_url,
                timeout=timeout,
                verify_ssl=verify_ssl,
                api_key=api_key,
                options=options
            )
            logger.info(
                "Created %s engine: %s (url: %s)",
                engine_type, name, service_url
            )
            return engine
        except Exception as e:
            logger.error(
                "Failed to create %s engine '%s': %s",
                engine_type, name, str(e)
            )
            raise

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> BaseExtractionEngine:
        """
        Create an extraction engine from a configuration dictionary.

        This is a convenience method for creating engines from config.yml
        or database connection configurations.

        Args:
            config: Configuration dictionary with keys:
                - engine_type (required): Type of engine
                - name (required): Engine name
                - service_url (required): Service URL
                - timeout (optional): Timeout in seconds
                - verify_ssl (optional): SSL verification flag
                - api_key (optional): API key
                - options (optional): Engine-specific options

        Returns:
            Instantiated extraction engine

        Raises:
            ValueError: If required config keys are missing

        Example:
            >>> config = {
            ...     "engine_type": "docling",
            ...     "name": "docling-prod",
            ...     "service_url": "http://docling:5001",
            ...     "timeout": 300,
            ...     "options": {
            ...         "output_format": "markdown",
            ...         "enable_ocr": True
            ...     }
            ... }
            >>> engine = ExtractionEngineFactory.from_config(config)
        """
        # Validate required fields
        required = ["engine_type", "name", "service_url"]
        missing = [k for k in required if k not in config]
        if missing:
            raise ValueError(f"Missing required config keys: {', '.join(missing)}")

        # Extract configuration with defaults
        return cls.create_engine(
            engine_type=config["engine_type"],
            name=config["name"],
            service_url=config["service_url"],
            timeout=config.get("timeout", 300),
            verify_ssl=config.get("verify_ssl", True),
            api_key=config.get("api_key"),
            options=config.get("options")
        )

    @classmethod
    def register_engine(cls, engine_type: str, engine_class: type):
        """
        Register a new engine type.

        This allows external modules to register custom extraction engines
        without modifying the factory code.

        Args:
            engine_type: Unique identifier for the engine type
            engine_class: Engine class (must inherit from BaseExtractionEngine)

        Raises:
            TypeError: If engine_class doesn't inherit from BaseExtractionEngine

        Example:
            >>> class MyCustomEngine(BaseExtractionEngine):
            ...     pass
            >>> ExtractionEngineFactory.register_engine("custom", MyCustomEngine)
        """
        from .base import BaseExtractionEngine

        if not issubclass(engine_class, BaseExtractionEngine):
            raise TypeError(
                f"Engine class must inherit from BaseExtractionEngine, "
                f"got {engine_class.__name__}"
            )

        if engine_type in cls._engines:
            logger.warning(
                "Overriding existing engine type: %s (was: %s, now: %s)",
                engine_type,
                cls._engines[engine_type].__name__,
                engine_class.__name__
            )

        cls._engines[engine_type] = engine_class
        logger.info("Registered engine type: %s -> %s", engine_type, engine_class.__name__)

    @classmethod
    def get_supported_engines(cls) -> list[str]:
        """
        Get list of supported engine types.

        Returns:
            List of engine type identifiers
        """
        return list(cls._engines.keys())

    @classmethod
    def is_supported(cls, engine_type: str) -> bool:
        """
        Check if an engine type is supported.

        Args:
            engine_type: Engine type to check

        Returns:
            True if engine type is supported
        """
        return engine_type in cls._engines
