"""Add solicitation_number column to sam_notices table.

SAM.gov's naming is confusing:
- API "noticeId" = internal UUID (we store as sam_notice_id)
- API "solicitationNumber" = what SAM.gov website calls "Notice ID" (e.g., 70RSAT26RFI000006)

Even Special Notices can have a solicitationNumber. This column allows standalone
notices to be searched by the identifier users see on SAM.gov website.

Revision ID: 20260205_notices_solnum
Revises: 20260203_expand_sam_agency_columns
Create Date: 2026-02-05
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260205_notices_solnum"
down_revision = "add_description_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add solicitation_number column to sam_notices
    op.add_column(
        "sam_notices",
        sa.Column("solicitation_number", sa.String(100), nullable=True),
    )

    # Add index for searching by solicitation_number
    op.create_index(
        "ix_sam_notices_solicitation_number",
        "sam_notices",
        ["solicitation_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_sam_notices_solicitation_number", table_name="sam_notices")
    op.drop_column("sam_notices", "solicitation_number")
