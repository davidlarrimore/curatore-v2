"""Add indexed_at to sam_solicitations, sam_notices, salesforce_contacts

Revision ID: add_indexed_at_columns
Revises: add_forecast_history
Create Date: 2026-02-07

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "add_indexed_at_columns"
down_revision = "add_forecast_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add indexed_at column to tables missing it for incremental reindex support."""

    op.add_column(
        "sam_solicitations",
        sa.Column("indexed_at", sa.DateTime(), nullable=True),
    )

    op.add_column(
        "sam_notices",
        sa.Column("indexed_at", sa.DateTime(), nullable=True),
    )

    op.add_column(
        "salesforce_contacts",
        sa.Column("indexed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Remove indexed_at columns."""

    op.drop_column("salesforce_contacts", "indexed_at")
    op.drop_column("sam_notices", "indexed_at")
    op.drop_column("sam_solicitations", "indexed_at")
