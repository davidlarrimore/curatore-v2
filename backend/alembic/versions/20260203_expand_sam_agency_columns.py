"""Expand SAM agency code and abbreviation column sizes.

Revision ID: 20260203_2200
Revises: 20260203_2100
Create Date: 2026-02-03 22:00:00.000000

This migration increases the column sizes for sam_agencies and sam_sub_agencies
tables to accommodate longer agency codes and abbreviations from SAM.gov.

The issue was that agency paths like:
"HOMELAND SECURITY, DEPARTMENT OF.US IMMIGRATION AND CUSTOMS ENFORCEMENT.INFORMATION TECHNOLOGY DIVISION"
exceed the previous VARCHAR(50) limit.

Changes:
- sam_agencies.code: VARCHAR(50) -> VARCHAR(255)
- sam_agencies.abbreviation: VARCHAR(50) -> VARCHAR(100)
- sam_sub_agencies.code: VARCHAR(50) -> VARCHAR(255)
- sam_sub_agencies.abbreviation: VARCHAR(50) -> VARCHAR(100)
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = '20260203_2200'
down_revision = '20260203_2100'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Expand SAM agency column sizes."""
    # Expand sam_agencies columns
    op.alter_column(
        'sam_agencies',
        'code',
        existing_type=sa.String(50),
        type_=sa.String(255),
        existing_nullable=False,
    )
    op.alter_column(
        'sam_agencies',
        'abbreviation',
        existing_type=sa.String(50),
        type_=sa.String(100),
        existing_nullable=True,
    )

    # Expand sam_sub_agencies columns
    op.alter_column(
        'sam_sub_agencies',
        'code',
        existing_type=sa.String(50),
        type_=sa.String(255),
        existing_nullable=False,
    )
    op.alter_column(
        'sam_sub_agencies',
        'abbreviation',
        existing_type=sa.String(50),
        type_=sa.String(100),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Shrink SAM agency column sizes back to original."""
    # Note: This may fail if there's data longer than 50 characters
    op.alter_column(
        'sam_sub_agencies',
        'abbreviation',
        existing_type=sa.String(100),
        type_=sa.String(50),
        existing_nullable=True,
    )
    op.alter_column(
        'sam_sub_agencies',
        'code',
        existing_type=sa.String(255),
        type_=sa.String(50),
        existing_nullable=False,
    )
    op.alter_column(
        'sam_agencies',
        'abbreviation',
        existing_type=sa.String(100),
        type_=sa.String(50),
        existing_nullable=True,
    )
    op.alter_column(
        'sam_agencies',
        'code',
        existing_type=sa.String(255),
        type_=sa.String(50),
        existing_nullable=False,
    )
