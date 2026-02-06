# Maintenance Tasks

Curatore uses a scheduled task system for background maintenance operations. Tasks are defined in the database (`ScheduledTask` model) and executed by Celery workers.

## Overview

- Tasks stored in `scheduled_tasks` table
- Executed by the maintenance Celery queue
- Handlers defined in `backend/app/services/maintenance_handlers.py`
- Cron-style scheduling

---

## Naming Convention

Task types follow the pattern `{domain}.{action}`:
- **domain**: The resource area being acted upon
- **action**: A verb or verb_modifier describing the operation

---

## Handler Reference

| Task Type | Handler | Description |
|-----------|---------|-------------|
| **Assets Domain** |||
| `assets.detect_orphans` | `handle_orphan_detection` | Find/fix orphaned assets: stuck pending, missing files, orphaned SharePoint docs |
| **Runs Domain** |||
| `runs.cleanup_stale` | `handle_stale_run_cleanup` | Reset runs stuck in pending/submitted/running; retry before failing |
| `runs.cleanup_expired` | `handle_cleanup_expired_runs` | Delete old completed/failed runs after retention period |
| **Retention Domain** |||
| `retention.enforce` | `handle_retention_enforcement` | Mark old temp artifacts as deleted per retention policy |
| **Health Domain** |||
| `health.report` | `handle_health_report` | Generate system health summary with metrics and warnings |
| **Search Domain** |||
| `search.reindex` | `handle_search_reindex` | Rebuild PostgreSQL full-text + semantic search index |
| **SharePoint Domain** |||
| `sharepoint.trigger_sync` | `handle_sharepoint_scheduled_sync` | Trigger syncs for configs with specified frequency |
| **SAM.gov Domain** |||
| `sam.trigger_pull` | `handle_sam_scheduled_pull` | Trigger pulls for searches with specified frequency |
| **Forecast Domain** |||
| `forecast.trigger_pull` | `handle_forecast_scheduled_pull` | Trigger pulls for forecast syncs with specified frequency |
| **Extraction Domain** |||
| `extraction.queue_orphans` | `handle_queue_pending_assets` | Safety net: queue extractions for orphaned pending assets |
| **Procedure Domain** |||
| `procedure.execute` | `handle_procedure_execute` | Execute a procedure from scheduled task |

---

## Legacy Aliases

For backwards compatibility, these old names map to canonical handlers:

| Legacy Name | Maps To |
|-------------|---------|
| `orphan.detect` | `assets.detect_orphans` |
| `stale_run.cleanup` | `runs.cleanup_stale` |
| `gc.cleanup` | `runs.cleanup_expired` |
| `sharepoint.scheduled_sync` | `sharepoint.trigger_sync` |
| `sam.scheduled_pull` | `sam.trigger_pull` |
| `extraction.queue_pending` | `extraction.queue_orphans` |

---

## Handler Details

### `assets.detect_orphans`

Finds and fixes orphaned assets:
- Assets stuck in "pending" status (auto-retries extraction, up to 3 times)
- Assets marked "ready" but missing extraction results
- Assets with missing raw files in object storage
- Orphaned SharePoint assets (sync config deleted/archived)

**Config:**
```json
{"auto_fix": true}
```

---

### `runs.cleanup_stale`

Resets or fails runs stuck in non-terminal states:
- `submitted` runs older than `stale_submitted_minutes` (default: 30)
- `running` runs older than `stale_running_hours` (default: 2)
- `pending` runs older than `stale_pending_hours` (default: 1)
- Retries up to `max_retries` (default: 3) before marking as failed

**Config:**
```json
{
  "stale_submitted_minutes": 30,
  "stale_running_hours": 2,
  "stale_pending_hours": 1,
  "max_retries": 3,
  "dry_run": false
}
```

---

### `runs.cleanup_expired`

Deletes old completed/failed runs and their log events:
- Only deletes runs in terminal states (completed, failed, cancelled, timed_out)
- Respects `retention_days` config (default: 30)
- Processes up to `batch_size` runs per execution (default: 1000)

**Config:**
```json
{
  "retention_days": 30,
  "batch_size": 1000,
  "dry_run": false
}
```

---

### `sharepoint.trigger_sync` / `sam.trigger_pull` / `forecast.trigger_pull`

Trigger scheduled syncs/pulls for configs with matching frequency:
- Skips configs that already have a running sync/pull
- Creates new Run record and dispatches Celery task

**Config:**
```json
{"frequency": "hourly"}  // or "daily"
```

---

### `health.report`

Generates system health summary:
- Database connection status
- Redis connection status
- Object storage status
- Queue depths
- Recent error counts

**Config:**
```json
{
  "include_metrics": true,
  "alert_threshold": 100
}
```

---

### `search.reindex`

Rebuilds the search index:
- Reprocesses all indexed content
- Updates embeddings if model changed
- Can be filtered by source type

**Config:**
```json
{
  "source_types": ["asset", "solicitation"],  // optional filter
  "batch_size": 100
}
```

---

## Adding a New Maintenance Handler

1. **Add handler function** in `backend/app/services/maintenance_handlers.py`:
```python
async def handle_my_task(
    session: AsyncSession,
    run: Run,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Docstring describing the handler."""
    await _log_event(session, run.id, "INFO", "start", "Starting my task")

    # ... implementation ...

    await _log_event(session, run.id, "INFO", "complete", "Task completed")
    return {"status": "completed", "items_processed": count}
```

2. **Register in `MAINTENANCE_HANDLERS` dict**:
```python
MAINTENANCE_HANDLERS = {
    # ... existing handlers ...
    "mydomain.myaction": handle_my_task,
}
```

3. **Add default scheduled task** in `backend/app/commands/seed.py`:
```python
{
    "name": "my_task",
    "display_name": "My Task",
    "description": "What this task does",
    "task_type": "mydomain.myaction",
    "scope_type": "global",
    "schedule_expression": "0 * * * *",  # Cron expression
    "enabled": True,
    "config": {},
},
```

4. **Re-seed scheduled tasks**:
```bash
docker exec curatore-backend python -m app.commands.seed --seed-scheduled-tasks
```

---

## API Endpoints

```
GET    /api/v1/scheduled-tasks              # List all tasks
GET    /api/v1/scheduled-tasks/{id}         # Get task details
PATCH  /api/v1/scheduled-tasks/{id}         # Update task config
POST   /api/v1/scheduled-tasks/{id}/enable  # Enable task
POST   /api/v1/scheduled-tasks/{id}/disable # Disable task
POST   /api/v1/scheduled-tasks/{id}/run     # Trigger immediate execution
```

---

## Frontend Admin

Manage scheduled tasks at `/admin/scheduled-tasks`:
- View all tasks with status
- Enable/disable tasks
- Edit configuration
- Trigger manual execution
- View execution history

---

## Cron Expression Reference

```
┌───────────── minute (0 - 59)
│ ┌───────────── hour (0 - 23)
│ │ ┌───────────── day of month (1 - 31)
│ │ │ ┌───────────── month (1 - 12)
│ │ │ │ ┌───────────── day of week (0 - 6) (Sunday = 0)
│ │ │ │ │
* * * * *
```

Common patterns:
- `0 * * * *` - Every hour at minute 0
- `0 6 * * *` - Daily at 6 AM
- `0 0 * * 0` - Weekly on Sunday at midnight
- `*/15 * * * *` - Every 15 minutes
- `0 8 * * 1-5` - Weekdays at 8 AM
