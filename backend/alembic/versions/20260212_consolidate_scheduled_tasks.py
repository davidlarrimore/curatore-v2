"""Consolidate scheduled tasks: remove hourly/daily pairs

The three dispatcher handlers (SharePoint, SAM, Forecasts) are now unified
— a single scheduled task per domain checks each record's frequency and
last_sync_at to decide whether a sync is due.  The old hourly/daily pairs
are no longer needed.

Deleted tasks (6):
  - sharepoint_sync_hourly
  - sharepoint_sync_daily
  - sam_pull_hourly
  - sam_pull_daily
  - forecast_sync_hourly
  - forecast_sync_daily

Also updates any rows still carrying legacy task_type aliases to canonical
names, and migrates the legacy task_type values to the new canonical names.

Revision ID: consolidate_scheduled_tasks
Revises: decouple_forecast_sync
Create Date: 2026-02-12
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "consolidate_scheduled_tasks"
down_revision = "decouple_forecast_sync"
branch_labels = None
depends_on = None

# Old hourly/daily task names and other stale duplicates to delete
OLD_TASK_NAMES = [
    "sharepoint_sync_hourly",
    "sharepoint_sync_daily",
    "sam_pull_hourly",
    "sam_pull_daily",
    "forecast_sync_hourly",
    "forecast_sync_daily",
    "cleanup_expired_jobs",  # stale duplicate of expired_run_cleanup
]

# Legacy task_type aliases → canonical names
LEGACY_TYPE_MAP = {
    "orphan.detect": "assets.detect_orphans",
    "stale_run.cleanup": "runs.cleanup_stale",
    "gc.cleanup": "runs.cleanup_expired",
    "sharepoint.scheduled_sync": "sharepoint.trigger_sync",
    "sam.scheduled_pull": "sam.trigger_pull",
    "extraction.queue_pending": "extraction.queue_orphans",
}


def upgrade() -> None:
    # 1. Delete old hourly/daily tasks
    scheduled_tasks = sa.table(
        "scheduled_tasks",
        sa.column("name", sa.String),
        sa.column("task_type", sa.String),
    )

    for name in OLD_TASK_NAMES:
        op.execute(
            scheduled_tasks.delete().where(scheduled_tasks.c.name == name)
        )

    # 2. Fix any rows still using legacy task_type aliases
    for old_type, new_type in LEGACY_TYPE_MAP.items():
        op.execute(
            scheduled_tasks.update()
            .where(scheduled_tasks.c.task_type == old_type)
            .values(task_type=new_type)
        )


def downgrade() -> None:
    # Re-creating the old tasks with exact original values is not practical
    # (config, schedule, enabled state are all potentially customised).
    # Downgrade is a no-op; re-run the seed command to recreate if needed.
    pass
