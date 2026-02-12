"""Add run groups for parent-child job tracking.

Revision ID: 20260203_add_run_groups
Revises: 20260203_add_procedures
Create Date: 2026-02-03 15:00:00.000000

This migration adds:
- run_groups table: Tracks parent-child job relationships
- runs.group_id: Links child runs to their parent group
- runs.is_group_parent: Marks the parent run in a group
- sam_searches.automation_config: Configuration for automation triggers
- procedure_triggers.trigger_count: Track how many times a trigger has fired
- pipeline_triggers.trigger_count: Track how many times a trigger has fired
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic
revision = '20260203_add_run_groups'
down_revision = '20260203_add_procedures'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create run_groups table and add parent-child tracking fields."""

    # =========================================================================
    # RUN_GROUPS TABLE
    # Tracks parent-child job relationships (e.g., SAM pull -> extractions)
    # =========================================================================
    op.create_table(
        'run_groups',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('organization_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        # Group type: sam_pull, sharepoint_sync, scrape, upload_group
        sa.Column('group_type', sa.String(50), nullable=False),
        # Parent run that initiated this group
        sa.Column('parent_run_id', UUID(as_uuid=True), sa.ForeignKey('runs.id', ondelete='SET NULL'), nullable=True),
        # Group status: pending, running, completed, partial, failed
        sa.Column('status', sa.String(50), nullable=False, server_default="'pending'"),
        # Child run tracking
        sa.Column('total_children', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completed_children', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_children', sa.Integer(), nullable=False, server_default='0'),
        # JSONB config (e.g., after_procedure_slug, after_procedure_params)
        sa.Column('config', JSONB(), nullable=False, server_default='{}'),
        # JSONB results summary
        sa.Column('results_summary', JSONB(), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )

    # Indexes for run_groups
    op.create_index('ix_run_groups_org', 'run_groups', ['organization_id'])
    op.create_index('ix_run_groups_type', 'run_groups', ['group_type'])
    op.create_index('ix_run_groups_status', 'run_groups', ['status'])
    op.create_index('ix_run_groups_parent_run', 'run_groups', ['parent_run_id'], postgresql_where=sa.text("parent_run_id IS NOT NULL"))
    op.create_index('ix_run_groups_org_created', 'run_groups', ['organization_id', 'created_at'])

    # =========================================================================
    # ADD PARENT-CHILD TRACKING TO RUNS TABLE
    # =========================================================================
    op.add_column('runs', sa.Column('group_id', UUID(as_uuid=True), nullable=True))
    op.add_column('runs', sa.Column('is_group_parent', sa.Boolean(), nullable=False, server_default='false'))

    # Add foreign key for group_id
    op.create_foreign_key(
        'fk_runs_group',
        'runs', 'run_groups',
        ['group_id'], ['id'],
        ondelete='SET NULL'
    )

    # Index for finding runs by group
    op.create_index('ix_runs_group', 'runs', ['group_id'], postgresql_where=sa.text("group_id IS NOT NULL"))

    # =========================================================================
    # ADD AUTOMATION CONFIG TO SAM_SEARCHES
    # =========================================================================
    op.add_column('sam_searches', sa.Column('automation_config', JSONB(), nullable=False, server_default='{}'))

    # =========================================================================
    # ADD TRIGGER COUNT TO PROCEDURE_TRIGGERS AND PIPELINE_TRIGGERS
    # =========================================================================
    op.add_column('procedure_triggers', sa.Column('trigger_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('pipeline_triggers', sa.Column('trigger_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Drop run_groups and related fields."""
    # Drop trigger_count columns
    op.drop_column('pipeline_triggers', 'trigger_count')
    op.drop_column('procedure_triggers', 'trigger_count')

    # Drop automation_config from sam_searches
    op.drop_column('sam_searches', 'automation_config')

    # Drop parent-child tracking from runs
    op.drop_index('ix_runs_group', table_name='runs')
    op.drop_constraint('fk_runs_group', 'runs', type_='foreignkey')
    op.drop_column('runs', 'is_group_parent')
    op.drop_column('runs', 'group_id')

    # Drop run_groups table
    op.drop_index('ix_run_groups_org_created', table_name='run_groups')
    op.drop_index('ix_run_groups_parent_run', table_name='run_groups')
    op.drop_index('ix_run_groups_status', table_name='run_groups')
    op.drop_index('ix_run_groups_type', table_name='run_groups')
    op.drop_index('ix_run_groups_org', table_name='run_groups')
    op.drop_table('run_groups')
