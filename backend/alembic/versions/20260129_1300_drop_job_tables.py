"""Drop legacy job tables

Revision ID: drop_job_tables
Revises: add_standalone_notice_fields
Create Date: 2026-01-29 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'drop_job_tables'
down_revision = 'add_standalone_notice_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop the legacy job tables.

    The Job system has been deprecated in favor of the Run-based execution tracking
    introduced in Phase 0. All document processing now uses the Asset, Run, and
    ExtractionResult models.

    Tables being dropped:
    - job_logs: Log entries for job execution
    - job_documents: Individual documents within jobs
    - jobs: Batch processing jobs

    Also removes:
    - job_id column from artifacts table (no longer needed)

    Note: Data in these tables is permanently deleted. This migration should only
    be run after confirming that no important historical data needs to be preserved.
    """

    # First, remove job_id column from artifacts table (has FK to jobs)
    with op.batch_alter_table('artifacts', schema=None) as batch_op:
        batch_op.drop_index('ix_artifacts_job_id')
        batch_op.drop_column('job_id')

    # Drop tables in dependency order (children first)
    op.drop_table('job_logs')
    op.drop_table('job_documents')
    op.drop_table('jobs')


def downgrade() -> None:
    """Recreate the job tables.

    Note: This only recreates the table structure, not the data.
    """

    # Recreate jobs table first (artifacts FK depends on it)
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('organization_id', sa.String(36), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('job_type', sa.String(50), nullable=False, server_default='batch_processing'),
        sa.Column('status', sa.String(50), nullable=False, server_default='PENDING'),
        sa.Column('celery_batch_id', sa.String(255), nullable=True),
        sa.Column('total_documents', sa.Integer, nullable=False, server_default='0'),
        sa.Column('completed_documents', sa.Integer, nullable=False, server_default='0'),
        sa.Column('failed_documents', sa.Integer, nullable=False, server_default='0'),
        sa.Column('processing_options', sa.JSON, nullable=False, server_default='{}'),
        sa.Column('results_summary', sa.JSON, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('processed_folder', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('queued_at', sa.DateTime, nullable=True),
        sa.Column('started_at', sa.DateTime, nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('cancelled_at', sa.DateTime, nullable=True),
        sa.Column('expires_at', sa.DateTime, nullable=True),
    )
    op.create_index('ix_jobs_organization_id', 'jobs', ['organization_id'])
    op.create_index('ix_jobs_user_id', 'jobs', ['user_id'])
    op.create_index('ix_jobs_status', 'jobs', ['status'])
    op.create_index('ix_jobs_celery_batch_id', 'jobs', ['celery_batch_id'])
    op.create_index('ix_jobs_org_created', 'jobs', ['organization_id', 'created_at'])
    op.create_index('ix_jobs_org_status', 'jobs', ['organization_id', 'status'])
    op.create_index('ix_jobs_user', 'jobs', ['user_id', 'created_at'])
    op.create_index('ix_jobs_expires', 'jobs', ['expires_at'])

    # Recreate job_documents table
    op.create_table(
        'job_documents',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', sa.String(36), nullable=False),
        sa.Column('filename', sa.String(500), nullable=False),
        sa.Column('file_path', sa.Text, nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=True),
        sa.Column('file_size', sa.Integer, nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='PENDING'),
        sa.Column('celery_task_id', sa.String(255), nullable=True),
        sa.Column('conversion_score', sa.Integer, nullable=True),
        sa.Column('quality_scores', sa.JSON, nullable=True),
        sa.Column('is_rag_ready', sa.Boolean, nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('started_at', sa.DateTime, nullable=True),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('processing_time_seconds', sa.Float, nullable=True),
        sa.Column('processed_file_path', sa.Text, nullable=True),
    )
    op.create_index('ix_job_documents_job_id', 'job_documents', ['job_id'])
    op.create_index('ix_job_documents_document_id', 'job_documents', ['document_id'])
    op.create_index('ix_job_documents_status', 'job_documents', ['status'])
    op.create_index('ix_job_documents_celery_task_id', 'job_documents', ['celery_task_id'])
    op.create_index('ix_job_docs_document', 'job_documents', ['document_id'])
    op.create_index('ix_job_docs_celery_task', 'job_documents', ['celery_task_id'])

    # Recreate job_logs table
    op.create_table(
        'job_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', sa.String(36), nullable=True),
        sa.Column('timestamp', sa.DateTime, nullable=False),
        sa.Column('level', sa.String(20), nullable=False),
        sa.Column('message', sa.Text, nullable=False),
        sa.Column('log_metadata', sa.JSON, nullable=True),
    )
    op.create_index('ix_job_logs_job_id', 'job_logs', ['job_id'])
    op.create_index('ix_job_logs_document_id', 'job_logs', ['document_id'])
    op.create_index('ix_job_logs_level', 'job_logs', ['level'])
    op.create_index('ix_job_logs_job_ts', 'job_logs', ['job_id', 'timestamp'])

    # Add job_id column back to artifacts
    with op.batch_alter_table('artifacts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('job_id', sa.String(36), nullable=True))
        batch_op.create_index('ix_artifacts_job_id', ['job_id'])
