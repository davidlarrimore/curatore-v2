"""Add tiered extraction support.

Revision ID: add_tiered_extraction
Revises: 20260129_1000_add_sam_summary_status
Create Date: 2026-01-29 11:00:00.000000

Adds fields to support tiered extraction:
- extraction_tier: Track whether extraction is basic (fast) or enhanced (Docling)
- enhancement_eligible: Whether the file type supports enhancement
- enhancement_queued_at: When enhancement was queued
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = 'add_tiered_extraction'
down_revision = 'phase7_sam_summary'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add tiered extraction columns."""
    # Add extraction_tier to extraction_results
    # Values: 'basic' (fast MarkItDown), 'enhanced' (Docling quality)
    op.add_column(
        'extraction_results',
        sa.Column('extraction_tier', sa.String(50), nullable=True, server_default='basic')
    )

    # Add enhancement-related columns to assets
    # enhancement_eligible: Whether file type could benefit from Docling
    op.add_column(
        'assets',
        sa.Column('enhancement_eligible', sa.Boolean(), nullable=True, server_default='false')
    )

    # enhancement_queued_at: When background enhancement was queued
    op.add_column(
        'assets',
        sa.Column('enhancement_queued_at', sa.DateTime(), nullable=True)
    )

    # extraction_tier on asset for quick access to current tier
    op.add_column(
        'assets',
        sa.Column('extraction_tier', sa.String(50), nullable=True, server_default='basic')
    )

    # Create index for finding assets eligible for enhancement
    op.create_index(
        'ix_assets_enhancement_eligible',
        'assets',
        ['enhancement_eligible', 'status', 'extraction_tier']
    )


def downgrade() -> None:
    """Remove tiered extraction columns."""
    op.drop_index('ix_assets_enhancement_eligible', table_name='assets')
    op.drop_column('assets', 'extraction_tier')
    op.drop_column('assets', 'enhancement_queued_at')
    op.drop_column('assets', 'enhancement_eligible')
    op.drop_column('extraction_results', 'extraction_tier')
