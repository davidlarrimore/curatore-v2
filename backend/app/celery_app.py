"""
Celery application setup for Curatore v2.

Configures Celery using environment-driven settings so workers and the API
share the same broker/result backend. Tasks live in app.tasks.
"""
import os
from celery import Celery


def _bool(val: str, default: bool = False) -> bool:
    if val is None:
        return default
    return str(val).lower() in {"1", "true", "yes", "on"}


BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

app = Celery(
    "curatore",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["app.tasks"],
)

# Core settings with sensible defaults, overridable via env
app.conf.update(
    task_acks_late=_bool(os.getenv("CELERY_ACKS_LATE", "true"), True),
    worker_prefetch_multiplier=int(os.getenv("CELERY_PREFETCH_MULTIPLIER", "1")),
    worker_max_tasks_per_child=int(os.getenv("CELERY_MAX_TASKS_PER_CHILD", "50")),
    task_soft_time_limit=int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "600")),
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", "900")),
    result_expires=int(os.getenv("CELERY_RESULT_EXPIRES", "259200")),  # 3 days
    task_default_queue=os.getenv("CELERY_DEFAULT_QUEUE", "processing"),
    # Route maintenance/scheduled tasks to separate 'maintenance' queue
    # This prevents them from being blocked by slow extraction tasks
    task_routes={
        # Scheduled task system
        "app.tasks.check_scheduled_tasks": {"queue": "maintenance"},
        "app.tasks.execute_scheduled_task_async": {"queue": "maintenance"},
        # Recovery and maintenance
        "app.tasks.recover_orphaned_extractions": {"queue": "maintenance"},
        "app.tasks.cleanup_expired_jobs_task": {"queue": "maintenance"},
        # SAM.gov queue processing (lightweight, shouldn't block on extractions)
        "app.tasks.sam_process_queued_requests_task": {"queue": "maintenance"},
        # All extraction/indexing tasks stay on default 'processing' queue
    },
)

# ============================================================================
# Celery Beat Schedule (for periodic tasks)
# ============================================================================
from celery.schedules import crontab

# Parse cron schedule from config (default: daily at 2 AM)
cleanup_schedule_str = os.getenv("FILE_CLEANUP_SCHEDULE_CRON", "0 2 * * *")
cleanup_enabled = _bool(os.getenv("FILE_CLEANUP_ENABLED", "true"), True)

# Parse cron string (format: "minute hour day month day_of_week")
try:
    parts = cleanup_schedule_str.split()
    if len(parts) == 5:
        cleanup_schedule = crontab(
            minute=parts[0],
            hour=parts[1],
            day_of_month=parts[2],
            month_of_year=parts[3],
            day_of_week=parts[4],
        )
    else:
        # Default to daily at 2 AM if parsing fails
        cleanup_schedule = crontab(hour=2, minute=0)
except Exception:
    # Fallback to daily at 2 AM
    cleanup_schedule = crontab(hour=2, minute=0)

# Parse job cleanup schedule from config (default: daily at 3 AM)
job_cleanup_schedule_str = os.getenv("JOB_CLEANUP_SCHEDULE_CRON", "0 3 * * *")
job_cleanup_enabled = _bool(os.getenv("JOB_CLEANUP_ENABLED", "true"), True)

# Parse job cleanup cron string
try:
    parts = job_cleanup_schedule_str.split()
    if len(parts) == 5:
        job_cleanup_schedule = crontab(
            minute=parts[0],
            hour=parts[1],
            day_of_month=parts[2],
            month_of_year=parts[3],
            day_of_week=parts[4],
        )
    else:
        # Default to daily at 3 AM if parsing fails
        job_cleanup_schedule = crontab(hour=3, minute=0)
except Exception:
    # Fallback to daily at 3 AM
    job_cleanup_schedule = crontab(hour=3, minute=0)

beat_schedule = {
    "cleanup-expired-files": {
        "task": "app.tasks.cleanup_expired_files_task",
        "schedule": cleanup_schedule,
        "options": {"queue": "processing"},
    },
}

# Add job cleanup task if enabled (Phase 2+)
if job_cleanup_enabled:
    beat_schedule["cleanup-expired-jobs"] = {
        "task": "app.tasks.cleanup_expired_jobs_task",
        "schedule": job_cleanup_schedule,
        "options": {"queue": "maintenance"},
    }

# Add scheduled task checker (Phase 5)
# This task runs every minute to check for due ScheduledTasks in the database
scheduled_task_check_enabled = _bool(os.getenv("SCHEDULED_TASK_CHECK_ENABLED", "true"), True)
scheduled_task_check_interval = int(os.getenv("SCHEDULED_TASK_CHECK_INTERVAL", "60"))

if scheduled_task_check_enabled:
    beat_schedule["check-scheduled-tasks"] = {
        "task": "app.tasks.check_scheduled_tasks",
        "schedule": scheduled_task_check_interval,  # Every N seconds (default: 60)
        "options": {"queue": "maintenance"},
    }

# Add SAM.gov queued request processor (Phase 7)
# This processes API requests that were queued when rate limits were exceeded
sam_queue_process_enabled = _bool(os.getenv("SAM_QUEUE_PROCESS_ENABLED", "true"), True)
sam_queue_process_interval = int(os.getenv("SAM_QUEUE_PROCESS_INTERVAL", "300"))  # 5 minutes

if sam_queue_process_enabled:
    beat_schedule["sam-process-queued-requests"] = {
        "task": "app.tasks.sam_process_queued_requests_task",
        "schedule": sam_queue_process_interval,  # Every N seconds (default: 300 = 5 min)
        "options": {"queue": "maintenance"},
    }

# Add orphaned extraction recovery task
# This runs periodically as a backup to the worker_ready signal
# Helps catch any extractions that slipped through or got stuck
extraction_recovery_enabled = _bool(os.getenv("EXTRACTION_RECOVERY_ENABLED", "true"), True)
extraction_recovery_interval = int(os.getenv("EXTRACTION_RECOVERY_INTERVAL", "900"))  # 15 minutes

if extraction_recovery_enabled:
    beat_schedule["recover-orphaned-extractions"] = {
        "task": "app.tasks.recover_orphaned_extractions",
        "schedule": extraction_recovery_interval,  # Every N seconds (default: 900 = 15 min)
        "kwargs": {"max_age_hours": 24, "limit": 50},
        "options": {"queue": "maintenance"},
    }

app.conf.beat_schedule = beat_schedule

app.conf.timezone = "UTC"


# ============================================================================
# WORKER STARTUP RECOVERY
# ============================================================================
# Run orphaned extraction recovery when worker starts up
# This ensures any extractions stuck in pending/running state from a crash
# are automatically recovered

from celery.signals import worker_ready
import logging

_recovery_logger = logging.getLogger("curatore.celery.recovery")


@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    """
    Handle worker startup - trigger recovery of orphaned extractions.

    This runs when a Celery worker finishes initialization and is ready
    to process tasks. We delay the recovery task slightly to ensure
    all services are fully initialized.
    """
    recovery_enabled = _bool(os.getenv("CELERY_STARTUP_RECOVERY_ENABLED", "true"), True)

    if not recovery_enabled:
        _recovery_logger.info("Startup recovery disabled via CELERY_STARTUP_RECOVERY_ENABLED")
        return

    _recovery_logger.info("Worker ready - scheduling orphaned extraction recovery")

    # Import here to avoid circular imports
    from .tasks import recover_orphaned_extractions

    # Delay recovery by 10 seconds to ensure all services are ready
    recover_orphaned_extractions.apply_async(
        kwargs={"max_age_hours": 24, "limit": 200},
        countdown=10,
    )

    _recovery_logger.info("Orphaned extraction recovery task scheduled")

