"""Add summary_status columns to sam_solicitations table

This migration adds auto-summary tracking fields to the SamSolicitation model
as part of Phase 7.6: SAM.gov Frontend Restructuring.

Columns added to sam_solicitations:
- summary_status: Track auto-summary generation status (pending, generating, ready, failed, no_llm)
- summary_generated_at: Timestamp when summary was last generated

These changes enable:
- Auto-summary generation after SAM pull jobs
- UI status indicators showing summary generation progress
- Regenerate summary functionality

Revision ID: phase7_sam_summary
Revises: phase5_scheduling
Create Date: 2026-01-29 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'phase7_sam_summary'
down_revision = 'phase5_scheduling'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add summary_status and summary_generated_at columns to sam_solicitations."""

    # Bind to get connection for checking table/column existence
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Only add columns if sam_solicitations table exists
    if 'sam_solicitations' in existing_tables:
        existing_columns = [col['name'] for col in inspector.get_columns('sam_solicitations')]

        # Add summary_status column if it doesn't exist
        if 'summary_status' not in existing_columns:
            op.add_column(
                'sam_solicitations',
                sa.Column('summary_status', sa.String(length=50), nullable=True, server_default=text("'pending'"))
            )
            # Create index for summary_status queries
            op.create_index('ix_sam_solicitations_summary_status', 'sam_solicitations', ['summary_status'])

        # Add summary_generated_at column if it doesn't exist
        if 'summary_generated_at' not in existing_columns:
            op.add_column(
                'sam_solicitations',
                sa.Column('summary_generated_at', sa.DateTime(), nullable=True)
            )


def downgrade() -> None:
    """Remove summary_status and summary_generated_at columns from sam_solicitations."""

    # Bind to get connection for checking table/column existence
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'sam_solicitations' in existing_tables:
        existing_columns = [col['name'] for col in inspector.get_columns('sam_solicitations')]

        # Drop index first
        if 'summary_status' in existing_columns:
            try:
                op.drop_index('ix_sam_solicitations_summary_status', table_name='sam_solicitations')
            except:
                pass
            op.drop_column('sam_solicitations', 'summary_status')

        if 'summary_generated_at' in existing_columns:
            op.drop_column('sam_solicitations', 'summary_generated_at')
