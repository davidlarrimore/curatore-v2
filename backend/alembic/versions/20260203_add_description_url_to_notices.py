"""Add description_url column to sam_notices

Revision ID: add_description_url
Revises: add_raw_data_sam
Create Date: 2026-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_description_url'
down_revision: Union[str, None] = 'add_raw_data_sam'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'sam_notices',
        sa.Column('description_url', sa.String(1000), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('sam_notices', 'description_url')
