"""Add history field to forecast tables

Revision ID: 20260206_forecast_history
Revises: 20260205_add_forecast_integration
Create Date: 2026-02-06

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers
revision = "add_forecast_history"
down_revision = "add_forecast_integration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add history JSONB column to all forecast tables for version tracking."""

    # Add history column to ag_forecasts
    op.add_column(
        "ag_forecasts",
        sa.Column("history", JSONB, nullable=True, server_default="[]"),
    )

    # Add history column to apfs_forecasts
    op.add_column(
        "apfs_forecasts",
        sa.Column("history", JSONB, nullable=True, server_default="[]"),
    )

    # Add history column to state_forecasts
    op.add_column(
        "state_forecasts",
        sa.Column("history", JSONB, nullable=True, server_default="[]"),
    )


def downgrade() -> None:
    """Remove history columns from forecast tables."""

    op.drop_column("state_forecasts", "history")
    op.drop_column("apfs_forecasts", "history")
    op.drop_column("ag_forecasts", "history")
