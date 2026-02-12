"""Add triage fields and remove legacy enhancement fields.

Revision ID: 20260201_2100
Revises: 20260201_2000
Create Date: 2026-02-01 21:00:00.000000

Adds triage fields to support the new intelligent extraction routing architecture.
The triage phase analyzes documents upfront to select the optimal extraction engine:
- fast_pdf: PyMuPDF-based extraction for simple PDFs
- fast_office: Native Python extraction for Office files
- docling: Advanced extraction for complex documents
- ocr_only: OCR extraction for images and scanned documents

Also removes legacy enhancement fields from assets table since enhancement
is now integrated into the triage-based extraction flow.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision = '20260201_2100'
down_revision = '20260201_2000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add triage columns and remove legacy enhancement columns."""
    # =========================================================================
    # Add triage columns to extraction_results table
    # =========================================================================

    # triage_engine: The extraction engine selected by triage
    # Values: fast_pdf, fast_office, docling, ocr_only
    op.add_column(
        'extraction_results',
        sa.Column('triage_engine', sa.String(50), nullable=True)
    )

    # triage_needs_ocr: Whether document requires OCR
    op.add_column(
        'extraction_results',
        sa.Column('triage_needs_ocr', sa.Boolean(), nullable=True)
    )

    # triage_needs_layout: Whether document has complex layout
    op.add_column(
        'extraction_results',
        sa.Column('triage_needs_layout', sa.Boolean(), nullable=True)
    )

    # triage_complexity: Document complexity assessment
    # Values: low, medium, high
    op.add_column(
        'extraction_results',
        sa.Column('triage_complexity', sa.String(20), nullable=True)
    )

    # triage_duration_ms: Time taken for triage analysis in milliseconds
    op.add_column(
        'extraction_results',
        sa.Column('triage_duration_ms', sa.Integer(), nullable=True)
    )

    # Create index for querying by triage engine
    op.create_index(
        'ix_extraction_results_triage_engine',
        'extraction_results',
        ['triage_engine']
    )

    # =========================================================================
    # Remove legacy enhancement columns from assets table
    # =========================================================================
    op.drop_column('assets', 'enhancement_eligible')
    op.drop_column('assets', 'enhancement_queued_at')


def downgrade() -> None:
    """Remove triage columns and restore legacy enhancement columns."""
    # Restore enhancement columns
    op.add_column(
        'assets',
        sa.Column('enhancement_eligible', sa.Boolean(), nullable=True)
    )
    op.add_column(
        'assets',
        sa.Column('enhancement_queued_at', sa.DateTime(), nullable=True)
    )

    # Remove triage columns
    op.drop_index('ix_extraction_results_triage_engine', table_name='extraction_results')
    op.drop_column('extraction_results', 'triage_duration_ms')
    op.drop_column('extraction_results', 'triage_complexity')
    op.drop_column('extraction_results', 'triage_needs_layout')
    op.drop_column('extraction_results', 'triage_needs_ocr')
    op.drop_column('extraction_results', 'triage_engine')
