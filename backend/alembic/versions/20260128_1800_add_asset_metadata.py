"""Add Phase 3 AssetMetadata table for flexible metadata management

This migration introduces the AssetMetadata model as defined in
Phase 3: Flexible Metadata & Experimentation Core.

Tables added:
- asset_metadata: Flexible, versioned metadata artifacts per asset

Key features:
- Metadata stored as JSONB (not hard-coded columns)
- Support for metadata types (topics, summary, tags, entities, etc.)
- Canonical vs experimental metadata distinction
- Promotion/demotion mechanics with pointer updates
- Run attribution for all metadata-producing activity

These changes enable:
- LLM-driven metadata iteration without schema churn
- Side-by-side comparison of experimental variants
- Explicit promotion to canonical status
- Full traceability of metadata provenance

Revision ID: phase3_metadata
Revises: phase1_versioning
Create Date: 2026-01-28 18:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'phase3_metadata'
down_revision = 'phase1_versioning'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database to include AssetMetadata table."""

    # Bind to get connection for checking table existence
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Only create asset_metadata table if it doesn't exist
    if 'asset_metadata' not in existing_tables:
        op.create_table(
            'asset_metadata',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('asset_id', sa.String(length=36), nullable=False),

            # Metadata type and version
            sa.Column('metadata_type', sa.String(length=100), nullable=False),
            sa.Column('schema_version', sa.String(length=50), nullable=False, server_default=text("'1.0'")),

            # Attribution
            sa.Column('producer_run_id', sa.String(length=36), nullable=True),

            # Canonical vs Experimental
            sa.Column('is_canonical', sa.Boolean(), nullable=False, server_default=text('0')),

            # Status (active, superseded, deprecated)
            sa.Column('status', sa.String(length=50), nullable=False, server_default=text("'active'")),

            # Metadata content (JSONB for flexibility)
            sa.Column('metadata_content', sa.JSON(), nullable=False, server_default=text("'{}'")),

            # Optional object store reference for large payloads
            sa.Column('metadata_object_ref', sa.String(length=1024), nullable=True),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('promoted_at', sa.DateTime(), nullable=True),
            sa.Column('superseded_at', sa.DateTime(), nullable=True),

            # Promotion and supersession tracking
            sa.Column('promoted_from_id', sa.String(length=36), nullable=True),
            sa.Column('superseded_by_id', sa.String(length=36), nullable=True),

            # Foreign keys
            sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['producer_run_id'], ['runs.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['promoted_from_id'], ['asset_metadata.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['superseded_by_id'], ['asset_metadata.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Add indexes for common queries
        # Basic indexes
        op.create_index('ix_asset_metadata_asset_id', 'asset_metadata', ['asset_id'])
        op.create_index('ix_asset_metadata_metadata_type', 'asset_metadata', ['metadata_type'])
        op.create_index('ix_asset_metadata_is_canonical', 'asset_metadata', ['is_canonical'])
        op.create_index('ix_asset_metadata_status', 'asset_metadata', ['status'])

        # Composite indexes for efficient queries
        op.create_index('ix_asset_metadata_asset_canonical', 'asset_metadata', ['asset_id', 'is_canonical'])
        op.create_index('ix_asset_metadata_asset_type_canonical', 'asset_metadata', ['asset_id', 'metadata_type', 'is_canonical'])
        op.create_index('ix_asset_metadata_run', 'asset_metadata', ['producer_run_id'])
        op.create_index('ix_asset_metadata_asset_type_status', 'asset_metadata', ['asset_id', 'metadata_type', 'status'])


def downgrade() -> None:
    """Downgrade database to remove AssetMetadata table."""

    # Bind to get connection for checking existence
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Check and drop asset_metadata table and indexes
    if 'asset_metadata' in existing_tables:
        # Drop indexes first
        try:
            op.drop_index('ix_asset_metadata_asset_type_status', table_name='asset_metadata')
        except:
            pass
        try:
            op.drop_index('ix_asset_metadata_run', table_name='asset_metadata')
        except:
            pass
        try:
            op.drop_index('ix_asset_metadata_asset_type_canonical', table_name='asset_metadata')
        except:
            pass
        try:
            op.drop_index('ix_asset_metadata_asset_canonical', table_name='asset_metadata')
        except:
            pass
        try:
            op.drop_index('ix_asset_metadata_status', table_name='asset_metadata')
        except:
            pass
        try:
            op.drop_index('ix_asset_metadata_is_canonical', table_name='asset_metadata')
        except:
            pass
        try:
            op.drop_index('ix_asset_metadata_metadata_type', table_name='asset_metadata')
        except:
            pass
        try:
            op.drop_index('ix_asset_metadata_asset_id', table_name='asset_metadata')
        except:
            pass

        # Drop the table
        op.drop_table('asset_metadata')
