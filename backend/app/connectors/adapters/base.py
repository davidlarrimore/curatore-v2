"""
ServiceAdapter ABC — Base class for external service adapters.

All adapters follow a 3-tier configuration resolution:
    1. Database Connection (per-organization, via connection_service)
    2. config.yml section
    3. Environment variables (settings)

Subclasses must implement:
    - CONNECTION_TYPE: str matching the registered connection type
    - resolve_config(): returns merged config dict from tiers 2+3
    - resolve_config_for_org(): returns config with DB connection as tier 1
    - test_connection(): verifies the service is reachable
    - is_available: property indicating if the adapter is ready
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


class ServiceAdapter(ABC):
    """
    Base class for external service adapters.

    All adapters follow a 3-tier configuration resolution:
        1. Database Connection (per-organization, via connection_service)
        2. config.yml section
        3. Environment variables (settings)

    Subclasses must implement:
        - CONNECTION_TYPE: str matching the registered connection type
        - resolve_config(): returns merged config dict from tiers 2+3
        - resolve_config_for_org(): returns config with DB connection as tier 1
        - test_connection(): verifies the service is reachable
        - is_available: property indicating if the adapter is ready
    """

    CONNECTION_TYPE: str  # Must match connection_service registry

    @abstractmethod
    def resolve_config(self) -> Dict[str, Any]:
        """Resolve configuration from config.yml / ENV (tiers 2+3)."""
        ...

    @abstractmethod
    async def resolve_config_for_org(
        self, organization_id: UUID, session: AsyncSession
    ) -> Dict[str, Any]:
        """Resolve configuration with DB connection as tier 1."""
        ...

    @abstractmethod
    async def test_connection(self) -> Dict[str, Any]:
        """Test the service connection. Returns dict with 'success', 'message', etc."""
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether the adapter's client is initialized and ready."""
        ...

    async def _get_db_connection(
        self, organization_id: UUID, session: AsyncSession
    ) -> Optional[Any]:
        """Helper: get active DB connection for this adapter's CONNECTION_TYPE."""
        from app.core.auth.connection_service import connection_service

        connection = await connection_service.get_default_connection(
            session, organization_id, self.CONNECTION_TYPE
        )
        if connection and connection.is_active:
            return connection
        return None
