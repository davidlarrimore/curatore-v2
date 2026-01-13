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
