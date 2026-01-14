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
    task_routes={},
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

app.conf.beat_schedule = {
    "cleanup-expired-files": {
        "task": "app.tasks.cleanup_expired_files_task",
        "schedule": cleanup_schedule,
        "options": {"queue": "processing"},
    },
}

app.conf.timezone = "UTC"

