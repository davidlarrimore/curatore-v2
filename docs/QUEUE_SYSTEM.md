# Queue System

Curatore uses a centralized queue system for all background job processing. This document covers queue architecture, job groups, priority handling, and cancellation behavior.

## Overview

All background jobs are managed through the Queue Registry system:
- **Queue types defined in code** - See `backend/app/services/queue_registry.py`
- **Celery queues per job type** - Each job type has its own queue for isolation
- **Job Manager UI** - Unified view at `/admin/queue`
- **Configurable throttling** - Set `max_concurrent` per queue in `config.yml`

## Queue Types

| Queue | Run Type | Celery Queue | Capabilities |
|-------|----------|--------------|--------------|
| Extraction | `extraction` | `extraction` | cancel, retry |
| SAM.gov | `sam_pull` | `sam` | - |
| Forecasts | `forecast_pull` | `forecast` | cancel |
| Web Scrape | `scrape` | `scrape` | cancel |
| SharePoint | `sharepoint_sync` | `sharepoint` | cancel |
| Maintenance | `system_maintenance` | `maintenance` | - |
| Procedure | `procedure` | `maintenance` | cancel, retry |
| Pipeline | `pipeline` | `pipeline` | cancel, retry |

## Queue Priority System

Child extractions spawned by parent jobs are automatically assigned priority based on `group_type`:

```python
# QueuePriority levels (in backend/app/services/queue_registry.py)
SHAREPOINT_SYNC = 0  # Background SharePoint sync extractions (lowest)
SAM_SCRAPE = 1       # SAM.gov and web scrape extractions
PIPELINE = 2         # Pipeline/workflow extractions
USER_UPLOAD = 3      # Direct user uploads (default for new runs)
USER_BOOSTED = 4     # Manually boosted by user (highest)
```

Priority is auto-determined when `group_id` is passed to `asset_service.create_asset()`.

---

## Parent-Child Job Pattern (Run Groups)

For parent jobs that spawn child jobs (e.g., SAM pull creates extraction jobs for attachments), use Run Groups to track completion of all children before triggering follow-up procedures.

### Architecture

```
Parent Job (SAM Pull) → Creates Run Group → Downloads Attachments
                                                   ↓
                                         Creates Assets (with group_id)
                                                   ↓
                                         Queues Extractions (children linked to group)
                                                   ↓
                                   Each child extraction notifies group on complete/fail
                                                   ↓
                                   When all children done → Group completes
                                                   ↓
                                   Emits {group_type}.group_completed event
                                                   ↓
                                   Triggers configured after_procedure_slug
```

### Supported Group Types

| Type | Description | Parent Job | Priority |
|------|-------------|------------|----------|
| `sharepoint_sync` | SharePoint sync + file extractions | SharePoint sync task | 0 (lowest) |
| `sam_pull` | SAM.gov pull + attachment extractions | SAM pull task | 1 |
| `scrape` | Web crawl + document extractions | Scrape task | 1 |
| `pipeline` | Pipeline workflow extractions | Pipeline task | 2 |
| `upload_group` | Grouped uploads + extractions | Bulk upload | 3 |

### Backend Implementation

1. **Parent job creates group:**
```python
from .services.run_group_service import run_group_service

group = await run_group_service.create_group(
    session=session,
    organization_id=org_id,
    group_type="sam_pull",
    parent_run_id=run_id,
    config={
        "after_procedure_slug": "sam-weekly-digest",
        "after_procedure_params": {},
    },
)
```

2. **Pass group_id when creating assets:**
```python
asset = await asset_service.create_asset(
    session=session,
    # ... other params ...
    group_id=group.id,  # Links child extraction to group with auto-priority
)
```

3. **Extraction orchestrator auto-notifies group:**
The extraction orchestrator automatically calls `run_group_service.child_completed()` or `child_failed()` when extractions finish.

4. **Finalize group after parent job completes:**
```python
await run_group_service.finalize_group(session, group.id)
```

5. **Handle parent job failure:**
```python
try:
    # ... parent job work ...
except Exception as e:
    await run_group_service.mark_group_failed(session, group_id, str(e))
    raise
```

### Key Files

- `backend/app/services/run_group_service.py` - Group lifecycle management
- `backend/app/services/job_cancellation_service.py` - Cascade cancellation logic
- `backend/app/services/extraction_queue_service.py` - Priority handling, timeout exclusion
- `backend/app/services/queue_registry.py` - QueuePriority enum
- `backend/app/database/models.py` - `RunGroup` model, `Run.group_id`

---

## Timeout Handling

Parent jobs are excluded from timeout checks while they have active children:
- Parent jobs with `is_group_parent=True` are not timed out while `completed_children + failed_children < total_children`
- This prevents parent jobs from timing out while waiting for child extractions in queue

---

## Cancellation Behavior

Different job types have different cancellation cascade behavior:

| Job Type | Cascade Mode | Behavior |
|----------|--------------|----------|
| SharePoint Sync | `QUEUED_ONLY` | Cancel pending/submitted children only; running extractions complete |
| SAM.gov Pull | `QUEUED_ONLY` | Cancel pending/submitted children only; running extractions complete |
| Web Scrape | `QUEUED_ONLY` | Cancel pending/submitted children only; running extractions complete |
| Pipeline | `ALL` | Cancel ALL children including running (atomicity - partial results useless) |

Use `job_cancellation_service` for cascade cancellation:
```python
from .services.job_cancellation_service import job_cancellation_service

result = await job_cancellation_service.cancel_parent_job(
    session=session,
    run_id=run_id,
    reason="User cancelled",
)
# Returns: {"success": True, "children_cancelled": 5, "children_skipped": 2}
```

### Failure Handling

When a parent job fails:
1. The RunGroup is marked as failed (prevents post-job triggers from running)
2. No new children can be spawned (`should_spawn_children()` returns False)
3. For pipelines: all active children are cancelled
4. For other types: running children complete normally

```python
# In parent task error handler:
await run_group_service.mark_group_failed(session, group_id, str(error))
```

---

## Async Deletion Pattern

For resource-intensive deletion operations, use the async deletion pattern:

### Architecture

```
User clicks Delete → Confirmation Dialog → POST /delete
                                                ↓
                                    ┌─────────────────────┐
                                    │ Set status=deleting │
                                    │ Create Run record   │
                                    │ Queue Celery task   │
                                    │ Return run_id       │
                                    └─────────────────────┘
                                                ↓
                                    ┌─────────────────────┐
                                    │ Redirect to list    │
                                    │ Show "Deleting..."  │
                                    └─────────────────────┘
                                                ↓
                                    ┌─────────────────────┐
                                    │ UnifiedJobsProvider │
                                    │ WebSocket updates   │
                                    │ Shows toast on done │
                                    └─────────────────────┘
```

### Backend Implementation

```python
@router.delete("/configs/{config_id}")
async def delete_config(...):
    config.status = "deleting"
    run = await run_service.create_run(run_type="xxx_delete", ...)
    my_delete_task.delay(config_id, run_id)
    return {"run_id": str(run.id), "status": "deleting"}
```

### Frontend Implementation

```tsx
import { useDeletionJobs } from '@/lib/context-shims'

const { addJob, isDeleting } = useDeletionJobs()

const handleDelete = async () => {
  const { run_id } = await api.deleteConfig(id)
  addJob({ runId: run_id, configId: id, configName: name, configType: 'sharepoint' })
  router.push('/list')  // Redirect immediately
}
```

---

## Adding New Queue Types

1. **Define the queue class** in `backend/app/services/queue_registry.py`:
```python
class GoogleDriveQueue(QueueDefinition):
    """Google Drive document synchronization queue."""

    def __init__(self):
        super().__init__(
            queue_type="google_drive",           # Unique identifier
            celery_queue="google_drive",         # Celery queue name
            run_type_aliases=["gdrive_sync"],    # Alternative run_type values
            can_cancel=True,                     # Allow job cancellation
            can_retry=False,                     # No automatic retry
            label="Google Drive",                # UI display name
            description="Google Drive sync",     # UI description
            icon="cloud",                        # Lucide icon name
            color="blue",                        # Tailwind color
            default_max_concurrent=None,         # None = unlimited
            default_timeout_seconds=1800,        # 30 minutes
        )
```

2. **Register the queue** in `_register_defaults()`:
```python
def _register_defaults(self):
    self.register(ExtractionQueue())
    self.register(SamQueue())
    # ... existing queues ...
    self.register(GoogleDriveQueue())  # Add here
```

3. **Add Celery queue** in `backend/app/celery_app.py`:
```python
app.conf.task_queues = (
    # ... existing queues ...
    Queue("google_drive", routing_key="google_drive"),
)
```

4. **Route tasks** in `celery_app.py`:
```python
task_routes = {
    # ... existing routes ...
    "app.tasks.google_drive_sync_task": {"queue": "google_drive"},
}
```

5. **Update docker-compose.yml** worker command:
```yaml
celery -A app.celery_app worker -Q processing_priority,extraction,sam,scrape,sharepoint,google_drive,maintenance
```

6. **Create the task** in `backend/app/tasks.py`:
```python
@celery_app.task(name="app.tasks.google_drive_sync_task")
def google_drive_sync_task(run_id: str, ...):
    pass
```

**Runtime Configuration (optional)** in `config.yml`:
```yaml
queues:
  google_drive:
    max_concurrent: 2
    timeout_seconds: 3600
```

---

## Frontend Integration

The Job Manager UI (`/admin/queue`) displays:
- Parent job badge with "Parent" indicator
- Child job stats showing running/pending/completed/failed counts
- Child job badge for jobs that belong to a parent group

### Automation Configuration

Jobs can be configured with `automation_config` JSONB field:
```json
{
  "after_procedure_slug": "sam-weekly-digest",
  "after_procedure_params": {
    "include_summaries": true
  }
}
```
