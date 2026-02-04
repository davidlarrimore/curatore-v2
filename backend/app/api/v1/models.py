"""
Versioned models for API v1.

Provides a stable import surface and v1-specific request schemas that
map to internal domain models, allowing the frontend's v1 payload shape.
"""

from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime
from uuid import UUID
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
    connection_type: str = Field(..., description="Connection type (microsoft_graph, llm, extraction)")
    config: Dict[str, Any] = Field(..., description="Connection configuration")
    is_active: bool = Field(..., description="Whether connection is active")
    is_default: bool = Field(..., description="Whether this is the default connection for its type")
    is_managed: bool = Field(..., description="Whether connection is managed by environment variables")
    managed_by: Optional[str] = Field(None, description="Description of what manages this connection")
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
                "type": "llm",
                "display_name": "LLM API",
                "description": "Connect to OpenAI-compatible LLM APIs",
                "config_schema": {
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


# V1QualityThresholds removed - feature deprecated


class V1ProcessingOptions(BaseModel):
    """
    Frontend v1-friendly processing options.

    Maps to internal ProcessingOptions. Only common fields are exposed.
    """

    extraction_engine: Optional[str] = Field(
        default="docling-external",
        description="Extraction engine to use (e.g., 'docling-external', 'extraction-service', 'docling')",
    )

    def to_domain(self) -> ProcessingOptions:
        return ProcessingOptions(
            extraction_engine=self.extraction_engine,
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
    created_by: Optional[str] = None
    last_modified_by: Optional[str] = None
    mime: Optional[str] = None
    file_type: Optional[str] = None
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
    processing_time: float
    processed_at: Optional[datetime] = None

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
                    "processing_time": getattr(v, "processing_time", 0.0),
                    "processed_at": getattr(v, "processed_at", None),
                }
        except Exception:
            return v
        return v


class V1BatchProcessingResult(BaseModel):
    batch_id: str
    total_files: int
    successful: int
    failed: int
    results: List[V1ProcessingResult]
    processing_time: float
    started_at: datetime
    completed_at: datetime


# =========================================================================
# OBJECT STORAGE MODELS
# =========================================================================

class PresignedUploadRequest(BaseModel):
    """Request for presigned upload URL."""
    filename: str = Field(..., min_length=1, max_length=500, description="Original filename")
    content_type: str = Field(default="application/octet-stream", description="MIME type of the file")
    file_size: Optional[int] = Field(None, ge=0, description="File size in bytes (optional)")

    class Config:
        json_schema_extra = {
            "example": {
                "filename": "report_q4_2025.pdf",
                "content_type": "application/pdf",
                "file_size": 1048576
            }
        }


class PresignedUploadResponse(BaseModel):
    """Response with presigned upload URL."""
    document_id: str = Field(..., description="Generated document ID")
    artifact_id: str = Field(..., description="Artifact UUID for tracking")
    upload_url: str = Field(..., description="Presigned URL for direct upload to storage")
    expires_in: int = Field(..., description="URL expiration time in seconds")
    bucket: str = Field(..., description="Target storage bucket")
    object_key: str = Field(..., description="Object key/path in bucket")

    class Config:
        json_schema_extra = {
            "example": {
                "document_id": "doc_abc123",
                "artifact_id": "123e4567-e89b-12d3-a456-426614174000",
                "upload_url": "https://storage.example.com/curatore-uploads/...",
                "expires_in": 3600,
                "bucket": "curatore-uploads",
                "object_key": "org-uuid/doc-uuid/uploaded/report_q4_2025.pdf"
            }
        }


class ConfirmUploadRequest(BaseModel):
    """Request to confirm upload completion."""
    artifact_id: str = Field(..., description="Artifact UUID from presigned response")
    document_id: str = Field(..., description="Document ID from presigned response")

    class Config:
        json_schema_extra = {
            "example": {
                "artifact_id": "123e4567-e89b-12d3-a456-426614174000",
                "document_id": "doc_abc123"
            }
        }


class ConfirmUploadResponse(BaseModel):
    """Response confirming upload."""
    document_id: str = Field(..., description="Document ID")
    artifact_id: str = Field(..., description="Artifact UUID")
    status: str = Field(..., description="Artifact status (available)")
    filename: str = Field(..., description="Original filename")
    file_size: Optional[int] = Field(None, description="Actual file size in bytes")
    etag: Optional[str] = Field(None, description="Object ETag from storage")

    class Config:
        json_schema_extra = {
            "example": {
                "document_id": "doc_abc123",
                "artifact_id": "123e4567-e89b-12d3-a456-426614174000",
                "status": "available",
                "filename": "report_q4_2025.pdf",
                "file_size": 1048576,
                "etag": "d41d8cd98f00b204e9800998ecf8427e"
            }
        }


class PresignedDownloadResponse(BaseModel):
    """Response with presigned download URL."""
    document_id: str = Field(..., description="Document ID")
    artifact_id: str = Field(..., description="Artifact UUID")
    download_url: str = Field(..., description="Presigned URL for direct download")
    filename: str = Field(..., description="Original filename")
    content_type: Optional[str] = Field(None, description="Content type")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    expires_in: int = Field(..., description="URL expiration time in seconds")

    class Config:
        json_schema_extra = {
            "example": {
                "document_id": "doc_abc123",
                "artifact_id": "123e4567-e89b-12d3-a456-426614174000",
                "download_url": "https://storage.example.com/curatore-processed/...",
                "filename": "report_q4_2025.md",
                "content_type": "text/markdown",
                "file_size": 52428,
                "expires_in": 3600
            }
        }


class StorageHealthResponse(BaseModel):
    """Object storage health status."""
    status: str = Field(..., description="Storage status (healthy, unhealthy, disabled)")
    enabled: bool = Field(..., description="Whether object storage is enabled")
    provider_connected: Optional[bool] = Field(None, description="Whether provider is connected")
    buckets: Optional[List[str]] = Field(None, description="Available buckets")
    error: Optional[str] = Field(None, description="Error message if unhealthy")

    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "enabled": True,
                "provider_connected": True,
                "buckets": ["curatore-uploads", "curatore-processed", "curatore-temp"],
                "error": None
            }
        }


class ArtifactResponse(BaseModel):
    """Artifact details response."""
    id: str = Field(..., description="Artifact UUID")
    organization_id: str = Field(..., description="Organization UUID")
    document_id: str = Field(..., description="Document ID")
    job_id: Optional[str] = Field(None, description="Associated job UUID")
    artifact_type: str = Field(..., description="Artifact type (uploaded, processed, temp)")
    bucket: str = Field(..., description="Storage bucket")
    object_key: str = Field(..., description="Object key/path")
    original_filename: str = Field(..., description="Original filename")
    content_type: Optional[str] = Field(None, description="MIME type")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    etag: Optional[str] = Field(None, description="Object ETag")
    status: str = Field(..., description="Status (pending, available, deleted)")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    expires_at: Optional[datetime] = Field(None, description="Expiration timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "organization_id": "04ace7c6-2043-4935-b074-ec0a567d1fd2",
                "document_id": "doc_abc123",
                "job_id": None,
                "artifact_type": "uploaded",
                "bucket": "curatore-uploads",
                "object_key": "org-uuid/doc-uuid/uploaded/report.pdf",
                "original_filename": "report.pdf",
                "content_type": "application/pdf",
                "file_size": 1048576,
                "etag": "d41d8cd98f00b204e9800998ecf8427e",
                "status": "available",
                "created_at": "2026-01-20T10:00:00",
                "updated_at": "2026-01-20T10:00:30",
                "expires_at": "2026-01-27T10:00:00"
            }
        }


class BulkDeleteArtifactsRequest(BaseModel):
    """Request to bulk delete artifacts."""
    artifact_ids: List[str] = Field(..., min_length=1, max_length=100, description="List of artifact UUIDs to delete (max 100)")

    class Config:
        json_schema_extra = {
            "example": {
                "artifact_ids": [
                    "123e4567-e89b-12d3-a456-426614174000",
                    "223e4567-e89b-12d3-a456-426614174001"
                ]
            }
        }


class BulkDeleteResultItem(BaseModel):
    """Result for a single artifact deletion."""
    artifact_id: str = Field(..., description="Artifact UUID")
    document_id: Optional[str] = Field(None, description="Associated document ID")
    success: bool = Field(..., description="Whether deletion succeeded")
    error: Optional[str] = Field(None, description="Error message if deletion failed")


class BulkDeleteArtifactsResponse(BaseModel):
    """Response from bulk artifact deletion."""
    total: int = Field(..., description="Total artifacts requested for deletion")
    succeeded: int = Field(..., description="Number of successfully deleted artifacts")
    failed: int = Field(..., description="Number of failed deletions")
    results: List[BulkDeleteResultItem] = Field(..., description="Detailed results for each artifact")

    class Config:
        json_schema_extra = {
            "example": {
                "total": 2,
                "succeeded": 1,
                "failed": 1,
                "results": [
                    {
                        "artifact_id": "123e4567-e89b-12d3-a456-426614174000",
                        "document_id": "doc_abc123",
                        "success": True,
                        "error": None
                    },
                    {
                        "artifact_id": "223e4567-e89b-12d3-a456-426614174001",
                        "document_id": "doc_def456",
                        "success": False,
                        "error": "Artifact not found"
                    }
                ]
            }
        }


# =========================================================================
# STORAGE BROWSE MODELS
# =========================================================================

class BucketInfo(BaseModel):
    """Information about a storage bucket."""
    name: str = Field(..., description="Bucket name")
    display_name: str = Field(..., description="Human-readable display name")
    is_protected: bool = Field(..., description="Whether bucket is read-only for users")
    is_default: bool = Field(..., description="Whether this is the default uploads bucket")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "curatore-uploads",
                "display_name": "Default Storage",
                "is_protected": False,
                "is_default": True
            }
        }


class StorageObjectInfo(BaseModel):
    """Information about an object in storage."""
    key: str = Field(..., description="Object key/path")
    filename: str = Field(..., description="Filename extracted from key")
    size: int = Field(..., description="File size in bytes")
    content_type: Optional[str] = Field(None, description="MIME type")
    etag: str = Field(..., description="Object ETag")
    last_modified: datetime = Field(..., description="Last modification timestamp")
    is_folder: bool = Field(default=False, description="Whether this is a folder marker")

    class Config:
        json_schema_extra = {
            "example": {
                "key": "org_123/workspace/report.pdf",
                "filename": "report.pdf",
                "size": 1048576,
                "content_type": "application/pdf",
                "etag": "d41d8cd98f00b204e9800998ecf8427e",
                "last_modified": "2026-01-20T10:00:00",
                "is_folder": False
            }
        }


class BrowseResponse(BaseModel):
    """Response from browsing a bucket/folder."""
    bucket: str = Field(..., description="Bucket name")
    prefix: str = Field(..., description="Current prefix/path")
    folders: List[str] = Field(..., description="Folder names at this level")
    files: List[StorageObjectInfo] = Field(..., description="Files at this level")
    is_protected: bool = Field(..., description="Whether this bucket is read-only")
    parent_path: Optional[str] = Field(None, description="Parent folder path for navigation")

    class Config:
        json_schema_extra = {
            "example": {
                "bucket": "curatore-uploads",
                "prefix": "org_123/workspace/",
                "folders": ["reports", "images"],
                "files": [
                    {
                        "key": "org_123/workspace/readme.txt",
                        "filename": "readme.txt",
                        "size": 1024,
                        "content_type": "text/plain",
                        "etag": "abc123",
                        "last_modified": "2026-01-20T10:00:00",
                        "is_folder": False
                    }
                ],
                "is_protected": False,
                "parent_path": "org_123/"
            }
        }


class BucketsListResponse(BaseModel):
    """Response listing all accessible buckets."""
    buckets: List[BucketInfo] = Field(..., description="List of accessible buckets")
    default_bucket: str = Field(..., description="Name of the default uploads bucket")

    class Config:
        json_schema_extra = {
            "example": {
                "buckets": [
                    {"name": "curatore-uploads", "display_name": "Default Storage", "is_protected": False, "is_default": True},
                    {"name": "curatore-processed", "display_name": "Processed Files", "is_protected": True, "is_default": False}
                ],
                "default_bucket": "curatore-uploads"
            }
        }


class CreateFolderRequest(BaseModel):
    """Request to create a new folder."""
    bucket: str = Field(..., description="Bucket name")
    path: str = Field(..., min_length=1, max_length=500, description="Folder path to create")

    class Config:
        json_schema_extra = {
            "example": {
                "bucket": "curatore-uploads",
                "path": "org_123/my-workspace/new-folder"
            }
        }


class CreateFolderResponse(BaseModel):
    """Response after creating a folder."""
    success: bool = Field(..., description="Whether folder was created")
    bucket: str = Field(..., description="Bucket name")
    path: str = Field(..., description="Full folder path")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "bucket": "curatore-uploads",
                "path": "org_123/my-workspace/new-folder/"
            }
        }


class DeleteFolderResponse(BaseModel):
    """Response after deleting a folder."""
    success: bool = Field(..., description="Whether deletion was successful")
    bucket: str = Field(..., description="Bucket name")
    path: str = Field(..., description="Deleted folder path")
    deleted_count: int = Field(..., description="Number of objects deleted")
    failed_count: int = Field(..., description="Number of objects that failed to delete")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "bucket": "curatore-uploads",
                "path": "org_123/my-workspace/old-folder/",
                "deleted_count": 5,
                "failed_count": 0
            }
        }


class DeleteFileResponse(BaseModel):
    """Response after deleting a file."""
    success: bool = Field(..., description="Whether deletion was successful")
    bucket: str = Field(..., description="Bucket name")
    key: str = Field(..., description="Deleted file key")
    artifact_deleted: bool = Field(False, description="Whether artifact record was also deleted")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "bucket": "curatore-uploads",
                "key": "org_123/document.pdf",
                "artifact_deleted": True
            }
        }


class MoveFilesRequest(BaseModel):
    """Request to move files to a different location."""
    artifact_ids: List[str] = Field(..., min_length=1, description="List of artifact IDs to move")
    destination_bucket: str = Field(..., description="Destination bucket")
    destination_prefix: str = Field(..., description="Destination folder path")

    class Config:
        json_schema_extra = {
            "example": {
                "artifact_ids": ["123e4567-e89b-12d3-a456-426614174000"],
                "destination_bucket": "curatore-uploads",
                "destination_prefix": "org_123/archive/"
            }
        }


class MoveFilesResponse(BaseModel):
    """Response after moving files."""
    moved_count: int = Field(..., description="Number of files successfully moved")
    failed_count: int = Field(..., description="Number of files that failed to move")
    moved_artifacts: List[str] = Field(..., description="IDs of successfully moved artifacts")
    failed_artifacts: List[str] = Field(..., description="IDs of artifacts that failed to move")

    class Config:
        json_schema_extra = {
            "example": {
                "moved_count": 3,
                "failed_count": 0,
                "moved_artifacts": ["123e4567-e89b-12d3-a456-426614174000"],
                "failed_artifacts": []
            }
        }


class RenameFileRequest(BaseModel):
    """Request to rename a file."""
    artifact_id: str = Field(..., description="Artifact ID to rename")
    new_name: str = Field(..., min_length=1, max_length=255, description="New filename")

    class Config:
        json_schema_extra = {
            "example": {
                "artifact_id": "123e4567-e89b-12d3-a456-426614174000",
                "new_name": "renamed-file.pdf"
            }
        }


class RenameFileResponse(BaseModel):
    """Response after renaming a file."""
    success: bool = Field(..., description="Whether rename was successful")
    artifact_id: str = Field(..., description="Artifact ID")
    old_name: str = Field(..., description="Previous filename")
    new_name: str = Field(..., description="New filename")
    new_key: str = Field(..., description="New object key")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "artifact_id": "123e4567-e89b-12d3-a456-426614174000",
                "old_name": "old-file.pdf",
                "new_name": "renamed-file.pdf",
                "new_key": "org_123/workspace/renamed-file.pdf"
            }
        }


class ProtectedBucketsResponse(BaseModel):
    """Response listing protected bucket names."""
    protected_buckets: List[str] = Field(..., description="List of protected bucket names")

    class Config:
        json_schema_extra = {
            "example": {
                "protected_buckets": ["curatore-processed", "curatore-temp"]
            }
        }


# =========================================================================
# PHASE 0: ASSET AND RUN MODELS
# =========================================================================

class AssetResponse(BaseModel):
    """Asset response model."""
    id: str = Field(..., description="Asset UUID")
    organization_id: str = Field(..., description="Organization UUID")
    source_type: str = Field(..., description="Source type (upload, sharepoint, web_scrape, sam_gov)")
    source_metadata: Dict[str, Any] = Field(..., description="Source provenance metadata")
    original_filename: str = Field(..., description="Original filename")
    content_type: Optional[str] = Field(None, description="MIME type")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    file_hash: Optional[str] = Field(None, description="SHA-256 hash")
    raw_bucket: str = Field(..., description="Object storage bucket for raw content")
    raw_object_key: str = Field(..., description="Object storage key for raw content")
    status: str = Field(..., description="Asset status (pending, ready, failed, deleted)")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Update timestamp")
    created_by: Optional[str] = Field(None, description="User UUID who created the asset")

    # Version tracking
    current_version_number: Optional[int] = Field(None, description="Current version number")

    # Extraction pipeline status fields
    extraction_tier: Optional[str] = Field(None, description="Extraction quality tier (basic, enhanced)")
    indexed_at: Optional[datetime] = Field(None, description="When asset was indexed to search")

    class Config:
        from_attributes = True


class ExtractionResultResponse(BaseModel):
    """Extraction result response model."""
    id: str = Field(..., description="Extraction result UUID")
    asset_id: str = Field(..., description="Asset UUID")
    run_id: str = Field(..., description="Run UUID")
    extractor_version: str = Field(..., description="Extractor version used")
    extraction_tier: Optional[str] = Field(None, description="Extraction quality tier (basic, enhanced)")
    status: str = Field(..., description="Extraction status (pending, running, completed, failed)")
    extracted_bucket: Optional[str] = Field(None, description="Bucket for extracted content")
    extracted_object_key: Optional[str] = Field(None, description="Key for extracted markdown")
    structure_metadata: Optional[Dict[str, Any]] = Field(None, description="Structural metadata")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings")
    errors: List[str] = Field(default_factory=list, description="Errors (if failed)")
    extraction_time_seconds: Optional[float] = Field(None, description="Extraction time")
    created_at: datetime = Field(..., description="Creation timestamp")

    # Triage fields (new extraction routing architecture)
    triage_engine: Optional[str] = Field(
        None,
        description="Engine selected by triage (fast_pdf, fast_office, docling, ocr_only)"
    )
    triage_needs_ocr: Optional[bool] = Field(
        None,
        description="Whether document requires OCR (determined by triage)"
    )
    triage_needs_layout: Optional[bool] = Field(
        None,
        description="Whether document has complex layout requiring advanced processing"
    )
    triage_complexity: Optional[str] = Field(
        None,
        description="Document complexity level (low, medium, high)"
    )
    triage_duration_ms: Optional[int] = Field(
        None,
        description="Time taken for triage analysis in milliseconds"
    )

    class Config:
        from_attributes = True


class AssetVersionResponse(BaseModel):
    """Asset version response model (Phase 1)."""
    id: str = Field(..., description="Asset version UUID")
    asset_id: str = Field(..., description="Parent asset UUID")
    version_number: int = Field(..., description="Version number")
    raw_bucket: str = Field(..., description="Object storage bucket")
    raw_object_key: str = Field(..., description="Object storage key")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    file_hash: Optional[str] = Field(None, description="SHA-256 hash")
    content_type: Optional[str] = Field(None, description="MIME type")
    is_current: bool = Field(..., description="Whether this is the current version")
    created_at: datetime = Field(..., description="Creation timestamp")
    created_by: Optional[str] = Field(None, description="User UUID who created this version")

    # Extraction info (from extraction_results - permanent data)
    extraction_status: Optional[str] = Field(None, description="Extraction status (completed, failed, etc)")
    extraction_tier: Optional[str] = Field(None, description="Extraction quality tier (basic, enhanced)")
    extractor_version: Optional[str] = Field(None, description="Extractor engine used")
    extraction_time_seconds: Optional[float] = Field(None, description="Extraction duration")
    extraction_created_at: Optional[datetime] = Field(None, description="When extraction completed")
    # Run link (may be null if run was purged)
    extraction_run_id: Optional[str] = Field(None, description="Run UUID for detailed logs (if available)")

    class Config:
        from_attributes = True


class AssetWithExtractionResponse(BaseModel):
    """Asset with latest extraction result."""
    asset: AssetResponse
    extraction: Optional[ExtractionResultResponse] = None


class AssetVersionHistoryResponse(BaseModel):
    """Asset with version history (Phase 1)."""
    asset: AssetResponse
    versions: List[AssetVersionResponse] = Field(default_factory=list, description="Version history (newest first)")
    total_versions: int = Field(..., description="Total number of versions")


class RunLogEventResponse(BaseModel):
    """Run log event response model."""
    id: UUID = Field(..., description="Log event UUID")
    run_id: UUID = Field(..., description="Run UUID")
    level: str = Field(..., description="Log level (INFO, WARN, ERROR)")
    event_type: str = Field(..., description="Event type (start, progress, retry, error, summary)")
    message: str = Field(..., description="Human-readable message")
    context: Optional[Dict[str, Any]] = Field(None, description="Machine-readable context")
    created_at: datetime = Field(..., description="Event timestamp")

    class Config:
        from_attributes = True


class RunResponse(BaseModel):
    """Run response model."""
    id: UUID = Field(..., description="Run UUID")
    organization_id: UUID = Field(..., description="Organization UUID")
    run_type: str = Field(..., description="Run type (extraction, processing, experiment, system_maintenance, sync)")
    origin: str = Field(..., description="Run origin (user, system, scheduled)")
    status: str = Field(..., description="Run status (pending, running, completed, failed, cancelled)")
    input_asset_ids: List[str] = Field(default_factory=list, description="Input asset UUIDs")
    config: Dict[str, Any] = Field(default_factory=dict, description="Run configuration")
    progress: Optional[Dict[str, Any]] = Field(None, description="Progress tracking")
    results_summary: Optional[Dict[str, Any]] = Field(None, description="Results summary")
    error_message: Optional[str] = Field(None, description="Error message (if failed)")
    created_at: datetime = Field(..., description="Creation timestamp")
    started_at: Optional[datetime] = Field(None, description="Start timestamp")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")
    last_activity_at: Optional[datetime] = Field(None, description="Last activity timestamp (for timeout tracking)")
    created_by: Optional[UUID] = Field(None, description="User UUID who created the run")

    # Queue info (for pending runs)
    queue_position: Optional[int] = Field(None, description="Position in queue (1-indexed, only for pending runs)")
    queue_priority: Optional[int] = Field(None, description="Queue priority (0=normal, 1=high)")

    class Config:
        from_attributes = True


class RunWithLogsResponse(BaseModel):
    """Run with log events."""
    run: RunResponse
    logs: List[RunLogEventResponse] = Field(default_factory=list)


class AssetsListResponse(BaseModel):
    """Paginated assets list response."""
    items: List[AssetResponse]
    total: int
    limit: int
    offset: int


class RunsListResponse(BaseModel):
    """Paginated runs list response."""
    items: List[RunResponse]
    total: int
    limit: int
    offset: int


# =========================================================================
# BULK UPLOAD MODELS (Phase 2)
# =========================================================================

class BulkUploadFileInfo(BaseModel):
    """Information about a file in bulk upload analysis."""
    filename: str = Field(..., description="Filename")
    file_size: int = Field(..., description="File size in bytes")
    file_hash: str = Field(..., description="SHA-256 content hash")
    asset_id: Optional[str] = Field(None, description="Existing asset ID (for unchanged/updated)")
    current_version: Optional[int] = Field(None, description="Current version number")
    old_file_hash: Optional[str] = Field(None, description="Previous file hash (for updated files)")
    status: Optional[str] = Field(None, description="Asset status (for missing files)")


class BulkUploadAnalysisResponse(BaseModel):
    """Result of bulk upload analysis."""
    unchanged: List[BulkUploadFileInfo] = Field(default_factory=list, description="Files that match existing assets")
    updated: List[BulkUploadFileInfo] = Field(default_factory=list, description="Files with same name but different content")
    new: List[BulkUploadFileInfo] = Field(default_factory=list, description="Files not seen before")
    missing: List[BulkUploadFileInfo] = Field(default_factory=list, description="Assets in DB but not in upload")
    counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Summary counts (unchanged, updated, new, missing, total_uploaded)"
    )


class BulkUploadApplyRequest(BaseModel):
    """Request to apply bulk upload changes."""
    mark_missing_inactive: bool = Field(
        default=True,
        description="Whether to mark missing files as inactive"
    )


class BulkUploadApplyResponse(BaseModel):
    """Result of applying bulk upload changes."""
    analysis: BulkUploadAnalysisResponse = Field(..., description="Upload analysis")
    created_assets: List[str] = Field(default_factory=list, description="IDs of created assets")
    updated_assets: List[str] = Field(default_factory=list, description="IDs of updated assets")
    marked_inactive: List[str] = Field(default_factory=list, description="IDs of assets marked inactive")
    summary: Dict[str, int] = Field(
        default_factory=dict,
        description="Summary counts (created_count, updated_count, marked_inactive_count)"
    )


# =========================================================================
# ASSET METADATA MODELS (Phase 3)
# =========================================================================

class AssetMetadataResponse(BaseModel):
    """Asset metadata response model (Phase 3)."""
    id: str = Field(..., description="Metadata UUID")
    asset_id: str = Field(..., description="Asset UUID")
    metadata_type: str = Field(..., description="Metadata type (e.g., topics.v1, summary.short.v1)")
    schema_version: str = Field(..., description="Schema version for this metadata type")
    producer_run_id: Optional[str] = Field(None, description="Run UUID that produced this metadata")
    is_canonical: bool = Field(..., description="Whether this is canonical (production) metadata")
    status: str = Field(..., description="Status (active, superseded, deprecated)")
    metadata_content: Dict[str, Any] = Field(..., description="The actual metadata payload")
    metadata_object_ref: Optional[str] = Field(None, description="Object store reference for large payloads")
    created_at: datetime = Field(..., description="Creation timestamp")
    promoted_at: Optional[datetime] = Field(None, description="When promoted to canonical")
    superseded_at: Optional[datetime] = Field(None, description="When superseded by newer canonical")
    promoted_from_id: Optional[str] = Field(None, description="ID of metadata this was promoted from")
    superseded_by_id: Optional[str] = Field(None, description="ID of metadata that superseded this")

    class Config:
        from_attributes = True


class AssetMetadataCreateRequest(BaseModel):
    """Request to create new asset metadata."""
    metadata_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Metadata type (e.g., topics.v1, summary.short.v1, tags.llm.v1)"
    )
    metadata_content: Dict[str, Any] = Field(..., description="The metadata payload")
    schema_version: str = Field(default="1.0", description="Schema version")
    is_canonical: bool = Field(default=False, description="Create as canonical (production) metadata")
    producer_run_id: Optional[str] = Field(None, description="Run UUID that produced this (for attribution)")

    class Config:
        json_schema_extra = {
            "example": {
                "metadata_type": "summary.short.v1",
                "metadata_content": {
                    "summary": "This document describes the procurement process for IT services."
                },
                "schema_version": "1.0",
                "is_canonical": False
            }
        }


class AssetMetadataUpdateRequest(BaseModel):
    """Request to update asset metadata content."""
    metadata_content: Dict[str, Any] = Field(..., description="Updated metadata payload")

    class Config:
        json_schema_extra = {
            "example": {
                "metadata_content": {
                    "summary": "Updated summary content."
                }
            }
        }


class AssetMetadataListResponse(BaseModel):
    """List of metadata for an asset."""
    canonical: List[AssetMetadataResponse] = Field(
        default_factory=list,
        description="Canonical (production) metadata"
    )
    experimental: List[AssetMetadataResponse] = Field(
        default_factory=list,
        description="Experimental (non-promoted) metadata"
    )
    total_canonical: int = Field(..., description="Count of canonical metadata")
    total_experimental: int = Field(..., description="Count of experimental metadata")
    metadata_types: List[str] = Field(default_factory=list, description="Available metadata types")


class AssetMetadataPromoteResponse(BaseModel):
    """Response after promoting metadata to canonical."""
    promoted: AssetMetadataResponse = Field(..., description="The promoted metadata")
    superseded: Optional[AssetMetadataResponse] = Field(
        None,
        description="Previously canonical metadata that was superseded"
    )
    message: str = Field(..., description="Success message")


class AssetMetadataCompareRequest(BaseModel):
    """Request to compare two metadata records."""
    metadata_id_a: str = Field(..., description="First metadata UUID to compare")
    metadata_id_b: str = Field(..., description="Second metadata UUID to compare")


class AssetMetadataCompareResponse(BaseModel):
    """Response comparing two metadata records."""
    metadata_a: AssetMetadataResponse = Field(..., description="First metadata")
    metadata_b: AssetMetadataResponse = Field(..., description="Second metadata")
    differences: Dict[str, Any] = Field(
        default_factory=dict,
        description="Differences between the two metadata contents"
    )


# =========================================================================
# SCRAPE COLLECTION MODELS (Phase 4)
# =========================================================================

class ScrapeCollectionResponse(BaseModel):
    """Scrape collection response model."""
    id: str = Field(..., description="Collection UUID")
    organization_id: str = Field(..., description="Organization UUID")
    name: str = Field(..., description="Collection name")
    slug: str = Field(..., description="URL-friendly slug")
    description: Optional[str] = Field(None, description="Collection description")
    collection_mode: str = Field(..., description="Mode: snapshot or record_preserving")
    root_url: str = Field(..., description="Root URL for this collection")
    url_patterns: List[Dict[str, Any]] = Field(default_factory=list, description="URL include/exclude patterns")
    crawl_config: Dict[str, Any] = Field(default_factory=dict, description="Crawl configuration")
    status: str = Field(..., description="Status: active, paused, archived")
    last_crawl_at: Optional[datetime] = Field(None, description="Last crawl timestamp")
    last_crawl_run_id: Optional[str] = Field(None, description="Last crawl run UUID")
    stats: Dict[str, Any] = Field(default_factory=dict, description="Collection statistics")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Update timestamp")
    created_by: Optional[str] = Field(None, description="User UUID who created the collection")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "organization_id": "04ace7c6-2043-4935-b074-ec0a567d1fd2",
                "name": "SAM.gov Opportunities",
                "slug": "sam-gov-opportunities",
                "description": "Federal procurement opportunities from SAM.gov",
                "collection_mode": "record_preserving",
                "root_url": "https://sam.gov/search",
                "url_patterns": [{"type": "include", "pattern": "/opp/*"}],
                "crawl_config": {"max_depth": 3, "delay_seconds": 1.0},
                "status": "active",
                "last_crawl_at": "2026-01-28T12:00:00",
                "stats": {"page_count": 150, "record_count": 25},
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-28T12:00:00"
            }
        }


class ScrapeCollectionCreateRequest(BaseModel):
    """Request to create a scrape collection."""
    name: str = Field(..., min_length=1, max_length=255, description="Collection name")
    description: Optional[str] = Field(None, max_length=2000, description="Collection description")
    root_url: str = Field(..., min_length=1, max_length=2048, description="Root URL")
    collection_mode: str = Field(
        default="record_preserving",
        description="Mode: snapshot (auto-delete old) or record_preserving (never auto-delete)"
    )
    url_patterns: Optional[List[Dict[str, str]]] = Field(
        None,
        description="URL patterns: [{type: 'include'|'exclude', pattern: '/path/*'}]"
    )
    crawl_config: Optional[Dict[str, Any]] = Field(
        None,
        description="Crawl config: max_depth, max_pages, delay_seconds, etc."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "name": "SAM.gov Opportunities",
                "description": "Federal procurement opportunities",
                "root_url": "https://sam.gov/search",
                "collection_mode": "record_preserving",
                "url_patterns": [
                    {"type": "include", "pattern": "/opp/*"},
                    {"type": "exclude", "pattern": "/opp/archive/*"}
                ],
                "crawl_config": {
                    "max_depth": 3,
                    "max_pages": 100,
                    "delay_seconds": 1.0
                }
            }
        }


class ScrapeCollectionUpdateRequest(BaseModel):
    """Request to update a scrape collection."""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Collection name")
    description: Optional[str] = Field(None, max_length=2000, description="Description")
    collection_mode: Optional[str] = Field(None, description="Mode: snapshot or record_preserving")
    url_patterns: Optional[List[Dict[str, str]]] = Field(None, description="URL patterns")
    crawl_config: Optional[Dict[str, Any]] = Field(None, description="Crawl configuration")
    status: Optional[str] = Field(None, description="Status: active, paused, archived")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Updated Collection Name",
                "status": "paused"
            }
        }


class ScrapeCollectionListResponse(BaseModel):
    """Paginated list of scrape collections."""
    collections: List[ScrapeCollectionResponse] = Field(..., description="List of collections")
    total: int = Field(..., description="Total count")
    limit: int = Field(..., description="Page size")
    offset: int = Field(..., description="Offset")

    class Config:
        json_schema_extra = {
            "example": {
                "collections": [],
                "total": 5,
                "limit": 50,
                "offset": 0
            }
        }


class ScrapeSourceResponse(BaseModel):
    """Scrape source response model."""
    id: str = Field(..., description="Source UUID")
    collection_id: str = Field(..., description="Collection UUID")
    url: str = Field(..., description="Source URL")
    source_type: str = Field(..., description="Type: seed, discovered, manual")
    is_active: bool = Field(..., description="Whether source is active")
    crawl_config: Optional[Dict[str, Any]] = Field(None, description="Source-specific config")
    last_crawl_at: Optional[datetime] = Field(None, description="Last crawl timestamp")
    last_status: Optional[str] = Field(None, description="Last crawl status")
    discovered_pages: int = Field(..., description="Number of pages discovered from this source")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Update timestamp")

    class Config:
        from_attributes = True


class ScrapeSourceCreateRequest(BaseModel):
    """Request to add a source to a collection."""
    url: str = Field(..., min_length=1, max_length=2048, description="Source URL")
    source_type: str = Field(default="seed", description="Type: seed, discovered, manual")
    crawl_config: Optional[Dict[str, Any]] = Field(None, description="Source-specific configuration")

    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://sam.gov/search?status=active",
                "source_type": "seed"
            }
        }


class ScrapeSourceListResponse(BaseModel):
    """List of sources for a collection."""
    sources: List[ScrapeSourceResponse] = Field(..., description="List of sources")
    total: int = Field(..., description="Total count")


class ScrapedAssetResponse(BaseModel):
    """Scraped asset response model."""
    id: str = Field(..., description="ScrapedAsset UUID")
    asset_id: str = Field(..., description="Asset UUID")
    collection_id: str = Field(..., description="Collection UUID")
    source_id: Optional[str] = Field(None, description="Source UUID")
    asset_subtype: str = Field(..., description="Type: page or record")
    url: str = Field(..., description="Original URL")
    url_path: Optional[str] = Field(None, description="URL path for hierarchical browsing")
    parent_url: Optional[str] = Field(None, description="Parent page URL")
    crawl_depth: int = Field(..., description="Depth from seed URL")
    crawl_run_id: Optional[str] = Field(None, description="Crawl run UUID")
    is_promoted: bool = Field(..., description="Whether promoted to record")
    promoted_at: Optional[datetime] = Field(None, description="Promotion timestamp")
    promoted_by: Optional[str] = Field(None, description="User who promoted")
    scrape_metadata: Dict[str, Any] = Field(default_factory=dict, description="Scrape metadata")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Update timestamp")
    # Include asset details
    original_filename: Optional[str] = Field(None, description="Original filename from asset")
    asset_status: Optional[str] = Field(None, description="Asset status")

    class Config:
        from_attributes = True


class ScrapedAssetListResponse(BaseModel):
    """Paginated list of scraped assets."""
    assets: List[ScrapedAssetResponse] = Field(..., description="List of scraped assets")
    total: int = Field(..., description="Total count")
    limit: int = Field(..., description="Page size")
    offset: int = Field(..., description="Offset")


class PathTreeNode(BaseModel):
    """Node in hierarchical path tree."""
    path: str = Field(..., description="Full path")
    name: str = Field(..., description="Path segment name")
    page_count: int = Field(..., description="Number of pages at/below this path")
    record_count: int = Field(..., description="Number of records at/below this path")
    has_children: bool = Field(..., description="Whether this path has children")


class PathTreeResponse(BaseModel):
    """Hierarchical tree structure for browsing."""
    path_prefix: str = Field(..., description="Current path prefix")
    nodes: List[PathTreeNode] = Field(..., description="Child nodes")


class PromoteToRecordRequest(BaseModel):
    """Request to promote a page to record."""
    pass  # No body needed, just confirmation via POST


class PromoteToRecordResponse(BaseModel):
    """Response after promoting to record."""
    scraped_asset: ScrapedAssetResponse = Field(..., description="Updated scraped asset")
    message: str = Field(..., description="Success message")


class CrawlCollectionRequest(BaseModel):
    """Request to start a crawl."""
    max_pages: Optional[int] = Field(None, ge=1, le=10000, description="Override max pages")

    class Config:
        json_schema_extra = {
            "example": {
                "max_pages": 50
            }
        }


class CrawlCollectionResponse(BaseModel):
    """Response from starting a crawl."""
    run_id: str = Field(..., description="Crawl run UUID")
    collection_id: str = Field(..., description="Collection UUID")
    status: str = Field(..., description="Run status")
    message: str = Field(..., description="Status message")

    class Config:
        json_schema_extra = {
            "example": {
                "run_id": "123e4567-e89b-12d3-a456-426614174000",
                "collection_id": "456e4567-e89b-12d3-a456-426614174000",
                "status": "running",
                "message": "Crawl started successfully"
            }
        }


class CrawlStatusResponse(BaseModel):
    """Status of a crawl run."""
    run_id: str = Field(..., description="Run UUID")
    status: str = Field(..., description="Run status")
    progress: Optional[Dict[str, Any]] = Field(None, description="Progress info")
    results_summary: Optional[Dict[str, Any]] = Field(None, description="Results summary")
    error_message: Optional[str] = Field(None, description="Error if failed")


# =========================================================================
# SHAREPOINT SYNC MODELS (Phase 8)
# =========================================================================

class SharePointSyncConfigResponse(BaseModel):
    """SharePoint sync config response model."""
    id: str = Field(..., description="Sync config UUID")
    organization_id: str = Field(..., description="Organization UUID")
    connection_id: Optional[str] = Field(None, description="SharePoint connection UUID")
    connection_name: Optional[str] = Field(None, description="SharePoint connection name")
    name: str = Field(..., description="Sync config name")
    slug: str = Field(..., description="URL-friendly slug")
    description: Optional[str] = Field(None, description="Description")
    folder_url: str = Field(..., description="SharePoint folder URL")
    folder_name: Optional[str] = Field(None, description="Cached folder name")
    folder_drive_id: Optional[str] = Field(None, description="Microsoft Graph drive ID")
    folder_item_id: Optional[str] = Field(None, description="Microsoft Graph item ID")
    sync_config: Dict[str, Any] = Field(default_factory=dict, description="Sync configuration")
    status: str = Field(..., description="Status: active, paused, archived")
    is_active: bool = Field(..., description="Whether sync is enabled")
    last_sync_at: Optional[datetime] = Field(None, description="Last sync timestamp")
    last_sync_status: Optional[str] = Field(None, description="Last sync status")
    last_sync_run_id: Optional[str] = Field(None, description="Last sync run UUID")
    sync_frequency: str = Field(..., description="Sync frequency: manual, hourly, daily")
    stats: Dict[str, Any] = Field(default_factory=dict, description="Sync statistics")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Update timestamp")
    created_by: Optional[str] = Field(None, description="User UUID who created this")
    # Active sync tracking
    is_syncing: bool = Field(default=False, description="True if sync is currently running")
    current_sync_status: Optional[str] = Field(None, description="Current sync run status")
    # Delta query tracking
    delta_enabled: bool = Field(default=False, description="Whether delta query is enabled for incremental sync")
    has_delta_token: bool = Field(default=False, description="Whether a delta token is available")
    last_delta_sync_at: Optional[datetime] = Field(None, description="When delta was last used successfully")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "organization_id": "04ace7c6-2043-4935-b074-ec0a567d1fd2",
                "connection_id": "789e4567-e89b-12d3-a456-426614174000",
                "name": "IT Policies",
                "slug": "it-policies",
                "description": "IT policy documents from SharePoint",
                "folder_url": "https://company.sharepoint.com/sites/IT/Documents/Policies",
                "folder_name": "Policies",
                "sync_config": {
                    "recursive": True,
                    "include_patterns": ["*.pdf", "*.docx"],
                    "exclude_patterns": ["~$*", "*.tmp"]
                },
                "status": "active",
                "is_active": True,
                "last_sync_at": "2026-01-29T10:00:00",
                "last_sync_status": "success",
                "sync_frequency": "daily",
                "stats": {"total_files": 25, "synced_files": 25, "deleted_count": 0},
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-29T10:00:00"
            }
        }


class SharePointSyncConfigCreateRequest(BaseModel):
    """Request to create a SharePoint sync config."""
    name: str = Field(..., min_length=1, max_length=255, description="Sync config name")
    description: Optional[str] = Field(None, max_length=2000, description="Description")
    connection_id: Optional[str] = Field(None, description="SharePoint connection UUID")
    folder_url: str = Field(..., min_length=1, max_length=2048, description="SharePoint folder URL")
    sync_config: Optional[Dict[str, Any]] = Field(
        None,
        description="Sync configuration: recursive, include_patterns, exclude_patterns, max_file_size_mb"
    )
    sync_frequency: str = Field(
        default="manual",
        description="Sync frequency: manual, hourly, daily"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "name": "IT Policies",
                "description": "IT policy documents from SharePoint",
                "connection_id": "789e4567-e89b-12d3-a456-426614174000",
                "folder_url": "https://company.sharepoint.com/sites/IT/Documents/Policies",
                "sync_config": {
                    "recursive": True,
                    "include_patterns": ["*.pdf", "*.docx"],
                    "exclude_patterns": ["~$*", "*.tmp"],
                    "max_file_size_mb": 100
                },
                "sync_frequency": "daily"
            }
        }


class SharePointSyncConfigUpdateRequest(BaseModel):
    """Request to update a SharePoint sync config.

    Safe changes (no asset impact):
    - name, description, sync_frequency, is_active, status
    - sync_config.include_patterns, sync_config.exclude_patterns (affects future syncs only)
    - sync_config.recursive: false -> true (only adds more files)

    Breaking changes (require reset_existing_assets=True):
    - sync_config.recursive: true -> false (would orphan subfolder assets)

    Cannot be changed (create a new sync config instead):
    - folder_url
    - connection_id
    """
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Sync config name")
    description: Optional[str] = Field(None, max_length=2000, description="Description")
    sync_config: Optional[Dict[str, Any]] = Field(None, description="Sync configuration (recursive, include_patterns, exclude_patterns)")
    status: Optional[str] = Field(None, description="Status: active, paused, archived")
    is_active: Optional[bool] = Field(None, description="Whether sync is enabled")
    sync_frequency: Optional[str] = Field(None, description="Sync frequency: manual, hourly, daily")
    reset_existing_assets: bool = Field(
        default=False,
        description="If True, delete all existing synced assets when disabling recursive mode"
    )
    # These fields are included for validation but cannot be changed
    # The endpoint will reject any attempt to modify them
    folder_url: Optional[str] = Field(None, description="Cannot be changed - create new config instead")
    connection_id: Optional[str] = Field(None, description="Cannot be changed - create new config instead")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Updated Name",
                "sync_frequency": "daily",
                "sync_config": {"exclude_patterns": ["~$*", "*.tmp"]},
                "reset_existing_assets": False
            }
        }


class SharePointSyncConfigListResponse(BaseModel):
    """Paginated list of SharePoint sync configs."""
    configs: List[SharePointSyncConfigResponse] = Field(..., description="List of sync configs")
    total: int = Field(..., description="Total count")
    limit: int = Field(..., description="Page size")
    offset: int = Field(..., description="Offset")

    class Config:
        json_schema_extra = {
            "example": {
                "configs": [],
                "total": 5,
                "limit": 50,
                "offset": 0
            }
        }


class SharePointSyncedDocumentResponse(BaseModel):
    """SharePoint synced document response model."""
    id: str = Field(..., description="Document UUID")
    asset_id: str = Field(..., description="Asset UUID")
    sync_config_id: str = Field(..., description="Sync config UUID")
    sharepoint_item_id: str = Field(..., description="Microsoft Graph item ID")
    sharepoint_drive_id: str = Field(..., description="Microsoft Graph drive ID")
    sharepoint_path: Optional[str] = Field(None, description="Relative path in synced folder")
    sharepoint_web_url: Optional[str] = Field(None, description="Direct link to file in SharePoint")
    sharepoint_etag: Optional[str] = Field(None, description="ETag for change detection")
    content_hash: Optional[str] = Field(None, description="SHA-256 content hash")
    sharepoint_created_at: Optional[datetime] = Field(None, description="Creation date in SharePoint")
    sharepoint_modified_at: Optional[datetime] = Field(None, description="Last modified date in SharePoint")
    sharepoint_created_by: Optional[str] = Field(None, description="Creator email/name")
    sharepoint_modified_by: Optional[str] = Field(None, description="Last modifier email/name")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    sync_status: str = Field(..., description="Sync status: synced, deleted_in_source, orphaned")
    last_synced_at: Optional[datetime] = Field(None, description="Last sync timestamp")
    last_sync_run_id: Optional[str] = Field(None, description="Last sync run UUID")
    deleted_detected_at: Optional[datetime] = Field(None, description="When deletion was detected")
    sync_metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Update timestamp")
    # Include asset details
    original_filename: Optional[str] = Field(None, description="Original filename from asset")
    asset_status: Optional[str] = Field(None, description="Asset status")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "asset_id": "456e4567-e89b-12d3-a456-426614174000",
                "sync_config_id": "789e4567-e89b-12d3-a456-426614174000",
                "sharepoint_item_id": "abc123",
                "sharepoint_drive_id": "xyz789",
                "sharepoint_path": "Reports/Q4",
                "sharepoint_web_url": "https://company.sharepoint.com/sites/IT/Documents/Policies/report.pdf",
                "sync_status": "synced",
                "file_size": 1024000,
                "last_synced_at": "2026-01-29T10:00:00",
                "created_at": "2026-01-15T00:00:00",
                "updated_at": "2026-01-29T10:00:00",
                "original_filename": "report.pdf"
            }
        }


class SharePointSyncedDocumentListResponse(BaseModel):
    """Paginated list of synced documents."""
    documents: List[SharePointSyncedDocumentResponse] = Field(..., description="List of documents")
    total: int = Field(..., description="Total count")
    limit: int = Field(..., description="Page size")
    offset: int = Field(..., description="Offset")


class SharePointSyncTriggerRequest(BaseModel):
    """Request to trigger a sync."""
    full_sync: bool = Field(
        default=False,
        description="If true, re-download all files regardless of etag"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "full_sync": False
            }
        }


class SharePointSyncTriggerResponse(BaseModel):
    """Response from triggering a sync."""
    sync_config_id: str = Field(..., description="Sync config UUID")
    run_id: str = Field(..., description="Sync run UUID")
    status: str = Field(..., description="Run status")
    message: str = Field(..., description="Status message")

    class Config:
        json_schema_extra = {
            "example": {
                "sync_config_id": "123e4567-e89b-12d3-a456-426614174000",
                "run_id": "456e4567-e89b-12d3-a456-426614174000",
                "status": "pending",
                "message": "Sync queued for execution"
            }
        }


class SharePointSyncHistoryResponse(BaseModel):
    """Sync run history response."""
    runs: List[RunResponse] = Field(..., description="List of sync runs")
    total: int = Field(..., description="Total count")


class SharePointBrowseFolderRequest(BaseModel):
    """Request to browse a SharePoint folder."""
    connection_id: Optional[str] = Field(None, description="SharePoint connection UUID")
    folder_url: str = Field(..., min_length=1, max_length=2048, description="SharePoint folder URL")
    recursive: bool = Field(default=False, description="Include subfolders")
    include_folders: bool = Field(default=True, description="Include folders in results")

    class Config:
        json_schema_extra = {
            "example": {
                "folder_url": "https://company.sharepoint.com/sites/IT/Documents",
                "recursive": False,
                "include_folders": True
            }
        }


class SharePointBrowseFolderResponse(BaseModel):
    """Response from browsing a SharePoint folder."""
    folder_name: str = Field(..., description="Folder name")
    folder_id: str = Field(..., description="Folder item ID")
    folder_url: str = Field(..., description="Folder web URL")
    drive_id: str = Field(..., description="Drive ID")
    items: List[Dict[str, Any]] = Field(..., description="Files and folders in the folder")
    total_items: int = Field(..., description="Total number of items")

    class Config:
        json_schema_extra = {
            "example": {
                "folder_name": "Documents",
                "folder_id": "abc123",
                "folder_url": "https://company.sharepoint.com/sites/IT/Documents",
                "drive_id": "xyz789",
                "items": [
                    {"name": "Policies", "type": "folder", "id": "folder1"},
                    {"name": "report.pdf", "type": "file", "id": "file1", "size": 1024}
                ],
                "total_items": 2
            }
        }


class SharePointImportRequest(BaseModel):
    """Request to import selected files from SharePoint.

    For new sync configs: set create_sync_config=True and provide sync_config_name.
    For existing sync configs: set sync_config_id to add files to an existing config.
    """
    connection_id: Optional[str] = Field(None, description="SharePoint connection UUID")
    folder_url: str = Field(..., min_length=1, max_length=2048, description="SharePoint folder URL")
    selected_items: List[Dict[str, Any]] = Field(
        ...,
        description="List of items to import with their IDs and paths"
    )
    sync_config_id: Optional[str] = Field(
        None,
        description="Existing sync config UUID to add files to"
    )
    sync_config_name: Optional[str] = Field(
        None,
        max_length=255,
        description="Name for new sync config (if creating one)"
    )
    sync_config_description: Optional[str] = Field(
        None,
        max_length=2000,
        description="Description for new sync config"
    )
    create_sync_config: bool = Field(
        default=True,
        description="Whether to create a sync config for ongoing sync"
    )
    sync_frequency: str = Field(
        default="manual",
        description="Sync frequency: manual, hourly, daily"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "folder_url": "https://company.sharepoint.com/sites/IT/Documents/Policies",
                "selected_items": [
                    {"id": "file1", "name": "policy.pdf", "folder": ""},
                    {"id": "file2", "name": "guideline.docx", "folder": "Guidelines"}
                ],
                "sync_config_name": "IT Policies Import",
                "create_sync_config": True,
                "sync_frequency": "daily"
            }
        }


class SharePointImportResponse(BaseModel):
    """Response from import operation."""
    run_id: str = Field(..., description="Import run UUID")
    sync_config_id: Optional[str] = Field(None, description="Created sync config UUID")
    status: str = Field(..., description="Run status")
    message: str = Field(..., description="Status message")
    selected_count: int = Field(..., description="Number of items selected for import")

    class Config:
        json_schema_extra = {
            "example": {
                "run_id": "123e4567-e89b-12d3-a456-426614174000",
                "sync_config_id": "456e4567-e89b-12d3-a456-426614174000",
                "status": "pending",
                "message": "Import queued for 5 files",
                "selected_count": 5
            }
        }


class SharePointCleanupRequest(BaseModel):
    """Request to cleanup deleted files."""
    delete_assets: bool = Field(
        default=False,
        description="If true, also soft-delete the Asset records"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "delete_assets": False
            }
        }


class SharePointCleanupResponse(BaseModel):
    """Response from cleanup operation."""
    sync_config_id: str = Field(..., description="Sync config UUID")
    documents_removed: int = Field(..., description="Number of document records removed")
    assets_deleted: int = Field(..., description="Number of assets soft-deleted")
    message: str = Field(..., description="Status message")

    class Config:
        json_schema_extra = {
            "example": {
                "sync_config_id": "123e4567-e89b-12d3-a456-426614174000",
                "documents_removed": 3,
                "assets_deleted": 0,
                "message": "Cleaned up 3 deleted documents"
            }
        }


class SharePointRemoveItemsRequest(BaseModel):
    """Request to remove specific synced items from a sync config."""
    item_ids: List[str] = Field(
        ...,
        description="List of SharePoint item IDs to remove"
    )
    delete_assets: bool = Field(
        default=True,
        description="If true, also soft-delete the associated Asset records"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "item_ids": ["01ABCDEF123456", "01ABCDEF789012"],
                "delete_assets": True
            }
        }


class SharePointRemoveItemsResponse(BaseModel):
    """Response from remove items operation."""
    sync_config_id: str = Field(..., description="Sync config UUID")
    documents_removed: int = Field(..., description="Number of document records removed")
    assets_deleted: int = Field(..., description="Number of assets soft-deleted")
    message: str = Field(..., description="Status message")

    class Config:
        json_schema_extra = {
            "example": {
                "sync_config_id": "123e4567-e89b-12d3-a456-426614174000",
                "documents_removed": 2,
                "assets_deleted": 2,
                "message": "Removed 2 items"
            }
        }


# =========================================================================
# UNIFIED QUEUE MODELS
# =========================================================================


class ExtractionQueueInfo(BaseModel):
    """Extraction queue counts."""
    pending: int = Field(..., description="Extractions waiting in queue")
    submitted: int = Field(..., description="Extractions submitted to worker")
    running: int = Field(..., description="Extractions currently processing")
    max_concurrent: int = Field(..., description="Maximum concurrent extractions")


class CeleryQueuesInfo(BaseModel):
    """Celery queue lengths."""
    processing_priority: int = Field(default=0, description="High priority queue length")
    extraction: int = Field(default=0, description="Extraction queue length")
    enhancement: int = Field(default=0, description="Enhancement queue length (Docling)")
    sam: int = Field(default=0, description="SAM.gov queue length")
    scrape: int = Field(default=0, description="Web scrape queue length")
    sharepoint: int = Field(default=0, description="SharePoint queue length")
    maintenance: int = Field(default=0, description="Maintenance queue length")


class ThroughputInfo(BaseModel):
    """Extraction throughput metrics."""
    per_minute: float = Field(..., description="Extractions completed per minute")
    avg_extraction_seconds: Optional[float] = Field(None, description="Average extraction time in seconds")


class Recent24hInfo(BaseModel):
    """Last 24 hours statistics."""
    completed: int = Field(..., description="Extractions completed in last 24h")
    failed: int = Field(..., description="Extractions failed in last 24h")
    timed_out: int = Field(..., description="Extractions timed out in last 24h")


class WorkersInfo(BaseModel):
    """Celery worker information."""
    active: int = Field(..., description="Number of active workers")
    tasks_running: int = Field(..., description="Total tasks currently running")


class UnifiedQueueStatsResponse(BaseModel):
    """
    Unified queue statistics response.

    Consolidates all queue information into a single response:
    - extraction_queue: Database-tracked queue counts
    - celery_queues: Redis queue lengths
    - throughput: Processing rate metrics
    - recent_24h: Last 24 hours statistics
    - workers: Worker status
    """
    extraction_queue: ExtractionQueueInfo
    celery_queues: CeleryQueuesInfo
    throughput: ThroughputInfo
    recent_24h: Recent24hInfo
    workers: WorkersInfo

    class Config:
        json_schema_extra = {
            "example": {
                "extraction_queue": {
                    "pending": 5,
                    "submitted": 2,
                    "running": 3,
                    "max_concurrent": 10
                },
                "celery_queues": {
                    "processing_priority": 0,
                    "extraction": 5,
                    "sam": 0,
                    "scrape": 0,
                    "sharepoint": 0,
                    "maintenance": 2
                },
                "throughput": {
                    "per_minute": 2.4,
                    "avg_extraction_seconds": 45.2
                },
                "recent_24h": {
                    "completed": 142,
                    "failed": 3,
                    "timed_out": 1
                },
                "workers": {
                    "active": 2,
                    "tasks_running": 3
                }
            }
        }


class AssetQueueInfoResponse(BaseModel):
    """Queue information for a specific asset."""
    unified_status: str = Field(..., description="Unified status (queued, submitted, processing, completed, failed, timed_out, cancelled)")
    asset_id: str = Field(..., description="Asset UUID")
    run_id: Optional[str] = Field(None, description="Current extraction run UUID")
    in_queue: bool = Field(..., description="Whether extraction is queued/processing")
    queue_position: Optional[int] = Field(None, description="Position in queue (if pending)")
    total_pending: Optional[int] = Field(None, description="Total items in queue")
    estimated_wait_seconds: Optional[float] = Field(None, description="Estimated wait time")
    submitted_to_celery: Optional[bool] = Field(None, description="Whether task has been sent to Celery")
    timeout_at: Optional[str] = Field(None, description="Task timeout timestamp")
    celery_task_id: Optional[str] = Field(None, description="Celery task ID")
    extractor_version: Optional[str] = Field(None, description="Extraction service version")

    class Config:
        json_schema_extra = {
            "example": {
                "unified_status": "queued",
                "asset_id": "123e4567-e89b-12d3-a456-426614174000",
                "run_id": "456e4567-e89b-12d3-a456-426614174000",
                "in_queue": True,
                "queue_position": 3,
                "total_pending": 10,
                "estimated_wait_seconds": 135.0,
                "submitted_to_celery": False,
                "timeout_at": None,
                "celery_task_id": None,
                "extractor_version": "markitdown-1.0"
            }
        }
