"""Add raw_data column to SAM tables

Revision ID: add_raw_data_sam
Revises:
Create Date: 2026-02-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_raw_data_sam'
down_revision: Union[str, None] = '20260203_2200'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add raw_data column to sam_solicitations
    op.add_column(
        'sam_solicitations',
        sa.Column('raw_data', postgresql.JSON(astext_type=sa.Text()), nullable=True)
    )

    # Add raw_data and full_parent_path columns to sam_notices
    op.add_column(
        'sam_notices',
        sa.Column('raw_data', postgresql.JSON(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        'sam_notices',
        sa.Column('full_parent_path', sa.String(1000), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('sam_notices', 'full_parent_path')
    op.drop_column('sam_notices', 'raw_data')
    op.drop_column('sam_solicitations', 'raw_data')
