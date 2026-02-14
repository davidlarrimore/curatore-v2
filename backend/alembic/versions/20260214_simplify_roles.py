"""Simplify roles from 4 (admin, org_admin, member, viewer) to 2 (admin, member)

Converts org_admin and viewer users to member role, removes unused role rows.

Revision ID: simplify_roles
Revises: collection_chunks_table
Create Date: 2026-02-14
"""

from alembic import op

# revision identifiers
revision = "simplify_roles"
down_revision = "collection_chunks_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Convert org_admin and viewer users to member
    op.execute("UPDATE users SET role = 'member' WHERE role IN ('org_admin', 'viewer')")

    # Convert viewer service accounts to member
    op.execute("UPDATE service_accounts SET role = 'member' WHERE role = 'viewer'")

    # Remove unused role rows
    op.execute("DELETE FROM roles WHERE name IN ('org_admin', 'viewer')")

    # Update member role description
    op.execute(
        "UPDATE roles SET description = 'Organization member with data access and CWR tool usage' "
        "WHERE name = 'member'"
    )


def downgrade() -> None:
    # Re-insert removed role rows (no user data rollback)
    op.execute(
        "INSERT INTO roles (name, display_name, description, is_system_role, "
        "can_manage_users, can_manage_org, can_manage_system) VALUES "
        "('org_admin', 'Organization Admin', 'Organization administrator with full org management', "
        "false, true, true, false)"
    )
    op.execute(
        "INSERT INTO roles (name, display_name, description, is_system_role, "
        "can_manage_users, can_manage_org, can_manage_system) VALUES "
        "('viewer', 'Viewer', 'Read-only organization member', "
        "false, false, false, false)"
    )
