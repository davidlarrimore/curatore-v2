"""Add multi-org admin support

This migration adds:
1. Admin role to users (system-wide admin with null organization_id)
2. Services table for system-scoped infrastructure (LLM, extraction, playwright)
3. System scope for connections (organization_id nullable for system-scoped)
4. OrganizationConnection table for per-org connection enablement
5. ServiceAccount table for org-scoped API clients
6. API key support for service accounts

The admin role enables cross-organization access and system administration.
Regular users continue to belong to exactly one organization.

Revision ID: multi_org_admin
Revises: consolidate_scheduled_tasks
Create Date: 2026-02-12
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy import inspect

# revision identifiers
revision = "multi_org_admin"
down_revision = "consolidate_scheduled_tasks"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def constraint_exists(table_name: str, constraint_name: str) -> bool:
    """Check if a constraint exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    # Check check constraints
    for constraint in inspector.get_check_constraints(table_name):
        if constraint["name"] == constraint_name:
            return True
    return False


def index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = [idx["name"] for idx in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade() -> None:
    # 1. Create services table for system-scoped infrastructure
    if not table_exists("services"):
        op.create_table(
            "services",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            sa.Column("name", sa.String(100), nullable=False, unique=True),
            sa.Column("service_type", sa.String(50), nullable=False),  # llm, extraction, browser
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("config", JSONB, nullable=False, server_default="{}"),
            sa.Column("is_active", sa.Boolean, nullable=False, default=True, server_default="true"),
            sa.Column("last_tested_at", sa.DateTime, nullable=True),
            sa.Column("test_status", sa.String(20), nullable=True),  # healthy, unhealthy, not_tested
            sa.Column("test_result", JSONB, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )

    if not index_exists("services", "ix_services_name"):
        op.create_index("ix_services_name", "services", ["name"], unique=True)
    if not index_exists("services", "ix_services_type"):
        op.create_index("ix_services_type", "services", ["service_type"])
    if not index_exists("services", "ix_services_active"):
        op.create_index("ix_services_active", "services", ["is_active"])

    # 2. Make users.organization_id nullable (for admin users)
    # Check current column state and alter if needed
    bind = op.get_bind()
    inspector = inspect(bind)
    user_cols = {col["name"]: col for col in inspector.get_columns("users")}
    if user_cols.get("organization_id", {}).get("nullable") is False:
        op.alter_column(
            "users",
            "organization_id",
            existing_type=UUID(as_uuid=True),
            nullable=True,
        )

    # 3. Add 'system' to scope options and make organization_id nullable on connections
    conn_cols = {col["name"]: col for col in inspector.get_columns("connections")}
    if conn_cols.get("organization_id", {}).get("nullable") is False:
        op.alter_column(
            "connections",
            "organization_id",
            existing_type=UUID(as_uuid=True),
            nullable=True,
        )

    # Add check constraint for connection scope validity
    if not constraint_exists("connections", "chk_connection_scope"):
        op.execute("""
            ALTER TABLE connections
            ADD CONSTRAINT chk_connection_scope CHECK (
                (scope = 'system' AND organization_id IS NULL) OR
                (scope IN ('organization', 'user') AND organization_id IS NOT NULL)
            )
        """)

    # 4. Create organization_connections table for per-org connection enablement
    if not table_exists("organization_connections"):
        op.create_table(
            "organization_connections",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "connection_id",
                UUID(as_uuid=True),
                sa.ForeignKey("connections.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("is_enabled", sa.Boolean, nullable=False, default=True, server_default="true"),
            sa.Column("enabled_at", sa.DateTime, nullable=True),
            sa.Column(
                "enabled_by",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("config_overrides", JSONB, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("organization_id", "connection_id", name="uq_org_connection"),
        )

    if table_exists("organization_connections"):
        if not index_exists("organization_connections", "ix_org_connections_org"):
            op.create_index("ix_org_connections_org", "organization_connections", ["organization_id"])
        if not index_exists("organization_connections", "ix_org_connections_conn"):
            op.create_index("ix_org_connections_conn", "organization_connections", ["connection_id"])
        if not index_exists("organization_connections", "ix_org_connections_enabled"):
            op.create_index("ix_org_connections_enabled", "organization_connections", ["is_enabled"])

    # 5. Create service_accounts table for org-scoped API clients
    if not table_exists("service_accounts"):
        op.create_table(
            "service_accounts",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(50), nullable=False, default="member", server_default="member"),
            sa.Column("is_active", sa.Boolean, nullable=False, default=True, server_default="true"),
            sa.Column(
                "created_by",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("last_used_at", sa.DateTime, nullable=True),
            sa.UniqueConstraint("organization_id", "name", name="uq_service_account_org_name"),
        )

    if table_exists("service_accounts"):
        if not index_exists("service_accounts", "ix_service_accounts_org"):
            op.create_index("ix_service_accounts_org", "service_accounts", ["organization_id"])
        if not index_exists("service_accounts", "ix_service_accounts_active"):
            op.create_index("ix_service_accounts_active", "service_accounts", ["is_active"])

    # 6. Add service_account_id to api_keys and update constraint
    if not column_exists("api_keys", "service_account_id"):
        op.add_column(
            "api_keys",
            sa.Column(
                "service_account_id",
                UUID(as_uuid=True),
                sa.ForeignKey("service_accounts.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )

    if not index_exists("api_keys", "ix_api_keys_service_account"):
        op.create_index("ix_api_keys_service_account", "api_keys", ["service_account_id"])

    # Add check constraint: exactly one of user_id or service_account_id must be set
    if not constraint_exists("api_keys", "chk_api_key_owner"):
        op.execute("""
            ALTER TABLE api_keys
            ADD CONSTRAINT chk_api_key_owner CHECK (
                (user_id IS NOT NULL AND service_account_id IS NULL) OR
                (user_id IS NULL AND service_account_id IS NOT NULL)
            )
        """)


def downgrade() -> None:
    # Remove check constraint from api_keys
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS chk_api_key_owner")

    # Remove service_account_id from api_keys
    if index_exists("api_keys", "ix_api_keys_service_account"):
        op.drop_index("ix_api_keys_service_account", table_name="api_keys")
    if column_exists("api_keys", "service_account_id"):
        op.drop_column("api_keys", "service_account_id")

    # Drop service_accounts table
    if table_exists("service_accounts"):
        if index_exists("service_accounts", "ix_service_accounts_active"):
            op.drop_index("ix_service_accounts_active", table_name="service_accounts")
        if index_exists("service_accounts", "ix_service_accounts_org"):
            op.drop_index("ix_service_accounts_org", table_name="service_accounts")
        op.drop_table("service_accounts")

    # Drop organization_connections table
    if table_exists("organization_connections"):
        if index_exists("organization_connections", "ix_org_connections_enabled"):
            op.drop_index("ix_org_connections_enabled", table_name="organization_connections")
        if index_exists("organization_connections", "ix_org_connections_conn"):
            op.drop_index("ix_org_connections_conn", table_name="organization_connections")
        if index_exists("organization_connections", "ix_org_connections_org"):
            op.drop_index("ix_org_connections_org", table_name="organization_connections")
        op.drop_table("organization_connections")

    # Remove check constraint from connections
    op.execute("ALTER TABLE connections DROP CONSTRAINT IF EXISTS chk_connection_scope")

    # Make connections.organization_id non-nullable again
    # Note: This will fail if any system-scoped connections exist
    op.alter_column(
        "connections",
        "organization_id",
        existing_type=UUID(as_uuid=True),
        nullable=False,
    )

    # Make users.organization_id non-nullable again
    # Note: This will fail if any admin users exist
    op.alter_column(
        "users",
        "organization_id",
        existing_type=UUID(as_uuid=True),
        nullable=False,
    )

    # Drop services table
    if table_exists("services"):
        if index_exists("services", "ix_services_active"):
            op.drop_index("ix_services_active", table_name="services")
        if index_exists("services", "ix_services_type"):
            op.drop_index("ix_services_type", table_name="services")
        if index_exists("services", "ix_services_name"):
            op.drop_index("ix_services_name", table_name="services")
        op.drop_table("services")
