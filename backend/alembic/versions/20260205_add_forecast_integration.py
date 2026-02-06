"""Add Acquisition Forecast integration tables

This migration introduces the forecast integration models for importing
acquisition forecasts from three federal sources:
- AG (GSA Acquisition Gateway) - Multi-agency, API with list + detail endpoints
- APFS (DHS) - DHS-only, single bulk API endpoint
- State Department - Monthly Excel download from website

Tables added:
- forecast_syncs: Sync configuration (like SamSearch)
- ag_forecasts: Acquisition Gateway forecasts
- apfs_forecasts: DHS APFS forecasts
- state_forecasts: State Department forecasts

Key features:
- Upsert support via unique constraints per source
- Change tracking via hash for detecting updates
- Search indexing support via indexed_at
- Unified view across all sources

Revision ID: add_forecast_integration
Revises: add_salesforce_integration
Create Date: 2026-02-05 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'add_forecast_integration'
down_revision = 'add_salesforce_integration'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database to include forecast integration tables."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # =========================================================================
    # Create forecast_syncs table (configuration for sync jobs)
    # =========================================================================
    if 'forecast_syncs' not in existing_tables:
        op.create_table(
            'forecast_syncs',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('organization_id', sa.String(length=36), nullable=False),

            # Identity
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('slug', sa.String(length=100), nullable=False),
            sa.Column('source_type', sa.String(length=20), nullable=False),  # ag, apfs, state

            # Status
            sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=text('true')),

            # Scheduling
            sa.Column('sync_frequency', sa.String(length=20), nullable=False, server_default='manual'),

            # Pull tracking
            sa.Column('last_sync_at', sa.DateTime(), nullable=True),
            sa.Column('last_sync_status', sa.String(length=50), nullable=True),
            sa.Column('last_sync_run_id', sa.String(length=36), nullable=True),

            # Filter config (JSONB - source-specific)
            sa.Column('filter_config', sa.JSON(), nullable=False, server_default='{}'),

            # Automation config
            sa.Column('automation_config', sa.JSON(), nullable=False, server_default='{}'),

            # Stats
            sa.Column('forecast_count', sa.Integer(), nullable=False, server_default='0'),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('created_by', sa.String(length=36), nullable=True),

            # Foreign keys
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['last_sync_run_id'], ['runs.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Indexes for forecast_syncs
        op.create_index('ix_forecast_syncs_org_id', 'forecast_syncs', ['organization_id'])
        op.create_index('ix_forecast_syncs_org_slug', 'forecast_syncs', ['organization_id', 'slug'], unique=True)
        op.create_index('ix_forecast_syncs_org_status', 'forecast_syncs', ['organization_id', 'status'])
        op.create_index('ix_forecast_syncs_org_frequency', 'forecast_syncs', ['organization_id', 'sync_frequency'])
        op.create_index('ix_forecast_syncs_source_type', 'forecast_syncs', ['source_type'])

    # =========================================================================
    # Create ag_forecasts table (Acquisition Gateway forecasts)
    # =========================================================================
    if 'ag_forecasts' not in existing_tables:
        op.create_table(
            'ag_forecasts',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('organization_id', sa.String(length=36), nullable=False),
            sa.Column('sync_id', sa.String(length=36), nullable=False),

            # AG identifiers
            sa.Column('nid', sa.String(length=50), nullable=False),

            # Core fields
            sa.Column('title', sa.Text(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('agency_name', sa.String(length=255), nullable=True),
            sa.Column('agency_id', sa.Integer(), nullable=True),
            sa.Column('organization_name', sa.String(length=255), nullable=True),

            # NAICS (JSONB array)
            sa.Column('naics_codes', sa.JSON(), nullable=True),

            # Acquisition details
            sa.Column('acquisition_phase', sa.String(length=100), nullable=True),
            sa.Column('acquisition_strategies', sa.JSON(), nullable=True),
            sa.Column('award_status', sa.String(length=100), nullable=True),
            sa.Column('requirement_type', sa.String(length=100), nullable=True),
            sa.Column('procurement_method', sa.String(length=100), nullable=True),
            sa.Column('set_aside_type', sa.String(length=100), nullable=True),
            sa.Column('extent_competed', sa.String(length=100), nullable=True),
            sa.Column('listing_id', sa.String(length=255), nullable=True),

            # Timeline
            sa.Column('estimated_solicitation_date', sa.Date(), nullable=True),
            sa.Column('estimated_award_fy', sa.Integer(), nullable=True),
            sa.Column('estimated_award_quarter', sa.String(length=20), nullable=True),
            sa.Column('period_of_performance', sa.String(length=255), nullable=True),

            # Contacts
            sa.Column('poc_name', sa.String(length=255), nullable=True),
            sa.Column('poc_email', sa.String(length=255), nullable=True),
            sa.Column('sbs_name', sa.String(length=255), nullable=True),
            sa.Column('sbs_email', sa.String(length=255), nullable=True),

            # Source tracking
            sa.Column('source_url', sa.String(length=1000), nullable=True),
            sa.Column('raw_data', sa.JSON(), nullable=True),

            # Change tracking
            sa.Column('first_seen_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('last_updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('change_hash', sa.String(length=64), nullable=True),

            # Search
            sa.Column('indexed_at', sa.DateTime(), nullable=True),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),

            # Foreign keys
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['sync_id'], ['forecast_syncs.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Indexes for ag_forecasts
        op.create_index('ix_ag_forecasts_org_id', 'ag_forecasts', ['organization_id'])
        op.create_index('ix_ag_forecasts_sync_id', 'ag_forecasts', ['sync_id'])
        op.create_index('ix_ag_forecasts_nid', 'ag_forecasts', ['nid'])
        op.create_index('ix_ag_forecasts_org_nid', 'ag_forecasts', ['organization_id', 'nid'], unique=True)
        op.create_index('ix_ag_forecasts_agency_id', 'ag_forecasts', ['agency_id'])
        op.create_index('ix_ag_forecasts_award_status', 'ag_forecasts', ['award_status'])
        op.create_index('ix_ag_forecasts_est_award_fy', 'ag_forecasts', ['estimated_award_fy'])
        op.create_index('ix_ag_forecasts_org_agency', 'ag_forecasts', ['organization_id', 'agency_id'])
        op.create_index('ix_ag_forecasts_org_status', 'ag_forecasts', ['organization_id', 'award_status'])

    # =========================================================================
    # Create apfs_forecasts table (DHS APFS forecasts)
    # =========================================================================
    if 'apfs_forecasts' not in existing_tables:
        op.create_table(
            'apfs_forecasts',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('organization_id', sa.String(length=36), nullable=False),
            sa.Column('sync_id', sa.String(length=36), nullable=False),

            # APFS identifiers
            sa.Column('apfs_number', sa.String(length=50), nullable=False),
            sa.Column('apfs_id', sa.Integer(), nullable=True),

            # Core fields
            sa.Column('title', sa.Text(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('component', sa.String(length=255), nullable=True),
            sa.Column('mission', sa.String(length=255), nullable=True),

            # NAICS
            sa.Column('naics_code', sa.String(length=20), nullable=True),
            sa.Column('naics_description', sa.String(length=500), nullable=True),

            # Contract details
            sa.Column('contract_type', sa.String(length=100), nullable=True),
            sa.Column('contract_vehicle', sa.String(length=255), nullable=True),
            sa.Column('contract_status', sa.String(length=100), nullable=True),
            sa.Column('competition_type', sa.String(length=100), nullable=True),

            # Small business
            sa.Column('small_business_program', sa.String(length=100), nullable=True),
            sa.Column('small_business_set_aside', sa.String(length=100), nullable=True),

            # Financial
            sa.Column('dollar_range', sa.String(length=100), nullable=True),

            # Timeline
            sa.Column('fiscal_year', sa.Integer(), nullable=True),
            sa.Column('award_quarter', sa.String(length=50), nullable=True),
            sa.Column('anticipated_award_date', sa.Date(), nullable=True),
            sa.Column('estimated_solicitation_date', sa.Date(), nullable=True),
            sa.Column('pop_start_date', sa.Date(), nullable=True),
            sa.Column('pop_end_date', sa.Date(), nullable=True),

            # Offices
            sa.Column('requirements_office', sa.String(length=255), nullable=True),
            sa.Column('contracting_office', sa.String(length=255), nullable=True),

            # Contacts
            sa.Column('poc_name', sa.String(length=255), nullable=True),
            sa.Column('poc_email', sa.String(length=255), nullable=True),
            sa.Column('poc_phone', sa.String(length=50), nullable=True),
            sa.Column('alt_contact_name', sa.String(length=255), nullable=True),
            sa.Column('alt_contact_email', sa.String(length=255), nullable=True),
            sa.Column('sbs_name', sa.String(length=255), nullable=True),
            sa.Column('sbs_email', sa.String(length=255), nullable=True),
            sa.Column('sbs_phone', sa.String(length=50), nullable=True),

            # State
            sa.Column('current_state', sa.String(length=50), nullable=True),
            sa.Column('published_date', sa.Date(), nullable=True),

            # Source tracking
            sa.Column('raw_data', sa.JSON(), nullable=True),

            # Change tracking
            sa.Column('first_seen_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('last_updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('change_hash', sa.String(length=64), nullable=True),

            # Search
            sa.Column('indexed_at', sa.DateTime(), nullable=True),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),

            # Foreign keys
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['sync_id'], ['forecast_syncs.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Indexes for apfs_forecasts
        op.create_index('ix_apfs_forecasts_org_id', 'apfs_forecasts', ['organization_id'])
        op.create_index('ix_apfs_forecasts_sync_id', 'apfs_forecasts', ['sync_id'])
        op.create_index('ix_apfs_forecasts_apfs_number', 'apfs_forecasts', ['apfs_number'])
        op.create_index('ix_apfs_forecasts_org_apfs_num', 'apfs_forecasts', ['organization_id', 'apfs_number'], unique=True)
        op.create_index('ix_apfs_forecasts_component', 'apfs_forecasts', ['component'])
        op.create_index('ix_apfs_forecasts_fiscal_year', 'apfs_forecasts', ['fiscal_year'])
        op.create_index('ix_apfs_forecasts_contract_status', 'apfs_forecasts', ['contract_status'])
        op.create_index('ix_apfs_forecasts_org_component', 'apfs_forecasts', ['organization_id', 'component'])
        op.create_index('ix_apfs_forecasts_org_fy', 'apfs_forecasts', ['organization_id', 'fiscal_year'])

    # =========================================================================
    # Create state_forecasts table (State Department forecasts)
    # =========================================================================
    if 'state_forecasts' not in existing_tables:
        op.create_table(
            'state_forecasts',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('organization_id', sa.String(length=36), nullable=False),
            sa.Column('sync_id', sa.String(length=36), nullable=False),

            # Identifier (generated from row content hash)
            sa.Column('row_hash', sa.String(length=64), nullable=False),

            # Core fields
            sa.Column('title', sa.Text(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),

            # NAICS
            sa.Column('naics_code', sa.String(length=20), nullable=True),

            # Place of performance
            sa.Column('pop_city', sa.String(length=255), nullable=True),
            sa.Column('pop_state', sa.String(length=100), nullable=True),
            sa.Column('pop_country', sa.String(length=100), nullable=True),

            # Acquisition details
            sa.Column('acquisition_phase', sa.String(length=100), nullable=True),
            sa.Column('set_aside_type', sa.String(length=100), nullable=True),
            sa.Column('contract_type', sa.String(length=100), nullable=True),
            sa.Column('anticipated_award_type', sa.String(length=100), nullable=True),

            # Financial & Timeline
            sa.Column('estimated_value', sa.String(length=255), nullable=True),
            sa.Column('fiscal_year', sa.Integer(), nullable=True),
            sa.Column('estimated_award_quarter', sa.String(length=50), nullable=True),
            sa.Column('estimated_solicitation_date', sa.Date(), nullable=True),

            # Additional
            sa.Column('incumbent_contractor', sa.String(length=255), nullable=True),
            sa.Column('awarded_contract_order', sa.String(length=255), nullable=True),
            sa.Column('facility_clearance', sa.String(length=100), nullable=True),

            # Source tracking
            sa.Column('source_file', sa.String(length=255), nullable=True),
            sa.Column('source_row', sa.Integer(), nullable=True),
            sa.Column('raw_data', sa.JSON(), nullable=True),

            # Change tracking
            sa.Column('first_seen_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('last_updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('change_hash', sa.String(length=64), nullable=True),

            # Search
            sa.Column('indexed_at', sa.DateTime(), nullable=True),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),

            # Foreign keys
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['sync_id'], ['forecast_syncs.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Indexes for state_forecasts
        op.create_index('ix_state_forecasts_org_id', 'state_forecasts', ['organization_id'])
        op.create_index('ix_state_forecasts_sync_id', 'state_forecasts', ['sync_id'])
        op.create_index('ix_state_forecasts_row_hash', 'state_forecasts', ['row_hash'])
        op.create_index('ix_state_forecasts_org_hash', 'state_forecasts', ['organization_id', 'row_hash'], unique=True)
        op.create_index('ix_state_forecasts_fiscal_year', 'state_forecasts', ['fiscal_year'])
        op.create_index('ix_state_forecasts_org_fy', 'state_forecasts', ['organization_id', 'fiscal_year'])

    # =========================================================================
    # Create unified_forecasts VIEW
    # =========================================================================
    # Drop view if exists to allow recreation
    op.execute("DROP VIEW IF EXISTS unified_forecasts")

    op.execute("""
        CREATE VIEW unified_forecasts AS
        SELECT
            id, organization_id, sync_id,
            'ag' AS source_type,
            nid AS source_id,
            title, description,
            agency_name,
            naics_codes::jsonb AS naics_codes,
            acquisition_phase,
            set_aside_type,
            NULL::varchar AS contract_type,
            NULL::varchar AS contract_vehicle,
            estimated_solicitation_date,
            estimated_award_fy AS fiscal_year,
            estimated_award_quarter,
            NULL::varchar AS dollar_range,
            NULL::date AS pop_start_date,
            NULL::date AS pop_end_date,
            NULL::varchar AS pop_city,
            NULL::varchar AS pop_state,
            NULL::varchar AS pop_country,
            poc_name, poc_email,
            sbs_name, sbs_email,
            NULL::varchar AS incumbent_contractor,
            source_url,
            first_seen_at, last_updated_at, change_hash,
            indexed_at, created_at, updated_at
        FROM ag_forecasts

        UNION ALL

        SELECT
            id, organization_id, sync_id,
            'apfs' AS source_type,
            apfs_number AS source_id,
            title, description,
            'Department of Homeland Security' AS agency_name,
            jsonb_build_array(jsonb_build_object('code', naics_code, 'description', naics_description)) AS naics_codes,
            NULL::varchar AS acquisition_phase,
            small_business_set_aside AS set_aside_type,
            contract_type,
            contract_vehicle,
            estimated_solicitation_date,
            fiscal_year,
            award_quarter AS estimated_award_quarter,
            dollar_range,
            pop_start_date,
            pop_end_date,
            NULL::varchar AS pop_city,
            NULL::varchar AS pop_state,
            NULL::varchar AS pop_country,
            poc_name, poc_email,
            sbs_name, sbs_email,
            NULL::varchar AS incumbent_contractor,
            NULL::varchar AS source_url,
            first_seen_at, last_updated_at, change_hash,
            indexed_at, created_at, updated_at
        FROM apfs_forecasts

        UNION ALL

        SELECT
            id, organization_id, sync_id,
            'state' AS source_type,
            row_hash AS source_id,
            title, description,
            'Department of State' AS agency_name,
            jsonb_build_array(jsonb_build_object('code', naics_code)) AS naics_codes,
            acquisition_phase,
            set_aside_type,
            contract_type,
            NULL::varchar AS contract_vehicle,
            estimated_solicitation_date,
            fiscal_year,
            estimated_award_quarter,
            estimated_value AS dollar_range,
            NULL::date AS pop_start_date,
            NULL::date AS pop_end_date,
            pop_city, pop_state, pop_country,
            NULL::varchar AS poc_name, NULL::varchar AS poc_email,
            NULL::varchar AS sbs_name, NULL::varchar AS sbs_email,
            incumbent_contractor,
            NULL::varchar AS source_url,
            first_seen_at, last_updated_at, change_hash,
            indexed_at, created_at, updated_at
        FROM state_forecasts
    """)


def downgrade() -> None:
    """Downgrade database to remove forecast integration tables."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Drop the unified view first
    op.execute("DROP VIEW IF EXISTS unified_forecasts")

    # Drop state_forecasts table
    if 'state_forecasts' in existing_tables:
        for idx_name in [
            'ix_state_forecasts_org_fy', 'ix_state_forecasts_fiscal_year',
            'ix_state_forecasts_org_hash', 'ix_state_forecasts_row_hash',
            'ix_state_forecasts_sync_id', 'ix_state_forecasts_org_id',
        ]:
            try:
                op.drop_index(idx_name, table_name='state_forecasts')
            except Exception:
                pass
        op.drop_table('state_forecasts')

    # Drop apfs_forecasts table
    if 'apfs_forecasts' in existing_tables:
        for idx_name in [
            'ix_apfs_forecasts_org_fy', 'ix_apfs_forecasts_org_component',
            'ix_apfs_forecasts_contract_status', 'ix_apfs_forecasts_fiscal_year',
            'ix_apfs_forecasts_component', 'ix_apfs_forecasts_org_apfs_num',
            'ix_apfs_forecasts_apfs_number', 'ix_apfs_forecasts_sync_id',
            'ix_apfs_forecasts_org_id',
        ]:
            try:
                op.drop_index(idx_name, table_name='apfs_forecasts')
            except Exception:
                pass
        op.drop_table('apfs_forecasts')

    # Drop ag_forecasts table
    if 'ag_forecasts' in existing_tables:
        for idx_name in [
            'ix_ag_forecasts_org_status', 'ix_ag_forecasts_org_agency',
            'ix_ag_forecasts_est_award_fy', 'ix_ag_forecasts_award_status',
            'ix_ag_forecasts_agency_id', 'ix_ag_forecasts_org_nid',
            'ix_ag_forecasts_nid', 'ix_ag_forecasts_sync_id',
            'ix_ag_forecasts_org_id',
        ]:
            try:
                op.drop_index(idx_name, table_name='ag_forecasts')
            except Exception:
                pass
        op.drop_table('ag_forecasts')

    # Drop forecast_syncs table
    if 'forecast_syncs' in existing_tables:
        for idx_name in [
            'ix_forecast_syncs_source_type', 'ix_forecast_syncs_org_frequency',
            'ix_forecast_syncs_org_status', 'ix_forecast_syncs_org_slug',
            'ix_forecast_syncs_org_id',
        ]:
            try:
                op.drop_index(idx_name, table_name='forecast_syncs')
            except Exception:
                pass
        op.drop_table('forecast_syncs')
