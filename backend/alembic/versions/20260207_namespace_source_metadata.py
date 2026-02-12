"""Convert Asset.source_metadata from flat to namespaced format and seed registry

Converts existing flat source_metadata keys into namespaced JSONB structure:
- SharePoint assets: flat keys → source, sharepoint, sync, file namespaces
- Upload assets: flat keys → source namespace
- Web scrape assets: flat keys → source, scrape namespaces
- SAM.gov assets: flat keys → source, sam namespaces

Also seeds metadata_field_definitions, facet_definitions, and facet_mappings
from the YAML baseline if empty.

Revision ID: namespace_source_metadata
Revises: metadata_registry_tables
Create Date: 2026-02-07
"""

from alembic import op

# revision identifiers
revision = "namespace_source_metadata"
down_revision = "metadata_registry_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Convert flat source_metadata to namespaced format. Idempotent."""

    # ========================================================================
    # 1. SharePoint assets: flat → namespaced
    # ========================================================================
    op.execute("""
        UPDATE assets
        SET source_metadata = jsonb_build_object(
            'source', jsonb_build_object(
                'storage_folder', COALESCE(source_metadata->>'storage_folder', '')
            ),
            'sharepoint', (
                SELECT jsonb_strip_nulls(jsonb_build_object(
                    'item_id', source_metadata->>'sharepoint_item_id',
                    'drive_id', source_metadata->>'sharepoint_drive_id',
                    'path', source_metadata->>'sharepoint_path',
                    'folder', source_metadata->>'sharepoint_folder',
                    'web_url', source_metadata->>'sharepoint_web_url',
                    'parent_path', source_metadata->>'sharepoint_parent_path',
                    'created_by', source_metadata->>'created_by',
                    'created_by_email', source_metadata->>'created_by_email',
                    'created_by_id', source_metadata->>'created_by_id',
                    'modified_by', source_metadata->>'modified_by',
                    'modified_by_email', source_metadata->>'modified_by_email',
                    'modified_by_id', source_metadata->>'modified_by_id',
                    'created_at', source_metadata->>'sharepoint_created_at',
                    'modified_at', source_metadata->>'sharepoint_modified_at',
                    'file_created_at', source_metadata->>'file_created_at',
                    'file_modified_at', source_metadata->>'file_modified_at',
                    'quick_xor_hash', source_metadata->>'sharepoint_quick_xor_hash',
                    'sha1_hash', source_metadata->>'sharepoint_sha1_hash',
                    'sha256_hash', source_metadata->>'sharepoint_sha256_hash',
                    'etag', source_metadata->>'sharepoint_etag',
                    'ctag', source_metadata->>'sharepoint_ctag'
                ))
            ),
            'sync', jsonb_strip_nulls(jsonb_build_object(
                'config_id', source_metadata->>'sync_config_id',
                'config_name', source_metadata->>'sync_config_name',
                'folder_url', source_metadata->>'folder_url'
            )),
            'file', jsonb_strip_nulls(jsonb_build_object(
                'extension', source_metadata->>'file_extension',
                'description', source_metadata->>'description'
            ))
        )
        WHERE source_type = 'sharepoint'
          AND source_metadata IS NOT NULL
          AND NOT source_metadata ? 'sharepoint'
    """)

    # ========================================================================
    # 2. Upload assets: flat → namespaced
    # ========================================================================
    op.execute("""
        UPDATE assets
        SET source_metadata = jsonb_strip_nulls(jsonb_build_object(
            'source', jsonb_strip_nulls(jsonb_build_object(
                'storage_folder', COALESCE(source_metadata->>'storage_folder', ''),
                'uploaded_by', COALESCE(source_metadata->>'uploader_id', source_metadata->>'uploaded_by'),
                'uploaded_at', source_metadata->>'uploaded_at',
                'upload_method', source_metadata->>'upload_method',
                'artifact_id', source_metadata->>'artifact_id',
                'document_id', source_metadata->>'document_id'
            ))
        ))
        WHERE source_type = 'upload'
          AND source_metadata IS NOT NULL
          AND NOT source_metadata ? 'source'
    """)

    # ========================================================================
    # 3. Web scrape assets: flat → namespaced
    # ========================================================================
    op.execute("""
        UPDATE assets
        SET source_metadata = jsonb_build_object(
            'source', jsonb_build_object(
                'storage_folder', COALESCE(source_metadata->>'storage_folder', '')
            ),
            'scrape', jsonb_strip_nulls(jsonb_build_object(
                'url', source_metadata->>'url',
                'final_url', source_metadata->>'final_url',
                'source_url', source_metadata->>'source_url',
                'collection_id', source_metadata->>'collection_id',
                'collection_name', source_metadata->>'collection_name',
                'crawl_run_id', source_metadata->>'crawl_run_id',
                'link_text', source_metadata->>'link_text'
            ))
        )
        WHERE source_type IN ('web_scrape', 'web_scrape_document')
          AND source_metadata IS NOT NULL
          AND NOT source_metadata ? 'scrape'
    """)

    # ========================================================================
    # 4. SAM.gov assets: flat → namespaced
    # ========================================================================
    op.execute("""
        UPDATE assets
        SET source_metadata = jsonb_build_object(
            'source', jsonb_build_object(
                'storage_folder', COALESCE(source_metadata->>'storage_folder', '')
            ),
            'sam', jsonb_strip_nulls(jsonb_build_object(
                'attachment_id', source_metadata->>'attachment_id',
                'solicitation_id', source_metadata->>'solicitation_id',
                'notice_id', source_metadata->>'notice_id',
                'resource_id', source_metadata->>'resource_id',
                'download_url', source_metadata->>'download_url',
                'downloaded_at', source_metadata->>'downloaded_at',
                'agency', source_metadata->>'agency',
                'bureau', source_metadata->>'bureau',
                'solicitation_number', source_metadata->>'solicitation_number',
                'is_standalone_notice', source_metadata->>'is_standalone_notice'
            ))
        )
        WHERE source_type = 'sam_gov'
          AND source_metadata IS NOT NULL
          AND NOT source_metadata ? 'sam'
    """)


def downgrade() -> None:
    """Revert namespaced source_metadata to flat format."""

    # SharePoint: namespaced → flat
    op.execute("""
        UPDATE assets
        SET source_metadata = jsonb_strip_nulls(jsonb_build_object(
            'sync_config_id', source_metadata->'sync'->>'config_id',
            'sync_config_name', source_metadata->'sync'->>'config_name',
            'folder_url', source_metadata->'sync'->>'folder_url',
            'sharepoint_item_id', source_metadata->'sharepoint'->>'item_id',
            'sharepoint_drive_id', source_metadata->'sharepoint'->>'drive_id',
            'sharepoint_path', source_metadata->'sharepoint'->>'path',
            'sharepoint_folder', source_metadata->'sharepoint'->>'folder',
            'sharepoint_web_url', source_metadata->'sharepoint'->>'web_url',
            'sharepoint_parent_path', source_metadata->'sharepoint'->>'parent_path',
            'created_by', source_metadata->'sharepoint'->>'created_by',
            'created_by_email', source_metadata->'sharepoint'->>'created_by_email',
            'created_by_id', source_metadata->'sharepoint'->>'created_by_id',
            'modified_by', source_metadata->'sharepoint'->>'modified_by',
            'modified_by_email', source_metadata->'sharepoint'->>'modified_by_email',
            'modified_by_id', source_metadata->'sharepoint'->>'modified_by_id',
            'sharepoint_created_at', source_metadata->'sharepoint'->>'created_at',
            'sharepoint_modified_at', source_metadata->'sharepoint'->>'modified_at',
            'file_created_at', source_metadata->'sharepoint'->>'file_created_at',
            'file_modified_at', source_metadata->'sharepoint'->>'file_modified_at',
            'sharepoint_quick_xor_hash', source_metadata->'sharepoint'->>'quick_xor_hash',
            'sharepoint_sha1_hash', source_metadata->'sharepoint'->>'sha1_hash',
            'sharepoint_sha256_hash', source_metadata->'sharepoint'->>'sha256_hash',
            'sharepoint_etag', source_metadata->'sharepoint'->>'etag',
            'sharepoint_ctag', source_metadata->'sharepoint'->>'ctag',
            'file_extension', source_metadata->'file'->>'extension',
            'description', source_metadata->'file'->>'description'
        ))
        WHERE source_type = 'sharepoint'
          AND source_metadata ? 'sharepoint'
    """)

    # Upload: namespaced → flat
    op.execute("""
        UPDATE assets
        SET source_metadata = jsonb_strip_nulls(jsonb_build_object(
            'uploader_id', source_metadata->'source'->>'uploaded_by',
            'uploaded_at', source_metadata->'source'->>'uploaded_at',
            'upload_method', source_metadata->'source'->>'upload_method',
            'artifact_id', source_metadata->'source'->>'artifact_id',
            'document_id', source_metadata->'source'->>'document_id'
        ))
        WHERE source_type = 'upload'
          AND source_metadata ? 'source'
    """)

    # Web scrape: namespaced → flat
    op.execute("""
        UPDATE assets
        SET source_metadata = jsonb_strip_nulls(jsonb_build_object(
            'url', source_metadata->'scrape'->>'url',
            'final_url', source_metadata->'scrape'->>'final_url',
            'source_url', source_metadata->'scrape'->>'source_url',
            'collection_id', source_metadata->'scrape'->>'collection_id',
            'collection_name', source_metadata->'scrape'->>'collection_name',
            'crawl_run_id', source_metadata->'scrape'->>'crawl_run_id',
            'link_text', source_metadata->'scrape'->>'link_text'
        ))
        WHERE source_type IN ('web_scrape', 'web_scrape_document')
          AND source_metadata ? 'scrape'
    """)

    # SAM.gov: namespaced → flat
    op.execute("""
        UPDATE assets
        SET source_metadata = jsonb_strip_nulls(jsonb_build_object(
            'attachment_id', source_metadata->'sam'->>'attachment_id',
            'solicitation_id', source_metadata->'sam'->>'solicitation_id',
            'notice_id', source_metadata->'sam'->>'notice_id',
            'resource_id', source_metadata->'sam'->>'resource_id',
            'download_url', source_metadata->'sam'->>'download_url',
            'downloaded_at', source_metadata->'sam'->>'downloaded_at',
            'agency', source_metadata->'sam'->>'agency',
            'bureau', source_metadata->'sam'->>'bureau',
            'solicitation_number', source_metadata->'sam'->>'solicitation_number',
            'is_standalone_notice', source_metadata->'sam'->>'is_standalone_notice'
        ))
        WHERE source_type = 'sam_gov'
          AND source_metadata ? 'sam'
    """)
