# Backend Client Service
"""HTTP client for communicating with curatore-backend."""

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger("mcp.services.backend_client")


class BackendClient:
    """HTTP client for curatore-backend API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        self.base_url = base_url or settings.backend_url
        self.timeout = timeout or settings.backend_timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _build_headers(
        self,
        api_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """Build request headers."""
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        return headers

    async def get_contracts(
        self,
        side_effects: Optional[bool] = None,
        api_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch tool contracts from backend.

        Args:
            side_effects: Filter by side_effects value (None = no filter)
            api_key: API key for authentication
            correlation_id: Request correlation ID

        Returns:
            List of tool contract dictionaries
        """
        client = await self._get_client()
        headers = self._build_headers(api_key, correlation_id)

        params = {}
        if side_effects is not None:
            params["side_effects"] = str(side_effects).lower()

        try:
            response = await client.get(
                "/api/v1/cwr/contracts/",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("contracts", [])
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch contracts: {e.response.status_code}")
            raise
        except Exception as e:
            logger.exception(f"Error fetching contracts: {e}")
            raise

    async def get_contract(
        self,
        name: str,
        api_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch a specific tool contract.

        Args:
            name: Function name
            api_key: API key for authentication
            correlation_id: Request correlation ID

        Returns:
            Tool contract dictionary or None if not found
        """
        client = await self._get_client()
        headers = self._build_headers(api_key, correlation_id)

        try:
            response = await client.get(
                f"/api/v1/cwr/contracts/{name}",
                headers=headers,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            logger.error(f"Failed to fetch contract {name}: {e.response.status_code}")
            raise
        except Exception as e:
            logger.exception(f"Error fetching contract {name}: {e}")
            raise

    async def get_metadata_catalog(
        self,
        org_id: Optional[str] = None,
        api_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetch metadata catalog from backend.

        Args:
            org_id: Organization ID
            api_key: API key for authentication
            correlation_id: Request correlation ID

        Returns:
            Metadata catalog dictionary
        """
        client = await self._get_client()
        headers = self._build_headers(api_key, correlation_id)

        params = {}
        if org_id:
            params["org_id"] = org_id

        try:
            response = await client.get(
                "/api/v1/data/metadata/catalog",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch metadata catalog: {e.response.status_code}")
            raise
        except Exception as e:
            logger.exception(f"Error fetching metadata catalog: {e}")
            raise

    async def get_facets(
        self,
        org_id: Optional[str] = None,
        api_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch facet definitions from backend.

        Args:
            org_id: Organization ID
            api_key: API key for authentication
            correlation_id: Request correlation ID

        Returns:
            List of facet definitions
        """
        client = await self._get_client()
        headers = self._build_headers(api_key, correlation_id)

        params = {}
        if org_id:
            params["org_id"] = org_id

        try:
            response = await client.get(
                "/api/v1/data/metadata/facets",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("facets", [])
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch facets: {e.response.status_code}")
            raise
        except Exception as e:
            logger.exception(f"Error fetching facets: {e}")
            raise

    async def execute_function(
        self,
        name: str,
        params: Dict[str, Any],
        api_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute a CWR function.

        Args:
            name: Function name
            params: Function parameters
            api_key: API key for authentication
            correlation_id: Request correlation ID
            dry_run: If true, function will not make changes

        Returns:
            Function execution result
        """
        client = await self._get_client()
        headers = self._build_headers(api_key, correlation_id)

        request_body = {
            "params": params,
            "dry_run": dry_run,
        }

        try:
            response = await client.post(
                f"/api/v1/cwr/functions/{name}/execute",
                headers=headers,
                json=request_body,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Function execution failed: {e.response.status_code}")
            # Try to extract error message from response
            try:
                error_data = e.response.json()
                detail = error_data.get("detail") or error_data.get("message") or str(e)
                return {
                    "status": "error",
                    "error": str(detail) if detail else f"HTTP {e.response.status_code}",
                }
            except Exception:
                return {
                    "status": "error",
                    "error": f"HTTP {e.response.status_code}: {str(e)}",
                }
        except Exception as e:
            logger.exception(f"Error executing function {name}: {e}")
            return {
                "status": "error",
                "error": str(e) or f"Unexpected error executing {name}",
            }


# Global client instance
backend_client = BackendClient()
