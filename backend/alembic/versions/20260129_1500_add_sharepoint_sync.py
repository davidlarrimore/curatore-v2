"""Add Phase 8 SharePoint sync integration tables

This migration introduces the SharePoint sync models as defined in
Phase 8: SharePoint Sync Integration.

Tables added:
- sharepoint_sync_configs: Sync configurations for SharePoint folders
- sharepoint_synced_documents: Bridge table linking assets to sync configs

Key features:
- One-way pull from SharePoint
- Replace with latest on re-sync (no version history)
- Deletion detection without auto-delete
- ETag and content hash for change detection

These changes enable:
- SharePoint folder synchronization
- Asset creation from SharePoint files
- Change detection via etag/hash comparison
- Deleted file tracking and cleanup

Revision ID: phase8_sharepoint_sync
Revises: phase7_decouple_search
Create Date: 2026-01-29 15:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'phase8_sharepoint_sync'
down_revision = 'decouple_sam_search'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database to include SharePoint sync tables."""

    # Bind to get connection for checking table existence
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Create sharepoint_sync_configs table
    if 'sharepoint_sync_configs' not in existing_tables:
        op.create_table(
            'sharepoint_sync_configs',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('organization_id', sa.String(length=36), nullable=False),
            sa.Column('connection_id', sa.String(length=36), nullable=True),

            # Config metadata
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('slug', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),

            # SharePoint folder information
            sa.Column('folder_url', sa.String(length=2048), nullable=False),
            sa.Column('folder_name', sa.String(length=500), nullable=True),
            sa.Column('folder_drive_id', sa.String(length=255), nullable=True),
            sa.Column('folder_item_id', sa.String(length=255), nullable=True),

            # Sync configuration
            sa.Column('sync_config', sa.JSON(), nullable=False, server_default=text("'{}'")),

            # Status
            sa.Column('status', sa.String(length=50), nullable=False, server_default=text("'active'")),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=text('1')),

            # Sync tracking
            sa.Column('last_sync_at', sa.DateTime(), nullable=True),
            sa.Column('last_sync_status', sa.String(length=50), nullable=True),
            sa.Column('last_sync_run_id', sa.String(length=36), nullable=True),
            sa.Column('sync_frequency', sa.String(length=50), nullable=False, server_default=text("'manual'")),

            # Statistics
            sa.Column('stats', sa.JSON(), nullable=False, server_default=text("'{}'")),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('created_by', sa.String(length=36), nullable=True),

            # Foreign keys
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['last_sync_run_id'], ['runs.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Add indexes
        op.create_index('ix_sharepoint_sync_organization_id', 'sharepoint_sync_configs', ['organization_id'])
        op.create_index('ix_sharepoint_sync_status', 'sharepoint_sync_configs', ['status'])
        op.create_index('ix_sharepoint_sync_is_active', 'sharepoint_sync_configs', ['is_active'])
        op.create_index('ix_sharepoint_sync_org_slug', 'sharepoint_sync_configs', ['organization_id', 'slug'], unique=True)
        op.create_index('ix_sharepoint_sync_org_status', 'sharepoint_sync_configs', ['organization_id', 'status'])
        op.create_index('ix_sharepoint_sync_org_active', 'sharepoint_sync_configs', ['organization_id', 'is_active'])
        op.create_index('ix_sharepoint_sync_connection', 'sharepoint_sync_configs', ['connection_id'])

    # Create sharepoint_synced_documents table
    if 'sharepoint_synced_documents' not in existing_tables:
        op.create_table(
            'sharepoint_synced_documents',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('asset_id', sa.String(length=36), nullable=False),
            sa.Column('sync_config_id', sa.String(length=36), nullable=False),

            # SharePoint identifiers
            sa.Column('sharepoint_item_id', sa.String(length=255), nullable=False),
            sa.Column('sharepoint_drive_id', sa.String(length=255), nullable=False),
            sa.Column('sharepoint_path', sa.String(length=2048), nullable=True),
            sa.Column('sharepoint_web_url', sa.String(length=2048), nullable=True),

            # Change detection
            sa.Column('sharepoint_etag', sa.String(length=255), nullable=True),
            sa.Column('content_hash', sa.String(length=64), nullable=True),

            # SharePoint metadata
            sa.Column('sharepoint_created_at', sa.DateTime(), nullable=True),
            sa.Column('sharepoint_modified_at', sa.DateTime(), nullable=True),
            sa.Column('sharepoint_created_by', sa.String(length=255), nullable=True),
            sa.Column('sharepoint_modified_by', sa.String(length=255), nullable=True),
            sa.Column('file_size', sa.Integer(), nullable=True),

            # Sync status
            sa.Column('sync_status', sa.String(length=50), nullable=False, server_default=text("'synced'")),

            # Sync tracking
            sa.Column('last_synced_at', sa.DateTime(), nullable=True),
            sa.Column('last_sync_run_id', sa.String(length=36), nullable=True),
            sa.Column('deleted_detected_at', sa.DateTime(), nullable=True),

            # Additional metadata
            sa.Column('sync_metadata', sa.JSON(), nullable=False, server_default=text("'{}'")),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),

            # Foreign keys
            sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['sync_config_id'], ['sharepoint_sync_configs.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['last_sync_run_id'], ['runs.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Add indexes
        op.create_index('ix_sp_synced_asset_id', 'sharepoint_synced_documents', ['asset_id'])
        op.create_index('ix_sp_synced_sync_config_id', 'sharepoint_synced_documents', ['sync_config_id'])
        op.create_index('ix_sp_synced_sync_status', 'sharepoint_synced_documents', ['sync_status'])
        op.create_index('ix_sp_synced_config_item', 'sharepoint_synced_documents', ['sync_config_id', 'sharepoint_item_id'], unique=True)
        op.create_index('ix_sp_synced_config_status', 'sharepoint_synced_documents', ['sync_config_id', 'sync_status'])
        op.create_index('ix_sp_synced_config_path', 'sharepoint_synced_documents', ['sync_config_id', 'sharepoint_path'])
        op.create_index('ix_sp_synced_asset', 'sharepoint_synced_documents', ['asset_id'])
        op.create_index('ix_sp_synced_run', 'sharepoint_synced_documents', ['last_sync_run_id'])


def downgrade() -> None:
    """Downgrade database to remove SharePoint sync tables."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Drop sharepoint_synced_documents table
    if 'sharepoint_synced_documents' in existing_tables:
        # Drop indexes first
        for idx_name in [
            'ix_sp_synced_run', 'ix_sp_synced_asset', 'ix_sp_synced_config_path',
            'ix_sp_synced_config_status', 'ix_sp_synced_config_item',
            'ix_sp_synced_sync_status', 'ix_sp_synced_sync_config_id',
            'ix_sp_synced_asset_id',
        ]:
            try:
                op.drop_index(idx_name, table_name='sharepoint_synced_documents')
            except:
                pass
        op.drop_table('sharepoint_synced_documents')

    # Drop sharepoint_sync_configs table
    if 'sharepoint_sync_configs' in existing_tables:
        for idx_name in [
            'ix_sharepoint_sync_connection', 'ix_sharepoint_sync_org_active',
            'ix_sharepoint_sync_org_status', 'ix_sharepoint_sync_org_slug',
            'ix_sharepoint_sync_is_active', 'ix_sharepoint_sync_status',
            'ix_sharepoint_sync_organization_id',
        ]:
            try:
                op.drop_index(idx_name, table_name='sharepoint_sync_configs')
            except:
                pass
        op.drop_table('sharepoint_sync_configs')
