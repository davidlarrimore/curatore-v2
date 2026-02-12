"""Add Phase 1 asset versioning support

This migration introduces asset versioning capabilities as defined in
Phase 1: Asset-Centric UX & Versioning Foundations.

Tables added:
- asset_versions: Immutable version tracking for assets

Columns added:
- assets.current_version_number: Current version number of the asset
- extraction_results.asset_version_id: Link extraction to specific version

These changes enable:
- Non-destructive asset updates (old versions preserved)
- Version history tracking
- Re-extraction of any version
- Immutable version snapshots

Revision ID: phase1_versioning
Revises: phase0_models
Create Date: 2026-01-28 17:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'phase1_versioning'
down_revision = 'phase0_models'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database to include asset versioning support."""

    # Bind to get connection for checking table existence
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Only create asset_versions table if it doesn't exist
    if 'asset_versions' not in existing_tables:
        op.create_table(
            'asset_versions',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('asset_id', sa.String(length=36), nullable=False),
            sa.Column('version_number', sa.Integer(), nullable=False),
            sa.Column('raw_bucket', sa.String(length=255), nullable=False),
            sa.Column('raw_object_key', sa.String(length=1024), nullable=False),
            sa.Column('file_size', sa.Integer(), nullable=True),
            sa.Column('file_hash', sa.String(length=64), nullable=True),
            sa.Column('content_type', sa.String(length=255), nullable=True),
            sa.Column('is_current', sa.Boolean(), nullable=False, server_default=text('1')),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('created_by', sa.String(length=36), nullable=True),
            sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Add indexes for common queries
        op.create_index('ix_asset_versions_asset_id', 'asset_versions', ['asset_id'])
        op.create_index('ix_asset_versions_asset_version', 'asset_versions', ['asset_id', 'version_number'], unique=True)
        op.create_index('ix_asset_versions_is_current', 'asset_versions', ['is_current'])

    # Check and add current_version_number to assets table
    existing_columns = [col['name'] for col in inspector.get_columns('assets')]
    if 'current_version_number' not in existing_columns:
        op.add_column('assets', sa.Column('current_version_number', sa.Integer(), nullable=True, server_default=text('1')))

    # Check and add asset_version_id to extraction_results table
    existing_columns = [col['name'] for col in inspector.get_columns('extraction_results')]
    if 'asset_version_id' not in existing_columns:
        # Use batch mode for SQLite compatibility
        with op.batch_alter_table('extraction_results', schema=None) as batch_op:
            batch_op.add_column(sa.Column('asset_version_id', sa.String(length=36), nullable=True))
            batch_op.create_foreign_key(
                'fk_extraction_results_asset_version_id',
                'asset_versions',
                ['asset_version_id'], ['id'],
                ondelete='CASCADE'
            )
            batch_op.create_index('ix_extraction_results_asset_version_id', ['asset_version_id'])


def downgrade() -> None:
    """Downgrade database to remove asset versioning support."""

    # Bind to get connection for checking existence
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check and remove asset_version_id from extraction_results
    existing_columns = [col['name'] for col in inspector.get_columns('extraction_results')]
    if 'asset_version_id' in existing_columns:
        # Use batch mode for SQLite compatibility
        with op.batch_alter_table('extraction_results', schema=None) as batch_op:
            try:
                batch_op.drop_index('ix_extraction_results_asset_version_id')
            except:
                pass  # Index might not exist
            try:
                batch_op.drop_constraint('fk_extraction_results_asset_version_id', type_='foreignkey')
            except:
                pass  # Constraint might not exist
            batch_op.drop_column('asset_version_id')

    # Check and remove current_version_number from assets
    existing_columns = [col['name'] for col in inspector.get_columns('assets')]
    if 'current_version_number' in existing_columns:
        op.drop_column('assets', 'current_version_number')

    # Check and drop asset_versions table and indexes
    existing_tables = inspector.get_table_names()
    if 'asset_versions' in existing_tables:
        try:
            op.drop_index('ix_asset_versions_is_current', table_name='asset_versions')
        except:
            pass
        try:
            op.drop_index('ix_asset_versions_asset_version', table_name='asset_versions')
        except:
            pass
        try:
            op.drop_index('ix_asset_versions_asset_id', table_name='asset_versions')
        except:
            pass
        op.drop_table('asset_versions')
