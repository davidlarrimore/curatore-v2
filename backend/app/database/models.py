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
