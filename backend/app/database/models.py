# backend/app/database/models.py
"""
SQLAlchemy ORM models for Curatore v2 multi-tenant persistence architecture.

Models:
    - Organization: Tenant/organization with settings
    - User: User accounts with authentication
    - ApiKey: API keys for headless/backend access
    - Connection: Runtime-configurable service connections (SharePoint, LLM, etc.)
    - SystemSetting: Global system settings
    - AuditLog: Audit trail for configuration changes
    - Job: Batch job tracking for document processing
    - JobDocument: Per-document status within jobs
    - JobLog: Job execution logs and audit trail

All models use UUID primary keys and include timestamps for auditing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship

from .base import Base


# UUID type that works with both SQLite and PostgreSQL
class UUID(TypeDecorator):
    """Platform-independent UUID type.

    Uses PostgreSQL's UUID type when available, otherwise uses String(36).
    """
    impl = String
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return str(value)
        else:
            return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if not isinstance(value, uuid.UUID):
                return uuid.UUID(value)
            else:
                return value


class Organization(Base):
    """
    Organization (tenant) model.

    Represents a multi-tenant organization with users, connections, and settings.
    Each organization is isolated from others for data security.

    Attributes:
        id: Unique organization identifier
        name: Internal organization name (unique)
        display_name: Human-readable organization name
        slug: URL-friendly organization identifier (unique)
        is_active: Whether organization is active
        settings: JSONB field for org-level settings (quality thresholds, defaults, etc.)
        created_at: Timestamp when organization was created
        updated_at: Timestamp of last update
        created_by: User ID who created the organization (nullable for first org)

    Relationships:
        users: List of users belonging to this organization
        connections: List of connections owned by this organization
        api_keys: List of API keys for this organization
    """

    __tablename__ = "organizations"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True, index=True)
    display_name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    # Settings stored as JSONB for flexibility
    # Example: {"quality_thresholds": {...}, "auto_optimize": true, "default_connection_llm": "uuid"}
    settings = Column(JSON, nullable=False, default=dict, server_default="{}")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    created_by = Column(UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    users = relationship(
        "User",
        back_populates="organization",
        foreign_keys="User.organization_id",
        cascade="all, delete-orphan",
    )
    connections = relationship(
        "Connection", back_populates="organization", cascade="all, delete-orphan"
    )
    api_keys = relationship(
        "ApiKey", back_populates="organization", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Organization(id={self.id}, name={self.name}, slug={self.slug})>"


class User(Base):
    """
    User model with authentication and organization membership.

    Users belong to exactly one organization and have a role that determines
    their permissions within that organization.

    Attributes:
        id: Unique user identifier
        organization_id: Organization this user belongs to
        email: User's email address (unique, used for login)
        username: User's username (unique, used for login)
        password_hash: Bcrypt hashed password
        full_name: User's full name (optional)
        is_active: Whether user account is active
        is_verified: Whether user's email is verified
        role: User's role (org_admin, member, viewer)
        settings: JSONB field for user-specific settings overrides
        created_at: Timestamp when user was created
        updated_at: Timestamp of last update
        last_login_at: Timestamp of last successful login

    Relationships:
        organization: Organization this user belongs to
        api_keys: API keys created by this user
        created_connections: Connections created by this user
    """

    __tablename__ = "users"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Authentication
    email = Column(String(255), nullable=False, unique=True, index=True)
    username = Column(String(100), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)

    # Profile
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_verified = Column(Boolean, default=False, nullable=False)

    # Role: org_admin, member, viewer
    role = Column(String(50), nullable=False, default="member", index=True)

    # User-specific settings (optional overrides)
    settings = Column(JSON, nullable=False, default=dict, server_default="{}")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_login_at = Column(DateTime, nullable=True)

    # Relationships
    organization = relationship(
        "Organization", back_populates="users", foreign_keys=[organization_id]
    )
    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    created_connections = relationship(
        "Connection",
        back_populates="created_by_user",
        foreign_keys="Connection.created_by",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, email={self.email})>"


class EmailVerificationToken(Base):
    """
    Email verification token model.

    Stores tokens for email verification during user registration.
    Tokens expire after a configurable period (default 24 hours).

    Attributes:
        id: Unique token identifier
        user_id: User this token belongs to
        token: Verification token (unique, indexed)
        expires_at: Token expiration timestamp
        used_at: Timestamp when token was used (null if unused)
        created_at: Timestamp when token was created

    Relationships:
        user: User this token belongs to
    """

    __tablename__ = "email_verification_tokens"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token = Column(String(255), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User")

    def __repr__(self) -> str:
        return f"<EmailVerificationToken(id={self.id}, user_id={self.user_id})>"


class PasswordResetToken(Base):
    """
    Password reset token model.

    Stores tokens for password reset requests.
    Tokens expire after a short period (default 1 hour) for security.

    Attributes:
        id: Unique token identifier
        user_id: User this token belongs to
        token: Reset token (unique, indexed)
        expires_at: Token expiration timestamp
        used_at: Timestamp when token was used (null if unused)
        created_at: Timestamp when token was created

    Relationships:
        user: User this token belongs to
    """

    __tablename__ = "password_reset_tokens"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token = Column(String(255), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User")

    def __repr__(self) -> str:
        return f"<PasswordResetToken(id={self.id}, user_id={self.user_id})>"


class ApiKey(Base):
    """
    API Key model for headless/backend authentication.

    API keys provide programmatic access to the API without requiring
    user login. Each key is scoped to an organization and optionally a user.

    Attributes:
        id: Unique API key identifier
        organization_id: Organization this key belongs to
        user_id: User who created this key (nullable for org-wide keys)
        name: Human-readable name for the key
        key_hash: Bcrypt hashed API key (actual key shown only once on creation)
        prefix: First 12 characters of key for display (e.g., "cur_abcd1234")
        scopes: List of permission scopes (e.g., ["read:documents", "write:documents"])
        is_active: Whether key is active
        last_used_at: Timestamp of last use
        expires_at: Optional expiration timestamp
        created_at: Timestamp when key was created
        updated_at: Timestamp of last update

    Relationships:
        organization: Organization this key belongs to
        user: User who created this key
    """

    __tablename__ = "api_keys"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        UUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Key details
    name = Column(String(255), nullable=False)
    key_hash = Column(String(255), nullable=False, unique=True, index=True)
    prefix = Column(String(20), nullable=False, index=True)  # For display (e.g., "cur_1234abcd")

    # Permissions
    scopes = Column(JSON, nullable=False, default=list, server_default="[]")

    # Status
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    organization = relationship("Organization", back_populates="api_keys")
    user = relationship("User", back_populates="api_keys")

    def __repr__(self) -> str:
        return f"<ApiKey(id={self.id}, name={self.name}, prefix={self.prefix})>"


class Connection(Base):
    """
    Connection model for runtime-configurable service connections.

    Supports multiple connection types (SharePoint, LLM, Extraction, S3, etc.)
    with type-specific configuration stored as JSONB. Each connection can be
    tested for health and set as the default for its type.

    Attributes:
        id: Unique connection identifier
        organization_id: Organization that owns this connection
        name: Human-readable connection name
        description: Optional description
        connection_type: Type of connection (sharepoint, llm, extraction, s3, etc.)
        config: JSONB field for type-specific configuration
        is_active: Whether connection is active
        is_default: Whether this is the default connection for its type
        is_managed: Whether connection is managed by environment variables
        managed_by: Description of what manages this connection (e.g., env vars)
        last_tested_at: Timestamp of last health check
        test_status: Health check status (healthy, unhealthy, not_tested)
        test_result: Detailed test results (JSONB)
        scope: Connection scope (organization, user)
        owner_user_id: User who owns this connection (for user-scoped connections)
        created_by: User who created this connection
        created_at: Timestamp when connection was created
        updated_at: Timestamp of last update

    Relationships:
        organization: Organization that owns this connection
        created_by_user: User who created this connection
        owner_user: User who owns this connection (for user-scoped)

    Connection Type Examples:
        SharePoint: {"tenant_id": "...", "client_id": "...", "client_secret": "..."}
        LLM: {"api_key": "...", "model": "gpt-4", "base_url": "..."}
        Extraction: {"service_url": "...", "api_key": "...", "timeout": 60}
    """

    __tablename__ = "connections"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Connection metadata
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    connection_type = Column(String(50), nullable=False, index=True)

    # Configuration (JSONB for flexibility)
    config = Column(JSON, nullable=False)

    # Status
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_default = Column(Boolean, default=False, nullable=False)
    is_managed = Column(Boolean, default=False, nullable=False)
    managed_by = Column(String(255), nullable=True)

    # Health check
    last_tested_at = Column(DateTime, nullable=True)
    test_status = Column(String(20), nullable=True)  # healthy, unhealthy, not_tested
    test_result = Column(JSON, nullable=True)

    # Scope (organization-wide or user-specific)
    scope = Column(String(20), nullable=False, default="organization")  # organization, user
    owner_user_id = Column(
        UUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    created_by = Column(
        UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    organization = relationship("Organization", back_populates="connections")
    created_by_user = relationship(
        "User", back_populates="created_connections", foreign_keys=[created_by]
    )
    owner_user = relationship("User", foreign_keys=[owner_user_id])

    # Indexes for common queries
    __table_args__ = (
        Index("ix_connections_org_type", "organization_id", "connection_type"),
        Index(
            "ix_connections_org_type_default",
            "organization_id",
            "connection_type",
            "is_default",
        ),
    )

    def __repr__(self) -> str:
        return f"<Connection(id={self.id}, name={self.name}, type={self.connection_type})>"


class SystemSetting(Base):
    """
    System-wide settings model.

    Stores global configuration settings that apply across all organizations.
    Settings can be public (readable by all users) or private (admin only).

    Attributes:
        id: Unique setting identifier
        key: Setting key (unique)
        value: Setting value (JSONB for flexibility)
        description: Human-readable description
        is_public: Whether non-admin users can read this setting
        created_at: Timestamp when setting was created
        updated_at: Timestamp of last update
    """

    __tablename__ = "system_settings"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    key = Column(String(255), nullable=False, unique=True, index=True)
    value = Column(JSON, nullable=False)
    description = Column(Text, nullable=True)
    is_public = Column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<SystemSetting(key={self.key})>"


class AuditLog(Base):
    """
    Audit log model for tracking configuration changes and actions.

    Records all significant actions (create, update, delete, test) for
    organizations, users, connections, and settings. Includes user context,
    IP address, and detailed action information.

    Attributes:
        id: Unique log entry identifier
        organization_id: Organization context (nullable for system-level actions)
        user_id: User who performed the action (nullable for system actions)
        action: Action type (create_connection, update_user, login, etc.)
        entity_type: Type of entity affected (connection, user, api_key, etc.)
        entity_id: ID of affected entity
        details: Detailed action information (JSONB)
        ip_address: Client IP address
        user_agent: Client user agent string
        status: Action status (success, failure)
        error_message: Error message if action failed
        created_at: Timestamp when action occurred
    """

    __tablename__ = "audit_logs"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id = Column(
        UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Action details
    action = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(50), nullable=True, index=True)
    entity_id = Column(UUID(), nullable=True)

    # Details (JSONB for flexibility)
    details = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    # Status
    status = Column(String(20), nullable=False)  # success, failure
    error_message = Column(Text, nullable=True)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action={self.action}, status={self.status})>"


# NOTE: Job, JobDocument, and JobLog models have been removed.
# The Job system was deprecated in favor of the Run-based execution tracking.
# See migration 20260129_1300_drop_job_tables.py for details.
# All document processing now uses Asset, Run, and ExtractionResult models.


class Artifact(Base):
    """
    Artifact model for tracking files in object storage (MinIO/S3).

    Represents a single file stored in object storage, including both
    uploaded source files and processed output files. Replaces filesystem-based
    metadata tracking with database-backed tracking.

    Attributes:
        id: Unique artifact identifier
        organization_id: Organization that owns this artifact
        document_id: Document identifier (links uploaded/processed pairs)
        artifact_type: Type of artifact (uploaded, processed, temp)
        bucket: Object storage bucket name
        object_key: Full object key (path) in the bucket
        original_filename: Original filename from upload
        content_type: MIME type of the file
        file_size: File size in bytes
        etag: Object storage ETag (for caching/validation)
        file_hash: SHA-256 hash of content (optional, for reference)
        status: Artifact status (pending, available, deleted)
        metadata: Additional metadata (JSONB)
        created_at: When artifact was created
        updated_at: When artifact was last updated
        expires_at: When artifact should expire (for lifecycle)
        deleted_at: Soft delete timestamp

    Relationships:
        organization: Organization that owns this artifact

    Artifact Types:
        - uploaded: Original uploaded source file
        - processed: Processed markdown output
        - temp: Temporary processing file

    Status Flow:
        pending (upload in progress) → available (ready to use) → deleted (soft deleted)
    """

    __tablename__ = "artifacts"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id = Column(String(36), nullable=False, index=True)  # UUID or legacy doc_* format

    # Object storage location
    artifact_type = Column(String(50), nullable=False, index=True)  # uploaded, processed, temp
    bucket = Column(String(255), nullable=False)
    object_key = Column(String(1024), nullable=False)

    # File metadata
    original_filename = Column(String(500), nullable=False)
    content_type = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    etag = Column(String(255), nullable=True)
    file_hash = Column(String(64), nullable=True)  # SHA-256 for reference

    # Status tracking
    status = Column(String(50), nullable=False, default="pending", index=True)
    file_metadata = Column(JSON, nullable=False, default=dict, server_default="{}")

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    expires_at = Column(DateTime, nullable=True, index=True)
    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    organization = relationship("Organization")

    # Composite indexes for common queries
    __table_args__ = (
        Index("ix_artifacts_org_doc", "organization_id", "document_id"),
        Index("ix_artifacts_org_type", "organization_id", "artifact_type"),
        Index("ix_artifacts_bucket_key", "bucket", "object_key", unique=True),
        Index("ix_artifacts_doc_type", "document_id", "artifact_type"),
    )

    def __repr__(self) -> str:
        return f"<Artifact(id={self.id}, document_id={self.document_id}, type={self.artifact_type})>"


# ============================================================================
# Phase 0 Models: Asset-Centric Architecture
# ============================================================================


class Asset(Base):
    """
    Asset model representing a document with full provenance tracking.

    Assets are the canonical representation of documents in Curatore. Each asset
    has immutable raw content stored in object storage, automatic extraction,
    and full provenance information.

    This model is part of Phase 0: Stabilization & Baseline Observability.

    Attributes:
        id: Unique asset identifier
        organization_id: Organization that owns this asset
        source_type: Where asset came from (upload, sharepoint, web_scrape, sam_gov)
        source_metadata: JSONB with source-specific details (URL, timestamp, uploader, etc.)
        original_filename: Original filename from source
        content_type: MIME type of the asset
        file_size: File size in bytes
        file_hash: SHA-256 hash for content deduplication
        raw_bucket: Object storage bucket for raw content
        raw_object_key: Object storage key for raw content
        status: Asset status (pending, ready, failed, deleted)
        created_at: When asset was created
        updated_at: When asset was last updated
        created_by: User who created this asset (nullable for system ingestion)

    Relationships:
        organization: Organization that owns this asset
        user: User who created this asset
        extraction_results: List of extraction attempts for this asset
        runs_as_input: Runs that used this asset as input

    Asset Lifecycle:
        1. Asset created with raw content in object storage
        2. Automatic extraction triggered (creates ExtractionResult + Run)
        3. Asset becomes "ready" when extraction succeeds
        4. Asset may be reprocessed by multiple Runs
    """

    __tablename__ = "assets"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Source provenance
    source_type = Column(String(50), nullable=False, index=True)  # upload, sharepoint, web_scrape, sam_gov
    source_metadata = Column(JSON, nullable=False, default=dict, server_default="{}")

    # File metadata
    original_filename = Column(String(500), nullable=False)
    content_type = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)  # SHA-256 for deduplication

    # Object storage reference
    raw_bucket = Column(String(255), nullable=False)
    raw_object_key = Column(String(1024), nullable=False)

    # Status
    status = Column(String(50), nullable=False, default="pending", index=True)  # pending, ready, failed, deleted

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    created_by = Column(
        UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Phase 1: Version tracking
    current_version_number = Column(Integer, nullable=True, default=1)  # Track current version

    # Phase 2: Tiered Extraction
    # enhancement_eligible: Whether file type could benefit from Docling enhancement
    # Eligible types: PDF, DOCX, PPTX, DOC, PPT, XLS, XLSX (structured documents)
    enhancement_eligible = Column(Boolean, nullable=True, default=False)
    # enhancement_queued_at: When background enhancement was queued (null = not queued)
    enhancement_queued_at = Column(DateTime, nullable=True)
    # extraction_tier: Current extraction quality tier ('basic' = fast MarkItDown, 'enhanced' = Docling)
    extraction_tier = Column(String(50), nullable=True, default="basic")

    # Relationships
    organization = relationship("Organization")
    user = relationship("User")
    versions = relationship(
        "AssetVersion", back_populates="asset", cascade="all, delete-orphan", order_by="AssetVersion.version_number"
    )
    extraction_results = relationship(
        "ExtractionResult",
        back_populates="asset",
        cascade="all, delete-orphan",
        foreign_keys="ExtractionResult.asset_id",
    )

    # Indexes for common queries
    __table_args__ = (
        Index("ix_assets_org_created", "organization_id", "created_at"),
        Index("ix_assets_org_status", "organization_id", "status"),
        Index("ix_assets_hash", "file_hash"),
        Index("ix_assets_bucket_key", "raw_bucket", "raw_object_key", unique=True),
    )

    def __repr__(self) -> str:
        return f"<Asset(id={self.id}, filename={self.original_filename}, status={self.status})>"


class AssetVersion(Base):
    """
    AssetVersion model for immutable asset version tracking (Phase 1).

    Each time an asset's raw content changes, a new version is created.
    Versions are immutable - the raw content never changes after creation.
    Each version can have its own extraction results.

    This enables:
    - Version history (see all past versions of a document)
    - Re-extraction (extract any version again)
    - Non-destructive updates (old versions remain accessible)

    Attributes:
        id: Unique version identifier
        asset_id: Parent asset
        version_number: Sequential version number (1, 2, 3, ...)
        raw_bucket: Object storage bucket for this version's raw content
        raw_object_key: Object storage key for this version's raw content
        file_size: File size in bytes
        file_hash: SHA-256 hash of file content
        content_type: MIME type
        created_at: When this version was created
        created_by: User who created this version (nullable for system)
        is_current: Whether this is the current active version

    Relationships:
        asset: Parent asset
        extraction_results: Extraction results for this specific version

    Version Lifecycle:
        1. User uploads new version of file
        2. New AssetVersion created with version_number++
        3. Asset.current_version_id updated to point to new version
        4. Automatic extraction triggered for new version
        5. Old versions remain accessible for history
    """

    __tablename__ = "asset_versions"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    asset_id = Column(
        UUID(), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number = Column(Integer, nullable=False)

    # Raw content reference (immutable)
    raw_bucket = Column(String(255), nullable=False)
    raw_object_key = Column(String(1024), nullable=False)

    # File metadata (snapshot at creation time)
    file_size = Column(Integer, nullable=True)
    file_hash = Column(String(64), nullable=True)  # SHA-256
    content_type = Column(String(255), nullable=True)

    # Version tracking
    is_current = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(
        UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    asset = relationship("Asset", back_populates="versions")
    extraction_results = relationship(
        "ExtractionResult",
        back_populates="asset_version",
        cascade="all, delete-orphan",
        foreign_keys="ExtractionResult.asset_version_id",
    )

    # Indexes
    __table_args__ = (
        Index("ix_asset_versions_asset_id", "asset_id"),
        Index("ix_asset_versions_asset_version", "asset_id", "version_number", unique=True),
        Index("ix_asset_versions_current", "asset_id", "is_current"),
    )

    def __repr__(self) -> str:
        return f"<AssetVersion(id={self.id}, asset_id={self.asset_id}, version={self.version_number})>"


class Run(Base):
    """
    Run model representing any execution in Curatore.

    Runs are the universal execution tracking mechanism. Every background activity
    (extraction, processing, experiments, sync, maintenance) is represented as a Run.
    Runs are fully observable with structured logging and progress tracking.

    This model is part of Phase 0: Stabilization & Baseline Observability.

    Attributes:
        id: Unique run identifier
        organization_id: Organization context for this run
        run_type: Type of run (extraction, processing, experiment, system_maintenance, sync)
        origin: Who/what triggered the run (user, system, scheduled)
        status: Current run status (pending, running, completed, failed, cancelled)
        input_asset_ids: JSON array of asset IDs used as input
        config: JSONB with run-specific configuration
        progress: JSONB with progress tracking (current, total, unit, percent)
        results_summary: JSONB with aggregated results after completion
        error_message: Error message if run failed
        started_at: When run started executing
        completed_at: When run completed (success or failure)
        created_at: When run was created
        created_by: User who created this run (nullable for system runs)

    Relationships:
        organization: Organization context for this run
        user: User who created this run
        extraction_results: Extraction results produced by this run
        log_events: Structured log events for this run

    Run Status Transitions (Strict):
        pending → running → completed
        pending → running → failed
        pending → running → cancelled

    Run Types:
        - extraction: Automatic document extraction (system-triggered)
        - processing: User-triggered document processing
        - experiment: Experimental metadata generation
        - system_maintenance: GC, orphan cleanup, etc.
        - sync: Output synchronization to external systems
    """

    __tablename__ = "runs"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Run metadata
    run_type = Column(String(50), nullable=False, index=True)
    origin = Column(String(50), nullable=False, default="user")  # user, system, scheduled

    # Run status
    status = Column(String(50), nullable=False, default="pending", index=True)

    # Input and configuration
    input_asset_ids = Column(JSON, nullable=False, default=list, server_default="[]")
    config = Column(JSON, nullable=False, default=dict, server_default="{}")

    # Progress tracking
    progress = Column(JSON, nullable=True)  # {current, total, unit, percent}

    # Results
    results_summary = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_by = Column(
        UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    organization = relationship("Organization")
    user = relationship("User")
    extraction_results = relationship(
        "ExtractionResult", back_populates="run", cascade="all, delete-orphan"
    )
    log_events = relationship(
        "RunLogEvent", back_populates="run", cascade="all, delete-orphan"
    )

    # Indexes for common queries
    __table_args__ = (
        Index("ix_runs_org_created", "organization_id", "created_at"),
        Index("ix_runs_org_status", "organization_id", "status"),
        Index("ix_runs_type_status", "run_type", "status"),
    )

    def __repr__(self) -> str:
        return f"<Run(id={self.id}, type={self.run_type}, status={self.status})>"


class ExtractionResult(Base):
    """
    ExtractionResult model tracking document extraction attempts.

    Extraction is automatic platform infrastructure in Curatore. Every asset gets
    extracted to canonical markdown, and extraction attempts are tracked here.
    ExtractionResults are always produced by a Run and are version-tracked.

    This model is part of Phase 0: Stabilization & Baseline Observability.

    Attributes:
        id: Unique extraction result identifier
        asset_id: Asset that was extracted
        run_id: Run that performed the extraction
        extractor_version: Version of extraction engine used (e.g., "markitdown-1.0")
        status: Extraction status (pending, running, completed, failed)
        extracted_bucket: Object storage bucket for extracted content
        extracted_object_key: Object storage key for extracted markdown
        structure_metadata: JSONB with structural information (sections, pages, etc.)
        warnings: JSON array of non-fatal warnings
        errors: JSON array of errors (if failed)
        extraction_time_seconds: Time taken to extract
        created_at: When extraction started

    Relationships:
        asset: Asset that was extracted
        run: Run that performed the extraction

    Extraction Lifecycle:
        1. Asset created → triggers automatic extraction Run
        2. ExtractionResult created in "pending" status
        3. Extraction executes → status becomes "running"
        4. On success → status "completed", extracted content stored
        5. On failure → status "failed", errors recorded (non-blocking)

    Important Notes:
        - Extraction failures are visible but non-blocking
        - Multiple extraction attempts may exist per asset (version changes)
        - Extraction is always attributed to a Run
    """

    __tablename__ = "extraction_results"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    asset_id = Column(
        UUID(), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id = Column(
        UUID(), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Phase 1: Link to specific asset version
    asset_version_id = Column(
        UUID(), ForeignKey("asset_versions.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Extractor information
    extractor_version = Column(String(100), nullable=False)

    # Phase 2: Tiered Extraction
    # extraction_tier: Quality tier of this extraction ('basic' = fast MarkItDown, 'enhanced' = Docling)
    extraction_tier = Column(String(50), nullable=True, default="basic")

    # Extraction status
    status = Column(String(50), nullable=False, default="pending", index=True)

    # Extracted content reference
    extracted_bucket = Column(String(255), nullable=True)
    extracted_object_key = Column(String(1024), nullable=True)

    # Structural metadata (for hierarchical extraction in Phase 4+)
    structure_metadata = Column(JSON, nullable=True)

    # Warnings and errors
    warnings = Column(JSON, nullable=False, default=list, server_default="[]")
    errors = Column(JSON, nullable=False, default=list, server_default="[]")

    # Performance metrics
    extraction_time_seconds = Column(Float, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    asset = relationship("Asset", back_populates="extraction_results")
    run = relationship("Run", back_populates="extraction_results")
    asset_version = relationship("AssetVersion", back_populates="extraction_results")

    # Indexes for common queries
    __table_args__ = (
        Index("ix_extraction_asset_status", "asset_id", "status"),
        Index("ix_extraction_run", "run_id"),
    )

    def __repr__(self) -> str:
        return f"<ExtractionResult(id={self.id}, asset_id={self.asset_id}, status={self.status})>"


class RunLogEvent(Base):
    """
    RunLogEvent model for structured run logging.

    Provides structured, queryable logging for all run activity. Stores
    human-readable messages alongside machine-readable context for debugging,
    auditing, and UI timelines. Replaces ad-hoc logging patterns.

    This model is part of Phase 0: Stabilization & Baseline Observability.

    Attributes:
        id: Unique log event identifier
        run_id: Run this event belongs to
        level: Log level (INFO, WARN, ERROR)
        event_type: Event classification (start, progress, retry, error, summary)
        message: Human-readable message
        context: JSONB with machine-readable context
        created_at: When event occurred

    Relationships:
        run: Run this event belongs to

    Log Levels:
        - INFO: General progress and informational messages
        - WARN: Non-critical issues or warnings
        - ERROR: Errors and failures

    Event Types:
        - start: Run started
        - progress: Progress update
        - retry: Retry attempt
        - error: Error occurred
        - summary: Final summary (for maintenance runs)

    Usage Pattern:
        - Store events in DB for queryability
        - UI shows structured events by default
        - Full verbose logs (stack traces) go to object store if needed
        - Progress events update Run.progress field
    """

    __tablename__ = "run_log_events"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Event details
    level = Column(String(20), nullable=False, index=True)  # INFO, WARN, ERROR
    event_type = Column(String(50), nullable=False, index=True)  # start, progress, retry, error, summary
    message = Column(Text, nullable=False)
    context = Column(JSON, nullable=True)  # Machine-readable details

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    run = relationship("Run", back_populates="log_events")

    # Indexes for common queries
    __table_args__ = (
        Index("ix_run_log_run_created", "run_id", "created_at"),
        Index("ix_run_log_level", "level"),
    )

    def __repr__(self) -> str:
        return f"<RunLogEvent(id={self.id}, run_id={self.run_id}, level={self.level}, type={self.event_type})>"


# ============================================================================
# Phase 3 Models: Flexible Metadata & Experimentation
# ============================================================================


class AssetMetadata(Base):
    """
    AssetMetadata model for flexible, versioned document metadata (Phase 3).

    Stores derived metadata as first-class artifacts, enabling LLM-driven iteration
    without schema churn. Supports both canonical (production) and experimental
    metadata, with explicit promotion mechanics.

    Key Concepts:
    - Metadata is stored as artifacts, not hard-coded columns
    - Each asset can have multiple metadata types (topics, summary, tags, etc.)
    - Canonical metadata: Single active version per type per asset, used by default
    - Experimental metadata: Multiple variants, attributed to runs, promotable

    Attributes:
        id: Unique metadata identifier
        asset_id: Asset this metadata belongs to
        metadata_type: Type of metadata (e.g., "topics.v1", "summary.short.v1", "tags.llm.v1")
        schema_version: Schema version for this metadata type
        producer_run_id: Run that produced this metadata (nullable for system-generated)
        is_canonical: Whether this is the canonical (production) metadata for its type
        status: Lifecycle status (active, superseded, deprecated)
        metadata_content: The actual metadata payload (JSONB)
        metadata_object_ref: Optional object store reference for large payloads
        created_at: When metadata was created
        promoted_at: When metadata was promoted to canonical (if applicable)
        promoted_from_id: ID of experimental metadata this was promoted from
        superseded_at: When this metadata was superseded by newer canonical
        superseded_by_id: ID of metadata that superseded this one

    Relationships:
        asset: Asset this metadata belongs to
        producer_run: Run that produced this metadata
        superseded_by: Metadata that superseded this one
        supersedes: Metadata that this one superseded

    Metadata Types (Examples):
        - topics.v1: List of topics/themes
        - summary.short.v1: Brief summary (1-2 sentences)
        - summary.long.v1: Detailed summary
        - tags.llm.v1: LLM-generated tags
        - entities.v1: Extracted entities (people, orgs, etc.)
        - classification.v1: Document classification

    Status Transitions:
        active → superseded (when newer canonical is promoted)
        active → deprecated (when manually deprecated)

    Promotion Flow:
        1. Experimental metadata created by experiment Run
        2. User compares experimental variants
        3. User promotes selected experimental to canonical
        4. Previous canonical (if any) marked superseded
        5. Promoted metadata marked is_canonical=True

    Usage:
        # Create experimental metadata from run
        metadata = AssetMetadata(
            asset_id=asset_id,
            metadata_type="summary.short.v1",
            schema_version="1.0",
            producer_run_id=run_id,
            is_canonical=False,
            status="active",
            metadata_content={"summary": "Document describes..."},
        )

        # Promote to canonical
        await asset_metadata_service.promote_to_canonical(metadata_id)
    """

    __tablename__ = "asset_metadata"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    asset_id = Column(
        UUID(), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Metadata type and version
    metadata_type = Column(String(100), nullable=False, index=True)  # e.g., "topics.v1", "summary.short.v1"
    schema_version = Column(String(50), nullable=False, default="1.0")

    # Attribution
    producer_run_id = Column(
        UUID(), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Canonical vs Experimental
    is_canonical = Column(Boolean, nullable=False, default=False, index=True)

    # Status (active, superseded, deprecated)
    status = Column(String(50), nullable=False, default="active", index=True)

    # Metadata content (JSONB for flexibility)
    # For most metadata, this is the primary storage
    metadata_content = Column(JSON, nullable=False, default=dict, server_default="{}")

    # Optional object store reference for large payloads
    metadata_object_ref = Column(String(1024), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    promoted_at = Column(DateTime, nullable=True)  # When promoted to canonical
    superseded_at = Column(DateTime, nullable=True)  # When superseded by newer canonical

    # Promotion and supersession tracking
    promoted_from_id = Column(
        UUID(), ForeignKey("asset_metadata.id", ondelete="SET NULL"), nullable=True
    )
    superseded_by_id = Column(
        UUID(), ForeignKey("asset_metadata.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    asset = relationship("Asset", backref="metadata_records")
    producer_run = relationship("Run", backref="produced_metadata")
    superseded_by = relationship(
        "AssetMetadata",
        foreign_keys=[superseded_by_id],
        remote_side="AssetMetadata.id",
        backref="supersedes",
    )
    promoted_from = relationship(
        "AssetMetadata",
        foreign_keys=[promoted_from_id],
        remote_side="AssetMetadata.id",
    )

    # Indexes for common queries
    __table_args__ = (
        # Find canonical metadata for an asset
        Index("ix_asset_metadata_asset_canonical", "asset_id", "is_canonical"),
        # Find canonical metadata by type for an asset
        Index("ix_asset_metadata_asset_type_canonical", "asset_id", "metadata_type", "is_canonical"),
        # Find metadata by run
        Index("ix_asset_metadata_run", "producer_run_id"),
        # Find active metadata for an asset by type
        Index("ix_asset_metadata_asset_type_status", "asset_id", "metadata_type", "status"),
    )

    def __repr__(self) -> str:
        return f"<AssetMetadata(id={self.id}, asset_id={self.asset_id}, type={self.metadata_type}, canonical={self.is_canonical})>"


# ============================================================================
# Phase 4 Models: Web Scraping as Durable Data Source
# ============================================================================


class ScrapeCollection(Base):
    """
    ScrapeCollection model for managing web scraping collections (Phase 4).

    A collection groups related scraped content from one or more URL sources.
    Supports two behavioral modes:
    - Snapshot Mode: Focus on current site state, pages are primary
    - Record-Preserving Mode: Focus on durable records, never auto-delete

    Key Concepts:
    - Collections contain pages (ephemeral discovery assets) and records (durable assets)
    - Records are promoted from pages and are never auto-deleted
    - Re-crawls create new versions, preserving history
    - Hierarchical path metadata enables tree-based browsing

    Attributes:
        id: Unique collection identifier
        organization_id: Organization that owns this collection
        name: Collection name (display)
        slug: URL-friendly identifier (unique within org)
        description: Optional description
        collection_mode: snapshot or record_preserving
        root_url: Primary URL for this collection
        url_patterns: JSONB array of URL patterns to include/exclude
        crawl_config: JSONB with crawl settings (depth, rate limit, etc.)
        status: Collection status (active, paused, archived)
        last_crawl_at: When collection was last crawled
        last_crawl_run_id: Run ID of last crawl
        stats: JSONB with collection statistics (page_count, record_count, etc.)

    Relationships:
        organization: Organization that owns this collection
        sources: URL sources in this collection
        crawl_runs: Runs associated with this collection
    """

    __tablename__ = "scrape_collections"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Collection metadata
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Collection mode: snapshot or record_preserving
    # - snapshot: Pages are primary, limited retention, focus on current state
    # - record_preserving: Records promoted to permanent assets, never auto-delete
    collection_mode = Column(String(50), nullable=False, default="record_preserving")

    # Root URL and patterns
    root_url = Column(String(2048), nullable=False)
    url_patterns = Column(JSON, nullable=False, default=list, server_default="[]")
    # url_patterns format: [{"pattern": "...", "type": "include|exclude"}]

    # Crawl configuration
    crawl_config = Column(JSON, nullable=False, default=dict, server_default="{}")
    # crawl_config may include:
    # - max_depth: Maximum crawl depth
    # - max_pages: Maximum pages to crawl
    # - rate_limit: Requests per second
    # - user_agent: Custom user agent
    # - follow_robots: Whether to respect robots.txt

    # Status
    status = Column(String(50), nullable=False, default="active", index=True)
    # active, paused, archived

    # Crawl tracking
    last_crawl_at = Column(DateTime, nullable=True)
    last_crawl_run_id = Column(
        UUID(), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )

    # Statistics (denormalized for performance)
    stats = Column(JSON, nullable=False, default=dict, server_default="{}")
    # stats may include: page_count, record_count, total_size, last_updated

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    created_by = Column(
        UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    organization = relationship("Organization")
    sources = relationship(
        "ScrapeSource",
        back_populates="collection",
        cascade="all, delete-orphan",
    )
    last_crawl_run = relationship("Run", foreign_keys=[last_crawl_run_id])

    # Indexes
    __table_args__ = (
        Index("ix_scrape_collections_org_slug", "organization_id", "slug", unique=True),
        Index("ix_scrape_collections_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<ScrapeCollection(id={self.id}, name={self.name}, mode={self.collection_mode})>"


class ScrapeSource(Base):
    """
    ScrapeSource model for URL sources within a collection (Phase 4).

    Each source represents a specific URL or URL pattern to crawl within
    a collection. Sources can be configured independently for crawl behavior.

    Attributes:
        id: Unique source identifier
        collection_id: Parent collection
        url: Source URL to crawl
        source_type: Type of source (seed, discovered, manual)
        is_active: Whether to include in crawls
        crawl_config: Source-specific crawl config (overrides collection config)
        last_crawl_at: When this source was last crawled
        last_status: Status of last crawl (success, failed, skipped)
        discovered_pages: Count of pages discovered from this source
        created_at: When source was added

    Relationships:
        collection: Parent collection
    """

    __tablename__ = "scrape_sources"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    collection_id = Column(
        UUID(), ForeignKey("scrape_collections.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Source URL
    url = Column(String(2048), nullable=False)
    source_type = Column(String(50), nullable=False, default="seed")
    # seed: Manually added starting URL
    # discovered: Found during crawl
    # manual: Manually added specific page

    # Status
    is_active = Column(Boolean, nullable=False, default=True)

    # Source-specific config (overrides collection config)
    crawl_config = Column(JSON, nullable=True)

    # Crawl tracking
    last_crawl_at = Column(DateTime, nullable=True)
    last_status = Column(String(50), nullable=True)  # success, failed, skipped
    discovered_pages = Column(Integer, nullable=False, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    collection = relationship("ScrapeCollection", back_populates="sources")

    # Indexes
    __table_args__ = (
        Index("ix_scrape_sources_collection_url", "collection_id", "url"),
        Index("ix_scrape_sources_collection_active", "collection_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<ScrapeSource(id={self.id}, url={self.url[:50]}...)>"


class ScrapedAsset(Base):
    """
    ScrapedAsset model linking assets to scrape collections (Phase 4).

    This is a junction table that adds scrape-specific metadata to assets.
    Supports hierarchical path metadata for tree-based browsing.

    Key Concepts:
    - Assets are created via normal Asset model
    - ScrapedAsset adds scrape-specific context
    - asset_subtype distinguishes pages from records
    - url_path enables hierarchical browsing

    Asset Subtypes:
    - page: Ephemeral discovery asset (listings, navigation, indexes)
    - record: Durable captured asset (RFPs, notices, attachments)

    Attributes:
        id: Unique identifier
        asset_id: Reference to Asset
        collection_id: Reference to ScrapeCollection
        source_id: Reference to ScrapeSource (nullable)
        asset_subtype: page or record
        url: Original URL this asset was scraped from
        url_path: Hierarchical path (e.g., "/opportunities/active/12345")
        parent_url: URL of the page that linked to this asset
        crawl_depth: Depth at which this was discovered
        crawl_run_id: Run that discovered this asset
        is_promoted: Whether page has been promoted to record
        promoted_at: When promoted to record
        promoted_by: User who promoted to record
        scrape_metadata: JSONB with scrape-specific metadata

    Relationships:
        asset: The underlying Asset
        collection: Parent collection
        source: Source that discovered this
        crawl_run: Run that discovered this
    """

    __tablename__ = "scraped_assets"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    asset_id = Column(
        UUID(), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    collection_id = Column(
        UUID(), ForeignKey("scrape_collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id = Column(
        UUID(), ForeignKey("scrape_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Asset subtype: page or record
    # - page: Ephemeral, GC-eligible, discovery mechanism
    # - record: Durable, never auto-deleted, first-class asset
    asset_subtype = Column(String(50), nullable=False, default="page", index=True)

    # URL and hierarchy
    url = Column(String(2048), nullable=False)
    url_path = Column(String(2048), nullable=True)  # Hierarchical path for tree browsing
    parent_url = Column(String(2048), nullable=True)  # URL that linked to this

    # Crawl context
    crawl_depth = Column(Integer, nullable=False, default=0)
    crawl_run_id = Column(
        UUID(), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Promotion tracking (page → record)
    is_promoted = Column(Boolean, nullable=False, default=False, index=True)
    promoted_at = Column(DateTime, nullable=True)
    promoted_by = Column(
        UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Scrape-specific metadata
    scrape_metadata = Column(JSON, nullable=False, default=dict, server_default="{}")
    # May include: title, description, links_found, content_type, http_status, etc.

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    asset = relationship("Asset", backref="scraped_info")
    collection = relationship("ScrapeCollection", backref="scraped_assets")
    source = relationship("ScrapeSource", backref="scraped_assets")
    crawl_run = relationship("Run", foreign_keys=[crawl_run_id])

    # Indexes for common queries
    __table_args__ = (
        # Find all assets in a collection
        Index("ix_scraped_assets_collection", "collection_id"),
        # Find assets by URL path (tree browsing)
        Index("ix_scraped_assets_collection_path", "collection_id", "url_path"),
        # Find pages vs records
        Index("ix_scraped_assets_collection_subtype", "collection_id", "asset_subtype"),
        # Find promoted records
        Index("ix_scraped_assets_collection_promoted", "collection_id", "is_promoted"),
        # Find assets from specific crawl
        Index("ix_scraped_assets_crawl_run", "crawl_run_id"),
        # Ensure no duplicate URLs in collection
        Index("ix_scraped_assets_collection_url", "collection_id", "url", unique=True),
    )

    def __repr__(self) -> str:
        return f"<ScrapedAsset(id={self.id}, url={self.url[:50]}..., subtype={self.asset_subtype})>"


# ============================================================================
# Phase 5 Models: System Maintenance & Scheduling
# ============================================================================


class ScheduledTask(Base):
    """
    ScheduledTask model for database-backed scheduled maintenance tasks (Phase 5).

    This model enables admin visibility and control over scheduled tasks that
    were previously hardcoded in Celery Beat configuration. Tasks can be
    enabled/disabled, triggered manually, and have their schedules modified
    at runtime without service restarts.

    Key Concepts:
    - Global tasks (organization_id=None) run system-wide maintenance
    - Organization tasks run maintenance scoped to a specific org
    - Tasks create Runs with run_type="system_maintenance" and origin="scheduled"
    - Task execution is tracked via last_run_id linking to Run model

    Task Types:
    - gc.cleanup: Garbage collection (expired jobs, orphaned files)
    - orphan.detect: Find orphaned objects (assets without extraction, etc.)
    - retention.enforce: Enforce data retention policies
    - health.report: Generate system health summary

    Scope Types:
    - global: Runs across all organizations
    - organization: Runs for a specific organization

    Attributes:
        id: Unique task identifier
        organization_id: Organization scope (nullable for global tasks)
        name: Internal task name (unique, used for lookups)
        display_name: Human-readable name for UI
        description: Task description
        task_type: Type of maintenance task
        scope_type: global or organization
        schedule_expression: Cron expression (e.g., "0 3 * * *" for daily 3 AM)
        enabled: Whether task is active
        config: JSONB for task-specific settings
        last_run_id: Reference to most recent Run
        last_run_at: When task last executed
        last_run_status: Status of last run (success, failed)
        next_run_at: Calculated next execution time
        created_at: When task was created
        updated_at: When task was last modified

    Relationships:
        organization: Organization this task belongs to (for scoped tasks)
        last_run: Most recent Run for this task

    Usage:
        # Create a global cleanup task
        task = ScheduledTask(
            name="cleanup_expired_jobs",
            display_name="Cleanup Expired Jobs",
            task_type="gc.cleanup",
            scope_type="global",
            schedule_expression="0 3 * * *",  # Daily at 3 AM
            enabled=True,
            config={"dry_run": False}
        )

        # Trigger task manually
        await scheduled_task_service.trigger_task_now(task.id)
    """

    __tablename__ = "scheduled_tasks"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Task identification
    name = Column(String(100), nullable=False, unique=True, index=True)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Task classification
    task_type = Column(String(50), nullable=False, index=True)
    # gc.cleanup, orphan.detect, retention.enforce, health.report
    scope_type = Column(String(50), nullable=False, default="global")
    # global, organization

    # Schedule
    schedule_expression = Column(String(100), nullable=False)  # Cron format: "0 3 * * *"
    enabled = Column(Boolean, nullable=False, default=True, index=True)

    # Configuration
    config = Column(JSON, nullable=False, default=dict, server_default="{}")

    # Execution tracking
    last_run_id = Column(
        UUID(), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String(50), nullable=True)  # success, failed
    next_run_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    organization = relationship("Organization", backref="scheduled_tasks")
    last_run = relationship("Run", foreign_keys=[last_run_id])

    # Indexes for common queries
    __table_args__ = (
        Index("ix_scheduled_tasks_enabled", "enabled"),
        Index("ix_scheduled_tasks_task_type", "task_type"),
        Index("ix_scheduled_tasks_org_enabled", "organization_id", "enabled"),
        Index("ix_scheduled_tasks_next_run", "next_run_at"),
    )

    def __repr__(self) -> str:
        return f"<ScheduledTask(id={self.id}, name={self.name}, enabled={self.enabled})>"


# ============================================================================
# Phase 7 Models: SAM.gov Domain Integration
# ============================================================================


class SamSearch(Base):
    """
    SamSearch model for managing SAM.gov opportunity searches (Phase 7).

    A search defines a set of filters for pulling opportunities from SAM.gov API.
    Similar to ScrapeCollection for web scraping, this is the top-level entity
    for organizing SAM.gov data ingestion.

    Key Concepts:
    - Each search has a unique configuration (NAICS codes, agencies, etc.)
    - Searches can be scheduled for automatic pulls
    - Tracks solicitation and notice counts for quick stats
    - Supports multiple pull frequencies (manual, hourly, daily)

    Attributes:
        id: Unique search identifier
        organization_id: Organization that owns this search
        name: Display name for the search
        slug: URL-friendly identifier (unique within org)
        description: Optional description
        search_config: JSONB with filter configuration
        status: Search status (active, paused, archived)
        is_active: Whether search is enabled
        last_pull_at: Timestamp of last pull
        last_pull_status: Status of last pull (success, failed, partial)
        last_pull_run_id: Run ID of last pull
        pull_frequency: How often to pull (manual, hourly, daily)

    search_config Example:
        {
            "naics_codes": ["541512", "541519"],
            "psc_codes": ["D302", "D307"],
            "set_aside_codes": ["SBA", "8A"],
            "agencies": ["DEPT OF DEFENSE"],
            "notice_types": ["o", "p", "k"],
            "posted_from": "2024-01-01",
            "posted_to": "2024-12-31",
            "active_only": true,
            "keyword": "software development"
        }

    Relationships:
        organization: Organization that owns this search
        last_pull_run: Most recent pull Run

    Note: Solicitations are NOT directly linked to searches. They exist
    organization-wide and may match multiple search configurations.
    """

    __tablename__ = "sam_searches"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Search metadata
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Search configuration (NAICS, agencies, dates, etc.)
    search_config = Column(JSON, nullable=False, default=dict, server_default="{}")

    # Status
    status = Column(String(50), nullable=False, default="active", index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    # Pull tracking
    last_pull_at = Column(DateTime, nullable=True)
    last_pull_status = Column(String(50), nullable=True)  # success, failed, partial
    last_pull_run_id = Column(
        UUID(), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    pull_frequency = Column(String(50), nullable=False, default="manual")  # manual, hourly, daily

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    created_by = Column(
        UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    organization = relationship("Organization", backref="sam_searches")
    last_pull_run = relationship("Run", foreign_keys=[last_pull_run_id])

    # Indexes
    __table_args__ = (
        Index("ix_sam_searches_org_slug", "organization_id", "slug", unique=True),
        Index("ix_sam_searches_org_status", "organization_id", "status"),
        Index("ix_sam_searches_org_active", "organization_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<SamSearch(id={self.id}, name={self.name}, status={self.status})>"


class SamAgency(Base):
    """
    SamAgency model for SAM.gov agency reference data (Phase 7).

    Stores agency information from SAM.gov for denormalization and display.
    Agencies are the top-level organizational units in federal contracting.

    Attributes:
        id: Unique agency identifier
        code: SAM.gov agency code (e.g., "DOD", "HHS")
        name: Full agency name
        abbreviation: Common abbreviation
        is_active: Whether agency is currently active

    Relationships:
        sub_agencies: List of sub-agencies under this agency
    """

    __tablename__ = "sam_agencies"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), nullable=False, unique=True, index=True)
    name = Column(String(500), nullable=False)
    abbreviation = Column(String(50), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    sub_agencies = relationship(
        "SamSubAgency",
        back_populates="agency",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<SamAgency(id={self.id}, code={self.code}, name={self.name})>"


class SamSubAgency(Base):
    """
    SamSubAgency model for SAM.gov sub-agency reference data (Phase 7).

    Sub-agencies are organizational units within agencies that issue contracts.
    Examples: Army, Navy, Air Force under DOD.

    Attributes:
        id: Unique sub-agency identifier
        agency_id: Parent agency
        code: SAM.gov sub-agency code
        name: Full sub-agency name
        abbreviation: Common abbreviation
        is_active: Whether sub-agency is currently active

    Relationships:
        agency: Parent agency
        solicitations: Solicitations from this sub-agency
    """

    __tablename__ = "sam_sub_agencies"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    agency_id = Column(
        UUID(), ForeignKey("sam_agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code = Column(String(50), nullable=False, index=True)
    name = Column(String(500), nullable=False)
    abbreviation = Column(String(50), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    agency = relationship("SamAgency", back_populates="sub_agencies")
    solicitations = relationship("SamSolicitation", back_populates="sub_agency")

    # Indexes
    __table_args__ = (
        Index("ix_sam_sub_agencies_agency_code", "agency_id", "code", unique=True),
    )

    def __repr__(self) -> str:
        return f"<SamSubAgency(id={self.id}, code={self.code}, name={self.name})>"


class SamSolicitation(Base):
    """
    SamSolicitation model for tracking federal contract opportunities (Phase 7).

    Represents a single solicitation/opportunity from SAM.gov. Solicitations
    go through a lifecycle (posted → active → awarded/cancelled) and may
    have multiple notices (amendments, modifications).

    Key Concepts:
    - notice_id is the SAM.gov unique identifier
    - solicitation_number is the contract number
    - Multiple notices track version history (amendments)
    - Attachments become Assets for extraction

    Notice Types:
    - o: Combined Synopsis/Solicitation
    - p: Presolicitation
    - k: Sources Sought
    - r: Special Notice
    - s: Award Notice
    - a: Amendment

    Attributes:
        id: Unique solicitation identifier
        organization_id: Organization that owns this solicitation
        sub_agency_id: Issuing sub-agency (optional)
        notice_id: SAM.gov unique notice ID
        solicitation_number: Contract number
        title: Opportunity title
        description: Full description
        notice_type: Type code (o, p, k, r, s)
        naics_code: NAICS classification
        psc_code: Product/Service code
        set_aside_code: Set-aside type (SBA, 8A, etc.)
        status: Opportunity status (active, awarded, cancelled)
        posted_date: Original post date
        response_deadline: Due date for responses
        archive_date: When opportunity was archived
        ui_link: Link to SAM.gov UI
        api_link: Link to SAM.gov API
        notice_count: Number of notices/versions
        attachment_count: Number of attachments
        summary_status: Auto-summary status (pending, generating, ready, failed, no_llm)
        summary_generated_at: When AI summary was generated

    Relationships:
        organization: Owning organization
        sub_agency: Issuing sub-agency
        notices: Version history
        attachments: Linked files
        summaries: LLM-generated summaries

    Note: Solicitations are NOT directly linked to searches. They exist
    organization-wide and may match multiple search configurations.
    """

    __tablename__ = "sam_solicitations"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sub_agency_id = Column(
        UUID(), ForeignKey("sam_sub_agencies.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # SAM.gov identifiers
    notice_id = Column(String(100), nullable=False, unique=True, index=True)
    solicitation_number = Column(String(255), nullable=True, index=True)

    # Opportunity details
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    notice_type = Column(String(50), nullable=False, index=True)  # o, p, k, r, s

    # Organization hierarchy (parsed from fullParentPathName: AGENCY.BUREAU.OFFICE)
    agency_name = Column(String(500), nullable=True, index=True)
    bureau_name = Column(String(500), nullable=True, index=True)
    office_name = Column(String(500), nullable=True)
    full_parent_path = Column(String(1000), nullable=True)  # Original fullParentPathName

    # Classification
    naics_code = Column(String(20), nullable=True, index=True)
    psc_code = Column(String(20), nullable=True, index=True)
    set_aside_code = Column(String(50), nullable=True, index=True)

    # Status
    status = Column(String(50), nullable=False, default="active", index=True)
    # active, awarded, cancelled, archived

    # Important dates
    posted_date = Column(DateTime, nullable=True, index=True)
    response_deadline = Column(DateTime, nullable=True, index=True)
    archive_date = Column(DateTime, nullable=True)

    # Links
    ui_link = Column(String(1000), nullable=True)
    api_link = Column(String(1000), nullable=True)

    # Contact information (JSONB for flexibility)
    contact_info = Column(JSON, nullable=True)

    # Place of performance (JSONB)
    place_of_performance = Column(JSON, nullable=True)

    # Denormalized counts
    notice_count = Column(Integer, nullable=False, default=1)
    attachment_count = Column(Integer, nullable=False, default=0)

    # Auto-summary tracking (Phase 7.6)
    # Values: pending, generating, ready, failed, no_llm
    summary_status = Column(String(50), nullable=True, default="pending", index=True)
    summary_generated_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    organization = relationship("Organization", backref="sam_solicitations")
    sub_agency = relationship("SamSubAgency", back_populates="solicitations")
    notices = relationship(
        "SamNotice",
        back_populates="solicitation",
        cascade="all, delete-orphan",
        order_by="SamNotice.version_number",
    )
    attachments = relationship(
        "SamAttachment",
        back_populates="solicitation",
        cascade="all, delete-orphan",
    )
    summaries = relationship(
        "SamSolicitationSummary",
        back_populates="solicitation",
        cascade="all, delete-orphan",
    )

    # Indexes
    __table_args__ = (
        Index("ix_sam_solicitations_org_status", "organization_id", "status"),
        Index("ix_sam_solicitations_deadline", "response_deadline"),
        Index("ix_sam_solicitations_posted", "posted_date"),
    )

    def __repr__(self) -> str:
        return f"<SamSolicitation(id={self.id}, notice_id={self.notice_id}, title={self.title[:50]}...)>"


class SamNotice(Base):
    """
    SamNotice model for tracking solicitation version history (Phase 7).

    Each time a solicitation is amended or modified, a new notice is created.
    This enables tracking changes over time and comparing versions.

    Key Concepts:
    - version_number=1 is the original posting
    - version_number>1 represents amendments
    - Raw JSON is stored in object storage for full data preservation
    - changes_summary can be AI-generated to explain differences

    Attributes:
        id: Unique notice identifier
        solicitation_id: Parent solicitation
        sam_notice_id: SAM.gov notice ID for this version
        notice_type: Type code (same as solicitation, or 'a' for amendment)
        version_number: Sequential version (1=original, 2+=amendments)
        title: Title at this version
        description: Description at this version
        posted_date: When this version was posted
        response_deadline: Deadline at this version
        raw_json_bucket: MinIO bucket for raw JSON
        raw_json_key: MinIO key for raw JSON
        changes_summary: AI-generated summary of changes from previous version

    Relationships:
        solicitation: Parent solicitation
        attachments: Attachments added in this notice
    """

    __tablename__ = "sam_notices"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)

    # Parent solicitation - NULLABLE for standalone notices (e.g., Special Notices)
    solicitation_id = Column(
        UUID(), ForeignKey("sam_solicitations.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # For standalone notices (when solicitation_id is NULL)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # SAM.gov identifiers
    sam_notice_id = Column(String(100), nullable=False, index=True)
    notice_type = Column(String(50), nullable=False)  # o, p, k, r, s, a (amendment)

    # Version tracking
    version_number = Column(Integer, nullable=False, default=1)

    # Snapshot of data at this version
    title = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    posted_date = Column(DateTime, nullable=True)
    response_deadline = Column(DateTime, nullable=True)

    # Classification (for standalone notices)
    naics_code = Column(String(20), nullable=True)
    psc_code = Column(String(20), nullable=True)
    set_aside_code = Column(String(50), nullable=True)

    # Organization hierarchy (for standalone notices)
    agency_name = Column(String(500), nullable=True)
    bureau_name = Column(String(500), nullable=True)
    office_name = Column(String(500), nullable=True)

    # Links
    ui_link = Column(String(500), nullable=True)

    # Raw API response storage
    raw_json_bucket = Column(String(255), nullable=True)
    raw_json_key = Column(String(500), nullable=True)

    # Change tracking
    changes_summary = Column(Text, nullable=True)  # AI-generated or manual

    # AI Summary (similar to SamSolicitation)
    summary_status = Column(String(50), nullable=True, default="pending")
    # Values: pending, generating, ready, failed, no_llm
    summary_generated_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    solicitation = relationship("SamSolicitation", back_populates="notices")
    attachments = relationship(
        "SamAttachment",
        back_populates="notice",
        cascade="all, delete-orphan",
    )

    # Indexes - updated for nullable solicitation_id
    __table_args__ = (
        Index("ix_sam_notices_sol_version", "solicitation_id", "version_number", unique=True,
              postgresql_where=Column("solicitation_id").isnot(None)),
        Index("ix_sam_notices_sam_id", "sam_notice_id"),
        Index("ix_sam_notices_org", "organization_id"),
        Index("ix_sam_notices_standalone", "organization_id", "sam_notice_id",
              postgresql_where=Column("solicitation_id").is_(None)),
    )

    def __repr__(self) -> str:
        return f"<SamNotice(id={self.id}, solicitation_id={self.solicitation_id}, version={self.version_number})>"


class SamAttachment(Base):
    """
    SamAttachment model linking SAM.gov attachments to Assets (Phase 7).

    Attachments are files associated with solicitations (SOWs, pricing templates,
    etc.). When downloaded, they become Assets and trigger automatic extraction.

    Key Concepts:
    - resource_id is SAM.gov's identifier for the attachment
    - asset_id links to the downloaded Asset (nullable until downloaded)
    - download_status tracks the download lifecycle
    - Downloading creates an Asset with source_type='sam_gov'

    Attributes:
        id: Unique attachment identifier
        solicitation_id: Parent solicitation
        notice_id: Notice that introduced this attachment
        asset_id: Linked Asset after download
        resource_id: SAM.gov resource identifier
        filename: Original filename
        file_type: File extension (pdf, docx, etc.)
        file_size: Size in bytes
        download_url: SAM.gov download URL
        download_status: pending, downloaded, failed, skipped
        downloaded_at: When file was downloaded
        download_error: Error message if download failed

    Relationships:
        solicitation: Parent solicitation
        notice: Notice that introduced this
        asset: Downloaded Asset
    """

    __tablename__ = "sam_attachments"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    # Nullable for standalone notice attachments
    solicitation_id = Column(
        UUID(), ForeignKey("sam_solicitations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    notice_id = Column(
        UUID(), ForeignKey("sam_notices.id", ondelete="CASCADE"), nullable=True, index=True
    )
    asset_id = Column(
        UUID(), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # SAM.gov identifiers
    resource_id = Column(String(255), nullable=False, index=True)

    # File metadata
    filename = Column(String(500), nullable=False)
    file_type = Column(String(100), nullable=True)  # pdf, docx, xlsx, etc.
    file_size = Column(Integer, nullable=True)  # bytes
    description = Column(Text, nullable=True)

    # Download information
    download_url = Column(String(1000), nullable=True)
    download_status = Column(String(50), nullable=False, default="pending", index=True)
    # pending, downloading, downloaded, failed, skipped
    downloaded_at = Column(DateTime, nullable=True)
    download_error = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    solicitation = relationship("SamSolicitation", back_populates="attachments")
    notice = relationship("SamNotice", back_populates="attachments")
    asset = relationship("Asset", backref="sam_attachment")

    # Indexes
    __table_args__ = (
        Index("ix_sam_attachments_sol_status", "solicitation_id", "download_status"),
        Index("ix_sam_attachments_resource", "resource_id"),
    )

    def __repr__(self) -> str:
        return f"<SamAttachment(id={self.id}, filename={self.filename}, status={self.download_status})>"


class SamSolicitationSummary(Base):
    """
    SamSolicitationSummary model for LLM-generated analysis (Phase 7).

    Stores AI-generated summaries and analysis of solicitations. Integrates
    with the AssetMetadata experiment system for comparing different prompts
    and models.

    Key Concepts:
    - Multiple summaries can exist per solicitation (experiments)
    - is_canonical marks the promoted/active summary
    - Links to AssetMetadata for experiment tracking
    - Structured extraction (key_requirements, compliance_checklist)

    Summary Types:
    - full: Comprehensive analysis
    - executive: Brief executive summary
    - technical: Technical requirements focus
    - compliance: Compliance/eligibility focus

    Attributes:
        id: Unique summary identifier
        solicitation_id: Parent solicitation
        asset_metadata_id: Link to experiment system
        summary_type: Type of summary (full, executive, technical)
        is_canonical: Whether this is the active summary
        model: LLM model used
        prompt_template: Prompt used for generation
        summary: Generated summary text
        key_requirements: Structured key requirements (JSONB)
        compliance_checklist: Compliance items (JSONB)
        confidence_score: Quality/confidence score
        token_count: Tokens used for generation

    Relationships:
        solicitation: Parent solicitation
        asset_metadata: Experiment tracking
    """

    __tablename__ = "sam_solicitation_summaries"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    solicitation_id = Column(
        UUID(), ForeignKey("sam_solicitations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_metadata_id = Column(
        UUID(), ForeignKey("asset_metadata.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Summary classification
    summary_type = Column(String(50), nullable=False, default="full")
    # full, executive, technical, compliance
    is_canonical = Column(Boolean, nullable=False, default=False, index=True)

    # Generation metadata
    model = Column(String(100), nullable=False)
    prompt_template = Column(Text, nullable=True)
    prompt_version = Column(String(50), nullable=True)

    # Generated content
    summary = Column(Text, nullable=False)
    key_requirements = Column(JSON, nullable=True)
    # Example: [{"category": "Technical", "requirement": "...", "mandatory": true}]
    compliance_checklist = Column(JSON, nullable=True)
    # Example: [{"item": "Small Business", "eligible": true, "notes": "..."}]

    # Quality metrics
    confidence_score = Column(Float, nullable=True)
    token_count = Column(Integer, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    promoted_at = Column(DateTime, nullable=True)

    # Relationships
    solicitation = relationship("SamSolicitation", back_populates="summaries")
    asset_metadata = relationship("AssetMetadata", backref="sam_summaries")

    # Indexes
    __table_args__ = (
        Index("ix_sam_summaries_sol_canonical", "solicitation_id", "is_canonical"),
        Index("ix_sam_summaries_sol_type", "solicitation_id", "summary_type"),
    )

    def __repr__(self) -> str:
        return f"<SamSolicitationSummary(id={self.id}, type={self.summary_type}, canonical={self.is_canonical})>"


class SamApiUsage(Base):
    """
    Tracks daily SAM.gov API usage per organization.

    SAM.gov enforces a 1,000 calls per day limit. This model tracks
    usage to prevent going over limits and to show users their
    remaining API budget.

    Attributes:
        id: Unique usage record identifier
        organization_id: Organization this usage belongs to
        date: The date this usage record is for (UTC)
        search_calls: Number of search API calls
        detail_calls: Number of opportunity detail calls
        attachment_calls: Number of attachment download calls
        total_calls: Total API calls (computed)
        daily_limit: Maximum allowed calls per day
        reset_at: When the daily limit resets (midnight UTC next day)

    Usage:
        - Each organization has one record per day
        - Reset daily at midnight UTC
        - Used to check limits before making API calls
    """

    __tablename__ = "sam_api_usage"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Date for this usage record (one per day per org)
    date = Column(Date, nullable=False, index=True)

    # Call counts by type
    search_calls = Column(Integer, nullable=False, default=0)
    detail_calls = Column(Integer, nullable=False, default=0)
    attachment_calls = Column(Integer, nullable=False, default=0)

    # Total and limits
    total_calls = Column(Integer, nullable=False, default=0)
    daily_limit = Column(Integer, nullable=False, default=1000)

    # Reset timing
    reset_at = Column(DateTime, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    organization = relationship("Organization", backref="sam_api_usage")

    # Unique constraint: one record per org per day
    __table_args__ = (
        Index("ix_sam_api_usage_org_date", "organization_id", "date", unique=True),
    )

    @property
    def remaining_calls(self) -> int:
        """Calculate remaining API calls for today."""
        return max(0, self.daily_limit - self.total_calls)

    @property
    def usage_percent(self) -> float:
        """Calculate usage percentage."""
        if self.daily_limit == 0:
            return 100.0
        return (self.total_calls / self.daily_limit) * 100

    def __repr__(self) -> str:
        return f"<SamApiUsage(org={self.organization_id}, date={self.date}, used={self.total_calls}/{self.daily_limit})>"


class SamQueuedRequest(Base):
    """
    Stores deferred SAM.gov API calls when rate limit is exceeded.

    When an organization exceeds their daily API limit, requests
    are queued here for execution after the limit resets.

    Attributes:
        id: Unique queued request identifier
        organization_id: Organization this request belongs to
        request_type: Type of request (search, detail, attachment)
        status: Request status (pending, processing, completed, failed, cancelled)
        request_params: JSON parameters for the request
        search_id: Associated search (if applicable)
        solicitation_id: Associated solicitation (if applicable)
        attachment_id: Associated attachment (if applicable)
        scheduled_for: Earliest time to execute (after limit reset)
        priority: Priority order (lower = higher priority)
        attempts: Number of execution attempts
        last_error: Last error message if failed
        result: Stored result after successful execution

    Lifecycle:
        1. Created when API limit exceeded
        2. Picked up by scheduled task after limit resets
        3. Executed and marked completed/failed
        4. Cleaned up after retention period
    """

    __tablename__ = "sam_queued_requests"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Request type and status
    request_type = Column(String(50), nullable=False)  # search, detail, attachment
    status = Column(String(50), nullable=False, default="pending", index=True)
    # pending, processing, completed, failed, cancelled

    # Request parameters (stored as JSON)
    request_params = Column(JSON, nullable=False, default=dict)
    # Example for search: {"naics_codes": ["541512"], "posted_from": "2024-01-01"}
    # Example for detail: {"notice_id": "abc123"}
    # Example for attachment: {"resource_id": "xyz789", "download_url": "https://..."}

    # Related entities (optional, for context)
    search_id = Column(UUID(), ForeignKey("sam_searches.id", ondelete="SET NULL"), nullable=True)
    solicitation_id = Column(UUID(), ForeignKey("sam_solicitations.id", ondelete="SET NULL"), nullable=True)
    attachment_id = Column(UUID(), ForeignKey("sam_attachments.id", ondelete="SET NULL"), nullable=True)

    # Scheduling
    scheduled_for = Column(DateTime, nullable=False, index=True)  # When to execute
    priority = Column(Integer, nullable=False, default=100)  # Lower = higher priority

    # Execution tracking
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    last_attempt_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    # Result storage (for completed requests)
    result = Column(JSON, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    organization = relationship("Organization", backref="sam_queued_requests")
    search = relationship("SamSearch", backref="queued_requests")
    solicitation = relationship("SamSolicitation", backref="queued_requests")
    attachment = relationship("SamAttachment", backref="queued_requests")

    # Indexes
    __table_args__ = (
        Index("ix_sam_queued_org_status", "organization_id", "status"),
        Index("ix_sam_queued_scheduled", "status", "scheduled_for"),
        Index("ix_sam_queued_priority", "status", "priority", "scheduled_for"),
    )

    def __repr__(self) -> str:
        return f"<SamQueuedRequest(id={self.id}, type={self.request_type}, status={self.status})>"
