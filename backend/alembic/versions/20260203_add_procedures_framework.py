"""Add procedures framework tables.

Revision ID: 20260203_add_procedures
Revises: 20260201_2100
Create Date: 2026-02-03 10:00:00.000000

This migration adds tables for the procedures/pipelines framework:
- procedures: Procedure definitions (schedulable, event-driven workflows)
- pipelines: Pipeline definitions (multi-stage document processing)
- procedure_triggers: Trigger configurations for procedures (cron, events)
- pipeline_triggers: Trigger configurations for pipelines
- pipeline_runs: Links pipelines to runs with stage tracking
- pipeline_item_states: Per-item state tracking for pipelines
- function_executions: Optional audit log for function executions

Also adds procedure tracking columns to the runs table.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic
revision = '20260203_add_procedures'
down_revision = '20260201_2100'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create procedures framework tables."""

    # =========================================================================
    # PROCEDURES TABLE
    # =========================================================================
    op.create_table(
        'procedures',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('organization_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        # JSONB definition containing steps, parameters, outputs, etc.
        sa.Column('definition', JSONB(), nullable=False, server_default='{}'),
        # Version tracking for definition changes
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        # System procedures are managed by code, not editable via UI
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false'),
        # Source: 'yaml', 'python', 'user' (created via UI)
        sa.Column('source_type', sa.String(50), nullable=False, server_default="'yaml'"),
        # Path to source file for yaml/python procedures
        sa.Column('source_path', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        # Unique slug per organization
        sa.UniqueConstraint('organization_id', 'slug', name='uq_procedures_org_slug'),
    )

    # Indexes for procedures
    op.create_index('ix_procedures_org', 'procedures', ['organization_id'])
    op.create_index('ix_procedures_slug', 'procedures', ['slug'])
    op.create_index('ix_procedures_active', 'procedures', ['organization_id', 'is_active'])

    # =========================================================================
    # PIPELINES TABLE
    # =========================================================================
    op.create_table(
        'pipelines',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('organization_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        # JSONB definition containing stages configuration
        sa.Column('definition', JSONB(), nullable=False, server_default='{}'),
        # JSONB stages array: [{name, type, function, config, on_error}, ...]
        sa.Column('stages', JSONB(), nullable=False, server_default='[]'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('source_type', sa.String(50), nullable=False, server_default="'yaml'"),
        sa.Column('source_path', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column('created_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.UniqueConstraint('organization_id', 'slug', name='uq_pipelines_org_slug'),
    )

    # Indexes for pipelines
    op.create_index('ix_pipelines_org', 'pipelines', ['organization_id'])
    op.create_index('ix_pipelines_slug', 'pipelines', ['slug'])
    op.create_index('ix_pipelines_active', 'pipelines', ['organization_id', 'is_active'])

    # =========================================================================
    # PROCEDURE_TRIGGERS TABLE
    # =========================================================================
    op.create_table(
        'procedure_triggers',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('procedure_id', UUID(as_uuid=True), sa.ForeignKey('procedures.id', ondelete='CASCADE'), nullable=False),
        sa.Column('organization_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        # Trigger type: 'cron', 'event', 'webhook'
        sa.Column('trigger_type', sa.String(50), nullable=False),
        # For cron triggers: cron expression (e.g., "0 6 * * 1-5")
        sa.Column('cron_expression', sa.String(100), nullable=True),
        # For event triggers: event name (e.g., "sam_pull.completed")
        sa.Column('event_name', sa.String(255), nullable=True),
        # For event triggers: JSONB filter for event payload matching
        sa.Column('event_filter', JSONB(), nullable=True),
        # For webhook triggers: secret for validation
        sa.Column('webhook_secret', sa.String(255), nullable=True),
        # Parameters to pass to procedure when triggered
        sa.Column('trigger_params', JSONB(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        # Last execution tracking for cron triggers
        sa.Column('last_triggered_at', sa.DateTime(), nullable=True),
        sa.Column('next_trigger_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )

    # Indexes for procedure_triggers
    op.create_index('ix_procedure_triggers_procedure', 'procedure_triggers', ['procedure_id'])
    op.create_index('ix_procedure_triggers_org', 'procedure_triggers', ['organization_id'])
    op.create_index('ix_procedure_triggers_type', 'procedure_triggers', ['trigger_type'])
    op.create_index('ix_procedure_triggers_event', 'procedure_triggers', ['event_name'], postgresql_where=sa.text("event_name IS NOT NULL"))
    op.create_index('ix_procedure_triggers_next', 'procedure_triggers', ['next_trigger_at'], postgresql_where=sa.text("is_active = true AND trigger_type = 'cron'"))

    # =========================================================================
    # PIPELINE_TRIGGERS TABLE
    # =========================================================================
    op.create_table(
        'pipeline_triggers',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('pipeline_id', UUID(as_uuid=True), sa.ForeignKey('pipelines.id', ondelete='CASCADE'), nullable=False),
        sa.Column('organization_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('trigger_type', sa.String(50), nullable=False),
        sa.Column('cron_expression', sa.String(100), nullable=True),
        sa.Column('event_name', sa.String(255), nullable=True),
        sa.Column('event_filter', JSONB(), nullable=True),
        sa.Column('webhook_secret', sa.String(255), nullable=True),
        sa.Column('trigger_params', JSONB(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_triggered_at', sa.DateTime(), nullable=True),
        sa.Column('next_trigger_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )

    # Indexes for pipeline_triggers
    op.create_index('ix_pipeline_triggers_pipeline', 'pipeline_triggers', ['pipeline_id'])
    op.create_index('ix_pipeline_triggers_org', 'pipeline_triggers', ['organization_id'])
    op.create_index('ix_pipeline_triggers_type', 'pipeline_triggers', ['trigger_type'])
    op.create_index('ix_pipeline_triggers_event', 'pipeline_triggers', ['event_name'], postgresql_where=sa.text("event_name IS NOT NULL"))
    op.create_index('ix_pipeline_triggers_next', 'pipeline_triggers', ['next_trigger_at'], postgresql_where=sa.text("is_active = true AND trigger_type = 'cron'"))

    # =========================================================================
    # PIPELINE_RUNS TABLE
    # =========================================================================
    op.create_table(
        'pipeline_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('pipeline_id', UUID(as_uuid=True), sa.ForeignKey('pipelines.id', ondelete='CASCADE'), nullable=False),
        sa.Column('run_id', UUID(as_uuid=True), sa.ForeignKey('runs.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('organization_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        # Current stage being executed (0-indexed)
        sa.Column('current_stage', sa.Integer(), nullable=False, server_default='0'),
        # Total number of stages
        sa.Column('total_stages', sa.Integer(), nullable=False, server_default='0'),
        # JSONB: results from each completed stage
        sa.Column('stage_results', JSONB(), nullable=False, server_default='{}'),
        # Items being processed in this pipeline run
        sa.Column('total_items', sa.Integer(), nullable=True),
        sa.Column('processed_items', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('failed_items', sa.Integer(), nullable=True, server_default='0'),
        # Checkpoint for resumability
        sa.Column('checkpoint_data', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )

    # Indexes for pipeline_runs
    op.create_index('ix_pipeline_runs_pipeline', 'pipeline_runs', ['pipeline_id'])
    op.create_index('ix_pipeline_runs_run', 'pipeline_runs', ['run_id'])
    op.create_index('ix_pipeline_runs_org', 'pipeline_runs', ['organization_id'])

    # =========================================================================
    # PIPELINE_ITEM_STATES TABLE
    # =========================================================================
    op.create_table(
        'pipeline_item_states',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('pipeline_run_id', UUID(as_uuid=True), sa.ForeignKey('pipeline_runs.id', ondelete='CASCADE'), nullable=False),
        # Item identifier: type + id (e.g., 'asset' + asset_id)
        sa.Column('item_type', sa.String(50), nullable=False),
        sa.Column('item_id', UUID(as_uuid=True), nullable=False),
        # Current stage status for this item: pending, processing, completed, failed, skipped
        sa.Column('stage_status', JSONB(), nullable=False, server_default='{}'),
        # Per-stage data accumulated during processing
        sa.Column('stage_data', JSONB(), nullable=False, server_default='{}'),
        # Overall item status: pending, processing, completed, failed
        sa.Column('status', sa.String(50), nullable=False, server_default="'pending'"),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        # Unique item per pipeline run
        sa.UniqueConstraint('pipeline_run_id', 'item_type', 'item_id', name='uq_pipeline_item_states_item'),
    )

    # Indexes for pipeline_item_states
    op.create_index('ix_pipeline_item_states_run', 'pipeline_item_states', ['pipeline_run_id'])
    op.create_index('ix_pipeline_item_states_item', 'pipeline_item_states', ['item_type', 'item_id'])
    op.create_index('ix_pipeline_item_states_status', 'pipeline_item_states', ['pipeline_run_id', 'status'])

    # =========================================================================
    # FUNCTION_EXECUTIONS TABLE (optional auditing)
    # =========================================================================
    op.create_table(
        'function_executions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('organization_id', UUID(as_uuid=True), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        # Function name that was executed
        sa.Column('function_name', sa.String(255), nullable=False),
        # Context: procedure, pipeline, direct (API call)
        sa.Column('execution_context', sa.String(50), nullable=False),
        # Reference to procedure/pipeline run if applicable
        sa.Column('run_id', UUID(as_uuid=True), sa.ForeignKey('runs.id', ondelete='SET NULL'), nullable=True),
        # Input parameters (JSONB for queryability)
        sa.Column('input_params', JSONB(), nullable=True),
        # Output result summary
        sa.Column('output_summary', JSONB(), nullable=True),
        # Execution status: success, failed, timeout
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        # Execution timing
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )

    # Indexes for function_executions
    op.create_index('ix_function_executions_org', 'function_executions', ['organization_id'])
    op.create_index('ix_function_executions_function', 'function_executions', ['function_name'])
    op.create_index('ix_function_executions_run', 'function_executions', ['run_id'], postgresql_where=sa.text("run_id IS NOT NULL"))
    op.create_index('ix_function_executions_status', 'function_executions', ['status'])
    op.create_index('ix_function_executions_created', 'function_executions', ['organization_id', 'created_at'])

    # =========================================================================
    # ADD PROCEDURE TRACKING TO RUNS TABLE
    # =========================================================================
    op.add_column('runs', sa.Column('procedure_id', UUID(as_uuid=True), nullable=True))
    op.add_column('runs', sa.Column('procedure_version', sa.Integer(), nullable=True))
    op.add_column('runs', sa.Column('pipeline_id', UUID(as_uuid=True), nullable=True))

    # Add foreign keys (without cascade to preserve run history)
    op.create_foreign_key(
        'fk_runs_procedure',
        'runs', 'procedures',
        ['procedure_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_runs_pipeline',
        'runs', 'pipelines',
        ['pipeline_id'], ['id'],
        ondelete='SET NULL'
    )

    # Index for finding runs by procedure/pipeline
    op.create_index('ix_runs_procedure', 'runs', ['procedure_id'], postgresql_where=sa.text("procedure_id IS NOT NULL"))
    op.create_index('ix_runs_pipeline', 'runs', ['pipeline_id'], postgresql_where=sa.text("pipeline_id IS NOT NULL"))


def downgrade() -> None:
    """Drop procedures framework tables."""
    # Drop indexes and columns from runs
    op.drop_index('ix_runs_pipeline', table_name='runs')
    op.drop_index('ix_runs_procedure', table_name='runs')
    op.drop_constraint('fk_runs_pipeline', 'runs', type_='foreignkey')
    op.drop_constraint('fk_runs_procedure', 'runs', type_='foreignkey')
    op.drop_column('runs', 'pipeline_id')
    op.drop_column('runs', 'procedure_version')
    op.drop_column('runs', 'procedure_id')

    # Drop function_executions
    op.drop_index('ix_function_executions_created', table_name='function_executions')
    op.drop_index('ix_function_executions_status', table_name='function_executions')
    op.drop_index('ix_function_executions_run', table_name='function_executions')
    op.drop_index('ix_function_executions_function', table_name='function_executions')
    op.drop_index('ix_function_executions_org', table_name='function_executions')
    op.drop_table('function_executions')

    # Drop pipeline_item_states
    op.drop_index('ix_pipeline_item_states_status', table_name='pipeline_item_states')
    op.drop_index('ix_pipeline_item_states_item', table_name='pipeline_item_states')
    op.drop_index('ix_pipeline_item_states_run', table_name='pipeline_item_states')
    op.drop_table('pipeline_item_states')

    # Drop pipeline_runs
    op.drop_index('ix_pipeline_runs_org', table_name='pipeline_runs')
    op.drop_index('ix_pipeline_runs_run', table_name='pipeline_runs')
    op.drop_index('ix_pipeline_runs_pipeline', table_name='pipeline_runs')
    op.drop_table('pipeline_runs')

    # Drop pipeline_triggers
    op.drop_index('ix_pipeline_triggers_next', table_name='pipeline_triggers')
    op.drop_index('ix_pipeline_triggers_event', table_name='pipeline_triggers')
    op.drop_index('ix_pipeline_triggers_type', table_name='pipeline_triggers')
    op.drop_index('ix_pipeline_triggers_org', table_name='pipeline_triggers')
    op.drop_index('ix_pipeline_triggers_pipeline', table_name='pipeline_triggers')
    op.drop_table('pipeline_triggers')

    # Drop procedure_triggers
    op.drop_index('ix_procedure_triggers_next', table_name='procedure_triggers')
    op.drop_index('ix_procedure_triggers_event', table_name='procedure_triggers')
    op.drop_index('ix_procedure_triggers_type', table_name='procedure_triggers')
    op.drop_index('ix_procedure_triggers_org', table_name='procedure_triggers')
    op.drop_index('ix_procedure_triggers_procedure', table_name='procedure_triggers')
    op.drop_table('procedure_triggers')

    # Drop pipelines
    op.drop_index('ix_pipelines_active', table_name='pipelines')
    op.drop_index('ix_pipelines_slug', table_name='pipelines')
    op.drop_index('ix_pipelines_org', table_name='pipelines')
    op.drop_table('pipelines')

    # Drop procedures
    op.drop_index('ix_procedures_active', table_name='procedures')
    op.drop_index('ix_procedures_slug', table_name='procedures')
    op.drop_index('ix_procedures_org', table_name='procedures')
    op.drop_table('procedures')
