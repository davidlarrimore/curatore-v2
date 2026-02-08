"""
LLM Adapter — ServiceAdapter implementation for OpenAI-compatible LLM services.

Manages LLM client initialization and configuration resolution using the
3-tier pattern (DB Connection > config.yml > ENV). The actual LLM operations
(evaluate, improve, summarize) remain in core/llm/llm_service.py.

Configuration Priority:
    1. Connection from database (per-organization)
    2. config.yml llm section
    3. Environment variables (OPENAI_API_KEY, etc.)

Usage:
    from app.connectors.adapters.llm_adapter import llm_adapter

    # Check availability
    if llm_adapter.is_available:
        client = llm_adapter.client
        # ... use the OpenAI client
"""

import asyncio
import logging
from typing import Any, Dict, Optional
from uuid import UUID

import httpx
import urllib3
from openai import OpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.adapters.base import ServiceAdapter
from app.core.models import LLMConnectionStatus
from app.core.models.llm_models import LLMTaskType
from app.core.shared.config_loader import config_loader

logger = logging.getLogger(__name__)


class LLMAdapter(ServiceAdapter):
    """
    Service adapter for OpenAI-compatible LLM connections.

    Owns client initialization, configuration resolution, and connection testing.
    The LLMService in core/llm/ delegates connection management to this adapter.
    """

    CONNECTION_TYPE = "llm"

    def __init__(self):
        self._client: Optional[OpenAI] = None
        self._initialize_client()

    # ========================================================================
    # Client management
    # ========================================================================

    @property
    def client(self) -> Optional[OpenAI]:
        """The initialized OpenAI client."""
        return self._client

    def _initialize_client(self) -> None:
        """
        Initialize OpenAI client with configuration from config.yml or settings.

        Configuration Sources (priority order):
            1. config.yml (if present) via config_loader.get_llm_config()
            2. Environment variables via settings (backward compatibility)
        """
        llm_config = config_loader.get_llm_config()

        if llm_config:
            logger.info("Loading LLM configuration from config.yml")
            api_key = llm_config.api_key
            base_url = llm_config.base_url
            timeout = llm_config.timeout
            max_retries = llm_config.max_retries
            verify_ssl = llm_config.verify_ssl
        else:
            logger.info("Loading LLM configuration from environment variables")
            api_key = settings.openai_api_key
            base_url = settings.openai_base_url
            timeout = settings.openai_timeout
            max_retries = settings.openai_max_retries
            verify_ssl = settings.openai_verify_ssl

        if not api_key:
            logger.warning("No LLM API key configured (checked config.yml and environment)")
            self._client = None
            return

        try:
            if not verify_ssl:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

            http_client = httpx.Client(
                verify=verify_ssl,
                timeout=timeout
            )

            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client,
                max_retries=max_retries
            )

        except Exception as e:
            print(f"Warning: Failed to initialize OpenAI client: {e}")
            self._client = None

    # ========================================================================
    # ServiceAdapter interface
    # ========================================================================

    def resolve_config(self) -> Dict[str, Any]:
        """Resolve configuration from config.yml / ENV (tiers 2+3)."""
        llm_config = config_loader.get_llm_config()

        if llm_config:
            return {
                "api_key": llm_config.api_key,
                "base_url": llm_config.base_url,
                "model": config_loader.get_model_for_task(LLMTaskType.STANDARD),
                "timeout": llm_config.timeout,
                "verify_ssl": llm_config.verify_ssl,
            }

        return {
            "api_key": settings.openai_api_key,
            "model": settings.openai_model,
            "base_url": settings.openai_base_url,
            "timeout": settings.openai_timeout,
            "verify_ssl": settings.openai_verify_ssl,
        }

    async def resolve_config_for_org(
        self, organization_id: UUID, session: AsyncSession
    ) -> Dict[str, Any]:
        """
        Resolve configuration with DB connection as tier 1.

        Priority:
            1. Database connection (if organization_id and session provided)
            2. config.yml / ENV fallback
        """
        try:
            connection = await self._get_db_connection(organization_id, session)

            if connection:
                config = connection.config
                return {
                    "api_key": config.get("api_key", ""),
                    "model": config.get("model", settings.openai_model),
                    "base_url": config.get("base_url", settings.openai_base_url),
                    "timeout": config.get("timeout", settings.openai_timeout),
                    "verify_ssl": config.get("verify_ssl", settings.openai_verify_ssl),
                }
        except Exception as e:
            print(f"Warning: Failed to get LLM connection from database: {e}")

        return self.resolve_config()

    async def test_connection(self) -> LLMConnectionStatus:
        """Test the LLM connection and return detailed status information."""
        if not self._client:
            return LLMConnectionStatus(
                connected=False,
                error="No API key provided or client initialization failed",
                endpoint=settings.openai_base_url,
                model=settings.openai_model,
                ssl_verify=settings.openai_verify_ssl,
                timeout=settings.openai_timeout
            )

        try:
            def _sync_test():
                return self._client.chat.completions.create(
                    model=settings.openai_model,
                    messages=[{"role": "user", "content": "Hello, respond with just 'OK'"}],
                    max_tokens=10,
                    temperature=0
                )

            resp = await asyncio.to_thread(_sync_test)

            return LLMConnectionStatus(
                connected=True,
                endpoint=settings.openai_base_url,
                model=settings.openai_model,
                response=resp.choices[0].message.content.strip(),
                ssl_verify=settings.openai_verify_ssl,
                timeout=settings.openai_timeout
            )
        except Exception as e:
            return LLMConnectionStatus(
                connected=False,
                error=str(e),
                endpoint=settings.openai_base_url,
                model=settings.openai_model,
                ssl_verify=settings.openai_verify_ssl,
                timeout=settings.openai_timeout
            )

    @property
    def is_available(self) -> bool:
        """Whether the adapter's client is initialized and ready."""
        return self._client is not None

    # ========================================================================
    # Model / temperature helpers
    # ========================================================================

    def get_model(self, task_type: LLMTaskType = LLMTaskType.STANDARD) -> str:
        """Get the LLM model name for a specific task type."""
        return config_loader.get_model_for_task(task_type)

    def get_temperature(self, task_type: LLMTaskType = LLMTaskType.STANDARD) -> float:
        """Get the temperature for a specific task type."""
        return config_loader.get_temperature_for_task(task_type)

    # ========================================================================
    # Client factory
    # ========================================================================

    def create_client_from_config(self, config: Dict[str, Any]) -> Optional[OpenAI]:
        """
        Create OpenAI client from configuration dictionary.

        Args:
            config: Configuration dictionary with api_key, base_url, etc.

        Returns:
            Optional[OpenAI]: Initialized client or None if config invalid
        """
        api_key = config.get("api_key")
        if not api_key:
            return None

        try:
            verify_ssl = config.get("verify_ssl", True)
            if not verify_ssl:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

            http_client = httpx.Client(
                verify=verify_ssl,
                timeout=config.get("timeout", 60)
            )

            return OpenAI(
                api_key=api_key,
                base_url=config.get("base_url", "https://api.openai.com/v1"),
                http_client=http_client,
                max_retries=settings.openai_max_retries
            )
        except Exception as e:
            print(f"Warning: Failed to create OpenAI client: {e}")
            return None


# ============================================================================
# Global LLM Adapter Instance
# ============================================================================

llm_adapter = LLMAdapter()
