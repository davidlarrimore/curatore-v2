"""Change JSON columns to JSONB for PostgreSQL query support.

Revision ID: 20260131_2200
Revises: 20260131_1200
Create Date: 2026-01-31 22:00:00.000000

The .astext accessor for JSON path queries requires JSONB columns in PostgreSQL.
This migration converts Run.config and Asset.source_metadata from JSON to JSONB.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "change_json_to_jsonb"
down_revision = "20260131_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Convert Run.config from JSON to JSONB
    # PostgreSQL allows direct ALTER TYPE for JSON -> JSONB
    op.execute("""
        ALTER TABLE runs
        ALTER COLUMN config
        TYPE JSONB
        USING config::JSONB
    """)

    # Convert Asset.source_metadata from JSON to JSONB
    op.execute("""
        ALTER TABLE assets
        ALTER COLUMN source_metadata
        TYPE JSONB
        USING source_metadata::JSONB
    """)


def downgrade() -> None:
    # Convert back to JSON (note: may lose some JSONB-specific features)
    op.execute("""
        ALTER TABLE runs
        ALTER COLUMN config
        TYPE JSON
        USING config::JSON
    """)

    op.execute("""
        ALTER TABLE assets
        ALTER COLUMN source_metadata
        TYPE JSON
        USING source_metadata::JSON
    """)
