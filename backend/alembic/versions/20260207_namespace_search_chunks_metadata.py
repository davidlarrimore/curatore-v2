"""Namespace search_chunks metadata into nested JSONB structure

Converts flat metadata keys in search_chunks to namespaced format:
- Assets: source.storage_folder, sharepoint.*, source.uploaded_by
- SAM: sam.notice_id, sam.agency, sam.posted_date, etc.
- Salesforce: salesforce.salesforce_id, salesforce.account_type, etc.
- Forecasts: forecast.source_type, forecast.agency_name, etc.

Also adds a GIN index for efficient namespaced containment queries.

Revision ID: namespace_search_metadata
Revises: add_indexed_at_columns
Create Date: 2026-02-07

"""

from alembic import op

# revision identifiers
revision = "namespace_search_metadata"
down_revision = "add_indexed_at_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Convert flat metadata to namespaced format. Idempotent via NOT metadata ? guards."""

    # --- SAM notices ---
    # Old keys: sam_notice_id, solicitation_id, notice_type, agency, posted_date, response_deadline
    # New: {"sam": {"notice_id": ..., "solicitation_id": ..., ...}}
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object('sam', jsonb_build_object(
            'notice_id', metadata->>'sam_notice_id',
            'solicitation_id', metadata->>'solicitation_id',
            'notice_type', metadata->>'notice_type',
            'agency', metadata->>'agency',
            'posted_date', metadata->>'posted_date',
            'response_deadline', metadata->>'response_deadline'
        ))
        WHERE source_type = 'sam_notice'
          AND metadata IS NOT NULL
          AND NOT metadata ? 'sam'
    """)

    # --- SAM solicitations ---
    # Old keys: solicitation_number, agency, office, naics_code, set_aside, posted_date, response_deadline
    # New: {"sam": {"solicitation_number": ..., ...}}
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object('sam', jsonb_build_object(
            'solicitation_number', metadata->>'solicitation_number',
            'agency', metadata->>'agency',
            'office', metadata->>'office',
            'naics_code', metadata->>'naics_code',
            'set_aside', metadata->>'set_aside',
            'posted_date', metadata->>'posted_date',
            'response_deadline', metadata->>'response_deadline'
        ))
        WHERE source_type = 'sam_solicitation'
          AND metadata IS NOT NULL
          AND NOT metadata ? 'sam'
    """)

    # --- Salesforce accounts ---
    # Old keys: salesforce_id, account_type, industry, website
    # New: {"salesforce": {...}}
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object('salesforce', metadata)
        WHERE source_type = 'salesforce_account'
          AND metadata IS NOT NULL
          AND NOT metadata ? 'salesforce'
    """)

    # --- Salesforce contacts ---
    # Old keys: salesforce_id, first_name, last_name, email, title, account_name
    # New: {"salesforce": {...}}
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object('salesforce', metadata)
        WHERE source_type = 'salesforce_contact'
          AND metadata IS NOT NULL
          AND NOT metadata ? 'salesforce'
    """)

    # --- Salesforce opportunities ---
    # Old keys: salesforce_id, stage_name, amount, opportunity_type, account_name, close_date
    # New: {"salesforce": {...}}
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object('salesforce', metadata)
        WHERE source_type = 'salesforce_opportunity'
          AND metadata IS NOT NULL
          AND NOT metadata ? 'salesforce'
    """)

    # --- Forecasts (all 3 types) ---
    # Old keys: source_type, source_id, agency_name, set_aside_type, fiscal_year, estimated_award_quarter
    # New: {"forecast": {...}}
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object('forecast', metadata)
        WHERE source_type IN ('ag_forecast', 'apfs_forecast', 'state_forecast')
          AND metadata IS NOT NULL
          AND NOT metadata ? 'forecast'
    """)

    # --- Assets (SharePoint) ---
    # Old keys: storage_folder, sharepoint_path, sharepoint_folder, sharepoint_web_url, created_by, modified_by
    # New: {"source": {"storage_folder": ...}, "sharepoint": {"path": ..., ...}}
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object(
            'source', jsonb_build_object('storage_folder', metadata->>'storage_folder'),
            'sharepoint', jsonb_build_object(
                'path', metadata->>'sharepoint_path',
                'folder', metadata->>'sharepoint_folder',
                'web_url', metadata->>'sharepoint_web_url',
                'created_by', metadata->>'created_by',
                'modified_by', metadata->>'modified_by'
            )
        )
        WHERE source_type = 'asset'
          AND source_type_filter = 'sharepoint'
          AND metadata IS NOT NULL
          AND NOT metadata ? 'sharepoint'
    """)

    # --- Assets (Upload) ---
    # Old keys: storage_folder, uploaded_by
    # New: {"source": {"storage_folder": ..., "uploaded_by": ...}}
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object(
            'source', jsonb_build_object(
                'storage_folder', metadata->>'storage_folder',
                'uploaded_by', metadata->>'uploaded_by'
            )
        )
        WHERE source_type = 'asset'
          AND source_type_filter = 'upload'
          AND metadata IS NOT NULL
          AND NOT metadata ? 'source'
    """)

    # --- Assets (Web Scrape) ---
    # Old keys: storage_folder
    # New: {"source": {"storage_folder": ...}}
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object(
            'source', jsonb_build_object('storage_folder', metadata->>'storage_folder')
        )
        WHERE source_type = 'asset'
          AND source_type_filter = 'web_scrape'
          AND metadata IS NOT NULL
          AND NOT metadata ? 'source'
    """)

    # --- Assets (other/unknown source types) ---
    # Old keys: storage_folder
    # New: {"source": {"storage_folder": ...}}
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object(
            'source', jsonb_build_object('storage_folder', metadata->>'storage_folder')
        )
        WHERE source_type = 'asset'
          AND source_type_filter NOT IN ('sharepoint', 'upload', 'web_scrape')
          AND metadata IS NOT NULL
          AND NOT metadata ? 'source'
    """)

    # --- GIN index for efficient namespaced containment queries ---
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_search_chunks_metadata_gin
        ON search_chunks USING GIN(metadata jsonb_path_ops)
    """)


def downgrade() -> None:
    """Revert namespaced metadata back to flat format."""

    op.execute("DROP INDEX IF EXISTS ix_search_chunks_metadata_gin")

    # SAM notices: {"sam": {...}} → flat
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object(
            'sam_notice_id', metadata->'sam'->>'notice_id',
            'solicitation_id', metadata->'sam'->>'solicitation_id',
            'notice_type', metadata->'sam'->>'notice_type',
            'agency', metadata->'sam'->>'agency',
            'posted_date', metadata->'sam'->>'posted_date',
            'response_deadline', metadata->'sam'->>'response_deadline'
        )
        WHERE source_type = 'sam_notice'
          AND metadata IS NOT NULL
          AND metadata ? 'sam'
    """)

    # SAM solicitations
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object(
            'solicitation_number', metadata->'sam'->>'solicitation_number',
            'agency', metadata->'sam'->>'agency',
            'office', metadata->'sam'->>'office',
            'naics_code', metadata->'sam'->>'naics_code',
            'set_aside', metadata->'sam'->>'set_aside',
            'posted_date', metadata->'sam'->>'posted_date',
            'response_deadline', metadata->'sam'->>'response_deadline'
        )
        WHERE source_type = 'sam_solicitation'
          AND metadata IS NOT NULL
          AND metadata ? 'sam'
    """)

    # Salesforce: unwrap {"salesforce": {...}} → flat
    op.execute("""
        UPDATE search_chunks SET metadata = metadata->'salesforce'
        WHERE source_type IN ('salesforce_account', 'salesforce_contact', 'salesforce_opportunity')
          AND metadata IS NOT NULL
          AND metadata ? 'salesforce'
    """)

    # Forecasts: unwrap {"forecast": {...}} → flat
    op.execute("""
        UPDATE search_chunks SET metadata = metadata->'forecast'
        WHERE source_type IN ('ag_forecast', 'apfs_forecast', 'state_forecast')
          AND metadata IS NOT NULL
          AND metadata ? 'forecast'
    """)

    # SharePoint assets: merge source + sharepoint back to flat
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object(
            'storage_folder', metadata->'source'->>'storage_folder',
            'sharepoint_path', metadata->'sharepoint'->>'path',
            'sharepoint_folder', metadata->'sharepoint'->>'folder',
            'sharepoint_web_url', metadata->'sharepoint'->>'web_url',
            'created_by', metadata->'sharepoint'->>'created_by',
            'modified_by', metadata->'sharepoint'->>'modified_by'
        )
        WHERE source_type = 'asset'
          AND source_type_filter = 'sharepoint'
          AND metadata IS NOT NULL
          AND metadata ? 'sharepoint'
    """)

    # Upload assets
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object(
            'storage_folder', metadata->'source'->>'storage_folder',
            'uploaded_by', metadata->'source'->>'uploaded_by'
        )
        WHERE source_type = 'asset'
          AND source_type_filter = 'upload'
          AND metadata IS NOT NULL
          AND metadata ? 'source'
    """)

    # Web scrape + other assets
    op.execute("""
        UPDATE search_chunks SET metadata = jsonb_build_object(
            'storage_folder', metadata->'source'->>'storage_folder'
        )
        WHERE source_type = 'asset'
          AND source_type_filter NOT IN ('sharepoint', 'upload')
          AND metadata IS NOT NULL
          AND metadata ? 'source'
    """)
