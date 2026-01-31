"""Add extraction queue management fields to runs table

This migration adds queue management fields to the Run model for the
Extraction Queue Management System. These fields enable:

1. Throttled Celery submissions - Only submit N concurrent jobs based on capacity
2. Explicit timeout tracking - New 'timed_out' status distinct from 'failed'
3. Duplicate prevention - Track pending/running extractions per asset
4. Queue position tracking - Priority ordering with created_at for FIFO within tier

New fields:
- celery_task_id: Links Run to Celery task for monitoring/cancellation
- submitted_to_celery_at: When the task was submitted (distinct from started_at)
- timeout_at: When the task should be considered timed out
- queue_priority: 0=normal, 1=high (user-requested re-extractions)

New status values:
- 'submitted': Sent to Celery, waiting for worker pickup
- 'timed_out': Exceeded soft time limit (distinct from 'failed')

Revision ID: add_extraction_queue
Revises: phase8_sharepoint_sync
Create Date: 2026-01-30 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_extraction_queue'
down_revision = 'phase8_sharepoint_sync'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add queue management fields to runs table."""

    # Add celery_task_id column
    op.add_column('runs', sa.Column('celery_task_id', sa.String(255), nullable=True))

    # Add submitted_to_celery_at column
    op.add_column('runs', sa.Column('submitted_to_celery_at', sa.DateTime(), nullable=True))

    # Add timeout_at column
    op.add_column('runs', sa.Column('timeout_at', sa.DateTime(), nullable=True))

    # Add queue_priority column with default 0
    op.add_column('runs', sa.Column('queue_priority', sa.Integer(), nullable=True, server_default='0'))

    # Create indexes for queue management queries
    op.create_index('ix_runs_celery_task_id', 'runs', ['celery_task_id'])
    op.create_index('ix_runs_queue_priority_status', 'runs', ['queue_priority', 'status'])


def downgrade() -> None:
    """Remove queue management fields from runs table."""

    # Drop indexes
    op.drop_index('ix_runs_queue_priority_status', table_name='runs')
    op.drop_index('ix_runs_celery_task_id', table_name='runs')

    # Drop columns
    op.drop_column('runs', 'queue_priority')
    op.drop_column('runs', 'timeout_at')
    op.drop_column('runs', 'submitted_to_celery_at')
    op.drop_column('runs', 'celery_task_id')
