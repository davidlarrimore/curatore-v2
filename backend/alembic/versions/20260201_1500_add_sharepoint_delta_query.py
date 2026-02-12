"""Add delta query support to SharePoint sync configs.

Revision ID: 20260201_1500
Revises: 20260201_0900
Create Date: 2026-02-01 15:00:00.000000

This migration adds columns to support Microsoft Graph Delta Query for
incremental SharePoint synchronization:
- delta_token: Opaque token from Microsoft Graph delta API
- delta_enabled: Whether to use delta query for incremental syncs
- last_delta_sync_at: When delta token was last used successfully
- delta_token_acquired_at: When current delta token was first obtained
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260201_1500"
down_revision = "20260201_0900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add delta query columns to sharepoint_sync_configs table
    op.add_column(
        "sharepoint_sync_configs",
        sa.Column("delta_token", sa.String(4096), nullable=True),
    )
    op.add_column(
        "sharepoint_sync_configs",
        sa.Column("delta_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "sharepoint_sync_configs",
        sa.Column("last_delta_sync_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "sharepoint_sync_configs",
        sa.Column("delta_token_acquired_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sharepoint_sync_configs", "delta_token_acquired_at")
    op.drop_column("sharepoint_sync_configs", "last_delta_sync_at")
    op.drop_column("sharepoint_sync_configs", "delta_enabled")
    op.drop_column("sharepoint_sync_configs", "delta_token")
