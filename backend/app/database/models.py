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


class Job(Base):
    """
    Job model for batch document processing tracking.

    Represents a batch processing job that processes multiple documents.
    Jobs track overall progress, status, and results across all documents.

    Attributes:
        id: Unique job identifier
        organization_id: Organization that owns this job
        user_id: User who created this job (nullable for system jobs)
        name: Human-readable job name
        description: Optional job description
        job_type: Type of job (default: 'batch_processing')
        status: Current job status (PENDING, QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED)
        celery_batch_id: Celery batch identifier for grouping tasks
        total_documents: Total number of documents in job
        completed_documents: Number of completed documents
        failed_documents: Number of failed documents
        processing_options: Snapshot of processing options used (JSONB)
        results_summary: Aggregated quality scores and metrics (JSONB)
        error_message: Error message if job failed
        created_at: When job was created
        queued_at: When job was queued for processing
        started_at: When job started processing
        completed_at: When job completed (success or failure)
        cancelled_at: When job was cancelled
        expires_at: When job should be automatically deleted (based on retention policy)

    Relationships:
        organization: Organization that owns this job
        user: User who created this job
        documents: List of documents in this job
        logs: List of log entries for this job

    Job Status Flow:
        PENDING → QUEUED → RUNNING → COMPLETED/FAILED/CANCELLED
    """

    __tablename__ = "jobs"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Job metadata
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    job_type = Column(String(50), nullable=False, default="batch_processing")

    # Job status
    status = Column(String(50), nullable=False, default="PENDING", index=True)
    celery_batch_id = Column(String(255), nullable=True, index=True)

    # Progress tracking
    total_documents = Column(Integer, nullable=False, default=0)
    completed_documents = Column(Integer, nullable=False, default=0)
    failed_documents = Column(Integer, nullable=False, default=0)

    # Processing configuration and results
    processing_options = Column(JSON, nullable=False, default=dict, server_default="{}")
    results_summary = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    processed_folder = Column(String(255), nullable=True, index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    queued_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    # Relationships
    organization = relationship("Organization")
    user = relationship("User")
    documents = relationship(
        "JobDocument", back_populates="job", cascade="all, delete-orphan"
    )
    logs = relationship("JobLog", back_populates="job", cascade="all, delete-orphan")

    # Indexes for common queries
    __table_args__ = (
        Index("ix_jobs_org_created", "organization_id", "created_at"),
        Index("ix_jobs_org_status", "organization_id", "status"),
        Index("ix_jobs_user", "user_id", "created_at"),
        Index("ix_jobs_expires", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, name={self.name}, status={self.status})>"


class JobDocument(Base):
    """
    JobDocument model for tracking individual documents within a job.

    Represents a single document being processed as part of a batch job.
    Tracks document-level status, quality scores, and processing results.

    Attributes:
        id: Unique job document identifier
        job_id: Job this document belongs to
        document_id: Document identifier (UUID from storage)
        filename: Original filename
        file_path: Path to original file
        file_hash: SHA-256 hash for deduplication
        file_size: File size in bytes
        status: Document processing status (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED)
        celery_task_id: Individual Celery task ID
        conversion_score: Overall conversion quality score (0-100)
        quality_scores: Detailed quality metrics (JSONB)
        is_rag_ready: Whether document meets RAG quality thresholds
        error_message: Error message if processing failed
        created_at: When document was added to job
        started_at: When document processing started
        completed_at: When document processing completed
        processing_time_seconds: Total processing time
        processed_file_path: Path to processed markdown file

    Relationships:
        job: Job this document belongs to

    Document Status Flow:
        PENDING → RUNNING → COMPLETED/FAILED/CANCELLED
    """

    __tablename__ = "job_documents"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        UUID(), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Document identification
    document_id = Column(String(36), nullable=False, index=True)  # UUID or legacy doc_* format
    filename = Column(String(500), nullable=False)
    file_path = Column(Text, nullable=False)
    file_hash = Column(String(64), nullable=True)
    file_size = Column(Integer, nullable=True)

    # Processing status
    status = Column(String(50), nullable=False, default="PENDING", index=True)
    celery_task_id = Column(String(255), nullable=True, index=True)

    # Quality metrics
    conversion_score = Column(Integer, nullable=True)
    quality_scores = Column(JSON, nullable=True)
    is_rag_ready = Column(Boolean, nullable=False, default=False)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    processing_time_seconds = Column(Float, nullable=True)

    # Result
    processed_file_path = Column(Text, nullable=True)

    # Relationships
    job = relationship("Job", back_populates="documents")

    # Indexes for common queries
    __table_args__ = (
        Index("ix_job_docs_document", "document_id"),
        Index("ix_job_docs_celery_task", "celery_task_id"),
    )

    def __repr__(self) -> str:
        return f"<JobDocument(id={self.id}, document_id={self.document_id}, status={self.status})>"


class JobLog(Base):
    """
    JobLog model for job execution logs and audit trail.

    Stores log entries for job execution, including progress updates,
    errors, and document-level events. Provides audit trail and debugging.

    Attributes:
        id: Unique log entry identifier
        job_id: Job this log belongs to
        document_id: Document this log relates to (nullable for job-level logs)
        timestamp: When log entry was created
        level: Log level (INFO, SUCCESS, WARNING, ERROR)
        message: Log message
        log_metadata: Additional structured data (JSONB)

    Relationships:
        job: Job this log belongs to

    Log Levels:
        - INFO: General progress updates
        - SUCCESS: Successful operations
        - WARNING: Non-critical issues
        - ERROR: Errors and failures
    """

    __tablename__ = "job_logs"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    job_id = Column(
        UUID(), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id = Column(String(36), nullable=True, index=True)  # UUID or legacy doc_* format

    # Log details
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    level = Column(String(20), nullable=False, index=True)
    message = Column(Text, nullable=False)
    log_metadata = Column(JSON, nullable=True)

    # Relationships
    job = relationship("Job", back_populates="logs")

    # Indexes for common queries
    __table_args__ = (Index("ix_job_logs_job_ts", "job_id", "timestamp"),)

    def __repr__(self) -> str:
        return f"<JobLog(id={self.id}, job_id={self.job_id}, level={self.level})>"


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
        job_id: Job this artifact belongs to (nullable for adhoc uploads)
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
        job: Job this artifact belongs to

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
    job_id = Column(
        UUID(), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )

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
    job = relationship("Job")

    # Composite indexes for common queries
    __table_args__ = (
        Index("ix_artifacts_org_doc", "organization_id", "document_id"),
        Index("ix_artifacts_org_type", "organization_id", "artifact_type"),
        Index("ix_artifacts_bucket_key", "bucket", "object_key", unique=True),
        Index("ix_artifacts_doc_type", "document_id", "artifact_type"),
    )

    def __repr__(self) -> str:
        return f"<Artifact(id={self.id}, document_id={self.document_id}, type={self.artifact_type})>"
