"""Decouple SAM searches from solicitations and notices

Revision ID: decouple_sam_search
Revises: drop_job_tables
Create Date: 2026-01-29 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'decouple_sam_search'
down_revision = 'drop_job_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Decouple SAM searches from solicitations and notices.

    SAM searches define filter criteria for pulling opportunities from SAM.gov,
    but solicitations and notices should exist independently as they represent
    real federal opportunities that may match multiple search configurations.

    This migration:
    - Removes search_id from sam_solicitations
    - Removes search_id from sam_notices
    - Removes solicitation_count from sam_searches
    - Removes notice_count from sam_searches

    Benefits:
    - Solicitations won't be deleted when a search is deleted
    - Same solicitation can be found by multiple searches
    - Cleaner data model that reflects reality
    """

    # Remove search_id from sam_solicitations
    # First drop the composite index, then the single-column index
    with op.batch_alter_table('sam_solicitations', schema=None) as batch_op:
        batch_op.drop_index('ix_sam_solicitations_org_search')
        batch_op.drop_index('ix_sam_solicitations_search_id')
        batch_op.drop_column('search_id')

    # Remove search_id from sam_notices
    with op.batch_alter_table('sam_notices', schema=None) as batch_op:
        batch_op.drop_index('ix_sam_notices_search_id')
        batch_op.drop_column('search_id')

    # Remove solicitation_count and notice_count from sam_searches
    # These were denormalized counters that are no longer needed since
    # solicitations and notices are now decoupled from searches
    with op.batch_alter_table('sam_searches', schema=None) as batch_op:
        batch_op.drop_column('solicitation_count')
        batch_op.drop_column('notice_count')


def downgrade() -> None:
    """Re-add removed columns.

    Note: This will not restore the original data - values will be NULL/0.
    """

    # Re-add solicitation_count and notice_count to sam_searches
    with op.batch_alter_table('sam_searches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('solicitation_count', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('notice_count', sa.Integer(), nullable=False, server_default='0'))

    # Re-add search_id to sam_notices
    with op.batch_alter_table('sam_notices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('search_id', sa.String(36), nullable=True))
        batch_op.create_index('ix_sam_notices_search_id', ['search_id'])

    # Re-add search_id to sam_solicitations
    with op.batch_alter_table('sam_solicitations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('search_id', sa.String(36), nullable=True))
        batch_op.create_index('ix_sam_solicitations_search_id', ['search_id'])
        batch_op.create_index('ix_sam_solicitations_org_search', ['organization_id', 'search_id'])
