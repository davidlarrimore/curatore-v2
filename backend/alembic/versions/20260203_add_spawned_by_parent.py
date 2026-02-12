"""Add spawned_by_parent field to runs table.

Revision ID: 20260203_add_spawned_by_parent
Revises: 20260203_add_run_groups
Create Date: 2026-02-03 18:00:00.000000

This migration adds:
- runs.spawned_by_parent: Boolean flag to track if extraction was spawned by a parent job
- Updates queue_priority default to 3 (user upload priority)
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision = '20260203_add_spawned_by_parent'
down_revision = '20260203_add_run_groups'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add spawned_by_parent column to runs table."""

    # Add spawned_by_parent column
    op.add_column(
        'runs',
        sa.Column('spawned_by_parent', sa.Boolean(), nullable=False, server_default='false')
    )

    # Add index for efficient queries
    op.create_index('ix_runs_spawned_by_parent', 'runs', ['spawned_by_parent'])

    # Update queue_priority default to 3 (user upload priority)
    # Note: This doesn't affect existing rows, only new inserts
    op.alter_column(
        'runs',
        'queue_priority',
        server_default='3'
    )

    # Backfill: Set spawned_by_parent=True for runs that have a group_id and are not group parents
    op.execute("""
        UPDATE runs
        SET spawned_by_parent = true
        WHERE group_id IS NOT NULL
          AND is_group_parent = false
    """)


def downgrade() -> None:
    """Remove spawned_by_parent column."""
    op.drop_index('ix_runs_spawned_by_parent', table_name='runs')
    op.drop_column('runs', 'spawned_by_parent')

    # Restore original queue_priority default
    op.alter_column(
        'runs',
        'queue_priority',
        server_default='0'
    )
