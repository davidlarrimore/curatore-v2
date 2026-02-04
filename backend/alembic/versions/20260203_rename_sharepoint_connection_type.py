"""Rename sharepoint connection type to microsoft_graph.

Revision ID: 20260203_2100
Revises: 20260203_add_automation_config
Create Date: 2026-02-03 21:00:00.000000

This migration renames the connection_type from 'sharepoint' to 'microsoft_graph'
to better reflect that it's a Microsoft Graph API connection that can be used
for SharePoint, OneDrive, and other Microsoft 365 services.
"""

from alembic import op

# revision identifiers, used by Alembic
revision = '20260203_2100'
down_revision = '20260203_add_automation_config'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rename sharepoint connection_type to microsoft_graph."""
    op.execute("""
        UPDATE connections
        SET connection_type = 'microsoft_graph'
        WHERE connection_type = 'sharepoint'
    """)


def downgrade() -> None:
    """Rename microsoft_graph connection_type back to sharepoint."""
    op.execute("""
        UPDATE connections
        SET connection_type = 'sharepoint'
        WHERE connection_type = 'microsoft_graph'
    """)
