"""Add user_organization_memberships table for multi-org access

Creates a many-to-many table so users can belong to multiple organizations.
Seeds existing users' organization_id into the new table.

Revision ID: user_org_memberships
Revises: simplify_roles
Create Date: 2026-02-15
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "user_org_memberships"
down_revision = "simplify_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_organization_memberships",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "organization_id", name="uq_user_org_membership"),
    )
    op.create_index("ix_user_org_memberships_user_id", "user_organization_memberships", ["user_id"])
    op.create_index("ix_user_org_memberships_organization_id", "user_organization_memberships", ["organization_id"])

    # Seed: create membership rows for all existing users that have an organization_id
    op.execute(
        """
        INSERT INTO user_organization_memberships (id, user_id, organization_id, created_at)
        SELECT gen_random_uuid(), id, organization_id, now()
        FROM users
        WHERE organization_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_user_org_memberships_organization_id", table_name="user_organization_memberships")
    op.drop_index("ix_user_org_memberships_user_id", table_name="user_organization_memberships")
    op.drop_table("user_organization_memberships")
