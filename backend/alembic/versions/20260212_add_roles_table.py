"""Add roles lookup table

Creates a roles table to store valid role definitions and adds a foreign key
constraint on users.role to ensure only valid roles can be assigned.

Revision ID: add_roles_table
Revises: multi_org_admin
Create Date: 2026-02-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers
revision = "add_roles_table"
down_revision = "multi_org_admin"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def constraint_exists(table_name: str, constraint_name: str) -> bool:
    """Check if a foreign key constraint exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    for fk in inspector.get_foreign_keys(table_name):
        if fk.get("name") == constraint_name:
            return True
    return False


def upgrade() -> None:
    # 1. Create roles table
    if not table_exists("roles"):
        op.create_table(
            "roles",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(50), unique=True, nullable=False),
            sa.Column("display_name", sa.String(100), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("is_system_role", sa.Boolean, nullable=False, default=False, server_default="false"),
            sa.Column("can_manage_users", sa.Boolean, nullable=False, default=False, server_default="false"),
            sa.Column("can_manage_org", sa.Boolean, nullable=False, default=False, server_default="false"),
            sa.Column("can_manage_system", sa.Boolean, nullable=False, default=False, server_default="false"),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_roles_name", "roles", ["name"], unique=True)

    # 2. Insert default roles (explicitly include created_at and updated_at)
    op.execute("""
        INSERT INTO roles (name, display_name, description, is_system_role, can_manage_users, can_manage_org, can_manage_system, created_at, updated_at)
        VALUES
            ('admin', 'System Admin', 'System-wide administrator with access to all organizations and system settings', true, true, true, true, NOW(), NOW()),
            ('org_admin', 'Org Admin', 'Organization administrator who can manage users, connections, and org settings', false, true, true, false, NOW(), NOW()),
            ('member', 'Member', 'Standard organization member who can create and manage content', false, false, false, false, NOW(), NOW()),
            ('viewer', 'Viewer', 'Read-only access to organization content', false, false, false, false, NOW(), NOW())
        ON CONFLICT (name) DO NOTHING
    """)

    # 3. Add foreign key constraint on users.role
    # First, ensure all existing roles are valid
    op.execute("""
        UPDATE users
        SET role = 'member'
        WHERE role NOT IN ('admin', 'org_admin', 'member', 'viewer')
    """)

    # Add the foreign key constraint
    if not constraint_exists("users", "fk_users_role"):
        op.create_foreign_key(
            "fk_users_role",
            "users",
            "roles",
            ["role"],
            ["name"],
            onupdate="CASCADE",
            ondelete="RESTRICT"
        )


def downgrade() -> None:
    # Remove foreign key constraint
    if constraint_exists("users", "fk_users_role"):
        op.drop_constraint("fk_users_role", "users", type_="foreignkey")

    # Drop roles table
    if table_exists("roles"):
        op.drop_index("ix_roles_name", table_name="roles")
        op.drop_table("roles")
