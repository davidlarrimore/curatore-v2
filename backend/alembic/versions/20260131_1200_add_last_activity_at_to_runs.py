"""Add last_activity_at to runs for activity-based timeouts

Revision ID: 20260131_1200
Revises: add_extraction_queue
Create Date: 2026-01-31 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20260131_1200'
down_revision: Union[str, None] = 'add_extraction_queue'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add last_activity_at column to runs table."""
    op.add_column(
        'runs',
        sa.Column('last_activity_at', sa.DateTime(), nullable=True)
    )
    op.create_index(
        'ix_runs_last_activity_at',
        'runs',
        ['last_activity_at'],
        unique=False
    )

    # Initialize last_activity_at for existing running jobs to started_at
    op.execute("""
        UPDATE runs
        SET last_activity_at = COALESCE(started_at, created_at)
        WHERE status IN ('running', 'submitted')
    """)


def downgrade() -> None:
    """Remove last_activity_at column from runs table."""
    op.drop_index('ix_runs_last_activity_at', table_name='runs')
    op.drop_column('runs', 'last_activity_at')
