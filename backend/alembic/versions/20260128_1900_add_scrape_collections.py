"""Add Phase 4 scrape collection tables for web scraping

This migration introduces the web scraping models as defined in
Phase 4: Web Scraping as Durable Data Source.

Tables added:
- scrape_collections: Collections of scraped content with modes
- scrape_sources: URL sources within collections
- scraped_assets: Junction table linking assets to collections

Key features:
- Snapshot vs Record-Preserving collection modes
- Page vs Record asset subtypes
- Hierarchical path metadata for tree browsing
- Promotion mechanics (page → record)
- Run-attributed crawl tracking

These changes enable:
- Web scraping as institutional memory
- Record preservation (never auto-delete)
- Hierarchical navigation of scraped content
- Re-crawl with version preservation

Revision ID: phase4_scraping
Revises: phase3_metadata
Create Date: 2026-01-28 19:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'phase4_scraping'
down_revision = 'phase3_metadata'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database to include scrape collection tables."""

    # Bind to get connection for checking table existence
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Create scrape_collections table
    if 'scrape_collections' not in existing_tables:
        op.create_table(
            'scrape_collections',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('organization_id', sa.String(length=36), nullable=False),

            # Collection metadata
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('slug', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),

            # Collection mode
            sa.Column('collection_mode', sa.String(length=50), nullable=False, server_default=text("'record_preserving'")),

            # Root URL and patterns
            sa.Column('root_url', sa.String(length=2048), nullable=False),
            sa.Column('url_patterns', sa.JSON(), nullable=False, server_default=text("'[]'")),

            # Crawl configuration
            sa.Column('crawl_config', sa.JSON(), nullable=False, server_default=text("'{}'")),

            # Status
            sa.Column('status', sa.String(length=50), nullable=False, server_default=text("'active'")),

            # Crawl tracking
            sa.Column('last_crawl_at', sa.DateTime(), nullable=True),
            sa.Column('last_crawl_run_id', sa.String(length=36), nullable=True),

            # Statistics
            sa.Column('stats', sa.JSON(), nullable=False, server_default=text("'{}'")),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('created_by', sa.String(length=36), nullable=True),

            # Foreign keys
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['last_crawl_run_id'], ['runs.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Add indexes
        op.create_index('ix_scrape_collections_organization_id', 'scrape_collections', ['organization_id'])
        op.create_index('ix_scrape_collections_status', 'scrape_collections', ['status'])
        op.create_index('ix_scrape_collections_org_slug', 'scrape_collections', ['organization_id', 'slug'], unique=True)
        op.create_index('ix_scrape_collections_org_status', 'scrape_collections', ['organization_id', 'status'])

    # Create scrape_sources table
    if 'scrape_sources' not in existing_tables:
        op.create_table(
            'scrape_sources',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('collection_id', sa.String(length=36), nullable=False),

            # Source URL
            sa.Column('url', sa.String(length=2048), nullable=False),
            sa.Column('source_type', sa.String(length=50), nullable=False, server_default=text("'seed'")),

            # Status
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=text('1')),

            # Source-specific config
            sa.Column('crawl_config', sa.JSON(), nullable=True),

            # Crawl tracking
            sa.Column('last_crawl_at', sa.DateTime(), nullable=True),
            sa.Column('last_status', sa.String(length=50), nullable=True),
            sa.Column('discovered_pages', sa.Integer(), nullable=False, server_default=text('0')),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),

            # Foreign keys
            sa.ForeignKeyConstraint(['collection_id'], ['scrape_collections.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Add indexes
        op.create_index('ix_scrape_sources_collection_id', 'scrape_sources', ['collection_id'])
        op.create_index('ix_scrape_sources_collection_url', 'scrape_sources', ['collection_id', 'url'])
        op.create_index('ix_scrape_sources_collection_active', 'scrape_sources', ['collection_id', 'is_active'])

    # Create scraped_assets table
    if 'scraped_assets' not in existing_tables:
        op.create_table(
            'scraped_assets',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('asset_id', sa.String(length=36), nullable=False),
            sa.Column('collection_id', sa.String(length=36), nullable=False),
            sa.Column('source_id', sa.String(length=36), nullable=True),

            # Asset subtype
            sa.Column('asset_subtype', sa.String(length=50), nullable=False, server_default=text("'page'")),

            # URL and hierarchy
            sa.Column('url', sa.String(length=2048), nullable=False),
            sa.Column('url_path', sa.String(length=2048), nullable=True),
            sa.Column('parent_url', sa.String(length=2048), nullable=True),

            # Crawl context
            sa.Column('crawl_depth', sa.Integer(), nullable=False, server_default=text('0')),
            sa.Column('crawl_run_id', sa.String(length=36), nullable=True),

            # Promotion tracking
            sa.Column('is_promoted', sa.Boolean(), nullable=False, server_default=text('0')),
            sa.Column('promoted_at', sa.DateTime(), nullable=True),
            sa.Column('promoted_by', sa.String(length=36), nullable=True),

            # Scrape metadata
            sa.Column('scrape_metadata', sa.JSON(), nullable=False, server_default=text("'{}'")),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),

            # Foreign keys
            sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['collection_id'], ['scrape_collections.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['source_id'], ['scrape_sources.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['crawl_run_id'], ['runs.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['promoted_by'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Add indexes
        op.create_index('ix_scraped_assets_asset_id', 'scraped_assets', ['asset_id'])
        op.create_index('ix_scraped_assets_collection_id', 'scraped_assets', ['collection_id'])
        op.create_index('ix_scraped_assets_source_id', 'scraped_assets', ['source_id'])
        op.create_index('ix_scraped_assets_asset_subtype', 'scraped_assets', ['asset_subtype'])
        op.create_index('ix_scraped_assets_is_promoted', 'scraped_assets', ['is_promoted'])
        op.create_index('ix_scraped_assets_crawl_run_id', 'scraped_assets', ['crawl_run_id'])
        op.create_index('ix_scraped_assets_collection', 'scraped_assets', ['collection_id'])
        op.create_index('ix_scraped_assets_collection_path', 'scraped_assets', ['collection_id', 'url_path'])
        op.create_index('ix_scraped_assets_collection_subtype', 'scraped_assets', ['collection_id', 'asset_subtype'])
        op.create_index('ix_scraped_assets_collection_promoted', 'scraped_assets', ['collection_id', 'is_promoted'])
        op.create_index('ix_scraped_assets_crawl_run', 'scraped_assets', ['crawl_run_id'])
        op.create_index('ix_scraped_assets_collection_url', 'scraped_assets', ['collection_id', 'url'], unique=True)


def downgrade() -> None:
    """Downgrade database to remove scrape collection tables."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Drop scraped_assets table
    if 'scraped_assets' in existing_tables:
        # Drop indexes first
        for idx_name in [
            'ix_scraped_assets_collection_url', 'ix_scraped_assets_crawl_run',
            'ix_scraped_assets_collection_promoted', 'ix_scraped_assets_collection_subtype',
            'ix_scraped_assets_collection_path', 'ix_scraped_assets_collection',
            'ix_scraped_assets_crawl_run_id', 'ix_scraped_assets_is_promoted',
            'ix_scraped_assets_asset_subtype', 'ix_scraped_assets_source_id',
            'ix_scraped_assets_collection_id', 'ix_scraped_assets_asset_id',
        ]:
            try:
                op.drop_index(idx_name, table_name='scraped_assets')
            except:
                pass
        op.drop_table('scraped_assets')

    # Drop scrape_sources table
    if 'scrape_sources' in existing_tables:
        for idx_name in [
            'ix_scrape_sources_collection_active', 'ix_scrape_sources_collection_url',
            'ix_scrape_sources_collection_id',
        ]:
            try:
                op.drop_index(idx_name, table_name='scrape_sources')
            except:
                pass
        op.drop_table('scrape_sources')

    # Drop scrape_collections table
    if 'scrape_collections' in existing_tables:
        for idx_name in [
            'ix_scrape_collections_org_status', 'ix_scrape_collections_org_slug',
            'ix_scrape_collections_status', 'ix_scrape_collections_organization_id',
        ]:
            try:
                op.drop_index(idx_name, table_name='scrape_collections')
            except:
                pass
        op.drop_table('scrape_collections')
