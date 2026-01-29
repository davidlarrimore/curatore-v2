"""Add Phase 5 scheduled tasks table for system maintenance

This migration introduces the ScheduledTask model as defined in
Phase 5: System Maintenance & Scheduling Maturity.

Tables added:
- scheduled_tasks: Database-backed scheduled maintenance tasks

Key features:
- Global vs organization-scoped tasks
- Cron-based scheduling
- Enable/disable at runtime
- Execution tracking via Run model
- Task-specific configuration

These changes enable:
- Admin visibility into scheduled tasks
- Runtime task management without restarts
- Manual task triggering
- Execution history via Runs

Revision ID: phase5_scheduling
Revises: phase4_scraping
Create Date: 2026-01-28 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'phase5_scheduling'
down_revision = 'phase4_scraping'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database to include scheduled tasks table."""

    # Bind to get connection for checking table existence
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Create scheduled_tasks table
    if 'scheduled_tasks' not in existing_tables:
        op.create_table(
            'scheduled_tasks',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('organization_id', sa.String(length=36), nullable=True),

            # Task identification
            sa.Column('name', sa.String(length=100), nullable=False, unique=True),
            sa.Column('display_name', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),

            # Task classification
            sa.Column('task_type', sa.String(length=50), nullable=False),
            sa.Column('scope_type', sa.String(length=50), nullable=False, server_default=text("'global'")),

            # Schedule
            sa.Column('schedule_expression', sa.String(length=100), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default=text('1')),

            # Configuration
            sa.Column('config', sa.JSON(), nullable=False, server_default=text("'{}'")),

            # Execution tracking
            sa.Column('last_run_id', sa.String(length=36), nullable=True),
            sa.Column('last_run_at', sa.DateTime(), nullable=True),
            sa.Column('last_run_status', sa.String(length=50), nullable=True),
            sa.Column('next_run_at', sa.DateTime(), nullable=True),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),

            # Foreign keys
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['last_run_id'], ['runs.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Add indexes
        op.create_index('ix_scheduled_tasks_name', 'scheduled_tasks', ['name'], unique=True)
        op.create_index('ix_scheduled_tasks_organization_id', 'scheduled_tasks', ['organization_id'])
        op.create_index('ix_scheduled_tasks_enabled', 'scheduled_tasks', ['enabled'])
        op.create_index('ix_scheduled_tasks_task_type', 'scheduled_tasks', ['task_type'])
        op.create_index('ix_scheduled_tasks_org_enabled', 'scheduled_tasks', ['organization_id', 'enabled'])
        op.create_index('ix_scheduled_tasks_next_run', 'scheduled_tasks', ['next_run_at'])


def downgrade() -> None:
    """Downgrade database to remove scheduled tasks table."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Drop scheduled_tasks table
    if 'scheduled_tasks' in existing_tables:
        # Drop indexes first
        for idx_name in [
            'ix_scheduled_tasks_next_run', 'ix_scheduled_tasks_org_enabled',
            'ix_scheduled_tasks_task_type', 'ix_scheduled_tasks_enabled',
            'ix_scheduled_tasks_organization_id', 'ix_scheduled_tasks_name',
        ]:
            try:
                op.drop_index(idx_name, table_name='scheduled_tasks')
            except:
                pass
        op.drop_table('scheduled_tasks')
