# backend/app/services/connection_service.py
"""
Connection management service for Curatore v2.

Provides runtime-configurable connections for SharePoint, LLM, and Extraction services
with extensible type registry, validation, and health testing.

Key Features:
    - Extensible type registry pattern for multiple connection types
    - Connection validation with type-specific schemas
    - Test-on-save functionality for health monitoring
    - CRUD operations with organization isolation
    - Default connection management per type
    - Connection health status tracking

Connection Types:
    - SharePoint: Microsoft Graph API connections
    - LLM: OpenAI-compatible API connections
    - Extraction: Document extraction service connections

Usage:
    from app.services.connection_service import connection_service

    # Get default LLM connection for organization
    llm_conn = await connection_service.get_default_connection(
        session, org_id, "llm"
    )

    # Test connection health
    result = await connection_service.test_connection(session, connection_id)

    # Get connection with decrypted config
    config = await connection_service.get_connection_config(session, connection_id)

Architecture:
    - BaseConnectionType: Abstract base class for all connection types
    - ConnectionTypeRegistry: Registry for registering and retrieving types
    - ConnectionService: Main service for CRUD and health testing
    - Type-specific classes: SharePointConnectionType, LLMConnectionType, etc.

Security:
    - Secrets are hashed/encrypted before storage (future enhancement)
    - Config validation prevents injection attacks
    - Organization-scoped queries prevent cross-tenant access
    - Health test results include sanitized error messages

Author: Curatore v2 Development Team
Version: 2.0.0
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Connection


# =========================================================================
# CONNECTION TYPE BASE CLASS
# =========================================================================


class ConnectionTestResult(BaseModel):
    """Result of a connection health test."""

    success: bool = Field(..., description="Whether the test succeeded")
    status: str = Field(..., description="Status: healthy, unhealthy, not_tested")
    message: str = Field(..., description="Human-readable message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional test details")
    error: Optional[str] = Field(None, description="Error message if test failed")


class BaseConnectionType(ABC):
    """
    Base class for all connection types.

    Connection types implement validation and testing for specific service types.
    Each type must provide:
    - Config validation schema
    - Health test implementation
    - Config schema for frontend generation

    Attributes:
        connection_type: Unique identifier for this connection type
        display_name: Human-readable name
        description: Description of what this connection type does
    """

    connection_type: str
    display_name: str
    description: str

    @abstractmethod
    def get_config_schema(self) -> Dict[str, Any]:
        """
        Get JSON schema for connection configuration.

        Returns:
            Dict[str, Any]: JSON schema for frontend form generation

        Example:
            {
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "writeOnly": true},
                    "model": {"type": "string", "default": "gpt-4"}
                },
                "required": ["api_key"]
            }
        """
        pass

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate connection configuration.

        Args:
            config: Configuration dictionary to validate

        Returns:
            Dict[str, Any]: Validated and potentially normalized config

        Raises:
            ValidationError: If configuration is invalid
        """
        pass

    @abstractmethod
    async def test_connection(self, config: Dict[str, Any]) -> ConnectionTestResult:
        """
        Test connection health.

        Args:
            config: Connection configuration to test

        Returns:
            ConnectionTestResult: Test results with status and message
        """
        pass


# =========================================================================
# SHAREPOINT CONNECTION TYPE
# =========================================================================


class SharePointConfigSchema(BaseModel):
    """SharePoint connection configuration schema."""

    tenant_id: str = Field(..., min_length=1, description="Azure AD tenant ID")
    client_id: str = Field(..., min_length=1, description="Azure AD application ID")
    client_secret: str = Field(..., min_length=1, description="Azure AD client secret")
    graph_base_url: str = Field(
        default="https://graph.microsoft.com/v1.0",
        description="Microsoft Graph API base URL"
    )
    graph_scope: str = Field(
        default="https://graph.microsoft.com/.default",
        description="OAuth scope"
    )


class MicrosoftGraphConnectionType(BaseConnectionType):
    """Microsoft Graph API connection type for SharePoint, OneDrive, and other Microsoft 365 services."""

    connection_type = "microsoft_graph"
    display_name = "Microsoft Graph API"
    description = "Connect to Microsoft 365 services (SharePoint, OneDrive, etc.) via Graph API"

    def get_config_schema(self) -> Dict[str, Any]:
        """Get JSON schema for Microsoft Graph API configuration."""
        return {
            "type": "object",
            "properties": {
                "tenant_id": {
                    "type": "string",
                    "title": "Tenant ID",
                    "description": "Azure AD tenant ID (GUID)",
                    "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
                },
                "client_id": {
                    "type": "string",
                    "title": "Client ID",
                    "description": "Azure AD application (client) ID"
                },
                "client_secret": {
                    "type": "string",
                    "title": "Client Secret",
                    "description": "Azure AD application client secret",
                    "writeOnly": True
                },
                "graph_base_url": {
                    "type": "string",
                    "title": "Graph API URL",
                    "description": "Microsoft Graph API base URL",
                    "default": "https://graph.microsoft.com/v1.0"
                },
                "graph_scope": {
                    "type": "string",
                    "title": "OAuth Scope",
                    "description": "OAuth scope for Graph API access",
                    "default": "https://graph.microsoft.com/.default"
                },
                "email_sender_user_id": {
                    "type": "string",
                    "title": "Email Sender User ID",
                    "description": "User ID or UPN for sending emails via Graph API (e.g., noreply@domain.com). Required if using Microsoft Graph for email."
                }
            },
            "required": ["tenant_id", "client_id", "client_secret"]
        }

    def validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate Microsoft Graph API configuration."""
        try:
            validated = SharePointConfigSchema(**config)
            return validated.model_dump()
        except ValidationError as e:
            raise ValueError(f"Invalid Microsoft Graph configuration: {e}")

    async def test_connection(self, config: Dict[str, Any]) -> ConnectionTestResult:
        """Test Microsoft Graph API connection by authenticating with Graph API."""
        try:
            tenant_id = config["tenant_id"]
            client_id = config["client_id"]
            client_secret = config["client_secret"]
            graph_scope = config.get("graph_scope", "https://graph.microsoft.com/.default")

            # Get OAuth token
            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    token_url,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "scope": graph_scope,
                        "grant_type": "client_credentials"
                    }
                )

                if response.status_code != 200:
                    return ConnectionTestResult(
                        success=False,
                        status="unhealthy",
                        message="Failed to authenticate with Microsoft Graph API",
                        error=f"HTTP {response.status_code}: {response.text}"
                    )

                token_data = response.json()
                access_token = token_data.get("access_token")

                if not access_token:
                    return ConnectionTestResult(
                        success=False,
                        status="unhealthy",
                        message="No access token received from authentication",
                        error="Empty access_token in response"
                    )

                # Test token with SharePoint sites endpoint
                # This validates credentials have proper SharePoint permissions
                graph_base_url = config.get("graph_base_url", "https://graph.microsoft.com/v1.0")
                test_response = await client.get(
                    f"{graph_base_url}/sites?$top=1",
                    headers={"Authorization": f"Bearer {access_token}"}
                )

                if test_response.status_code == 200:
                    # Successfully accessed SharePoint sites
                    try:
                        data = test_response.json()
                        site_count = len(data.get("value", []))
                        return ConnectionTestResult(
                            success=True,
                            status="healthy",
                            message="Successfully authenticated with Microsoft Graph API",
                            details={
                                "tenant_id": tenant_id,
                                "graph_endpoint": graph_base_url,
                                "sites_accessible": site_count > 0
                            }
                        )
                    except Exception:
                        # Valid response but couldn't parse
                        return ConnectionTestResult(
                            success=True,
                            status="healthy",
                            message="Successfully authenticated with Microsoft Graph API",
                            details={
                                "tenant_id": tenant_id,
                                "graph_endpoint": graph_base_url
                            }
                        )
                elif test_response.status_code == 401:
                    return ConnectionTestResult(
                        success=False,
                        status="unhealthy",
                        message="Authentication failed - invalid credentials or expired token",
                        error="HTTP 401 Unauthorized"
                    )
                elif test_response.status_code == 403:
                    return ConnectionTestResult(
                        success=False,
                        status="unhealthy",
                        message="Insufficient permissions - missing Sites.Read.All or Files.Read.All",
                        error="HTTP 403 Forbidden"
                    )
                else:
                    return ConnectionTestResult(
                        success=False,
                        status="unhealthy",
                        message="Unexpected response from Graph API",
                        error=f"HTTP {test_response.status_code}: {test_response.text[:200]}"
                    )

        except httpx.TimeoutException:
            return ConnectionTestResult(
                success=False,
                status="unhealthy",
                message="Connection timeout",
                error="Request timed out after 30 seconds"
            )
        except Exception as e:
            return ConnectionTestResult(
                success=False,
                status="unhealthy",
                message="Failed to test SharePoint connection",
                error=str(e)
            )


# =========================================================================
# LLM CONNECTION TYPE
# =========================================================================


class LLMConfigSchema(BaseModel):
    """LLM connection configuration schema."""

    api_key: str = Field(..., min_length=1, description="API key or authentication token")
    model: str = Field(..., min_length=1, description="Model name (e.g., gpt-4, gpt-3.5-turbo)")
    base_url: str = Field(..., description="API base URL")
    timeout: int = Field(default=60, ge=1, le=600, description="Request timeout in seconds")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")


class LLMConnectionType(BaseConnectionType):
    """LLM connection type for OpenAI-compatible APIs."""

    connection_type = "llm"
    display_name = "LLM API"
    description = "Connect to OpenAI-compatible LLM APIs (OpenAI, Ollama, LM Studio, etc.)"

    def get_config_schema(self) -> Dict[str, Any]:
        """Get JSON schema for LLM configuration."""
        return {
            "type": "object",
            "properties": {
                "api_key": {
                    "type": "string",
                    "title": "API Key",
                    "description": "API key or authentication token",
                    "writeOnly": True
                },
                "model": {
                    "type": "string",
                    "title": "Model",
                    "description": "Model name (e.g., gpt-4, claude-3, llama2)",
                    "default": "gpt-4"
                },
                "base_url": {
                    "type": "string",
                    "title": "Base URL",
                    "description": "API endpoint URL",
                    "default": "https://api.openai.com/v1"
                },
                "timeout": {
                    "type": "integer",
                    "title": "Timeout (seconds)",
                    "description": "Request timeout in seconds",
                    "default": 60,
                    "minimum": 1,
                    "maximum": 600
                },
                "verify_ssl": {
                    "type": "boolean",
                    "title": "Verify SSL",
                    "description": "Verify SSL certificates (disable for local servers)",
                    "default": True
                }
            },
            "required": ["api_key", "model", "base_url"]
        }

    def validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate LLM configuration."""
        try:
            validated = LLMConfigSchema(**config)
            return validated.model_dump()
        except ValidationError as e:
            raise ValueError(f"Invalid LLM configuration: {e}")

    async def test_connection(self, config: Dict[str, Any]) -> ConnectionTestResult:
        """Test LLM connection by making a simple API call."""
        try:
            api_key = config["api_key"]
            model = config["model"]
            base_url = config["base_url"].rstrip("/")
            timeout = config.get("timeout", 60)
            verify_ssl = config.get("verify_ssl", True)

            # Test with a simple completion request
            async with httpx.AsyncClient(timeout=float(timeout), verify=verify_ssl) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "test"}],
                        "max_tokens": 5
                    },
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    }
                )

                if response.status_code == 200:
                    return ConnectionTestResult(
                        success=True,
                        status="healthy",
                        message=f"Successfully connected to {model}",
                        details={
                            "model": model,
                            "endpoint": base_url
                        }
                    )
                elif response.status_code == 401:
                    return ConnectionTestResult(
                        success=False,
                        status="unhealthy",
                        message="Authentication failed - invalid API key",
                        error="HTTP 401 Unauthorized"
                    )
                elif response.status_code == 404:
                    return ConnectionTestResult(
                        success=False,
                        status="unhealthy",
                        message=f"Model '{model}' not found at endpoint",
                        error="HTTP 404 Not Found"
                    )
                else:
                    return ConnectionTestResult(
                        success=False,
                        status="unhealthy",
                        message=f"LLM API returned error",
                        error=f"HTTP {response.status_code}: {response.text[:200]}"
                    )

        except httpx.TimeoutException:
            return ConnectionTestResult(
                success=False,
                status="unhealthy",
                message="Connection timeout",
                error=f"Request timed out after {timeout} seconds"
            )
        except Exception as e:
            return ConnectionTestResult(
                success=False,
                status="unhealthy",
                message="Failed to test LLM connection",
                error=str(e)
            )


# =========================================================================
# EXTRACTION CONNECTION TYPE
# =========================================================================


class ExtractionConfigSchema(BaseModel):
    """Extraction service configuration schema."""

    service_url: str = Field(..., description="Extraction service URL")
    engine_type: Literal["extraction-service", "docling"] = Field(
        default="extraction-service",
        description="Type of extraction engine"
    )
    endpoint_path: Optional[str] = Field(
        default="",
        description="Custom endpoint path override"
    )
    timeout: int = Field(default=60, ge=1, le=600, description="Request timeout in seconds")
    api_key: Optional[str] = Field(None, description="Optional API key for authentication")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")
    docling_ocr_enabled: Optional[bool] = Field(
        default=None,
        description="Enable OCR for Docling extraction"
    )


class ExtractionConnectionType(BaseConnectionType):
    """Extraction service connection type."""

    connection_type = "extraction"
    display_name = "Extraction Service"
    description = "Connect to document extraction service for file conversion"

    async def _detect_docling_version(
        self,
        client: httpx.AsyncClient,
        service_url: str
    ) -> Optional[str]:
        """Detect Docling API version from OpenAPI metadata."""
        try:
            response = await client.get(f"{service_url}/openapi.json")
            if response.status_code != 200:
                return None
            payload = response.json()
            paths = payload.get("paths", {}) if isinstance(payload, dict) else {}
            if "/v1/convert/file" in paths:
                return "v1"
            if "/v1alpha/convert/file" in paths:
                return "v1alpha"
        except Exception:
            return None
        return None

    def get_config_schema(self) -> Dict[str, Any]:
        """Get JSON schema for extraction service configuration."""
        return {
            "type": "object",
            "properties": {
                "service_url": {
                    "type": "string",
                    "title": "Service URL",
                    "description": "Base URL for extraction service (e.g., http://extraction:8010 or http://docling:5001)",
                    "default": "http://extraction:8010"
                },
                "engine_type": {
                    "type": "string",
                    "title": "Engine Type",
                    "description": "Type of extraction engine",
                    "enum": ["extraction-service", "docling"],
                    "default": "extraction-service"
                },
                "docling_ocr_enabled": {
                    "type": "boolean",
                    "title": "Enable OCR (Docling)",
                    "description": "Enable OCR when using Docling (maps to do_ocr).",
                    "default": True
                },
                "endpoint_path": {
                    "type": "string",
                    "title": "Endpoint Path (optional)",
                    "description": "Custom endpoint path (e.g., /v1/convert/file for docling, /api/v1/extract for extraction-service). Leave empty to use defaults.",
                    "default": ""
                },
                "timeout": {
                    "type": "integer",
                    "title": "Timeout (seconds)",
                    "description": "Request timeout in seconds",
                    "default": 60,
                    "minimum": 1,
                    "maximum": 600
                },
                "api_key": {
                    "type": "string",
                    "title": "API Key (optional)",
                    "description": "API key if service requires authentication",
                    "writeOnly": True
                }
            },
            "required": ["service_url", "engine_type"]
        }

    def validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate extraction service configuration."""
        try:
            validated = ExtractionConfigSchema(**config)
            return validated.model_dump()
        except ValidationError as e:
            raise ValueError(f"Invalid extraction service configuration: {e}")

    async def test_connection(self, config: Dict[str, Any]) -> ConnectionTestResult:
        """Test extraction service connection."""
        try:
            service_url = config["service_url"].rstrip("/")
            timeout = config.get("timeout", 60)
            api_key = config.get("api_key")
            verify_ssl = config.get("verify_ssl", settings.extraction_service_verify_ssl)

            headers = {}
            if api_key:
                headers["X-API-Key"] = api_key

            # Docling uses /health, extraction-service uses /api/v1/system/health
            # Detect Docling by engine_type or URL pattern
            is_docling = config.get("engine_type") == "docling" or "docling" in service_url.lower() or ":5001" in service_url
            if is_docling:
                candidate_paths = [
                    "/health",
                    "/v1/health",
                    "/healthz",
                    "/api/v1/system/health",
                    "",
                ]
            else:
                candidate_paths = [
                    "/api/v1/system/health",
                    "/health",
                    "/v1/health",
                    "/healthz",
                    "",
                ]
            last_error = None
            last_status = None

            async with httpx.AsyncClient(timeout=float(timeout), verify=verify_ssl) as client:
                for path in candidate_paths:
                    url = f"{service_url}{path}"
                    try:
                        response = await client.get(url, headers=headers)
                    except httpx.RequestError as e:
                        last_error = str(e)
                        continue

                    if response.status_code == 200:
                        health_data: Dict[str, Any] = {}
                        try:
                            health_data = response.json()
                        except Exception:
                            health_data = {}

                        details: Dict[str, Any] = {
                            "url": url,
                            "status": health_data.get("status", "unknown")
                            if isinstance(health_data, dict)
                            else "unknown",
                        }

                        if is_docling:
                            docling_version = await self._detect_docling_version(client, service_url)
                            if docling_version:
                                details["docling_api_version"] = docling_version
                        return ConnectionTestResult(
                            success=True,
                            status="healthy",
                            message="Extraction service is responding",
                            details=details,
                        )

                    last_status = response.status_code

            error_message = last_error or (
                f"HTTP {last_status}" if last_status is not None else "No response"
            )
            return ConnectionTestResult(
                success=False,
                status="unhealthy",
                message="Extraction service returned error",
                error=error_message,
            )

        except httpx.TimeoutException:
            return ConnectionTestResult(
                success=False,
                status="unhealthy",
                message="Connection timeout",
                error=f"Request timed out after {timeout} seconds"
            )
        except Exception as e:
            return ConnectionTestResult(
                success=False,
                status="unhealthy",
                message="Failed to test extraction service",
                error=str(e)
            )


# =========================================================================
# PLAYWRIGHT CONNECTION TYPE
# =========================================================================


class PlaywrightConfigSchema(BaseModel):
    """Playwright rendering service configuration schema."""

    service_url: str = Field(..., description="Playwright service URL")
    timeout: int = Field(default=60, ge=1, le=600, description="Request timeout in seconds")
    max_retries: int = Field(default=3, ge=0, le=10, description="Maximum retry attempts")
    browser_pool_size: int = Field(default=3, ge=1, le=20, description="Browser pool size")
    default_viewport_width: int = Field(default=1920, ge=320, le=3840, description="Default viewport width")
    default_viewport_height: int = Field(default=1080, ge=240, le=2160, description="Default viewport height")
    default_timeout_ms: int = Field(default=60000, ge=1000, le=300000, description="Default page load timeout (ms)")
    default_wait_timeout_ms: int = Field(default=5000, ge=100, le=60000, description="Default wait for selector timeout (ms)")
    document_extensions: List[str] = Field(
        default=[".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"],
        description="Document extensions to detect"
    )


class PlaywrightConnectionType(BaseConnectionType):
    """Playwright rendering service connection type."""

    connection_type = "playwright"
    display_name = "Playwright Rendering"
    description = "Browser-based rendering service for JavaScript-heavy web scraping"

    def get_config_schema(self) -> Dict[str, Any]:
        """Get JSON schema for Playwright configuration."""
        return {
            "type": "object",
            "properties": {
                "service_url": {
                    "type": "string",
                    "title": "Service URL",
                    "description": "Playwright service URL (e.g., http://playwright:8011)",
                    "default": "http://playwright:8011"
                },
                "timeout": {
                    "type": "integer",
                    "title": "Timeout (seconds)",
                    "description": "Request timeout in seconds",
                    "default": 60,
                    "minimum": 1,
                    "maximum": 600
                },
                "max_retries": {
                    "type": "integer",
                    "title": "Max Retries",
                    "description": "Maximum retry attempts for failed requests",
                    "default": 3,
                    "minimum": 0,
                    "maximum": 10
                },
                "browser_pool_size": {
                    "type": "integer",
                    "title": "Browser Pool Size",
                    "description": "Number of browser instances to maintain",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 20
                },
                "default_viewport_width": {
                    "type": "integer",
                    "title": "Viewport Width",
                    "description": "Default browser viewport width",
                    "default": 1920,
                    "minimum": 320,
                    "maximum": 3840
                },
                "default_viewport_height": {
                    "type": "integer",
                    "title": "Viewport Height",
                    "description": "Default browser viewport height",
                    "default": 1080,
                    "minimum": 240,
                    "maximum": 2160
                },
                "default_timeout_ms": {
                    "type": "integer",
                    "title": "Page Load Timeout (ms)",
                    "description": "Default page load timeout in milliseconds",
                    "default": 30000,
                    "minimum": 1000,
                    "maximum": 120000
                },
                "default_wait_timeout_ms": {
                    "type": "integer",
                    "title": "Wait Timeout (ms)",
                    "description": "Default wait for selector timeout in milliseconds",
                    "default": 5000,
                    "minimum": 100,
                    "maximum": 60000
                },
                "document_extensions": {
                    "type": "array",
                    "title": "Document Extensions",
                    "description": "File extensions to identify as downloadable documents",
                    "items": {"type": "string"},
                    "default": [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"]
                }
            },
            "required": ["service_url"]
        }

    def validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate Playwright configuration."""
        try:
            validated = PlaywrightConfigSchema(**config)
            return validated.model_dump()
        except ValidationError as e:
            raise ValueError(f"Invalid Playwright configuration: {e}")

    async def test_connection(self, config: Dict[str, Any]) -> ConnectionTestResult:
        """Test Playwright service connection by calling health endpoint."""
        try:
            service_url = config["service_url"].rstrip("/")
            timeout = config.get("timeout", 60)

            async with httpx.AsyncClient(timeout=float(timeout)) as client:
                # Try health endpoint
                response = await client.get(f"{service_url}/health")

                if response.status_code == 200:
                    health_data = {}
                    try:
                        health_data = response.json()
                    except Exception:
                        pass

                    return ConnectionTestResult(
                        success=True,
                        status="healthy",
                        message="Playwright service is responding",
                        details={
                            "url": service_url,
                            "browser_pool_size": health_data.get("browser_pool_size"),
                            "active_contexts": health_data.get("active_contexts"),
                            "status": health_data.get("status", "healthy"),
                        }
                    )
                else:
                    return ConnectionTestResult(
                        success=False,
                        status="unhealthy",
                        message=f"Playwright service returned status {response.status_code}",
                        error=f"HTTP {response.status_code}: {response.text[:200]}"
                    )

        except httpx.TimeoutException:
            return ConnectionTestResult(
                success=False,
                status="unhealthy",
                message="Connection timeout",
                error=f"Request timed out after {timeout} seconds"
            )
        except Exception as e:
            return ConnectionTestResult(
                success=False,
                status="unhealthy",
                message="Failed to test Playwright connection",
                error=str(e)
            )


# =========================================================================
# SAM.GOV CONNECTION TYPE
# =========================================================================


class SamGovConfigSchema(BaseModel):
    """SAM.gov API configuration schema."""

    api_key: str = Field(..., min_length=1, description="SAM.gov API key")
    # Note: base_url is intentionally not configurable - SAM.gov API has a fixed endpoint
    timeout: int = Field(default=60, ge=1, le=600, description="Request timeout in seconds")
    rate_limit_delay: float = Field(
        default=0.5, ge=0, le=10, description="Delay between requests in seconds"
    )


# SAM.gov API has a fixed endpoint that cannot be changed
SAM_GOV_API_BASE_URL = "https://api.sam.gov/opportunities/v2"


class SamGovConnectionType(BaseConnectionType):
    """SAM.gov API connection type for federal opportunities data."""

    connection_type = "sam_gov"
    display_name = "SAM.gov API"
    description = "Connect to SAM.gov Opportunities API for federal contract data"

    def get_config_schema(self) -> Dict[str, Any]:
        """Get JSON schema for SAM.gov configuration."""
        return {
            "type": "object",
            "properties": {
                "api_key": {
                    "type": "string",
                    "title": "API Key",
                    "description": "SAM.gov API key from api.sam.gov",
                    "writeOnly": True
                },
                # Note: base_url is intentionally not configurable - SAM.gov API has a fixed endpoint
                "timeout": {
                    "type": "integer",
                    "title": "Timeout (seconds)",
                    "description": "Request timeout in seconds",
                    "default": 60,
                    "minimum": 1,
                    "maximum": 600
                },
                "rate_limit_delay": {
                    "type": "number",
                    "title": "Rate Limit Delay",
                    "description": "Delay between API requests in seconds",
                    "default": 0.5,
                    "minimum": 0,
                    "maximum": 10
                }
            },
            "required": ["api_key"]
        }

    def validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate SAM.gov configuration."""
        try:
            validated = SamGovConfigSchema(**config)
            return validated.model_dump()
        except ValidationError as e:
            raise ValueError(f"Invalid SAM.gov configuration: {e}")

    async def test_connection(self, config: Dict[str, Any]) -> ConnectionTestResult:
        """Test SAM.gov API connection by making a minimal search request."""
        try:
            api_key = config["api_key"]
            # Use hardcoded SAM.gov API endpoint (not configurable)
            base_url = SAM_GOV_API_BASE_URL.rstrip("/")
            timeout = config.get("timeout", 60)

            headers = {
                "X-Api-Key": api_key,
                "Accept": "application/json",
            }

            # SAM.gov API requires postedFrom and postedTo for search
            from datetime import datetime, timedelta
            today = datetime.now()
            week_ago = today - timedelta(days=7)
            posted_from = week_ago.strftime("%m/%d/%Y")
            posted_to = today.strftime("%m/%d/%Y")

            async with httpx.AsyncClient(timeout=float(timeout)) as client:
                # Make a minimal search request to test connection
                response = await client.get(
                    f"{base_url}/search",
                    params={
                        "limit": 1,
                        "postedFrom": posted_from,
                        "postedTo": posted_to,
                    },
                    headers=headers,
                )

                if response.status_code == 200:
                    try:
                        data = response.json()
                        total = data.get("totalRecords", 0)
                        return ConnectionTestResult(
                            success=True,
                            status="healthy",
                            message="Successfully connected to SAM.gov API",
                            details={
                                "api_version": "v2",
                                "total_opportunities": total,
                                "endpoint": base_url,
                            }
                        )
                    except Exception:
                        return ConnectionTestResult(
                            success=True,
                            status="healthy",
                            message="Successfully connected to SAM.gov API",
                            details={"endpoint": base_url}
                        )
                elif response.status_code == 401:
                    return ConnectionTestResult(
                        success=False,
                        status="unhealthy",
                        message="Authentication failed - invalid API key",
                        error="HTTP 401 Unauthorized"
                    )
                elif response.status_code == 403:
                    return ConnectionTestResult(
                        success=False,
                        status="unhealthy",
                        message="Access forbidden - check API key permissions",
                        error="HTTP 403 Forbidden"
                    )
                else:
                    return ConnectionTestResult(
                        success=False,
                        status="unhealthy",
                        message=f"SAM.gov API returned error",
                        error=f"HTTP {response.status_code}: {response.text[:200]}"
                    )

        except httpx.TimeoutException:
            return ConnectionTestResult(
                success=False,
                status="unhealthy",
                message="Connection timeout",
                error=f"Request timed out after {timeout} seconds"
            )
        except Exception as e:
            return ConnectionTestResult(
                success=False,
                status="unhealthy",
                message="Failed to test SAM.gov connection",
                error=str(e)
            )


# =========================================================================
# CONNECTION TYPE REGISTRY
# =========================================================================


class ConnectionTypeRegistry:
    """Registry for connection types."""

    def __init__(self):
        """Initialize registry."""
        self._types: Dict[str, BaseConnectionType] = {}
        self._logger = logging.getLogger("curatore.connection_registry")

    def register(self, connection_type: BaseConnectionType):
        """
        Register a connection type.

        Args:
            connection_type: Connection type instance to register
        """
        type_name = connection_type.connection_type
        if type_name in self._types:
            self._logger.warning(f"Connection type '{type_name}' already registered, overwriting")

        self._types[type_name] = connection_type
        self._logger.info(f"Registered connection type: {type_name}")

    def get(self, connection_type: str) -> Optional[BaseConnectionType]:
        """
        Get connection type by name.

        Args:
            connection_type: Connection type name

        Returns:
            Optional[BaseConnectionType]: Connection type instance or None
        """
        return self._types.get(connection_type)

    def list_types(self) -> List[Dict[str, Any]]:
        """
        List all registered connection types.

        Returns:
            List[Dict[str, Any]]: List of connection type metadata
        """
        return [
            {
                "type": ct.connection_type,
                "display_name": ct.display_name,
                "description": ct.description,
                "config_schema": ct.get_config_schema()
            }
            for ct in self._types.values()
        ]


# =========================================================================
# CONNECTION SERVICE
# =========================================================================


class ConnectionService:
    """
    Connection management service.

    Provides CRUD operations and health testing for connections.
    """

    def __init__(self):
        """Initialize connection service."""
        self._logger = logging.getLogger("curatore.connection_service")
        self._registry = ConnectionTypeRegistry()

        # Register built-in connection types
        self._registry.register(MicrosoftGraphConnectionType())
        self._registry.register(LLMConnectionType())
        self._registry.register(ExtractionConnectionType())
        self._registry.register(PlaywrightConnectionType())
        self._registry.register(SamGovConnectionType())

        self._logger.info("Connection service initialized")

    @property
    def registry(self) -> ConnectionTypeRegistry:
        """Get connection type registry."""
        return self._registry

    async def get_default_connection(
        self,
        session: AsyncSession,
        organization_id: UUID,
        connection_type: str
    ) -> Optional[Connection]:
        """
        Get default connection for organization and type.

        Args:
            session: Database session
            organization_id: Organization UUID
            connection_type: Connection type name

        Returns:
            Optional[Connection]: Default connection or None
        """
        result = await session.execute(
            select(Connection)
            .where(Connection.organization_id == organization_id)
            .where(Connection.connection_type == connection_type)
            .where(Connection.is_default == True)
            .where(Connection.is_active == True)
        )
        return result.scalar_one_or_none()

    async def test_connection(
        self,
        session: AsyncSession,
        connection_id: UUID
    ) -> ConnectionTestResult:
        """
        Test connection health.

        Args:
            session: Database session
            connection_id: Connection UUID

        Returns:
            ConnectionTestResult: Test results
        """
        # Fetch connection
        result = await session.execute(
            select(Connection).where(Connection.id == connection_id)
        )
        connection = result.scalar_one_or_none()

        if not connection:
            return ConnectionTestResult(
                success=False,
                status="not_tested",
                message="Connection not found"
            )

        # Get connection type handler
        conn_type = self._registry.get(connection.connection_type)
        if not conn_type:
            return ConnectionTestResult(
                success=False,
                status="not_tested",
                message=f"Unknown connection type: {connection.connection_type}"
            )

        # Test connection
        test_result = await conn_type.test_connection(connection.config)

        # Update connection status
        await session.execute(
            update(Connection)
            .where(Connection.id == connection_id)
            .values(
                last_tested_at=datetime.utcnow(),
                test_status=test_result.status,
                test_result=test_result.model_dump()
            )
        )
        await session.commit()

        self._logger.info(
            f"Tested connection {connection.name} (id: {connection_id}): {test_result.status}"
        )

        return test_result


# =========================================================================
# SINGLETON INSTANCE
# =========================================================================

connection_service = ConnectionService()


# =========================================================================
# DEFAULT CONNECTION SYNC
# =========================================================================


async def sync_default_connections_from_env(
    session: AsyncSession, organization_id: UUID
) -> Dict[str, str]:
    """
    Sync default connections from environment variables.

    Creates or updates "Default" connections for each type where env vars exist.
    Connections are marked as managed and cannot be edited through the UI.

    This function is called on application startup to ensure that connections
    defined in environment variables are always available in the database.

    Args:
        session: Database session
        organization_id: Organization to create connections for

    Returns:
        Dict mapping connection type to status:
            - "created": New connection was created
            - "updated": Existing connection was updated
            - "unchanged": Connection exists and is up to date
            - "skipped": Required env vars not found
            - "error": Failed to sync connection

    Example:
        >>> async with database_service.get_session() as session:
        ...     results = await sync_default_connections_from_env(
        ...         session, org_id
        ...     )
        ...     print(results)
        {"sharepoint": "created", "llm": "updated", "extraction": "unchanged"}
    """
    import os
    from datetime import datetime
    from sqlalchemy import select
    from ..database.models import Connection
    from ..config import settings
    from ..services.config_loader import config_loader

    logger = logging.getLogger("curatore.connection_sync")
    results: Dict[str, str] = {}

    # -------------------------------------------------------------------------
    # SharePoint Connection
    # -------------------------------------------------------------------------
    try:
        tenant_id = os.environ.get("MS_TENANT_ID")
        client_id = os.environ.get("MS_CLIENT_ID")
        client_secret = os.environ.get("MS_CLIENT_SECRET")

        if tenant_id and client_id and client_secret:
            config = {
                "tenant_id": tenant_id,
                "client_id": client_id,
                "client_secret": client_secret,
                "graph_base_url": os.environ.get(
                    "MS_GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0"
                ),
                "graph_scope": os.environ.get(
                    "MS_GRAPH_SCOPE", "https://graph.microsoft.com/.default"
                ),
            }

            # Query for existing managed Microsoft Graph connection
            result = await session.execute(
                select(Connection).where(
                    Connection.organization_id == organization_id,
                    Connection.connection_type == "microsoft_graph",
                    Connection.is_managed == True,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update if config changed
                if existing.config != config:
                    existing.config = config
                    existing.updated_at = datetime.utcnow()
                    await session.commit()
                    results["microsoft_graph"] = "updated"
                    logger.info("Updated managed Microsoft Graph connection")
                else:
                    results["microsoft_graph"] = "unchanged"
            else:
                # Create new managed connection
                new_connection = Connection(
                    organization_id=organization_id,
                    name="Default Microsoft Graph",
                    description="Auto-managed Microsoft Graph API connection from environment variables",
                    connection_type="microsoft_graph",
                    config=config,
                    is_active=True,
                    is_default=True,
                    is_managed=True,
                    managed_by="Environment variables: MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET",
                    scope="organization",
                )
                session.add(new_connection)
                await session.commit()
                results["microsoft_graph"] = "created"
                logger.info("Created managed Microsoft Graph connection")
        else:
            results["microsoft_graph"] = "skipped"
            logger.debug(
                "Skipping Microsoft Graph connection sync - missing required env vars"
            )

    except Exception as e:
        results["microsoft_graph"] = "error"
        logger.error(f"Failed to sync Microsoft Graph connection: {e}")

    # -------------------------------------------------------------------------
    # LLM Connection
    # -------------------------------------------------------------------------
    try:
        api_key = os.environ.get("OPENAI_API_KEY")

        if api_key:
            config = {
                "api_key": api_key,
                "model": settings.openai_model,
                "base_url": settings.openai_base_url,
                "timeout": int(settings.openai_timeout),
                "verify_ssl": settings.openai_verify_ssl,
            }

            # Query for existing managed LLM connection
            result = await session.execute(
                select(Connection).where(
                    Connection.organization_id == organization_id,
                    Connection.connection_type == "llm",
                    Connection.is_managed == True,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update if config changed
                if existing.config != config:
                    existing.config = config
                    existing.updated_at = datetime.utcnow()
                    await session.commit()
                    results["llm"] = "updated"
                    logger.info("Updated managed LLM connection")
                else:
                    results["llm"] = "unchanged"
            else:
                # Create new managed connection
                new_connection = Connection(
                    organization_id=organization_id,
                    name="Default LLM",
                    description="Auto-managed LLM connection from environment variables",
                    connection_type="llm",
                    config=config,
                    is_active=True,
                    is_default=True,
                    is_managed=True,
                    managed_by="Environment variables: OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL",
                    scope="organization",
                )
                session.add(new_connection)
                await session.commit()
                results["llm"] = "created"
                logger.info("Created managed LLM connection")
        else:
            results["llm"] = "skipped"
            logger.debug("Skipping LLM connection sync - missing OPENAI_API_KEY")

    except Exception as e:
        results["llm"] = "error"
        logger.error(f"Failed to sync LLM connection: {e}")

    # -------------------------------------------------------------------------
    # Extraction Service Connection(s)
    # -------------------------------------------------------------------------
    try:
        extraction_config = None
        try:
            extraction_config = config_loader.get_extraction_config()
        except Exception as e:
            logger.warning("Failed to load extraction config from config.yml: %s", e)

        if extraction_config is None:
            try:
                import os
                import yaml
                from ..models.config_models import ExtractionConfig

                def _resolve_extraction_env(obj: Any) -> Any:
                    if isinstance(obj, dict):
                        return {k: _resolve_extraction_env(v) for k, v in obj.items()}
                    if isinstance(obj, list):
                        return [_resolve_extraction_env(item) for item in obj]
                    if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
                        var_name = obj[2:-1]
                        value = os.getenv(var_name)
                        return value
                    return obj

                config_path = config_loader.config_path
                if os.path.exists(config_path):
                    with open(config_path, "r") as f:
                        raw_config = yaml.safe_load(f) or {}
                    extraction_raw = raw_config.get("extraction")
                    if extraction_raw:
                        resolved = _resolve_extraction_env(extraction_raw)
                        extraction_config = ExtractionConfig(**resolved)
            except Exception as e:
                logger.warning(
                    "Failed to parse extraction config from config.yml: %s", e
                )

        managed_result = await session.execute(
            select(Connection).where(
                Connection.organization_id == organization_id,
                Connection.connection_type == "extraction",
                Connection.is_managed == True,
            )
        )
        managed_connections = managed_result.scalars().all()

        created = 0
        updated = 0
        unchanged = 0

        def _normalize_url(value: Optional[str]) -> str:
            return (value or "").rstrip("/")

        default_url = _normalize_url(settings.extraction_service_url)

        if extraction_config and extraction_config.engines:
            for engine in extraction_config.engines:
                service_url = _normalize_url(engine.service_url)
                if not service_url:
                    continue

                config: Dict[str, Any] = {
                    "engine_type": engine.engine_type,  # Store engine_type in database
                    "service_url": service_url,
                    "timeout": int(engine.timeout),
                    "verify_ssl": engine.verify_ssl,
                }
                docling_ocr_enabled = getattr(engine, "docling_ocr_enabled", None)
                if engine.engine_type == "docling" and docling_ocr_enabled is not None:
                    config["docling_ocr_enabled"] = bool(docling_ocr_enabled)
                if engine.api_key:
                    config["api_key"] = engine.api_key
                if engine.options:
                    config["options"] = engine.options

                # Find existing connection by name or URL (case-insensitive name matching)
                existing = next(
                    (
                        conn
                        for conn in managed_connections
                        if conn.name.lower().replace(" ", "-") == engine.name.lower().replace(" ", "-")
                        or _normalize_url(conn.config.get("service_url")) == service_url
                    ),
                    None,
                )

                # Determine if this engine is the default based on top-level default_engine setting
                # The default_engine setting in config.yml specifies the engine name to use as default
                is_default = False
                if extraction_config.default_engine:
                    # Match by name (case-insensitive)
                    is_default = engine.name.lower() == extraction_config.default_engine.lower()
                elif default_url and service_url == default_url:
                    # Legacy fallback: match by URL from env var
                    is_default = True
                elif engine.name.lower() in {"extraction-service", "default"}:
                    # Ultimate fallback: extraction-service is default
                    is_default = True

                # Sync enabled/disabled state from config.yml
                is_active = engine.enabled

                if existing:
                    config_changed = existing.config != config
                    default_changed = existing.is_default != is_default
                    active_changed = existing.is_active != is_active
                    name_changed = existing.name != engine.name

                    if config_changed or default_changed or active_changed or name_changed:
                        existing.config = config
                        existing.is_default = is_default
                        existing.is_active = is_active
                        existing.name = engine.name
                        existing.updated_at = datetime.utcnow()
                        await session.commit()
                        updated += 1
                        status = "enabled" if is_active else "disabled"
                        logger.info(
                            "Updated managed extraction connection: %s (engine_type: %s, %s)",
                            engine.name,
                            engine.engine_type,
                            status
                        )
                    else:
                        unchanged += 1
                else:
                    # Only create new connections for enabled engines
                    if engine.enabled:
                        new_connection = Connection(
                            organization_id=organization_id,
                            name=engine.name,
                            description=f"Auto-managed {engine.engine_type} connection from config.yml",
                            connection_type="extraction",
                            config=config,
                            is_active=is_active,
                            is_default=is_default,
                            is_managed=True,
                            managed_by="config.yml: extraction.engines",
                            scope="organization",
                        )
                        session.add(new_connection)
                        await session.commit()
                        created += 1
                        logger.info(
                            "Created managed extraction connection: %s (engine_type: %s)",
                            engine.name,
                            engine.engine_type
                        )

            if updated:
                results["extraction"] = "updated"
            elif created:
                results["extraction"] = "created"
            elif unchanged:
                results["extraction"] = "unchanged"
            else:
                results["extraction"] = "skipped"
        else:
            service_url = settings.extraction_service_url

            if service_url:
                config = {
                    "service_url": service_url,
                    "timeout": int(settings.extraction_service_timeout),
                }

                # Add API key if present
                if settings.extraction_service_api_key:
                    config["api_key"] = settings.extraction_service_api_key

                # Add verify_ssl setting
                config["verify_ssl"] = settings.extraction_service_verify_ssl

                # Query for existing managed extraction connection
                result = await session.execute(
                    select(Connection).where(
                        Connection.organization_id == organization_id,
                        Connection.connection_type == "extraction",
                        Connection.is_managed == True,
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # Update if config changed
                    if existing.config != config:
                        existing.config = config
                        existing.updated_at = datetime.utcnow()
                        await session.commit()
                        results["extraction"] = "updated"
                        logger.info("Updated managed Extraction Service connection")
                    else:
                        results["extraction"] = "unchanged"
                else:
                    # Create new managed connection
                    new_connection = Connection(
                        organization_id=organization_id,
                        name="Default Extraction Service",
                        description="Auto-managed extraction service connection from environment variables",
                        connection_type="extraction",
                        config=config,
                        is_active=True,
                        is_default=True,
                        is_managed=True,
                        managed_by="Environment variables: EXTRACTION_SERVICE_URL",
                        scope="organization",
                    )
                    session.add(new_connection)
                    await session.commit()
                    results["extraction"] = "created"
                    logger.info("Created managed Extraction Service connection")
            else:
                results["extraction"] = "skipped"
                logger.debug(
                    "Skipping extraction connection sync - missing EXTRACTION_SERVICE_URL"
                )

    except Exception as e:
        results["extraction"] = "error"
        logger.error(f"Failed to sync Extraction Service connection: {e}")

    # -------------------------------------------------------------------------
    # Playwright Connection
    # -------------------------------------------------------------------------
    try:
        playwright_config = None
        try:
            playwright_config = config_loader.get_playwright_config()
        except Exception as e:
            logger.warning("Failed to load Playwright config from config.yml: %s", e)

        # Fall back to environment variable
        service_url = os.environ.get("PLAYWRIGHT_SERVICE_URL") or (
            playwright_config.service_url if playwright_config else None
        )

        if service_url:
            # Build config from config.yml or env vars
            config: Dict[str, Any] = {
                "service_url": service_url,
            }

            if playwright_config:
                config["timeout"] = playwright_config.timeout
                config["max_retries"] = playwright_config.max_retries
                config["browser_pool_size"] = playwright_config.browser_pool_size
                config["default_viewport_width"] = playwright_config.default_viewport_width
                config["default_viewport_height"] = playwright_config.default_viewport_height
                config["default_timeout_ms"] = playwright_config.default_timeout_ms
                config["default_wait_timeout_ms"] = playwright_config.default_wait_timeout_ms
                config["document_extensions"] = playwright_config.document_extensions
            else:
                # Defaults from environment or hardcoded
                config["timeout"] = int(os.environ.get("PLAYWRIGHT_TIMEOUT", "60"))
                config["max_retries"] = 3
                config["browser_pool_size"] = int(os.environ.get("PLAYWRIGHT_BROWSER_POOL_SIZE", "3"))
                config["default_viewport_width"] = 1920
                config["default_viewport_height"] = 1080
                config["default_timeout_ms"] = int(os.environ.get("PLAYWRIGHT_DEFAULT_TIMEOUT_MS", "60000"))
                config["default_wait_timeout_ms"] = int(os.environ.get("PLAYWRIGHT_DEFAULT_WAIT_TIMEOUT_MS", "5000"))
                config["document_extensions"] = [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"]

            # Query for existing managed Playwright connection
            result = await session.execute(
                select(Connection).where(
                    Connection.organization_id == organization_id,
                    Connection.connection_type == "playwright",
                    Connection.is_managed == True,
                )
            )
            existing = result.scalar_one_or_none()

            # Determine if enabled (from config.yml or default True)
            is_enabled = playwright_config.enabled if playwright_config else True

            if existing:
                # Update if config changed
                config_changed = existing.config != config
                active_changed = existing.is_active != is_enabled

                if config_changed or active_changed:
                    existing.config = config
                    existing.is_active = is_enabled
                    existing.updated_at = datetime.utcnow()
                    await session.commit()
                    results["playwright"] = "updated"
                    logger.info("Updated managed Playwright connection")
                else:
                    results["playwright"] = "unchanged"
            else:
                # Create new managed connection
                new_connection = Connection(
                    organization_id=organization_id,
                    name="Default Playwright",
                    description="Auto-managed Playwright rendering service connection",
                    connection_type="playwright",
                    config=config,
                    is_active=is_enabled,
                    is_default=True,
                    is_managed=True,
                    managed_by="config.yml: playwright or PLAYWRIGHT_SERVICE_URL",
                    scope="organization",
                )
                session.add(new_connection)
                await session.commit()
                results["playwright"] = "created"
                logger.info("Created managed Playwright connection")
        else:
            results["playwright"] = "skipped"
            logger.debug(
                "Skipping Playwright connection sync - missing PLAYWRIGHT_SERVICE_URL"
            )

    except Exception as e:
        results["playwright"] = "error"
        logger.error(f"Failed to sync Playwright connection: {e}")

    return results
