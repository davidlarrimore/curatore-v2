"""Add collection_chunks table and drop search_collection_id from search_chunks

Creates an isolated collection_chunks table with its own pgvector embeddings,
tsvector search, and metadata. Removes the broken search_collection_id column
from search_chunks since collections are now fully isolated vector stores.

Revision ID: collection_chunks_table
Revises: add_search_collections
Create Date: 2026-02-13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision = "collection_chunks_table"
down_revision = "add_search_collections"
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


def function_exists(func_name: str) -> bool:
    """Check if a PL/pgSQL function exists."""
    bind = op.get_bind()
    result = bind.execute(
        sa.text("SELECT 1 FROM pg_proc WHERE proname = :name"),
        {"name": func_name},
    )
    return result.fetchone() is not None


def trigger_exists(trigger_name: str, table_name: str) -> bool:
    """Check if a trigger exists on a table."""
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_trigger t "
            "JOIN pg_class c ON t.tgrelid = c.oid "
            "WHERE t.tgname = :tname AND c.relname = :table"
        ),
        {"tname": trigger_name, "table": table_name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create collection_chunks table — isolated vector store
    # ------------------------------------------------------------------
    if not table_exists("collection_chunks"):
        op.create_table(
            "collection_chunks",
            sa.Column(
                "id", UUID(as_uuid=True), primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "collection_id", UUID(as_uuid=True),
                sa.ForeignKey("search_collections.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("content", sa.Text(), nullable=False),
            # search_vector and embedding are added via raw SQL below
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("source_asset_id", UUID(as_uuid=True), nullable=True),
            sa.Column("source_chunk_id", UUID(as_uuid=True), nullable=True),
            sa.Column("metadata", JSONB(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
            ),
        )

        # Add tsvector column (not natively supported in SQLAlchemy column defs)
        op.execute("ALTER TABLE collection_chunks ADD COLUMN search_vector tsvector")

        # Add pgvector embedding column
        op.execute("ALTER TABLE collection_chunks ADD COLUMN embedding vector(1536)")

        # Unique constraint: one chunk per asset per index in a collection
        if not index_exists("uq_collection_chunks_coll_asset_idx"):
            op.create_index(
                "uq_collection_chunks_coll_asset_idx",
                "collection_chunks",
                ["collection_id", "source_asset_id", "chunk_index"],
                unique=True,
            )

        # B-tree on collection_id for fast collection-scoped queries
        if not index_exists("ix_collection_chunks_collection_id"):
            op.create_index(
                "ix_collection_chunks_collection_id",
                "collection_chunks",
                ["collection_id"],
            )

        # GIN index on search_vector for full-text search
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_collection_chunks_search_vector "
            "ON collection_chunks USING GIN (search_vector)"
        )

        # HNSW index on embedding for semantic search
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_collection_chunks_embedding "
            "ON collection_chunks USING hnsw (embedding vector_cosine_ops)"
        )

        # B-tree on (collection_id, source_asset_id) for dedup lookups
        if not index_exists("ix_collection_chunks_coll_asset"):
            op.create_index(
                "ix_collection_chunks_coll_asset",
                "collection_chunks",
                ["collection_id", "source_asset_id"],
            )

    # ------------------------------------------------------------------
    # 2. Create tsvector trigger for collection_chunks
    # ------------------------------------------------------------------
    if not function_exists("collection_chunks_update_search_vector"):
        op.execute("""
            CREATE OR REPLACE FUNCTION collection_chunks_update_search_vector()
            RETURNS trigger AS $$
            BEGIN
                NEW.search_vector :=
                    setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
                    setweight(to_tsvector('english', COALESCE(NEW.content, '')), 'C');
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)

    if not trigger_exists("trg_collection_chunks_search_vector", "collection_chunks"):
        op.execute("""
            CREATE TRIGGER trg_collection_chunks_search_vector
            BEFORE INSERT OR UPDATE OF title, content
            ON collection_chunks
            FOR EACH ROW
            EXECUTE FUNCTION collection_chunks_update_search_vector();
        """)

    # ------------------------------------------------------------------
    # 3. Drop search_collection_id from search_chunks
    # ------------------------------------------------------------------
    if table_exists("search_chunks") and column_exists("search_chunks", "search_collection_id"):
        if index_exists("ix_search_chunks_search_collection"):
            op.drop_index("ix_search_chunks_search_collection", table_name="search_chunks")
        op.drop_column("search_chunks", "search_collection_id")


def downgrade() -> None:
    # Re-add search_collection_id to search_chunks
    if table_exists("search_chunks") and not column_exists("search_chunks", "search_collection_id"):
        op.add_column(
            "search_chunks",
            sa.Column("search_collection_id", UUID(as_uuid=True), nullable=True),
        )
        op.create_index(
            "ix_search_chunks_search_collection",
            "search_chunks",
            ["search_collection_id"],
            postgresql_where=sa.text("search_collection_id IS NOT NULL"),
        )

    # Drop trigger and function
    if trigger_exists("trg_collection_chunks_search_vector", "collection_chunks"):
        op.execute("DROP TRIGGER trg_collection_chunks_search_vector ON collection_chunks")
    if function_exists("collection_chunks_update_search_vector"):
        op.execute("DROP FUNCTION collection_chunks_update_search_vector()")

    # Drop collection_chunks table
    if table_exists("collection_chunks"):
        op.drop_table("collection_chunks")
