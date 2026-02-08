"""Add procedure_versions table for version history

Creates:
- procedure_versions: Stores definition snapshots per version

Revision ID: procedure_versions
Revises: namespace_source_metadata
Create Date: 2026-02-07
"""

import sqlalchemy as sa
from alembic import op


# revision identifiers
revision = "procedure_versions"
down_revision = "namespace_source_metadata"
branch_labels = None
depends_on = None


def _table_exists(connection, table_name):
    """Check if a table exists in the database."""
    result = connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"),
        {"t": table_name},
    )
    return result.scalar()


def _index_exists(connection, index_name):
    """Check if an index exists."""
    result = connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :i)"),
        {"i": index_name},
    )
    return result.scalar()


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "procedure_versions"):
        op.create_table(
            "procedure_versions",
            sa.Column(
                "id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "procedure_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("procedures.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version", sa.Integer, nullable=False),
            sa.Column("definition", sa.dialects.postgresql.JSONB, nullable=False),
            sa.Column("change_summary", sa.Text, nullable=True),
            sa.Column(
                "created_by",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime,
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint("procedure_id", "version", name="uq_procedure_version"),
        )

    if not _index_exists(conn, "ix_procedure_versions_procedure_id"):
        op.create_index(
            "ix_procedure_versions_procedure_id",
            "procedure_versions",
            ["procedure_id"],
        )

    if not _index_exists(conn, "ix_procedure_versions_proc_version"):
        op.create_index(
            "ix_procedure_versions_proc_version",
            "procedure_versions",
            ["procedure_id", "version"],
        )


def downgrade() -> None:
    op.drop_table("procedure_versions")
