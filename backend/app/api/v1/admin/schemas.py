"""
Admin-related Pydantic models extracted from the monolithic models.py.

Covers connections, organizations, users, API keys, and system health models.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field

# Shared domain models
from app.core.models import HealthStatus, LLMConnectionStatus

# =========================================================================
# CONNECTION MODELS
# =========================================================================

class ConnectionResponse(BaseModel):
    """Connection details response."""
    id: str = Field(..., description="Connection UUID")
    organization_id: str = Field(..., description="Organization UUID")
    name: str = Field(..., description="Connection name")
    description: Optional[str] = Field(None, description="Connection description")
    connection_type: str = Field(..., description="Connection type (microsoft_graph, llm, extraction)")
    config: Dict[str, Any] = Field(..., description="Connection configuration")
    is_active: bool = Field(..., description="Whether connection is active")
    is_default: bool = Field(..., description="Whether this is the default connection for its type")
    is_managed: bool = Field(..., description="Whether connection is managed by environment variables")
    managed_by: Optional[str] = Field(None, description="Description of what manages this connection")
    last_tested_at: Optional[datetime] = Field(None, description="Last test timestamp")
    test_status: Optional[str] = Field(None, description="Test status (healthy, unhealthy, not_tested)")
    test_result: Optional[Dict[str, Any]] = Field(None, description="Detailed test results")
    organization_name: Optional[str] = Field(None, description="Organization name (included in system-wide listings)")
    scope: str = Field(..., description="Connection scope (organization, user)")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "organization_id": "04ace7c6-2043-4935-b074-ec0a567d1fd2",
                "name": "Production Extraction",
                "description": "Document extraction service",
                "connection_type": "extraction",
                "config": {
                    "service_url": "http://document-service:8010",
                    "engine_type": "document-service"
                },
                "is_active": True,
                "is_default": True,
                "is_managed": False,
                "managed_by": None,
                "last_tested_at": "2026-01-13T01:00:00",
                "test_status": "healthy",
                "test_result": {
                    "success": True,
                    "status": "healthy",
                    "message": "Successfully connected to gpt-4"
                },
                "scope": "organization",
                "created_at": "2026-01-13T00:00:00",
                "updated_at": "2026-01-13T01:00:00"
            }
        }


class ConnectionCreateRequest(BaseModel):
    """Request to create a new connection."""
    name: str = Field(..., min_length=1, max_length=255, description="Connection name")
    description: Optional[str] = Field(None, max_length=500, description="Connection description")
    connection_type: str = Field(..., description="Connection type (microsoft_graph, llm, extraction)")
    config: Dict[str, Any] = Field(..., description="Type-specific configuration")
    is_default: bool = Field(default=False, description="Set as default for this type")
    scope: str = Field(default="organization", description="Connection scope (organization, user)")
    test_on_save: bool = Field(default=True, description="Test connection after creation")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Production Extraction",
                "description": "Document extraction service",
                "connection_type": "extraction",
                "config": {
                    "service_url": "http://document-service:8010",
                    "engine_type": "document-service"
                },
                "is_default": True,
                "test_on_save": True
            }
        }


class ConnectionUpdateRequest(BaseModel):
    """Request to update connection details."""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Connection name")
    description: Optional[str] = Field(None, max_length=500, description="Connection description")
    config: Optional[Dict[str, Any]] = Field(None, description="Type-specific configuration")
    is_active: Optional[bool] = Field(None, description="Whether connection is active")
    is_default: Optional[bool] = Field(None, description="Set as default for this type")
    test_on_save: bool = Field(default=False, description="Test connection after update")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Updated Connection Name",
                "is_default": True,
                "test_on_save": True
            }
        }


class ConnectionListResponse(BaseModel):
    """List of connections response."""
    connections: List[ConnectionResponse] = Field(..., description="List of connections")
    total: int = Field(..., description="Total number of connections")

    class Config:
        json_schema_extra = {
            "example": {
                "connections": [
                    {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "organization_id": "04ace7c6-2043-4935-b074-ec0a567d1fd2",
                        "name": "Production Extraction",
                        "connection_type": "extraction",
                        "is_active": True,
                        "is_default": True,
                        "test_status": "healthy",
                        "scope": "organization",
                        "created_at": "2026-01-13T00:00:00",
                        "updated_at": "2026-01-13T01:00:00"
                    }
                ],
                "total": 1
            }
        }


class ConnectionTestResponse(BaseModel):
    """Connection test result response."""
    connection_id: str = Field(..., description="Connection UUID")
    success: bool = Field(..., description="Whether the test succeeded")
    status: str = Field(..., description="Test status (healthy, unhealthy, not_tested)")
    message: str = Field(..., description="Human-readable message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional test details")
    error: Optional[str] = Field(None, description="Error message if test failed")
    tested_at: datetime = Field(..., description="Test timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "connection_id": "123e4567-e89b-12d3-a456-426614174000",
                "success": True,
                "status": "healthy",
                "message": "Successfully connected to gpt-4",
                "details": {
                    "model": "gpt-4",
                    "endpoint": "https://api.openai.com/v1",
                    "docling_api_version": "v1"
                },
                "tested_at": "2026-01-13T01:00:00"
            }
        }


class ConnectionTypeInfo(BaseModel):
    """Connection type metadata."""
    type: str = Field(..., description="Connection type identifier")
    display_name: str = Field(..., description="Human-readable name")
    description: str = Field(..., description="Description of what this type does")
    config_schema: Dict[str, Any] = Field(..., description="JSON schema for configuration")

    class Config:
        json_schema_extra = {
            "example": {
                "type": "extraction",
                "display_name": "Document Service",
                "description": "Connect to document extraction services",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "service_url": {"type": "string"},
                        "engine_type": {"type": "string"}
                    },
                    "required": ["service_url"]
                }
            }
        }


class ConnectionTypesResponse(BaseModel):
    """List of available connection types."""
    types: List[ConnectionTypeInfo] = Field(..., description="Available connection types")


# =========================================================================
# ORGANIZATION MODELS
# =========================================================================

class OrganizationResponse(BaseModel):
    """Organization details response."""
    id: str = Field(..., description="Organization UUID")
    name: str = Field(..., description="Organization name")
    display_name: str = Field(..., description="Display name")
    slug: str = Field(..., description="URL-friendly slug")
    is_active: bool = Field(..., description="Whether organization is active")
    settings: Dict[str, Any] = Field(default_factory=dict, description="Organization settings")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "Acme Corporation",
                "display_name": "Acme Corp",
                "slug": "acme-corp",
                "is_active": True,
                "settings": {},
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-12T15:30:00"
            }
        }


class OrganizationUpdateRequest(BaseModel):
    """Request to update organization details."""
    display_name: Optional[str] = Field(None, min_length=1, max_length=255, description="Display name")
    slug: Optional[str] = Field(None, min_length=2, max_length=100, pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$', description="URL-friendly slug (lowercase letters, numbers, hyphens)")

    class Config:
        json_schema_extra = {
            "example": {
                "display_name": "Acme Corporation Ltd.",
                "slug": "acme-corp"
            }
        }


class OrganizationSettingsResponse(BaseModel):
    """Organization settings response."""
    settings: Dict[str, Any] = Field(..., description="Organization settings")

    class Config:
        json_schema_extra = {
            "example": {
                "settings": {
                    "max_file_size_mb": 100,
                    "allowed_formats": ["pdf", "docx", "pptx", "txt"]
                }
            }
        }


class OrganizationSettingsUpdateRequest(BaseModel):
    """Request to update organization settings."""
    settings: Dict[str, Any] = Field(..., description="Settings to update (merged with existing)")

    class Config:
        json_schema_extra = {
            "example": {
                "settings": {
                    "auto_optimize": True,
                    "max_file_size_mb": 200
                }
            }
        }


# =========================================================================
# USER MANAGEMENT MODELS
# =========================================================================

class UserResponse(BaseModel):
    """User details response."""
    id: str = Field(..., description="User UUID")
    email: str = Field(..., description="Email address")
    username: str = Field(..., description="Username")
    full_name: Optional[str] = Field(None, description="Full name")
    role: str = Field(..., description="Role (org_admin, member, viewer)")
    is_active: bool = Field(..., description="Whether user is active")
    is_verified: bool = Field(..., description="Whether email is verified")
    created_at: datetime = Field(..., description="Creation timestamp")
    last_login_at: Optional[datetime] = Field(None, description="Last login timestamp")
    organization_id: Optional[str] = Field(None, description="Organization UUID (included in system-wide listings)")
    organization_name: Optional[str] = Field(None, description="Organization name (included in system-wide listings)")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "email": "user@example.com",
                "username": "johndoe",
                "full_name": "John Doe",
                "role": "member",
                "is_active": True,
                "is_verified": True,
                "created_at": "2024-01-01T00:00:00",
                "last_login_at": "2024-01-12T15:30:00"
            }
        }


class UserInviteResponse(BaseModel):
    """Response from user invitation."""
    message: str = Field(..., description="Status message")
    user: UserResponse = Field(..., description="Created user details")
    temporary_password: Optional[str] = Field(None, description="Temporary password (only when send_email=False)")


class UserInviteRequest(BaseModel):
    """Request to invite a new user to the organization."""
    email: EmailStr = Field(..., description="Email address")
    username: str = Field(..., min_length=3, max_length=100, description="Username")
    full_name: Optional[str] = Field(None, max_length=255, description="Full name")
    role: str = Field(default="member", description="Role (org_admin, member, viewer)")
    send_email: bool = Field(default=False, description="Send invitation email to user")

    class Config:
        json_schema_extra = {
            "example": {
                "email": "newuser@example.com",
                "username": "newuser",
                "full_name": "New User",
                "role": "member",
                "send_email": True
            }
        }


class UserUpdateRequest(BaseModel):
    """Request to update user details."""
    full_name: Optional[str] = Field(None, max_length=255, description="Full name")
    role: Optional[str] = Field(None, description="Role (org_admin, member, viewer)")

    class Config:
        json_schema_extra = {
            "example": {
                "full_name": "John Smith",
                "role": "org_admin"
            }
        }


class UserListResponse(BaseModel):
    """List of users response."""
    users: List[UserResponse] = Field(..., description="List of users")
    total: int = Field(..., description="Total number of users")

    class Config:
        json_schema_extra = {
            "example": {
                "users": [
                    {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "email": "user@example.com",
                        "username": "johndoe",
                        "full_name": "John Doe",
                        "role": "member",
                        "is_active": True,
                        "is_verified": True,
                        "created_at": "2024-01-01T00:00:00",
                        "last_login_at": "2024-01-12T15:30:00"
                    }
                ],
                "total": 1
            }
        }


# =========================================================================
# API KEY MODELS
# =========================================================================

class ApiKeyResponse(BaseModel):
    """API key details response."""
    id: str = Field(..., description="API key UUID")
    name: str = Field(..., description="Key name/description")
    prefix: str = Field(..., description="Key prefix for identification")
    is_active: bool = Field(..., description="Whether key is active")
    created_at: datetime = Field(..., description="Creation timestamp")
    last_used_at: Optional[datetime] = Field(None, description="Last used timestamp")
    expires_at: Optional[datetime] = Field(None, description="Expiration timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "Production API Key",
                "prefix": "cur_1a2b3c4d",
                "is_active": True,
                "created_at": "2024-01-01T00:00:00",
                "last_used_at": "2024-01-12T15:30:00",
                "expires_at": None
            }
        }


class ApiKeyCreateRequest(BaseModel):
    """Request to create a new API key."""
    name: str = Field(..., min_length=1, max_length=255, description="Key name/description")
    expires_days: Optional[int] = Field(None, ge=1, le=365, description="Expiration in days (optional)")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Production API Key",
                "expires_days": 90
            }
        }


class ApiKeyCreateResponse(BaseModel):
    """API key creation response with full key (shown only once)."""
    id: str = Field(..., description="API key UUID")
    name: str = Field(..., description="Key name/description")
    key: str = Field(..., description="Full API key (SAVE THIS - shown only once!)")
    prefix: str = Field(..., description="Key prefix for identification")
    created_at: datetime = Field(..., description="Creation timestamp")
    expires_at: Optional[datetime] = Field(None, description="Expiration timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "Production API Key",
                "key": "cur_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p",
                "prefix": "cur_1a2b3c4d",
                "created_at": "2024-01-01T00:00:00",
                "expires_at": "2024-04-01T00:00:00"
            }
        }


class ApiKeyUpdateRequest(BaseModel):
    """Request to update API key details."""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Key name/description")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Updated Production Key"
            }
        }


class ApiKeyListResponse(BaseModel):
    """List of API keys response."""
    keys: List[ApiKeyResponse] = Field(..., description="List of API keys")
    total: int = Field(..., description="Total number of keys")

    class Config:
        json_schema_extra = {
            "example": {
                "keys": [
                    {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "name": "Production API Key",
                        "prefix": "cur_1a2b3c4d",
                        "is_active": True,
                        "created_at": "2024-01-01T00:00:00",
                        "last_used_at": "2024-01-12T15:30:00",
                        "expires_at": None
                    }
                ],
                "total": 1
            }
        }


# =========================================================================
# SERVICE MODELS (System-Scoped Infrastructure)
# =========================================================================


class ServiceResponse(BaseModel):
    """System service details response."""
    id: str = Field(..., description="Service UUID")
    name: str = Field(..., description="Service name (unique)")
    service_type: str = Field(..., description="Service type (llm, extraction, browser)")
    description: Optional[str] = Field(None, description="Service description")
    config: Dict[str, Any] = Field(default_factory=dict, description="Service configuration")
    is_active: bool = Field(..., description="Whether service is active")
    last_tested_at: Optional[datetime] = Field(None, description="Last test timestamp")
    test_status: Optional[str] = Field(None, description="Test status (healthy, unhealthy, not_tested)")
    test_result: Optional[Dict[str, Any]] = Field(None, description="Detailed test results")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "llm",
                "service_type": "llm",
                "description": "Primary LLM service",
                "config": {
                    "api_key": "***REDACTED***",
                    "model": "gpt-4",
                    "base_url": "https://api.openai.com/v1"
                },
                "is_active": True,
                "last_tested_at": "2026-01-13T01:00:00",
                "test_status": "healthy",
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-13T01:00:00"
            }
        }


class ServiceCreateRequest(BaseModel):
    """Request to create a new system service."""
    name: str = Field(..., min_length=1, max_length=100, description="Service name (unique)")
    service_type: str = Field(..., description="Service type (llm, extraction, browser)")
    description: Optional[str] = Field(None, max_length=500, description="Service description")
    config: Dict[str, Any] = Field(default_factory=dict, description="Type-specific configuration")
    is_active: bool = Field(default=True, description="Whether service is active")


class ServiceUpdateRequest(BaseModel):
    """Request to update a system service."""
    description: Optional[str] = Field(None, max_length=500, description="Service description")
    config: Optional[Dict[str, Any]] = Field(None, description="Type-specific configuration")
    is_active: Optional[bool] = Field(None, description="Whether service is active")


class ServiceListResponse(BaseModel):
    """List of services response."""
    services: List[ServiceResponse] = Field(..., description="List of services")
    total: int = Field(..., description="Total number of services")


# =========================================================================
# ORGANIZATION CONNECTION MODELS (Per-Org Enablement)
# =========================================================================


class OrganizationConnectionResponse(BaseModel):
    """Organization-connection enablement details."""
    id: str = Field(..., description="Enablement UUID")
    organization_id: str = Field(..., description="Organization UUID")
    organization_name: Optional[str] = Field(None, description="Organization name")
    connection_id: str = Field(..., description="Connection UUID")
    connection_name: Optional[str] = Field(None, description="Connection name")
    connection_type: Optional[str] = Field(None, description="Connection type")
    is_enabled: bool = Field(..., description="Whether connection is enabled for this org")
    enabled_at: Optional[datetime] = Field(None, description="When connection was enabled")
    config_overrides: Dict[str, Any] = Field(default_factory=dict, description="Org-specific config overrides")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class OrganizationConnectionEnableRequest(BaseModel):
    """Request to enable a connection for an organization."""
    config_overrides: Dict[str, Any] = Field(default_factory=dict, description="Org-specific config overrides")


class OrganizationConnectionListResponse(BaseModel):
    """List of organization-connection enablements."""
    connections: List[OrganizationConnectionResponse] = Field(..., description="List of enablements")
    total: int = Field(..., description="Total number of enablements")


# =========================================================================
# SERVICE ACCOUNT MODELS
# =========================================================================


class ServiceAccountResponse(BaseModel):
    """Service account details response."""
    id: str = Field(..., description="Service account UUID")
    name: str = Field(..., description="Service account name")
    description: Optional[str] = Field(None, description="Description")
    organization_id: str = Field(..., description="Organization UUID")
    organization_name: Optional[str] = Field(None, description="Organization name")
    role: str = Field(..., description="Role (member, viewer)")
    is_active: bool = Field(..., description="Whether account is active")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    last_used_at: Optional[datetime] = Field(None, description="Last API usage timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "name": "CI Pipeline",
                "description": "Automated CI/CD pipeline",
                "organization_id": "987fcdeb-51a2-43f7-8b6a-123456789abc",
                "organization_name": "Acme Corp",
                "role": "member",
                "is_active": True,
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-12T15:30:00",
                "last_used_at": "2024-01-12T16:00:00"
            }
        }


class ServiceAccountCreateRequest(BaseModel):
    """Request to create a new service account."""
    name: str = Field(..., min_length=1, max_length=255, description="Service account name")
    description: Optional[str] = Field(None, max_length=500, description="Description")
    role: str = Field(default="member", description="Role (member, viewer)")


class ServiceAccountUpdateRequest(BaseModel):
    """Request to update a service account."""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Service account name")
    description: Optional[str] = Field(None, max_length=500, description="Description")
    role: Optional[str] = Field(None, description="Role (member, viewer)")
    is_active: Optional[bool] = Field(None, description="Whether account is active")


class ServiceAccountListResponse(BaseModel):
    """List of service accounts response."""
    service_accounts: List[ServiceAccountResponse] = Field(..., description="List of service accounts")
    total: int = Field(..., description="Total number of service accounts")


class ServiceAccountApiKeyCreateResponse(BaseModel):
    """Response when creating an API key for a service account."""
    id: str = Field(..., description="API key UUID")
    name: str = Field(..., description="Key name")
    key: str = Field(..., description="Full API key (SAVE THIS - shown only once!)")
    prefix: str = Field(..., description="Key prefix for identification")
    service_account_id: str = Field(..., description="Service account UUID")
    service_account_name: str = Field(..., description="Service account name")
    created_at: datetime = Field(..., description="Creation timestamp")
    expires_at: Optional[datetime] = Field(None, description="Expiration timestamp")


# =========================================================================
# EXTENDED ORGANIZATION MODELS (Admin Access)
# =========================================================================


class OrganizationCreateRequest(BaseModel):
    """Request to create a new organization (admin only)."""
    name: str = Field(..., min_length=1, max_length=255, description="Organization name (unique)")
    display_name: str = Field(..., min_length=1, max_length=255, description="Display name")
    slug: str = Field(..., min_length=2, max_length=100, pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$', description="URL-friendly slug")
    settings: Dict[str, Any] = Field(default_factory=dict, description="Initial settings")


class OrganizationAdminResponse(BaseModel):
    """Organization details for admin view (includes extra metadata)."""
    id: str = Field(..., description="Organization UUID")
    name: str = Field(..., description="Organization name")
    display_name: str = Field(..., description="Display name")
    slug: str = Field(..., description="URL-friendly slug")
    is_active: bool = Field(..., description="Whether organization is active")
    settings: Dict[str, Any] = Field(default_factory=dict, description="Organization settings")
    user_count: int = Field(default=0, description="Number of users")
    enabled_connections_count: int = Field(default=0, description="Number of enabled connections")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class OrganizationAdminListResponse(BaseModel):
    """List of organizations for admin view."""
    organizations: List[OrganizationAdminResponse] = Field(..., description="List of organizations")
    total: int = Field(..., description="Total number of organizations")


# =========================================================================
# EXTENDED USER MODELS (Admin/Cross-Org Access)
# =========================================================================


class UserAdminResponse(BaseModel):
    """User details for admin view (includes organization info)."""
    id: str = Field(..., description="User UUID")
    email: str = Field(..., description="Email address")
    username: str = Field(..., description="Username")
    full_name: Optional[str] = Field(None, description="Full name")
    role: str = Field(..., description="Role (admin, org_admin, member, viewer)")
    organization_id: Optional[str] = Field(None, description="Organization UUID (null for admins)")
    organization_name: Optional[str] = Field(None, description="Organization name")
    is_active: bool = Field(..., description="Whether user is active")
    is_verified: bool = Field(..., description="Whether email is verified")
    created_at: datetime = Field(..., description="Creation timestamp")
    last_login_at: Optional[datetime] = Field(None, description="Last login timestamp")


class UserAdminListResponse(BaseModel):
    """List of users for admin view (cross-org)."""
    users: List[UserAdminResponse] = Field(..., description="List of users")
    total: int = Field(..., description="Total number of users")


class UserAdminCreateRequest(BaseModel):
    """Request to create a user (admin - can specify organization)."""
    email: EmailStr = Field(..., description="Email address")
    username: str = Field(..., min_length=3, max_length=100, description="Username")
    full_name: Optional[str] = Field(None, max_length=255, description="Full name")
    role: str = Field(default="member", description="Role (admin, org_admin, member, viewer)")
    organization_id: Optional[str] = Field(None, description="Organization UUID (required for non-admin users)")
    send_email: bool = Field(default=False, description="Send invitation email")


# =========================================================================
# ROLE MODELS
# =========================================================================


class RoleResponse(BaseModel):
    """Role details response."""
    id: int = Field(..., description="Role ID")
    name: str = Field(..., description="Role identifier (admin, org_admin, member, viewer)")
    display_name: str = Field(..., description="Human-readable role name")
    description: Optional[str] = Field(None, description="Role description")
    is_system_role: bool = Field(..., description="True for system-wide roles (admin)")
    can_manage_users: bool = Field(..., description="Permission to manage users")
    can_manage_org: bool = Field(..., description="Permission to manage organization settings")
    can_manage_system: bool = Field(..., description="Permission to manage system settings")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "name": "org_admin",
                "display_name": "Org Admin",
                "description": "Organization administrator",
                "is_system_role": False,
                "can_manage_users": True,
                "can_manage_org": True,
                "can_manage_system": False
            }
        }


class RoleListResponse(BaseModel):
    """List of roles response."""
    roles: List[RoleResponse] = Field(..., description="List of available roles")
    total: int = Field(..., description="Total number of roles")


# =========================================================================
# DATA CONNECTION MODELS (Per-Org Data Source Enablement)
# =========================================================================


class DataConnectionCatalogEntry(BaseModel):
    """Data connection source type with per-org enablement counts."""
    source_type: str = Field(..., description="Source type identifier (e.g., sam_gov, sharepoint)")
    display_name: str = Field(..., description="Human-readable name")
    description: Optional[str] = Field(None, description="Description of the data connection")
    capabilities: Optional[List[str]] = Field(None, description="What this source can do")
    is_globally_active: bool = Field(default=True, description="Whether source is active in baseline YAML")
    enabled_org_count: int = Field(default=0, description="Number of orgs with this source enabled")
    total_org_count: int = Field(default=0, description="Total number of active organizations")


class DataConnectionCatalogResponse(BaseModel):
    """Catalog of all data connections with per-org enablement counts."""
    data_connections: List[DataConnectionCatalogEntry] = Field(..., description="List of data connections")
    total: int = Field(..., description="Total number of data connections")


class DataConnectionStatus(BaseModel):
    """Data connection status for a specific organization."""
    source_type: str = Field(..., description="Source type identifier")
    display_name: str = Field(..., description="Human-readable name")
    description: Optional[str] = Field(None, description="Description of the data connection")
    is_enabled: bool = Field(..., description="Whether source is enabled for this org")
    capabilities: Optional[List[str]] = Field(None, description="What this source can do")
    updated_at: Optional[datetime] = Field(None, description="Last override update timestamp")


class DataConnectionOrgStatusResponse(BaseModel):
    """Data connection statuses for a specific organization."""
    data_connections: List[DataConnectionStatus] = Field(..., description="List of data connection statuses")
    organization_id: str = Field(..., description="Organization UUID")
    organization_name: Optional[str] = Field(None, description="Organization name")


class DataConnectionToggleRequest(BaseModel):
    """Request to enable or disable a data connection for an organization."""
    is_enabled: bool = Field(..., description="Whether to enable or disable the connection")


__all__ = [
    # Connection models
    "ConnectionResponse",
    "ConnectionCreateRequest",
    "ConnectionUpdateRequest",
    "ConnectionListResponse",
    "ConnectionTestResponse",
    "ConnectionTypeInfo",
    "ConnectionTypesResponse",
    # Organization models
    "OrganizationResponse",
    "OrganizationUpdateRequest",
    "OrganizationSettingsResponse",
    "OrganizationSettingsUpdateRequest",
    "OrganizationCreateRequest",
    "OrganizationAdminResponse",
    "OrganizationAdminListResponse",
    # User management models
    "UserResponse",
    "UserInviteRequest",
    "UserInviteResponse",
    "UserUpdateRequest",
    "UserListResponse",
    "UserAdminResponse",
    "UserAdminListResponse",
    "UserAdminCreateRequest",
    # API key models
    "ApiKeyResponse",
    "ApiKeyCreateRequest",
    "ApiKeyCreateResponse",
    "ApiKeyUpdateRequest",
    "ApiKeyListResponse",
    # Service models
    "ServiceResponse",
    "ServiceCreateRequest",
    "ServiceUpdateRequest",
    "ServiceListResponse",
    # Organization Connection models
    "OrganizationConnectionResponse",
    "OrganizationConnectionEnableRequest",
    "OrganizationConnectionListResponse",
    # Service Account models
    "ServiceAccountResponse",
    "ServiceAccountCreateRequest",
    "ServiceAccountUpdateRequest",
    "ServiceAccountListResponse",
    "ServiceAccountApiKeyCreateResponse",
    # Role models
    "RoleResponse",
    "RoleListResponse",
    # Data Connection models
    "DataConnectionCatalogEntry",
    "DataConnectionCatalogResponse",
    "DataConnectionStatus",
    "DataConnectionOrgStatusResponse",
    "DataConnectionToggleRequest",
    # System/health models (re-exported from app.core.models)
    "HealthStatus",
    "LLMConnectionStatus",
]
