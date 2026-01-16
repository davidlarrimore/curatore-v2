"""add_job_management_tables

Revision ID: bb34b325f40b
Revises: 64c1b2492422
Create Date: 2026-01-15 14:15:37.558465

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bb34b325f40b'
down_revision = '64c1b2492422'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create jobs, job_documents, and job_logs tables."""

    # Create jobs table
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('organization_id', sa.String(36), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('job_type', sa.String(50), nullable=False, server_default='batch_processing'),
        sa.Column('status', sa.String(50), nullable=False, server_default='PENDING'),
        sa.Column('celery_batch_id', sa.String(255), nullable=True),
        sa.Column('total_documents', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completed_documents', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_documents', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('processing_options', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('results_summary', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('queued_at', sa.DateTime(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
    )

    # Create indexes for jobs table
    op.create_index('ix_jobs_organization_id', 'jobs', ['organization_id'])
    op.create_index('ix_jobs_user_id', 'jobs', ['user_id'])
    op.create_index('ix_jobs_status', 'jobs', ['status'])
    op.create_index('ix_jobs_celery_batch_id', 'jobs', ['celery_batch_id'])
    op.create_index('ix_jobs_org_created', 'jobs', ['organization_id', 'created_at'])
    op.create_index('ix_jobs_org_status', 'jobs', ['organization_id', 'status'])
    op.create_index('ix_jobs_user', 'jobs', ['user_id', 'created_at'])
    op.create_index('ix_jobs_expires', 'jobs', ['expires_at'])

    # Create job_documents table
    op.create_table(
        'job_documents',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', sa.String(255), nullable=False),
        sa.Column('filename', sa.String(500), nullable=False),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='PENDING'),
        sa.Column('celery_task_id', sa.String(255), nullable=True),
        sa.Column('conversion_score', sa.Integer(), nullable=True),
        sa.Column('quality_scores', sa.JSON(), nullable=True),
        sa.Column('is_rag_ready', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('processing_time_seconds', sa.Float(), nullable=True),
        sa.Column('processed_file_path', sa.Text(), nullable=True),
    )

    # Create indexes for job_documents table
    op.create_index('ix_job_documents_job_id', 'job_documents', ['job_id'])
    op.create_index('ix_job_documents_document_id', 'job_documents', ['document_id'])
    op.create_index('ix_job_documents_status', 'job_documents', ['status'])
    op.create_index('ix_job_documents_celery_task_id', 'job_documents', ['celery_task_id'])
    op.create_index('ix_job_docs_document', 'job_documents', ['document_id'])
    op.create_index('ix_job_docs_celery_task', 'job_documents', ['celery_task_id'])

    # Create job_logs table
    op.create_table(
        'job_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', sa.String(255), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('level', sa.String(20), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('log_metadata', sa.JSON(), nullable=True),
    )

    # Create indexes for job_logs table
    op.create_index('ix_job_logs_job_id', 'job_logs', ['job_id'])
    op.create_index('ix_job_logs_document_id', 'job_logs', ['document_id'])
    op.create_index('ix_job_logs_level', 'job_logs', ['level'])
    op.create_index('ix_job_logs_job_ts', 'job_logs', ['job_id', 'timestamp'])


def downgrade() -> None:
    """Drop jobs, job_documents, and job_logs tables."""

    # Drop job_logs table (with indexes)
    op.drop_index('ix_job_logs_job_ts', table_name='job_logs')
    op.drop_index('ix_job_logs_level', table_name='job_logs')
    op.drop_index('ix_job_logs_document_id', table_name='job_logs')
    op.drop_index('ix_job_logs_job_id', table_name='job_logs')
    op.drop_table('job_logs')

    # Drop job_documents table (with indexes)
    op.drop_index('ix_job_docs_celery_task', table_name='job_documents')
    op.drop_index('ix_job_docs_document', table_name='job_documents')
    op.drop_index('ix_job_documents_celery_task_id', table_name='job_documents')
    op.drop_index('ix_job_documents_status', table_name='job_documents')
    op.drop_index('ix_job_documents_document_id', table_name='job_documents')
    op.drop_index('ix_job_documents_job_id', table_name='job_documents')
    op.drop_table('job_documents')

    # Drop jobs table (with indexes)
    op.drop_index('ix_jobs_expires', table_name='jobs')
    op.drop_index('ix_jobs_user', table_name='jobs')
    op.drop_index('ix_jobs_org_status', table_name='jobs')
    op.drop_index('ix_jobs_org_created', table_name='jobs')
    op.drop_index('ix_jobs_celery_batch_id', table_name='jobs')
    op.drop_index('ix_jobs_status', table_name='jobs')
    op.drop_index('ix_jobs_user_id', table_name='jobs')
    op.drop_index('ix_jobs_organization_id', table_name='jobs')
    op.drop_table('jobs')
