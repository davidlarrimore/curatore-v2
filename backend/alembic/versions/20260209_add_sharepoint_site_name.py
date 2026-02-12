"""Add site_name column to sharepoint_sync_configs

Stores the human-readable SharePoint site display name
(e.g., "IT Department", "Corporate Communications").

Revision ID: sharepoint_site_name
Revises: run_trace_fields
Create Date: 2026-02-09
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "sharepoint_site_name"
down_revision = "run_trace_fields"
branch_labels = None
depends_on = None


def _column_exists(connection, table_name, column_name):
    """Check if a column exists in a table."""
    result = connection.execute(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
            ")"
        ),
        {"t": table_name, "c": column_name},
    )
    return result.scalar()


def upgrade() -> None:
    connection = op.get_bind()

    if not _column_exists(connection, "sharepoint_sync_configs", "site_name"):
        op.add_column(
            "sharepoint_sync_configs",
            sa.Column("site_name", sa.String(500), nullable=True),
        )


def downgrade() -> None:
    connection = op.get_bind()

    if _column_exists(connection, "sharepoint_sync_configs", "site_name"):
        op.drop_column("sharepoint_sync_configs", "site_name")
