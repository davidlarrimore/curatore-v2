"""Add facet reference data tables

Stores canonical reference values and aliases for facet dimensions,
enabling cross-source naming resolution (e.g., "DHS" -> all variants
of Department of Homeland Security).

Revision ID: facet_reference_data
Revises: data_source_overrides
Create Date: 2026-02-10
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "facet_reference_data"
down_revision = "data_source_overrides"
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

    if not _table_exists(connection, "facet_reference_values"):
        op.create_table(
            "facet_reference_values",
            sa.Column("id", sa.dialects.postgresql.UUID(), primary_key=True),
            sa.Column(
                "organization_id",
                sa.dialects.postgresql.UUID(),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("facet_name", sa.String(100), nullable=False),
            sa.Column("canonical_value", sa.String(500), nullable=False),
            sa.Column("display_label", sa.String(200), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
            sa.Column("status", sa.String(20), server_default="active", nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_facet_ref_values_facet",
            "facet_reference_values",
            ["facet_name"],
        )
        op.create_index(
            "ix_facet_ref_values_org_facet",
            "facet_reference_values",
            ["organization_id", "facet_name"],
        )
        op.create_index(
            "ix_facet_ref_values_unique",
            "facet_reference_values",
            ["organization_id", "facet_name", "canonical_value"],
            unique=True,
        )

    if not _table_exists(connection, "facet_reference_aliases"):
        op.create_table(
            "facet_reference_aliases",
            sa.Column("id", sa.dialects.postgresql.UUID(), primary_key=True),
            sa.Column(
                "reference_value_id",
                sa.dialects.postgresql.UUID(),
                sa.ForeignKey("facet_reference_values.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("alias_value", sa.String(500), nullable=False),
            sa.Column("alias_value_lower", sa.String(500), nullable=False),
            sa.Column("source_hint", sa.String(100), nullable=True),
            sa.Column("match_method", sa.String(50), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("status", sa.String(20), server_default="active", nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_facet_ref_aliases_ref_id",
            "facet_reference_aliases",
            ["reference_value_id"],
        )
        op.create_index(
            "ix_facet_ref_aliases_lower",
            "facet_reference_aliases",
            ["alias_value_lower"],
        )
        op.create_index(
            "ix_facet_ref_aliases_unique",
            "facet_reference_aliases",
            ["reference_value_id", "alias_value_lower"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_table("facet_reference_aliases")
    op.drop_table("facet_reference_values")
