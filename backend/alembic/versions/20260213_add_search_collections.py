"""Add search collections and vector store sync

Creates search_collections table for named search collections (static, dynamic,
source_bound) and collection_vector_syncs table for external vector store sync
targets. Also adds a collection_id foreign key to search_chunks.

Revision ID: add_search_collections
Revises: add_roles_table
Create Date: 2026-02-13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision = "add_search_collections"
down_revision = "add_roles_table"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def index_exists(index_name: str) -> bool:
    """Check if an index exists."""
    bind = op.get_bind()
    result = bind.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :name"),
        {"name": index_name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. search_collections — named search collection groups
    # ------------------------------------------------------------------
    if not table_exists("search_collections"):
        op.create_table(
            "search_collections",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("collection_type", sa.String(50), nullable=False, server_default="static"),
            sa.Column("query_config", JSONB(), nullable=True),
            sa.Column("source_type", sa.String(50), nullable=True),
            sa.Column("source_id", UUID(as_uuid=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_synced_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )

        # Indexes
        if not index_exists("ix_search_collections_org_slug"):
            op.create_index(
                "ix_search_collections_org_slug",
                "search_collections",
                ["organization_id", "slug"],
                unique=True,
            )
        if not index_exists("ix_search_collections_org_type"):
            op.create_index(
                "ix_search_collections_org_type",
                "search_collections",
                ["organization_id", "collection_type"],
            )
        if not index_exists("ix_search_collections_org_id"):
            op.create_index(
                "ix_search_collections_org_id",
                "search_collections",
                ["organization_id"],
            )
        if not index_exists("ix_search_collections_is_active"):
            op.create_index(
                "ix_search_collections_is_active",
                "search_collections",
                ["is_active"],
            )
        if not index_exists("ix_search_collections_source"):
            op.create_index(
                "ix_search_collections_source",
                "search_collections",
                ["source_type", "source_id"],
                postgresql_where=sa.text("source_type IS NOT NULL"),
            )

    # ------------------------------------------------------------------
    # 2. collection_vector_syncs — external vector store sync targets
    # ------------------------------------------------------------------
    if not table_exists("collection_vector_syncs"):
        op.create_table(
            "collection_vector_syncs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("collection_id", UUID(as_uuid=True), sa.ForeignKey("search_collections.id", ondelete="CASCADE"), nullable=False),
            sa.Column("connection_id", UUID(as_uuid=True), sa.ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("sync_status", sa.String(50), nullable=False, server_default="pending"),
            sa.Column("last_sync_at", sa.DateTime(), nullable=True),
            sa.Column("last_sync_run_id", UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("chunks_synced", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sync_config", JSONB(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        )

        # Indexes
        if not index_exists("ix_collection_vector_syncs_coll_conn"):
            op.create_index(
                "ix_collection_vector_syncs_coll_conn",
                "collection_vector_syncs",
                ["collection_id", "connection_id"],
                unique=True,
            )
        if not index_exists("ix_collection_vector_syncs_collection_id"):
            op.create_index(
                "ix_collection_vector_syncs_collection_id",
                "collection_vector_syncs",
                ["collection_id"],
            )
        if not index_exists("ix_collection_vector_syncs_connection_id"):
            op.create_index(
                "ix_collection_vector_syncs_connection_id",
                "collection_vector_syncs",
                ["connection_id"],
            )

    # ------------------------------------------------------------------
    # 3. Add search_collection_id FK to search_chunks (if table exists)
    # ------------------------------------------------------------------
    if table_exists("search_chunks"):
        # The search_chunks table already has a collection_id column (used for scrape collections).
        # Add a new search_collection_id column that references the new search_collections table.
        if not column_exists("search_chunks", "search_collection_id"):
            op.add_column(
                "search_chunks",
                sa.Column("search_collection_id", UUID(as_uuid=True), nullable=True),
            )
            if not index_exists("ix_search_chunks_search_collection"):
                op.create_index(
                    "ix_search_chunks_search_collection",
                    "search_chunks",
                    ["search_collection_id"],
                    postgresql_where=sa.text("search_collection_id IS NOT NULL"),
                )


def downgrade() -> None:
    # Remove search_collection_id from search_chunks
    if table_exists("search_chunks") and column_exists("search_chunks", "search_collection_id"):
        if index_exists("ix_search_chunks_search_collection"):
            op.drop_index("ix_search_chunks_search_collection", table_name="search_chunks")
        op.drop_column("search_chunks", "search_collection_id")

    # Drop collection_vector_syncs
    if table_exists("collection_vector_syncs"):
        op.drop_table("collection_vector_syncs")

    # Drop search_collections
    if table_exists("search_collections"):
        op.drop_table("search_collections")
