"""add_job_processed_folder

Revision ID: 9a7d4c2b3f1e
Revises: c5a8f3d21e7b
Create Date: 2026-01-26 15:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "9a7d4c2b3f1e"
down_revision = "c5a8f3d21e7b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("processed_folder", sa.String(length=255), nullable=True))
    op.create_index("ix_jobs_processed_folder", "jobs", ["processed_folder"])


def downgrade() -> None:
    op.drop_index("ix_jobs_processed_folder", table_name="jobs")
    op.drop_column("jobs", "processed_folder")
