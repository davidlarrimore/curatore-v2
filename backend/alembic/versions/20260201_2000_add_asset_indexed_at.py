"""Add indexed_at field to assets table.

Revision ID: add_asset_indexed_at
Revises: 20260201_1500_add_sharepoint_delta_query
Create Date: 2026-02-01 20:00:00.000000

Adds indexed_at timestamp to track when assets were indexed to pgvector search.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = '20260201_2000'
down_revision = '20260201_1500'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add indexed_at column to assets table."""
    op.add_column(
        'assets',
        sa.Column('indexed_at', sa.DateTime(), nullable=True)
    )

    # Create index for finding unindexed assets
    op.create_index(
        'ix_assets_indexed_at',
        'assets',
        ['indexed_at', 'status']
    )


def downgrade() -> None:
    """Remove indexed_at column."""
    op.drop_index('ix_assets_indexed_at', table_name='assets')
    op.drop_column('assets', 'indexed_at')
