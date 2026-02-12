"""Add trace_id and parent_run_id to runs table for observability

Adds:
- trace_id: Groups related runs (e.g., a procedure run and its child pipeline runs)
- parent_run_id: Direct parent run (e.g., the procedure run that spawned a pipeline run)

Revision ID: run_trace_fields
Revises: procedure_versions
Create Date: 2026-02-08
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "run_trace_fields"
down_revision = "procedure_versions"
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


def _index_exists(connection, index_name):
    """Check if an index exists."""
    result = connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :i)"),
        {"i": index_name},
    )
    return result.scalar()


def upgrade() -> None:
    conn = op.get_bind()

    # Add trace_id column
    if not _column_exists(conn, "runs", "trace_id"):
        op.add_column(
            "runs",
            sa.Column("trace_id", sa.String(36), nullable=True),
        )

    if not _index_exists(conn, "ix_runs_trace_id"):
        op.create_index("ix_runs_trace_id", "runs", ["trace_id"])

    # Add parent_run_id column
    if not _column_exists(conn, "runs", "parent_run_id"):
        op.add_column(
            "runs",
            sa.Column(
                "parent_run_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("runs.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    if not _index_exists(conn, "ix_runs_parent_run_id"):
        op.create_index("ix_runs_parent_run_id", "runs", ["parent_run_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_parent_run_id", table_name="runs")
    op.drop_column("runs", "parent_run_id")
    op.drop_index("ix_runs_trace_id", table_name="runs")
    op.drop_column("runs", "trace_id")
