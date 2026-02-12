"""Decouple forecast records from sync configs

Make sync_id nullable and change ondelete from CASCADE to SET NULL
on all three forecast tables. Forecasts are tied to their data source
(AG/APFS/State), not to a specific sync configuration. Deleting a
sync config should not destroy forecast data.

Revision ID: decouple_forecast_sync
Revises: facet_reference_data
Create Date: 2026-02-12
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "decouple_forecast_sync"
down_revision = "facet_reference_data"
branch_labels = None
depends_on = None


TABLES = ["ag_forecasts", "apfs_forecasts", "state_forecasts"]
FK_NAMES = {
    "ag_forecasts": "ag_forecasts_sync_id_fkey",
    "apfs_forecasts": "apfs_forecasts_sync_id_fkey",
    "state_forecasts": "state_forecasts_sync_id_fkey",
}


def upgrade() -> None:
    conn = op.get_bind()

    for table in TABLES:
        # Make column nullable
        op.alter_column(table, "sync_id", existing_type=sa.UUID(), nullable=True)

        # Find the actual FK constraint name (may differ from convention)
        result = conn.execute(sa.text(
            "SELECT tc.constraint_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "WHERE tc.table_name = :table "
            "  AND tc.constraint_type = 'FOREIGN KEY' "
            "  AND kcu.column_name = 'sync_id'"
        ), {"table": table})
        row = result.fetchone()

        if row:
            fk_name = row[0]
            # Drop old CASCADE FK, recreate as SET NULL
            op.drop_constraint(fk_name, table, type_="foreignkey")
            op.create_foreign_key(
                FK_NAMES[table],
                table,
                "forecast_syncs",
                ["sync_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    for table in TABLES:
        # Set any NULLs back (would fail if there are orphans — best effort)
        op.alter_column(table, "sync_id", existing_type=sa.UUID(), nullable=False)

        # Drop SET NULL FK, recreate as CASCADE
        op.drop_constraint(FK_NAMES[table], table, type_="foreignkey")
        op.create_foreign_key(
            FK_NAMES[table],
            table,
            "forecast_syncs",
            ["sync_id"],
            ["id"],
            ondelete="CASCADE",
        )
