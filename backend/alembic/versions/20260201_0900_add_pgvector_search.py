"""Add pgvector extension and search_chunks table.

Revision ID: 20260201_0900
Revises: change_json_to_jsonb
Create Date: 2026-02-01 09:00:00.000000

This migration:
1. Enables the pgvector extension for semantic search
2. Creates the search_chunks table for hybrid search (full-text + semantic)
3. Creates necessary indexes for fast search queries
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = "20260201_0900"
down_revision = "change_json_to_jsonb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension (requires pgvector/pgvector Docker image)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create search_chunks table
    op.create_table(
        "search_chunks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_type", sa.String(50), nullable=False),  # 'asset', 'sam_notice', 'sam_solicitation'
        sa.Column("source_id", UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(500), nullable=True),
        sa.Column("url", sa.String(2048), nullable=True),
        # Full-text search vector - will be populated by trigger
        sa.Column("search_vector", sa.dialects.postgresql.TSVECTOR(), nullable=True),
        # Filtering metadata
        sa.Column("source_type_filter", sa.String(50), nullable=True),  # upload, sharepoint, web_scrape, sam_gov
        sa.Column("content_type", sa.String(255), nullable=True),
        sa.Column("collection_id", UUID(as_uuid=True), nullable=True),
        sa.Column("sync_config_id", UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True),  # Additional metadata for search/filtering
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        # Unique constraint on source
        sa.UniqueConstraint("source_type", "source_id", "chunk_index", name="uq_search_chunks_source"),
    )

    # Add embedding column with pgvector type (1536 dimensions for OpenAI text-embedding-3-small)
    # Using raw SQL because SQLAlchemy doesn't have native pgvector type support
    op.execute("ALTER TABLE search_chunks ADD COLUMN embedding vector(1536)")

    # Create indexes
    # Index for organization filtering
    op.create_index("ix_search_chunks_org", "search_chunks", ["organization_id"])

    # Index for source lookups
    op.create_index("ix_search_chunks_source", "search_chunks", ["source_type", "source_id"])

    # GIN index for full-text search
    op.execute("CREATE INDEX ix_search_chunks_fts ON search_chunks USING GIN(search_vector)")

    # IVFFlat index for vector similarity search (optimized for ~100k-1M vectors)
    # Note: This index needs to be created after data is populated for best results
    # For now, create with a reasonable default
    op.execute("""
        CREATE INDEX ix_search_chunks_embedding ON search_chunks
        USING ivfflat(embedding vector_cosine_ops) WITH (lists = 100)
    """)

    # Index for common filters
    op.create_index("ix_search_chunks_filters", "search_chunks", ["source_type_filter", "content_type"])

    # Index for collection/sync config filtering
    op.create_index("ix_search_chunks_collection", "search_chunks", ["collection_id"], postgresql_where=sa.text("collection_id IS NOT NULL"))
    op.create_index("ix_search_chunks_sync_config", "search_chunks", ["sync_config_id"], postgresql_where=sa.text("sync_config_id IS NOT NULL"))

    # Create trigger function for automatic search_vector updates
    op.execute("""
        CREATE OR REPLACE FUNCTION search_chunks_update_search_vector()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
                setweight(to_tsvector('english', COALESCE(NEW.filename, '')), 'B') ||
                setweight(to_tsvector('english', COALESCE(NEW.content, '')), 'C');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create trigger to update search_vector on insert/update
    op.execute("""
        CREATE TRIGGER search_chunks_search_vector_trigger
        BEFORE INSERT OR UPDATE ON search_chunks
        FOR EACH ROW
        EXECUTE FUNCTION search_chunks_update_search_vector();
    """)


def downgrade() -> None:
    # Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS search_chunks_search_vector_trigger ON search_chunks")
    op.execute("DROP FUNCTION IF EXISTS search_chunks_update_search_vector()")

    # Drop indexes
    op.execute("DROP INDEX IF EXISTS ix_search_chunks_embedding")
    op.execute("DROP INDEX IF EXISTS ix_search_chunks_fts")
    op.drop_index("ix_search_chunks_sync_config", table_name="search_chunks")
    op.drop_index("ix_search_chunks_collection", table_name="search_chunks")
    op.drop_index("ix_search_chunks_filters", table_name="search_chunks")
    op.drop_index("ix_search_chunks_source", table_name="search_chunks")
    op.drop_index("ix_search_chunks_org", table_name="search_chunks")

    # Drop table
    op.drop_table("search_chunks")

    # Note: We don't drop the pgvector extension as it may be used elsewhere
