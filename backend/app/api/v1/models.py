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
        default="extraction-service",
        description="Extraction engine to use (e.g., 'extraction-service', 'docling')",
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
# JOB MANAGEMENT MODELS (Phase 3)
# =========================================================================

class CreateJobRequest(BaseModel):
    """Request to create a new batch job."""
    document_ids: List[str] = Field(..., min_length=1, description="List of document IDs to process")
    options: Optional[Dict[str, Any]] = Field(default=None, description="Processing options")
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Job name (auto-generated if not provided)")
    description: Optional[str] = Field(None, max_length=1000, description="Job description")
    start_immediately: bool = Field(default=True, description="Start processing immediately after creation")

    class Config:
        json_schema_extra = {
            "example": {
                "document_ids": ["doc_123", "doc_456", "doc_789"],
                "options": {
                    "apply_llm_evaluation": True,
                    "apply_vector_optimization": False,
                    "quality_thresholds": {
                        "conversion_threshold": 70,
                        "clarity_threshold": 7
                    }
                },
                "name": "Q1 Report Processing",
                "description": "Process all Q1 reports for analysis",
                "start_immediately": True
            }
        }


class JobDocumentResponse(BaseModel):
    """Individual document within a job."""
    id: str = Field(..., description="Job document UUID")
    document_id: str = Field(..., description="Document ID")
    filename: str = Field(..., description="Original filename")
    status: str = Field(..., description="Document status (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED)")
    conversion_score: Optional[int] = Field(None, description="Conversion quality score (0-100)")
    is_rag_ready: bool = Field(..., description="Whether document meets RAG quality thresholds")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    started_at: Optional[datetime] = Field(None, description="When processing started")
    completed_at: Optional[datetime] = Field(None, description="When processing completed")
    processing_time_seconds: Optional[float] = Field(None, description="Processing time in seconds")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "document_id": "doc_123",
                "filename": "report_q1.pdf",
                "status": "COMPLETED",
                "conversion_score": 85,
                "is_rag_ready": True,
                "error_message": None,
                "started_at": "2026-01-15T10:00:00",
                "completed_at": "2026-01-15T10:02:30",
                "processing_time_seconds": 150.5
            }
        }


class JobLogResponse(BaseModel):
    """Job log entry."""
    id: str = Field(..., description="Log entry UUID")
    timestamp: datetime = Field(..., description="Log timestamp")
    level: str = Field(..., description="Log level (INFO, SUCCESS, WARNING, ERROR)")
    message: str = Field(..., description="Log message")
    document_id: Optional[str] = Field(None, description="Related document ID (if document-specific)")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional structured data")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174001",
                "timestamp": "2026-01-15T10:00:00",
                "level": "INFO",
                "message": "Job created with 3 documents",
                "document_id": None,
                "metadata": {"document_count": 3, "retention_days": 30}
            }
        }


class JobResponse(BaseModel):
    """Job summary response."""
    id: str = Field(..., description="Job UUID")
    organization_id: str = Field(..., description="Organization UUID")
    user_id: Optional[str] = Field(None, description="User UUID who created the job")
    name: str = Field(..., description="Job name")
    description: Optional[str] = Field(None, description="Job description")
    status: str = Field(..., description="Job status (PENDING, QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED)")
    total_documents: int = Field(..., description="Total number of documents")
    completed_documents: int = Field(..., description="Number of completed documents")
    failed_documents: int = Field(..., description="Number of failed documents")
    created_at: datetime = Field(..., description="When job was created")
    queued_at: Optional[datetime] = Field(None, description="When job was queued")
    started_at: Optional[datetime] = Field(None, description="When job started processing")
    completed_at: Optional[datetime] = Field(None, description="When job completed")
    cancelled_at: Optional[datetime] = Field(None, description="When job was cancelled")
    expires_at: Optional[datetime] = Field(None, description="When job will be auto-deleted")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "organization_id": "04ace7c6-2043-4935-b074-ec0a567d1fd2",
                "user_id": "usr_123",
                "name": "Q1 Report Processing",
                "description": "Process all Q1 reports for analysis",
                "status": "RUNNING",
                "total_documents": 3,
                "completed_documents": 1,
                "failed_documents": 0,
                "created_at": "2026-01-15T10:00:00",
                "queued_at": "2026-01-15T10:00:01",
                "started_at": "2026-01-15T10:00:05",
                "completed_at": None,
                "cancelled_at": None,
                "expires_at": "2026-02-14T10:00:00"
            }
        }


class JobDetailResponse(JobResponse):
    """Detailed job response with documents and logs."""
    documents: List[JobDocumentResponse] = Field(..., description="Documents in this job")
    recent_logs: List[JobLogResponse] = Field(..., description="Recent log entries")
    processing_options: Dict[str, Any] = Field(..., description="Processing options used")
    results_summary: Optional[Dict[str, Any]] = Field(None, description="Aggregated results")
    error_message: Optional[str] = Field(None, description="Error message if job failed")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "organization_id": "04ace7c6-2043-4935-b074-ec0a567d1fd2",
                "user_id": "usr_123",
                "name": "Q1 Report Processing",
                "description": "Process all Q1 reports",
                "status": "RUNNING",
                "total_documents": 3,
                "completed_documents": 1,
                "failed_documents": 0,
                "created_at": "2026-01-15T10:00:00",
                "queued_at": "2026-01-15T10:00:01",
                "started_at": "2026-01-15T10:00:05",
                "completed_at": None,
                "cancelled_at": None,
                "expires_at": "2026-02-14T10:00:00",
                "documents": [],
                "recent_logs": [],
                "processing_options": {"apply_llm_evaluation": True},
                "results_summary": None,
                "error_message": None
            }
        }


class JobListResponse(BaseModel):
    """Paginated list of jobs."""
    jobs: List[JobResponse] = Field(..., description="List of jobs")
    total: int = Field(..., description="Total number of jobs (across all pages)")
    page: int = Field(..., description="Current page number (1-indexed)")
    page_size: int = Field(..., description="Number of items per page")
    total_pages: int = Field(..., description="Total number of pages")

    class Config:
        json_schema_extra = {
            "example": {
                "jobs": [],
                "total": 42,
                "page": 1,
                "page_size": 50,
                "total_pages": 1
            }
        }


class CancelJobResponse(BaseModel):
    """Response from job cancellation."""
    job_id: str = Field(..., description="Job UUID")
    status: str = Field(..., description="Updated job status")
    tasks_revoked: int = Field(..., description="Number of Celery tasks revoked")
    tasks_verified_stopped: int = Field(..., description="Number of tasks verified stopped")
    verification_timeout: bool = Field(..., description="Whether verification timed out")
    cancelled_at: Optional[datetime] = Field(None, description="Cancellation timestamp")
    message: Optional[str] = Field(None, description="Additional message")

    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "123e4567-e89b-12d3-a456-426614174000",
                "status": "CANCELLED",
                "tasks_revoked": 5,
                "tasks_verified_stopped": 5,
                "verification_timeout": False,
                "cancelled_at": "2026-01-15T10:05:00",
                "message": None
            }
        }


class UserJobStatsResponse(BaseModel):
    """Job statistics for a user."""
    active_jobs: int = Field(..., description="Number of active jobs (QUEUED or RUNNING)")
    total_jobs_24h: int = Field(..., description="Total jobs created in last 24 hours")
    total_jobs_7d: int = Field(..., description="Total jobs created in last 7 days")
    completed_jobs_24h: int = Field(..., description="Completed jobs in last 24 hours")
    failed_jobs_24h: int = Field(..., description="Failed jobs in last 24 hours")

    class Config:
        json_schema_extra = {
            "example": {
                "active_jobs": 2,
                "total_jobs_24h": 5,
                "total_jobs_7d": 18,
                "completed_jobs_24h": 3,
                "failed_jobs_24h": 0
            }
        }


class OrganizationJobStatsResponse(BaseModel):
    """Job statistics for an organization (admin only)."""
    active_jobs: int = Field(..., description="Number of active jobs")
    concurrency_limit: int = Field(..., description="Organization's concurrency limit")
    total_jobs_24h: int = Field(..., description="Total jobs created in last 24 hours")
    total_jobs_7d: int = Field(..., description="Total jobs created in last 7 days")
    total_jobs_30d: int = Field(..., description="Total jobs created in last 30 days")
    completed_jobs_24h: int = Field(..., description="Completed jobs in last 24 hours")
    failed_jobs_24h: int = Field(..., description="Failed jobs in last 24 hours")
    avg_processing_time_minutes: Optional[float] = Field(None, description="Average processing time in minutes")
    success_rate_7d: Optional[float] = Field(None, description="Success rate over last 7 days (0.0-1.0)")

    class Config:
        json_schema_extra = {
            "example": {
                "active_jobs": 3,
                "concurrency_limit": 5,
                "total_jobs_24h": 12,
                "total_jobs_7d": 45,
                "total_jobs_30d": 180,
                "completed_jobs_24h": 10,
                "failed_jobs_24h": 1,
                "avg_processing_time_minutes": 15.5,
                "success_rate_7d": 0.96
            }
        }


class DeleteJobResponse(BaseModel):
    """Response from job deletion."""
    job_id: str = Field(..., description="Job UUID")
    job_name: str = Field(..., description="Name of deleted job")
    documents_deleted: int = Field(..., description="Number of job documents deleted")
    files_deleted: int = Field(..., description="Number of processed files deleted from disk")
    logs_deleted: int = Field(..., description="Number of job log entries deleted")
    deleted_at: datetime = Field(..., description="Deletion timestamp")
    message: str = Field(..., description="Deletion summary message")

    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "123e4567-e89b-12d3-a456-426614174000",
                "job_name": "Q4 Report Processing",
                "documents_deleted": 5,
                "files_deleted": 4,
                "logs_deleted": 12,
                "deleted_at": "2026-01-16T10:30:00",
                "message": "Job deleted successfully. 5 documents and 4 processed files removed."
            }
        }


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
