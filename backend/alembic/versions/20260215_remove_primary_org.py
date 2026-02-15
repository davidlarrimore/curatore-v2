"""Remove primary org — memberships are now source of truth

Backfills any missing membership rows from users.organization_id,
then NULLs out organization_id so all org association goes through
user_organization_memberships.

Revision ID: remove_primary_org
Revises: user_org_memberships
Create Date: 2026-02-15
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "remove_primary_org"
down_revision = "user_org_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Backfill any missing membership rows for users that have organization_id
    #    but no corresponding membership (belt-and-suspenders — the prior migration
    #    already seeded, but this catches any users created between migrations)
    op.execute(
        """
        INSERT INTO user_organization_memberships (id, user_id, organization_id, created_at)
        SELECT gen_random_uuid(), u.id, u.organization_id, now()
        FROM users u
        WHERE u.organization_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM user_organization_memberships m
            WHERE m.user_id = u.id AND m.organization_id = u.organization_id
          )
        """
    )

    # 2. NULL out organization_id — memberships are the source of truth
    op.execute("UPDATE users SET organization_id = NULL")


def downgrade() -> None:
    # Restore organization_id from first membership (by created_at)
    op.execute(
        """
        UPDATE users u
        SET organization_id = sub.organization_id
        FROM (
            SELECT DISTINCT ON (user_id) user_id, organization_id
            FROM user_organization_memberships
            ORDER BY user_id, created_at ASC
        ) sub
        WHERE u.id = sub.user_id
          AND u.organization_id IS NULL
        """
    )
