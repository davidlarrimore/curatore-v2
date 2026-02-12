"""Add missing organization_id columns for multi-tenant isolation

Adds organization_id to 7 models that were missing proper org-scoping:
- sam_attachments: NOT NULL after backfill from solicitation/notice
- sam_solicitation_summaries: NOT NULL after backfill from solicitation
- sharepoint_synced_documents: NOT NULL after backfill from sync_config
- scrape_sources: NOT NULL after backfill from collection
- scraped_assets: NOT NULL after backfill from source (after scrape_sources)
- facet_mappings: NULLABLE for org-level overrides (global stays NULL)
- procedure_versions: NOT NULL after backfill from procedure

Revision ID: add_missing_org_ids
Revises: sharepoint_site_name
Create Date: 2026-02-09
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "add_missing_org_ids"
down_revision = "sharepoint_site_name"
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

    # =========================================================================
    # 1. sam_attachments: backfill from solicitation or notice
    # =========================================================================
    if not _column_exists(conn, "sam_attachments", "organization_id"):
        # Add nullable column first
        op.add_column(
            "sam_attachments",
            sa.Column(
                "organization_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )

        # Backfill from solicitation_id or notice_id
        conn.execute(
            sa.text("""
                UPDATE sam_attachments sa
                SET organization_id = COALESCE(
                    (SELECT organization_id FROM sam_solicitations WHERE id = sa.solicitation_id),
                    (SELECT organization_id FROM sam_notices WHERE id = sa.notice_id)
                )
                WHERE sa.organization_id IS NULL
            """)
        )

        # Add NOT NULL constraint
        op.alter_column(
            "sam_attachments",
            "organization_id",
            nullable=False,
        )

        # Add foreign key constraint
        op.create_foreign_key(
            "fk_sam_attachments_organization",
            "sam_attachments",
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # Add index for org-scoped queries
    if not _index_exists(conn, "ix_sam_attachments_org"):
        op.create_index(
            "ix_sam_attachments_org",
            "sam_attachments",
            ["organization_id"],
        )

    if not _index_exists(conn, "ix_sam_attachments_org_status"):
        op.create_index(
            "ix_sam_attachments_org_status",
            "sam_attachments",
            ["organization_id", "download_status"],
        )

    # =========================================================================
    # 2. sam_solicitation_summaries: backfill from solicitation
    # =========================================================================
    if not _column_exists(conn, "sam_solicitation_summaries", "organization_id"):
        op.add_column(
            "sam_solicitation_summaries",
            sa.Column(
                "organization_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )

        # Backfill from solicitation_id
        conn.execute(
            sa.text("""
                UPDATE sam_solicitation_summaries ss
                SET organization_id = (
                    SELECT organization_id FROM sam_solicitations WHERE id = ss.solicitation_id
                )
                WHERE ss.organization_id IS NULL
            """)
        )

        # Add NOT NULL constraint
        op.alter_column(
            "sam_solicitation_summaries",
            "organization_id",
            nullable=False,
        )

        # Add foreign key constraint
        op.create_foreign_key(
            "fk_sam_summaries_organization",
            "sam_solicitation_summaries",
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="CASCADE",
        )

    if not _index_exists(conn, "ix_sam_summaries_org"):
        op.create_index(
            "ix_sam_summaries_org",
            "sam_solicitation_summaries",
            ["organization_id"],
        )

    if not _index_exists(conn, "ix_sam_summaries_org_canonical"):
        op.create_index(
            "ix_sam_summaries_org_canonical",
            "sam_solicitation_summaries",
            ["organization_id", "is_canonical"],
        )

    # =========================================================================
    # 3. sharepoint_synced_documents: backfill from sync_config
    # =========================================================================
    if not _column_exists(conn, "sharepoint_synced_documents", "organization_id"):
        op.add_column(
            "sharepoint_synced_documents",
            sa.Column(
                "organization_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )

        # Backfill from sync_config_id
        conn.execute(
            sa.text("""
                UPDATE sharepoint_synced_documents sd
                SET organization_id = (
                    SELECT organization_id FROM sharepoint_sync_configs WHERE id = sd.sync_config_id
                )
                WHERE sd.organization_id IS NULL
            """)
        )

        # Add NOT NULL constraint
        op.alter_column(
            "sharepoint_synced_documents",
            "organization_id",
            nullable=False,
        )

        # Add foreign key constraint
        op.create_foreign_key(
            "fk_sp_synced_docs_organization",
            "sharepoint_synced_documents",
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="CASCADE",
        )

    if not _index_exists(conn, "ix_sp_synced_docs_org"):
        op.create_index(
            "ix_sp_synced_docs_org",
            "sharepoint_synced_documents",
            ["organization_id"],
        )

    # =========================================================================
    # 4. scrape_sources: backfill from collection (MUST run before scraped_assets)
    # =========================================================================
    if not _column_exists(conn, "scrape_sources", "organization_id"):
        op.add_column(
            "scrape_sources",
            sa.Column(
                "organization_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )

        # Backfill from collection_id
        conn.execute(
            sa.text("""
                UPDATE scrape_sources ss
                SET organization_id = (
                    SELECT organization_id FROM scrape_collections WHERE id = ss.collection_id
                )
                WHERE ss.organization_id IS NULL
            """)
        )

        # Add NOT NULL constraint
        op.alter_column(
            "scrape_sources",
            "organization_id",
            nullable=False,
        )

        # Add foreign key constraint
        op.create_foreign_key(
            "fk_scrape_sources_organization",
            "scrape_sources",
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="CASCADE",
        )

    if not _index_exists(conn, "ix_scrape_sources_org"):
        op.create_index(
            "ix_scrape_sources_org",
            "scrape_sources",
            ["organization_id"],
        )

    # =========================================================================
    # 5. scraped_assets: backfill from source (after scrape_sources has org_id)
    # =========================================================================
    if not _column_exists(conn, "scraped_assets", "organization_id"):
        op.add_column(
            "scraped_assets",
            sa.Column(
                "organization_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )

        # Backfill from source_id (now that scrape_sources has organization_id)
        # Fall back to collection if source is null
        conn.execute(
            sa.text("""
                UPDATE scraped_assets sa
                SET organization_id = COALESCE(
                    (SELECT organization_id FROM scrape_sources WHERE id = sa.source_id),
                    (SELECT organization_id FROM scrape_collections WHERE id = sa.collection_id)
                )
                WHERE sa.organization_id IS NULL
            """)
        )

        # Add NOT NULL constraint
        op.alter_column(
            "scraped_assets",
            "organization_id",
            nullable=False,
        )

        # Add foreign key constraint
        op.create_foreign_key(
            "fk_scraped_assets_organization",
            "scraped_assets",
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="CASCADE",
        )

    if not _index_exists(conn, "ix_scraped_assets_org"):
        op.create_index(
            "ix_scraped_assets_org",
            "scraped_assets",
            ["organization_id"],
        )

    # =========================================================================
    # 6. facet_mappings: NULLABLE for org-level overrides (global stays NULL)
    # =========================================================================
    if not _column_exists(conn, "facet_mappings", "organization_id"):
        op.add_column(
            "facet_mappings",
            sa.Column(
                "organization_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                nullable=True,  # Stays nullable - NULL = global mapping
            ),
        )

        # Add foreign key constraint
        op.create_foreign_key(
            "fk_facet_mappings_organization",
            "facet_mappings",
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="CASCADE",
        )

    if not _index_exists(conn, "ix_facet_mappings_org"):
        op.create_index(
            "ix_facet_mappings_org",
            "facet_mappings",
            ["organization_id"],
        )

    # =========================================================================
    # 7. procedure_versions: backfill from procedure
    # =========================================================================
    if not _column_exists(conn, "procedure_versions", "organization_id"):
        op.add_column(
            "procedure_versions",
            sa.Column(
                "organization_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )

        # Backfill from procedure_id
        conn.execute(
            sa.text("""
                UPDATE procedure_versions pv
                SET organization_id = (
                    SELECT organization_id FROM procedures WHERE id = pv.procedure_id
                )
                WHERE pv.organization_id IS NULL
            """)
        )

        # Add NOT NULL constraint
        op.alter_column(
            "procedure_versions",
            "organization_id",
            nullable=False,
        )

        # Add foreign key constraint
        op.create_foreign_key(
            "fk_procedure_versions_organization",
            "procedure_versions",
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="CASCADE",
        )

    if not _index_exists(conn, "ix_procedure_versions_org"):
        op.create_index(
            "ix_procedure_versions_org",
            "procedure_versions",
            ["organization_id"],
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Drop in reverse order

    # 7. procedure_versions
    if _column_exists(conn, "procedure_versions", "organization_id"):
        if _index_exists(conn, "ix_procedure_versions_org"):
            op.drop_index("ix_procedure_versions_org", table_name="procedure_versions")
        op.drop_constraint("fk_procedure_versions_organization", "procedure_versions", type_="foreignkey")
        op.drop_column("procedure_versions", "organization_id")

    # 6. facet_mappings
    if _column_exists(conn, "facet_mappings", "organization_id"):
        if _index_exists(conn, "ix_facet_mappings_org"):
            op.drop_index("ix_facet_mappings_org", table_name="facet_mappings")
        op.drop_constraint("fk_facet_mappings_organization", "facet_mappings", type_="foreignkey")
        op.drop_column("facet_mappings", "organization_id")

    # 5. scraped_assets
    if _column_exists(conn, "scraped_assets", "organization_id"):
        if _index_exists(conn, "ix_scraped_assets_org"):
            op.drop_index("ix_scraped_assets_org", table_name="scraped_assets")
        op.drop_constraint("fk_scraped_assets_organization", "scraped_assets", type_="foreignkey")
        op.drop_column("scraped_assets", "organization_id")

    # 4. scrape_sources
    if _column_exists(conn, "scrape_sources", "organization_id"):
        if _index_exists(conn, "ix_scrape_sources_org"):
            op.drop_index("ix_scrape_sources_org", table_name="scrape_sources")
        op.drop_constraint("fk_scrape_sources_organization", "scrape_sources", type_="foreignkey")
        op.drop_column("scrape_sources", "organization_id")

    # 3. sharepoint_synced_documents
    if _column_exists(conn, "sharepoint_synced_documents", "organization_id"):
        if _index_exists(conn, "ix_sp_synced_docs_org"):
            op.drop_index("ix_sp_synced_docs_org", table_name="sharepoint_synced_documents")
        op.drop_constraint("fk_sp_synced_docs_organization", "sharepoint_synced_documents", type_="foreignkey")
        op.drop_column("sharepoint_synced_documents", "organization_id")

    # 2. sam_solicitation_summaries
    if _column_exists(conn, "sam_solicitation_summaries", "organization_id"):
        if _index_exists(conn, "ix_sam_summaries_org_canonical"):
            op.drop_index("ix_sam_summaries_org_canonical", table_name="sam_solicitation_summaries")
        if _index_exists(conn, "ix_sam_summaries_org"):
            op.drop_index("ix_sam_summaries_org", table_name="sam_solicitation_summaries")
        op.drop_constraint("fk_sam_summaries_organization", "sam_solicitation_summaries", type_="foreignkey")
        op.drop_column("sam_solicitation_summaries", "organization_id")

    # 1. sam_attachments
    if _column_exists(conn, "sam_attachments", "organization_id"):
        if _index_exists(conn, "ix_sam_attachments_org_status"):
            op.drop_index("ix_sam_attachments_org_status", table_name="sam_attachments")
        if _index_exists(conn, "ix_sam_attachments_org"):
            op.drop_index("ix_sam_attachments_org", table_name="sam_attachments")
        op.drop_constraint("fk_sam_attachments_organization", "sam_attachments", type_="foreignkey")
        op.drop_column("sam_attachments", "organization_id")
