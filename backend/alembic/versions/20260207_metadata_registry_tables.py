"""Add metadata registry tables and simplify AssetMetadata

Creates:
- metadata_field_definitions: DB-backed field registry per namespace
- facet_definitions: Cross-domain facet abstractions
- facet_mappings: Facet-to-content-type JSON path mappings

Simplifies AssetMetadata:
- Removes promotion/supersession columns (promoted_from_id, superseded_by_id,
  promoted_at, superseded_at, status)
- Changes is_canonical default to true
- Adds updated_at column

Revision ID: metadata_registry_tables
Revises: namespace_search_metadata
Create Date: 2026-02-07
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "metadata_registry_tables"
down_revision = "namespace_search_metadata"
branch_labels = None
depends_on = None


def _table_exists(connection, table_name):
    """Check if a table exists in the database."""
    result = connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"),
        {"t": table_name},
    )
    return result.scalar()


def _column_exists(connection, table_name, column_name):
    """Check if a column exists in a table."""
    result = connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c)"
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

    # ========================================================================
    # 1. Create metadata_field_definitions table (if not exists)
    # ========================================================================
    if not _table_exists(conn, "metadata_field_definitions"):
        op.create_table(
            "metadata_field_definitions",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("organization_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
            sa.Column("namespace", sa.String(100), nullable=False),
            sa.Column("field_name", sa.String(100), nullable=False),
            sa.Column("data_type", sa.String(50), nullable=False),
            sa.Column("indexed", sa.Boolean, nullable=False, server_default=sa.text("true")),
            sa.Column("facetable", sa.Boolean, nullable=False, server_default=sa.text("false")),
            sa.Column("applicable_content_types", sa.dialects.postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("examples", sa.dialects.postgresql.JSONB, nullable=True),
            sa.Column("sensitivity_tag", sa.String(50), nullable=True),
            sa.Column("version", sa.String(20), nullable=False, server_default=sa.text("'1.0'")),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("organization_id", "namespace", "field_name", name="uq_field_def_org_ns_field"),
        )

    if not _index_exists(conn, "ix_field_defs_org_namespace"):
        op.create_index(
            "ix_field_defs_org_namespace",
            "metadata_field_definitions",
            ["organization_id", "namespace"],
        )
    if not _index_exists(conn, "ix_field_defs_status"):
        op.create_index(
            "ix_field_defs_status",
            "metadata_field_definitions",
            ["status"],
        )

    # ========================================================================
    # 2. Create facet_definitions table (if not exists)
    # ========================================================================
    if not _table_exists(conn, "facet_definitions"):
        op.create_table(
            "facet_definitions",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("organization_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
            sa.Column("facet_name", sa.String(100), nullable=False),
            sa.Column("display_name", sa.String(200), nullable=True),
            sa.Column("data_type", sa.String(50), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("operators", sa.dialects.postgresql.JSONB, nullable=True, server_default=sa.text("'[\"eq\", \"in\"]'::jsonb")),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("organization_id", "facet_name", name="uq_facet_def_org_name"),
        )

    if not _index_exists(conn, "ix_facet_defs_org"):
        op.create_index(
            "ix_facet_defs_org",
            "facet_definitions",
            ["organization_id"],
        )

    # ========================================================================
    # 3. Create facet_mappings table (if not exists)
    # ========================================================================
    if not _table_exists(conn, "facet_mappings"):
        op.create_table(
            "facet_mappings",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("facet_definition_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("facet_definitions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("content_type", sa.String(100), nullable=False),
            sa.Column("json_path", sa.String(500), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("facet_definition_id", "content_type", name="uq_facet_mapping_facet_content"),
        )

    if not _index_exists(conn, "ix_facet_mappings_facet_id"):
        op.create_index(
            "ix_facet_mappings_facet_id",
            "facet_mappings",
            ["facet_definition_id"],
        )

    # ========================================================================
    # 4. Simplify AssetMetadata table (idempotent)
    # ========================================================================

    # Remove promotion/supersession columns if they still exist
    if _index_exists(conn, "ix_asset_metadata_asset_type_status"):
        op.drop_index("ix_asset_metadata_asset_type_status", table_name="asset_metadata")
    for col in ("promoted_from_id", "superseded_by_id", "promoted_at", "superseded_at", "status"):
        if _column_exists(conn, "asset_metadata", col):
            op.drop_column("asset_metadata", col)

    # Change is_canonical default to true
    op.alter_column(
        "asset_metadata",
        "is_canonical",
        server_default=sa.text("true"),
    )

    # Add updated_at column if it doesn't exist
    if not _column_exists(conn, "asset_metadata", "updated_at"):
        op.add_column(
            "asset_metadata",
            sa.Column("updated_at", sa.DateTime, nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        )


def downgrade() -> None:
    # Restore AssetMetadata columns
    op.drop_column("asset_metadata", "updated_at")

    op.alter_column(
        "asset_metadata",
        "is_canonical",
        server_default=sa.text("false"),
    )

    op.add_column(
        "asset_metadata",
        sa.Column("status", sa.String(50), nullable=False, server_default=sa.text("'active'")),
    )
    op.add_column(
        "asset_metadata",
        sa.Column("superseded_at", sa.DateTime, nullable=True),
    )
    op.add_column(
        "asset_metadata",
        sa.Column("promoted_at", sa.DateTime, nullable=True),
    )
    op.add_column(
        "asset_metadata",
        sa.Column("superseded_by_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("asset_metadata.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "asset_metadata",
        sa.Column("promoted_from_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("asset_metadata.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index(
        "ix_asset_metadata_asset_type_status",
        "asset_metadata",
        ["asset_id", "metadata_type", "status"],
    )

    # Drop new tables (reverse order)
    op.drop_table("facet_mappings")
    op.drop_table("facet_definitions")
    op.drop_table("metadata_field_definitions")
