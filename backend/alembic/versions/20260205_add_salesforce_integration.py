"""Add Salesforce CRM integration tables

This migration introduces the Salesforce integration models for importing
and managing CRM data from Salesforce exports.

Tables added:
- salesforce_accounts: Company/organization records with hierarchy support
- salesforce_contacts: Contact records linked to accounts
- salesforce_opportunities: Sales pipeline opportunities with future hooks

Key features:
- Upsert support via unique (organization_id, salesforce_id) constraints
- Account hierarchy via parent_salesforce_id
- Small business flags as JSONB for certification tracking
- Future integration hooks for SharePoint and SAM.gov linking

These changes enable:
- Salesforce export zip file processing
- Account/Contact/Opportunity CRUD operations
- Search indexing for opportunities and accounts
- Pipeline visibility within Curatore

Revision ID: add_salesforce_integration
Revises: add_solicitation_number_to_notices
Create Date: 2026-02-05 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'add_salesforce_integration'
down_revision = 'add_solicitation_number_to_notices'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database to include Salesforce integration tables."""

    # Bind to get connection for checking table existence
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # =========================================================================
    # Create salesforce_accounts table
    # =========================================================================
    if 'salesforce_accounts' not in existing_tables:
        op.create_table(
            'salesforce_accounts',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('organization_id', sa.String(length=36), nullable=False),

            # Salesforce identifiers
            sa.Column('salesforce_id', sa.String(length=18), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('parent_salesforce_id', sa.String(length=18), nullable=True),

            # Classification
            sa.Column('account_type', sa.String(length=100), nullable=True),
            sa.Column('industry', sa.String(length=100), nullable=True),
            sa.Column('department', sa.String(length=255), nullable=True),

            # Details
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('website', sa.String(length=500), nullable=True),
            sa.Column('phone', sa.String(length=50), nullable=True),

            # Addresses (JSONB)
            sa.Column('billing_address', sa.JSON(), nullable=True),
            sa.Column('shipping_address', sa.JSON(), nullable=True),

            # Small business certifications (JSONB)
            sa.Column('small_business_flags', sa.JSON(), nullable=True),

            # Audit trail
            sa.Column('raw_data', sa.JSON(), nullable=True),

            # Search indexing
            sa.Column('indexed_at', sa.DateTime(), nullable=True),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),

            # Foreign keys
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Add indexes for salesforce_accounts
        op.create_index('ix_sf_accounts_organization_id', 'salesforce_accounts', ['organization_id'])
        op.create_index('ix_sf_accounts_salesforce_id', 'salesforce_accounts', ['salesforce_id'])
        op.create_index('ix_sf_accounts_name', 'salesforce_accounts', ['name'])
        op.create_index('ix_sf_accounts_parent_sf_id', 'salesforce_accounts', ['parent_salesforce_id'])
        op.create_index('ix_sf_accounts_account_type', 'salesforce_accounts', ['account_type'])
        op.create_index('ix_sf_accounts_industry', 'salesforce_accounts', ['industry'])
        op.create_index('ix_sf_accounts_org_sf_id', 'salesforce_accounts', ['organization_id', 'salesforce_id'], unique=True)
        op.create_index('ix_sf_accounts_org_type', 'salesforce_accounts', ['organization_id', 'account_type'])
        op.create_index('ix_sf_accounts_org_industry', 'salesforce_accounts', ['organization_id', 'industry'])
        op.create_index('ix_sf_accounts_org_name', 'salesforce_accounts', ['organization_id', 'name'])

    # =========================================================================
    # Create salesforce_contacts table
    # =========================================================================
    if 'salesforce_contacts' not in existing_tables:
        op.create_table(
            'salesforce_contacts',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('organization_id', sa.String(length=36), nullable=False),

            # Salesforce identifiers
            sa.Column('salesforce_id', sa.String(length=18), nullable=False),
            sa.Column('account_id', sa.String(length=36), nullable=True),
            sa.Column('account_salesforce_id', sa.String(length=18), nullable=True),

            # Person details
            sa.Column('first_name', sa.String(length=100), nullable=True),
            sa.Column('last_name', sa.String(length=100), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=True),
            sa.Column('title', sa.String(length=255), nullable=True),
            sa.Column('phone', sa.String(length=50), nullable=True),
            sa.Column('mobile_phone', sa.String(length=50), nullable=True),
            sa.Column('department', sa.String(length=255), nullable=True),

            # Status
            sa.Column('is_current_employee', sa.Boolean(), nullable=True, server_default=text('true')),

            # Address (JSONB)
            sa.Column('mailing_address', sa.JSON(), nullable=True),

            # Audit trail
            sa.Column('raw_data', sa.JSON(), nullable=True),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),

            # Foreign keys
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['account_id'], ['salesforce_accounts.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Add indexes for salesforce_contacts
        op.create_index('ix_sf_contacts_organization_id', 'salesforce_contacts', ['organization_id'])
        op.create_index('ix_sf_contacts_salesforce_id', 'salesforce_contacts', ['salesforce_id'])
        op.create_index('ix_sf_contacts_account', 'salesforce_contacts', ['account_id'])
        op.create_index('ix_sf_contacts_account_sf_id', 'salesforce_contacts', ['account_salesforce_id'])
        op.create_index('ix_sf_contacts_email', 'salesforce_contacts', ['email'])
        op.create_index('ix_sf_contacts_org_sf_id', 'salesforce_contacts', ['organization_id', 'salesforce_id'], unique=True)
        op.create_index('ix_sf_contacts_org_name', 'salesforce_contacts', ['organization_id', 'last_name', 'first_name'])

    # =========================================================================
    # Create salesforce_opportunities table
    # =========================================================================
    if 'salesforce_opportunities' not in existing_tables:
        op.create_table(
            'salesforce_opportunities',
            sa.Column('id', sa.String(length=36), primary_key=True),
            sa.Column('organization_id', sa.String(length=36), nullable=False),

            # Salesforce identifiers
            sa.Column('salesforce_id', sa.String(length=18), nullable=False),
            sa.Column('account_id', sa.String(length=36), nullable=True),
            sa.Column('account_salesforce_id', sa.String(length=18), nullable=True),

            # Core opportunity fields
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('stage_name', sa.String(length=100), nullable=True),
            sa.Column('amount', sa.Float(), nullable=True),
            sa.Column('probability', sa.Float(), nullable=True),
            sa.Column('close_date', sa.Date(), nullable=True),
            sa.Column('is_closed', sa.Boolean(), nullable=True, server_default=text('false')),
            sa.Column('is_won', sa.Boolean(), nullable=True, server_default=text('false')),

            # Classification
            sa.Column('opportunity_type', sa.String(length=100), nullable=True),
            sa.Column('role', sa.String(length=100), nullable=True),
            sa.Column('lead_source', sa.String(length=100), nullable=True),
            sa.Column('fiscal_year', sa.String(length=10), nullable=True),
            sa.Column('fiscal_quarter', sa.String(length=10), nullable=True),

            # Details
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('custom_dates', sa.JSON(), nullable=True),

            # Future integration hooks
            sa.Column('linked_sharepoint_folder_id', sa.String(length=36), nullable=True),
            sa.Column('linked_sam_solicitation_id', sa.String(length=36), nullable=True),

            # Audit trail
            sa.Column('raw_data', sa.JSON(), nullable=True),

            # Search indexing
            sa.Column('indexed_at', sa.DateTime(), nullable=True),

            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=text('CURRENT_TIMESTAMP')),

            # Foreign keys
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['account_id'], ['salesforce_accounts.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['linked_sharepoint_folder_id'], ['sharepoint_sync_configs.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['linked_sam_solicitation_id'], ['sam_solicitations.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )

        # Add indexes for salesforce_opportunities
        op.create_index('ix_sf_opps_organization_id', 'salesforce_opportunities', ['organization_id'])
        op.create_index('ix_sf_opps_salesforce_id', 'salesforce_opportunities', ['salesforce_id'])
        op.create_index('ix_sf_opps_name', 'salesforce_opportunities', ['name'])
        op.create_index('ix_sf_opps_account', 'salesforce_opportunities', ['account_id'])
        op.create_index('ix_sf_opps_account_sf_id', 'salesforce_opportunities', ['account_salesforce_id'])
        op.create_index('ix_sf_opps_stage_name', 'salesforce_opportunities', ['stage_name'])
        op.create_index('ix_sf_opps_close_date', 'salesforce_opportunities', ['close_date'])
        op.create_index('ix_sf_opps_opportunity_type', 'salesforce_opportunities', ['opportunity_type'])
        op.create_index('ix_sf_opps_linked_sp', 'salesforce_opportunities', ['linked_sharepoint_folder_id'])
        op.create_index('ix_sf_opps_linked_sam', 'salesforce_opportunities', ['linked_sam_solicitation_id'])
        op.create_index('ix_sf_opps_org_sf_id', 'salesforce_opportunities', ['organization_id', 'salesforce_id'], unique=True)
        op.create_index('ix_sf_opps_org_stage', 'salesforce_opportunities', ['organization_id', 'stage_name'])
        op.create_index('ix_sf_opps_org_close_date', 'salesforce_opportunities', ['organization_id', 'close_date'])
        op.create_index('ix_sf_opps_org_type', 'salesforce_opportunities', ['organization_id', 'opportunity_type'])
        op.create_index('ix_sf_opps_org_is_closed', 'salesforce_opportunities', ['organization_id', 'is_closed'])


def downgrade() -> None:
    """Downgrade database to remove Salesforce integration tables."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Drop salesforce_opportunities table
    if 'salesforce_opportunities' in existing_tables:
        # Drop indexes first
        for idx_name in [
            'ix_sf_opps_org_is_closed', 'ix_sf_opps_org_type', 'ix_sf_opps_org_close_date',
            'ix_sf_opps_org_stage', 'ix_sf_opps_org_sf_id', 'ix_sf_opps_linked_sam',
            'ix_sf_opps_linked_sp', 'ix_sf_opps_opportunity_type', 'ix_sf_opps_close_date',
            'ix_sf_opps_stage_name', 'ix_sf_opps_account_sf_id', 'ix_sf_opps_account',
            'ix_sf_opps_name', 'ix_sf_opps_salesforce_id', 'ix_sf_opps_organization_id',
        ]:
            try:
                op.drop_index(idx_name, table_name='salesforce_opportunities')
            except Exception:
                pass
        op.drop_table('salesforce_opportunities')

    # Drop salesforce_contacts table
    if 'salesforce_contacts' in existing_tables:
        for idx_name in [
            'ix_sf_contacts_org_name', 'ix_sf_contacts_org_sf_id', 'ix_sf_contacts_email',
            'ix_sf_contacts_account_sf_id', 'ix_sf_contacts_account', 'ix_sf_contacts_salesforce_id',
            'ix_sf_contacts_organization_id',
        ]:
            try:
                op.drop_index(idx_name, table_name='salesforce_contacts')
            except Exception:
                pass
        op.drop_table('salesforce_contacts')

    # Drop salesforce_accounts table
    if 'salesforce_accounts' in existing_tables:
        for idx_name in [
            'ix_sf_accounts_org_name', 'ix_sf_accounts_org_industry', 'ix_sf_accounts_org_type',
            'ix_sf_accounts_org_sf_id', 'ix_sf_accounts_industry', 'ix_sf_accounts_account_type',
            'ix_sf_accounts_parent_sf_id', 'ix_sf_accounts_name', 'ix_sf_accounts_salesforce_id',
            'ix_sf_accounts_organization_id',
        ]:
            try:
                op.drop_index(idx_name, table_name='salesforce_accounts')
            except Exception:
                pass
        op.drop_table('salesforce_accounts')
