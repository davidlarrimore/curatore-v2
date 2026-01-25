"""add_artifacts_table

Revision ID: c5a8f3d21e7b
Revises: bb34b325f40b
Create Date: 2026-01-23 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c5a8f3d21e7b'
down_revision = 'bb34b325f40b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create artifacts table for object storage file tracking."""
    op.create_table(
        'artifacts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('organization_id', sa.String(36),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('document_id', sa.String(255), nullable=False),
        sa.Column('job_id', sa.String(36),
                  sa.ForeignKey('jobs.id', ondelete='SET NULL'),
                  nullable=True),

        # Object storage location
        sa.Column('artifact_type', sa.String(50), nullable=False),
        sa.Column('bucket', sa.String(255), nullable=False),
        sa.Column('object_key', sa.String(1024), nullable=False),

        # File metadata
        sa.Column('original_filename', sa.String(500), nullable=False),
        sa.Column('content_type', sa.String(255), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('etag', sa.String(255), nullable=True),
        sa.Column('file_hash', sa.String(64), nullable=True),

        # Status tracking
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('file_metadata', sa.JSON(), nullable=False, server_default='{}'),

        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )

    # Create indexes
    op.create_index('ix_artifacts_organization_id', 'artifacts', ['organization_id'])
    op.create_index('ix_artifacts_document_id', 'artifacts', ['document_id'])
    op.create_index('ix_artifacts_job_id', 'artifacts', ['job_id'])
    op.create_index('ix_artifacts_artifact_type', 'artifacts', ['artifact_type'])
    op.create_index('ix_artifacts_status', 'artifacts', ['status'])
    op.create_index('ix_artifacts_expires_at', 'artifacts', ['expires_at'])

    # Composite indexes
    op.create_index('ix_artifacts_org_doc', 'artifacts', ['organization_id', 'document_id'])
    op.create_index('ix_artifacts_org_type', 'artifacts', ['organization_id', 'artifact_type'])
    op.create_index('ix_artifacts_bucket_key', 'artifacts', ['bucket', 'object_key'], unique=True)
    op.create_index('ix_artifacts_doc_type', 'artifacts', ['document_id', 'artifact_type'])


def downgrade() -> None:
    """Drop artifacts table and indexes."""
    op.drop_index('ix_artifacts_doc_type', table_name='artifacts')
    op.drop_index('ix_artifacts_bucket_key', table_name='artifacts')
    op.drop_index('ix_artifacts_org_type', table_name='artifacts')
    op.drop_index('ix_artifacts_org_doc', table_name='artifacts')
    op.drop_index('ix_artifacts_expires_at', table_name='artifacts')
    op.drop_index('ix_artifacts_status', table_name='artifacts')
    op.drop_index('ix_artifacts_artifact_type', table_name='artifacts')
    op.drop_index('ix_artifacts_job_id', table_name='artifacts')
    op.drop_index('ix_artifacts_document_id', table_name='artifacts')
    op.drop_index('ix_artifacts_organization_id', table_name='artifacts')
    op.drop_table('artifacts')
