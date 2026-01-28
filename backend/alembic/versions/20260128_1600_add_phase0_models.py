"""Add Phase 0 models: Asset, Run, ExtractionResult, RunLogEvent

This migration introduces the foundational models for Curatore's asset-centric
architecture as defined in Phase 0: Stabilization & Baseline Observability.

Tables added:
- assets: Canonical document representation with provenance
- runs: Universal execution tracking for all background activity
- extraction_results: Extraction attempt tracking for assets
- run_log_events: Structured logging for runs

These models establish:
- Asset as the first-class document entity
- Run as the universal execution mechanism
- Extraction as automatic platform infrastructure
- Structured, queryable logging for observability

Revision ID: phase0_models
Revises: migrate_document_id_to_uuid
Create Date: 2026-01-28 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'phase0_models'
down_revision = 'migrate_document_id_to_uuid'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create Phase 0 tables and indexes."""

    # ========================================================================
    # Table: assets
    # ========================================================================
    op.create_table(
        'assets',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('organization_id', sa.String(36),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),

        # Source provenance
        sa.Column('source_type', sa.String(50), nullable=False),
        sa.Column('source_metadata', sa.JSON(), nullable=False, server_default='{}'),

        # File metadata
        sa.Column('original_filename', sa.String(500), nullable=False),
        sa.Column('content_type', sa.String(255), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('file_hash', sa.String(64), nullable=True),

        # Object storage reference
        sa.Column('raw_bucket', sa.String(255), nullable=False),
        sa.Column('raw_object_key', sa.String(1024), nullable=False),

        # Status
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),

        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_by', sa.String(36),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
    )

    # Assets indexes
    op.create_index('ix_assets_organization_id', 'assets', ['organization_id'])
    op.create_index('ix_assets_source_type', 'assets', ['source_type'])
    op.create_index('ix_assets_file_hash', 'assets', ['file_hash'])
    op.create_index('ix_assets_status', 'assets', ['status'])
    op.create_index('ix_assets_org_created', 'assets', ['organization_id', 'created_at'])
    op.create_index('ix_assets_org_status', 'assets', ['organization_id', 'status'])
    op.create_index('ix_assets_bucket_key', 'assets', ['raw_bucket', 'raw_object_key'], unique=True)

    # ========================================================================
    # Table: runs
    # ========================================================================
    op.create_table(
        'runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('organization_id', sa.String(36),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),

        # Run metadata
        sa.Column('run_type', sa.String(50), nullable=False),
        sa.Column('origin', sa.String(50), nullable=False, server_default='user'),

        # Run status
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),

        # Input and configuration
        sa.Column('input_asset_ids', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('config', sa.JSON(), nullable=False, server_default='{}'),

        # Progress tracking
        sa.Column('progress', sa.JSON(), nullable=True),

        # Results
        sa.Column('results_summary', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.String(36),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
    )

    # Runs indexes
    op.create_index('ix_runs_organization_id', 'runs', ['organization_id'])
    op.create_index('ix_runs_run_type', 'runs', ['run_type'])
    op.create_index('ix_runs_status', 'runs', ['status'])
    op.create_index('ix_runs_org_created', 'runs', ['organization_id', 'created_at'])
    op.create_index('ix_runs_org_status', 'runs', ['organization_id', 'status'])
    op.create_index('ix_runs_type_status', 'runs', ['run_type', 'status'])

    # ========================================================================
    # Table: extraction_results
    # ========================================================================
    op.create_table(
        'extraction_results',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('asset_id', sa.String(36),
                  sa.ForeignKey('assets.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('run_id', sa.String(36),
                  sa.ForeignKey('runs.id', ondelete='CASCADE'),
                  nullable=False),

        # Extractor information
        sa.Column('extractor_version', sa.String(100), nullable=False),

        # Extraction status
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),

        # Extracted content reference
        sa.Column('extracted_bucket', sa.String(255), nullable=True),
        sa.Column('extracted_object_key', sa.String(1024), nullable=True),

        # Structural metadata (for hierarchical extraction in Phase 4+)
        sa.Column('structure_metadata', sa.JSON(), nullable=True),

        # Warnings and errors
        sa.Column('warnings', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('errors', sa.JSON(), nullable=False, server_default='[]'),

        # Performance metrics
        sa.Column('extraction_time_seconds', sa.Float(), nullable=True),

        # Timestamp
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
    )

    # Extraction results indexes
    op.create_index('ix_extraction_results_asset_id', 'extraction_results', ['asset_id'])
    op.create_index('ix_extraction_results_run_id', 'extraction_results', ['run_id'])
    op.create_index('ix_extraction_results_status', 'extraction_results', ['status'])
    op.create_index('ix_extraction_asset_status', 'extraction_results', ['asset_id', 'status'])

    # ========================================================================
    # Table: run_log_events
    # ========================================================================
    op.create_table(
        'run_log_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('run_id', sa.String(36),
                  sa.ForeignKey('runs.id', ondelete='CASCADE'),
                  nullable=False),

        # Event details
        sa.Column('level', sa.String(20), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('context', sa.JSON(), nullable=True),

        # Timestamp
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
    )

    # Run log events indexes
    op.create_index('ix_run_log_events_run_id', 'run_log_events', ['run_id'])
    op.create_index('ix_run_log_events_level', 'run_log_events', ['level'])
    op.create_index('ix_run_log_events_event_type', 'run_log_events', ['event_type'])
    op.create_index('ix_run_log_events_created_at', 'run_log_events', ['created_at'])
    op.create_index('ix_run_log_run_created', 'run_log_events', ['run_id', 'created_at'])


def downgrade() -> None:
    """Drop Phase 0 tables and indexes."""

    # Drop run_log_events (must drop first due to FK to runs)
    op.drop_index('ix_run_log_run_created', table_name='run_log_events')
    op.drop_index('ix_run_log_events_created_at', table_name='run_log_events')
    op.drop_index('ix_run_log_events_event_type', table_name='run_log_events')
    op.drop_index('ix_run_log_events_level', table_name='run_log_events')
    op.drop_index('ix_run_log_events_run_id', table_name='run_log_events')
    op.drop_table('run_log_events')

    # Drop extraction_results (must drop before assets and runs due to FKs)
    op.drop_index('ix_extraction_asset_status', table_name='extraction_results')
    op.drop_index('ix_extraction_results_status', table_name='extraction_results')
    op.drop_index('ix_extraction_results_run_id', table_name='extraction_results')
    op.drop_index('ix_extraction_results_asset_id', table_name='extraction_results')
    op.drop_table('extraction_results')

    # Drop runs
    op.drop_index('ix_runs_type_status', table_name='runs')
    op.drop_index('ix_runs_org_status', table_name='runs')
    op.drop_index('ix_runs_org_created', table_name='runs')
    op.drop_index('ix_runs_status', table_name='runs')
    op.drop_index('ix_runs_run_type', table_name='runs')
    op.drop_index('ix_runs_organization_id', table_name='runs')
    op.drop_table('runs')

    # Drop assets
    op.drop_index('ix_assets_bucket_key', table_name='assets')
    op.drop_index('ix_assets_org_status', table_name='assets')
    op.drop_index('ix_assets_org_created', table_name='assets')
    op.drop_index('ix_assets_status', table_name='assets')
    op.drop_index('ix_assets_file_hash', table_name='assets')
    op.drop_index('ix_assets_source_type', table_name='assets')
    op.drop_index('ix_assets_organization_id', table_name='assets')
    op.drop_table('assets')
