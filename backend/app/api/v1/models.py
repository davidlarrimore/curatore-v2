"""
Versioned models for API v1.

Provides a stable import surface and v1-specific request schemas that
map to internal domain models, allowing the frontend's v1 payload shape.
"""

from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr
from pydantic import AliasChoices
from pydantic import model_validator
from pydantic import AliasChoices

# Shared domain models
from ...models import (
    FileUploadResponse,
    ConversionResult,
    LLMEvaluation,
    ProcessingStatus,
    DocumentEditRequest,
    ProcessingOptions,
    QualityThresholds,
    BulkDownloadRequest,
    ZipArchiveInfo,
    HealthStatus,
    LLMConnectionStatus,
)


# =========================================================================
# CONNECTION MODELS
# =========================================================================

class ConnectionResponse(BaseModel):
    """Connection details response."""
    id: str = Field(..., description="Connection UUID")
    organization_id: str = Field(..., description="Organization UUID")
    name: str = Field(..., description="Connection name")
    description: Optional[str] = Field(None, description="Connection description")
    connection_type: str = Field(..., description="Connection type (sharepoint, llm, extraction)")
    config: Dict[str, Any] = Field(..., description="Connection configuration")
    is_active: bool = Field(..., description="Whether connection is active")
    is_default: bool = Field(..., description="Whether this is the default connection for its type")
    last_tested_at: Optional[datetime] = Field(None, description="Last test timestamp")
    test_status: Optional[str] = Field(None, description="Test status (healthy, unhealthy, not_tested)")
    test_result: Optional[Dict[str, Any]] = Field(None, description="Detailed test results")
    scope: str = Field(..., description="Connection scope (organization, user)")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "organization_id": "04ace7c6-2043-4935-b074-ec0a567d1fd2",
                "name": "Production LLM",
                "description": "Main LLM for document processing",
                "connection_type": "llm",
                "config": {
                    "api_key": "***REDACTED***",
                    "model": "gpt-4",
                    "base_url": "https://api.openai.com/v1"
                },
                "is_active": True,
                "is_default": True,
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
    connection_type: str = Field(..., description="Connection type (sharepoint, llm, extraction)")
    config: Dict[str, Any] = Field(..., description="Type-specific configuration")
    is_default: bool = Field(default=False, description="Set as default for this type")
    scope: str = Field(default="organization", description="Connection scope (organization, user)")
    test_on_save: bool = Field(default=True, description="Test connection after creation")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Production LLM",
                "description": "Main LLM for document processing",
                "connection_type": "llm",
                "config": {
                    "api_key": "sk-...",
                    "model": "gpt-4",
                    "base_url": "https://api.openai.com/v1"
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
                        "name": "Production LLM",
                        "connection_type": "llm",
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
                    "endpoint": "https://api.openai.com/v1"
                },
                "tested_at": "2026-01-13T01:00:00"
            }
        }


class ConnectionTypeInfo(BaseModel):
    """Connection type metadata."""
    type: str = Field(..., description="Connection type identifier")
    display_name: str = Field(..., description="Human-readable name")
    description: str = Field(..., description="Description of what this type does")
    schema: Dict[str, Any] = Field(..., description="JSON schema for configuration")

    class Config:
        json_schema_extra = {
            "example": {
                "type": "llm",
                "display_name": "LLM API",
                "description": "Connect to OpenAI-compatible LLM APIs",
                "schema": {
                    "type": "object",
                    "properties": {
                        "api_key": {"type": "string", "writeOnly": True},
                        "model": {"type": "string"},
                        "base_url": {"type": "string"}
                    },
                    "required": ["api_key", "model", "base_url"]
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
                "settings": {
                    "quality_thresholds": {
                        "conversion": 70,
                        "clarity": 7,
                        "completeness": 7,
                        "relevance": 7,
                        "markdown": 7
                    },
                    "auto_optimize": False
                },
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-12T15:30:00"
            }
        }


class OrganizationUpdateRequest(BaseModel):
    """Request to update organization details."""
    display_name: Optional[str] = Field(None, min_length=1, max_length=255, description="Display name")

    class Config:
        json_schema_extra = {
            "example": {
                "display_name": "Acme Corporation Ltd."
            }
        }


class OrganizationSettingsResponse(BaseModel):
    """Organization settings response."""
    settings: Dict[str, Any] = Field(..., description="Organization settings")

    class Config:
        json_schema_extra = {
            "example": {
                "settings": {
                    "quality_thresholds": {
                        "conversion": 70,
                        "clarity": 7,
                        "completeness": 7,
                        "relevance": 7,
                        "markdown": 7
                    },
                    "auto_optimize": False,
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


class UserInviteRequest(BaseModel):
    """Request to invite a new user to the organization."""
    email: EmailStr = Field(..., description="Email address")
    username: str = Field(..., min_length=3, max_length=100, description="Username")
    full_name: Optional[str] = Field(None, max_length=255, description="Full name")
    role: str = Field(default="member", description="Role (org_admin, member, viewer)")

    class Config:
        json_schema_extra = {
            "example": {
                "email": "newuser@example.com",
                "username": "newuser",
                "full_name": "New User",
                "role": "member"
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


class V1QualityThresholds(BaseModel):
    """Frontend v1-friendly thresholds payload shape."""
    conversion: int = Field(default=70, ge=0, le=100)
    clarity: int = Field(default=7, ge=1, le=10)
    completeness: int = Field(default=7, ge=1, le=10)
    relevance: int = Field(default=7, ge=1, le=10)
    markdown: int = Field(default=7, ge=1, le=10)

    def to_domain(self) -> QualityThresholds:
        return QualityThresholds(
            conversion_quality=self.conversion,
            clarity_score=self.clarity,
            completeness_score=self.completeness,
            relevance_score=self.relevance,
            markdown_quality=self.markdown,
        )


class V1ProcessingOptions(BaseModel):
    """
    Frontend v1-friendly processing options.

    Maps to internal ProcessingOptions. Only common fields are exposed.
    """

    auto_optimize: bool = Field(default=True, description="Optimize for vector DB")
    quality_thresholds: Optional[V1QualityThresholds] = None

    def to_domain(self) -> ProcessingOptions:
        return ProcessingOptions(
            auto_improve=self.auto_optimize,
            vector_optimize=self.auto_optimize,
            quality_thresholds=self.quality_thresholds.to_domain() if self.quality_thresholds else None,
        )


class V1BatchProcessingRequest(BaseModel):
    document_ids: List[str]
    options: Optional[V1ProcessingOptions] = None


class SharePointInventoryRequest(BaseModel):
    folder_url: str = Field(..., description="SharePoint folder URL or share link")
    recursive: bool = Field(default=False, description="Traverse subfolders")
    include_folders: bool = Field(default=False, description="Include folders in results")
    page_size: int = Field(default=200, ge=1, le=2000, description="Items per page")
    max_items: Optional[int] = Field(default=None, ge=1, description="Max items to return")


class SharePointInventoryItem(BaseModel):
    index: int
    name: str
    type: str
    folder: str
    extension: str
    size: Optional[int] = None
    created: Optional[str] = None
    modified: Optional[str] = None
    mime: Optional[str] = None
    id: str
    web_url: Optional[str] = None


class SharePointInventoryFolder(BaseModel):
    name: str
    id: str
    web_url: Optional[str] = None
    drive_id: str


class SharePointInventoryResponse(BaseModel):
    folder: SharePointInventoryFolder
    items: List[SharePointInventoryItem]


class SharePointDownloadRequest(BaseModel):
    folder_url: str = Field(..., description="SharePoint folder URL or share link")
    indices: Optional[List[int]] = Field(default=None, description="Indices from inventory")
    download_all: bool = Field(default=False, description="Download all files")
    recursive: bool = Field(default=False, description="Traverse subfolders")
    page_size: int = Field(default=200, ge=1, le=2000, description="Items per page")
    max_items: Optional[int] = Field(default=None, ge=1, description="Max items to scan")
    preserve_folders: bool = Field(default=True, description="Preserve subfolder structure")


class SharePointDownloadItem(BaseModel):
    index: int
    name: str
    folder: str
    path: str
    size: Optional[int] = None


class SharePointDownloadResponse(BaseModel):
    downloaded: List[SharePointDownloadItem]
    skipped: List[SharePointDownloadItem]
    batch_dir: str


__all__ = [
    # Re-exports
    "FileUploadResponse",
    "DocumentEditRequest",
    "BulkDownloadRequest",
    "ZipArchiveInfo",
    "HealthStatus",
    "LLMConnectionStatus",
    # V1 request wrappers
    "V1ProcessingOptions",
    "V1QualityThresholds",
    "V1BatchProcessingRequest",
    # V1 response models
    "V1ProcessingResult",
    "V1BatchProcessingResult",
    # Domain mapping helper types
    "ProcessingOptions",
    # Connections
    "ConnectionResponse",
    "ConnectionCreateRequest",
    "ConnectionUpdateRequest",
    "ConnectionListResponse",
    "ConnectionTestResponse",
    "ConnectionTypeInfo",
    "ConnectionTypesResponse",
    # Organizations
    "OrganizationResponse",
    "OrganizationUpdateRequest",
    "OrganizationSettingsResponse",
    "OrganizationSettingsUpdateRequest",
    # Users
    "UserResponse",
    "UserInviteRequest",
    "UserUpdateRequest",
    "UserListResponse",
    # API Keys
    "ApiKeyResponse",
    "ApiKeyCreateRequest",
    "ApiKeyCreateResponse",
    "ApiKeyUpdateRequest",
    "ApiKeyListResponse",
    # SharePoint
    "SharePointInventoryRequest",
    "SharePointInventoryResponse",
    "SharePointDownloadRequest",
    "SharePointDownloadResponse",
]


class V1ProcessingResult(BaseModel):
    document_id: str
    filename: str
    status: ProcessingStatus
    success: bool
    message: Optional[str] = None
    original_path: Optional[str] = None
    markdown_path: Optional[str] = None
    conversion_result: ConversionResult
    llm_evaluation: Optional[LLMEvaluation] = None
    document_summary: Optional[str] = None
    conversion_score: int
    pass_all_thresholds: bool = Field(validation_alias=AliasChoices('pass_all_thresholds', 'is_rag_ready'))
    vector_optimized: bool
    processing_time: float
    processed_at: Optional[datetime] = None
    thresholds_used: Optional[QualityThresholds] = None

    class Config:
        from_attributes = True

    @model_validator(mode="before")
    @classmethod
    def ensure_fields(cls, v):
        try:
            # When v is a domain ProcessingResult instance
            if hasattr(v, "conversion_result"):
                cr = getattr(v, "conversion_result", None)
                # Coerce Path fields to strings for v1 API shape
                original_path = getattr(v, "original_path", None)
                if isinstance(original_path, Path):
                    original_path = str(original_path)
                markdown_path = getattr(v, "markdown_path", None)
                if isinstance(markdown_path, Path):
                    markdown_path = str(markdown_path)
                return {
                    "document_id": getattr(v, "document_id", None),
                    "filename": getattr(v, "filename", None),
                    "status": getattr(v, "status", None),
                    "success": getattr(v, "success", True if getattr(v, "status", None) == ProcessingStatus.COMPLETED else False),
                    "message": getattr(v, "message", getattr(v, "error_message", None)),
                    "original_path": original_path,
                    "markdown_path": markdown_path,
                    "conversion_result": cr,
                    "llm_evaluation": getattr(v, "llm_evaluation", None),
                    "document_summary": getattr(v, "document_summary", None),
                    "conversion_score": getattr(cr, "conversion_score", None) if cr else None,
                    "pass_all_thresholds": getattr(v, "is_rag_ready", getattr(v, "pass_all_thresholds", None)),
                    "vector_optimized": getattr(v, "vector_optimized", False),
                    "processing_time": getattr(v, "processing_time", 0.0),
                    "processed_at": getattr(v, "processed_at", None),
                    "thresholds_used": getattr(v, "thresholds_used", None),
                }
        except Exception:
            return v
        return v


class V1BatchProcessingResult(BaseModel):
    batch_id: str
    total_files: int
    successful: int
    failed: int
    rag_ready: int
    results: List[V1ProcessingResult]
    processing_time: float
    started_at: datetime
    completed_at: datetime
