"""Add automation_config field to sharepoint_sync_configs and scrape_collections tables.

Revision ID: 20260203_add_automation_config
Revises: 20260203_add_spawned_by_parent
Create Date: 2026-02-03 20:00:00.000000

This migration adds:
- sharepoint_sync_configs.automation_config: JSONB field for procedure/pipeline automation
  settings (e.g., after_procedure_slug to run after sync completes)
- scrape_collections.automation_config: Same field for web scrape collections
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic
revision = '20260203_add_automation_config'
down_revision = '20260203_add_spawned_by_parent'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add automation_config column to sharepoint_sync_configs and scrape_collections."""
    op.add_column(
        'sharepoint_sync_configs',
        sa.Column('automation_config', JSONB(), nullable=False, server_default='{}')
    )
    op.add_column(
        'scrape_collections',
        sa.Column('automation_config', JSONB(), nullable=False, server_default='{}')
    )


def downgrade() -> None:
    """Remove automation_config columns."""
    op.drop_column('sharepoint_sync_configs', 'automation_config')
    op.drop_column('scrape_collections', 'automation_config')
