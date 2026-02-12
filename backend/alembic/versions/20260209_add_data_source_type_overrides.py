"""Add data_source_type_overrides table

Stores org-level overrides for data source type definitions.
Baseline definitions live in data_sources.yaml; this table allows
admins to customize display_name, description, capabilities, or
hide irrelevant source types for their organization.

Revision ID: data_source_overrides
Revises: add_missing_org_ids
Create Date: 2026-02-09
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "data_source_overrides"
down_revision = "add_missing_org_ids"
branch_labels = None
depends_on = None


def _table_exists(connection, table_name):
    """Check if a table exists."""
    result = connection.execute(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :t"
            ")"
        ),
        {"t": table_name},
    )
    return result.scalar()


def upgrade() -> None:
    connection = op.get_bind()

    if not _table_exists(connection, "data_source_type_overrides"):
        op.create_table(
            "data_source_type_overrides",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("source_type", sa.String(100), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=True),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("capabilities", sa.JSON, nullable=True),
            sa.Column("is_active", sa.Boolean, default=True, nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )
        op.create_index(
            "ix_ds_override_org_type",
            "data_source_type_overrides",
            ["organization_id", "source_type"],
            unique=True,
        )


def downgrade() -> None:
    connection = op.get_bind()

    if _table_exists(connection, "data_source_type_overrides"):
        op.drop_index("ix_ds_override_org_type", "data_source_type_overrides")
        op.drop_table("data_source_type_overrides")
