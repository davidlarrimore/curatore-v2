"""Add standalone notice fields

Revision ID: add_standalone_notice_fields
Revises: add_tiered_extraction
Create Date: 2026-01-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_standalone_notice_fields'
down_revision = 'add_tiered_extraction'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add columns to sam_notices for standalone notice support.

    Standalone notices (e.g., Special Notices with notice_type='s') don't have
    a solicitation_number and shouldn't create solicitation records. They need
    their own organization_id, search_id, classification fields, and summary fields.
    """

    # Add new columns to sam_notices table
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('sam_notices', schema=None) as batch_op:
        # For standalone notices (when solicitation_id is NULL)
        batch_op.add_column(sa.Column('organization_id', sa.String(36), nullable=True))
        batch_op.add_column(sa.Column('search_id', sa.String(36), nullable=True))

        # Classification fields (for standalone notices)
        batch_op.add_column(sa.Column('naics_code', sa.String(20), nullable=True))
        batch_op.add_column(sa.Column('psc_code', sa.String(20), nullable=True))
        batch_op.add_column(sa.Column('set_aside_code', sa.String(50), nullable=True))

        # Organization hierarchy (for standalone notices)
        batch_op.add_column(sa.Column('agency_name', sa.String(500), nullable=True))
        batch_op.add_column(sa.Column('bureau_name', sa.String(500), nullable=True))
        batch_op.add_column(sa.Column('office_name', sa.String(500), nullable=True))

        # UI link for direct SAM.gov access
        batch_op.add_column(sa.Column('ui_link', sa.String(500), nullable=True))

        # AI Summary fields (similar to SamSolicitation)
        batch_op.add_column(sa.Column('summary_status', sa.String(50), nullable=True))
        batch_op.add_column(sa.Column('summary_generated_at', sa.DateTime(), nullable=True))

        # Create indexes for new columns
        batch_op.create_index('ix_sam_notices_organization_id', ['organization_id'], unique=False)
        batch_op.create_index('ix_sam_notices_search_id', ['search_id'], unique=False)


def downgrade() -> None:
    """Remove standalone notice columns from sam_notices."""

    with op.batch_alter_table('sam_notices', schema=None) as batch_op:
        # Drop indexes
        batch_op.drop_index('ix_sam_notices_organization_id')
        batch_op.drop_index('ix_sam_notices_search_id')

        # Drop columns
        batch_op.drop_column('summary_generated_at')
        batch_op.drop_column('summary_status')
        batch_op.drop_column('ui_link')
        batch_op.drop_column('office_name')
        batch_op.drop_column('bureau_name')
        batch_op.drop_column('agency_name')
        batch_op.drop_column('set_aside_code')
        batch_op.drop_column('psc_code')
        batch_op.drop_column('naics_code')
        batch_op.drop_column('search_id')
        batch_op.drop_column('organization_id')
