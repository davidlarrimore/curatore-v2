"""
Celery application setup for Curatore v2.

Configures Celery using environment-driven settings so workers and the API
share the same broker/result backend. Tasks live in app.tasks.

Queue Architecture:
- processing_priority: High-priority tasks (user-requested, SAM summarization dependencies)
- processing: Normal extraction and indexing tasks (FIFO)
- maintenance: Scheduled tasks, cleanup, recovery (non-blocking)

Workers consume queues left-to-right, so priority queue is processed first.
"""
import os
from celery import Celery
from kombu import Queue


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

# Define task queues - each job type has its own queue for isolation
#
# Queue Architecture:
# - processing_priority: High priority tasks (user-boosted extractions)
# - extraction: Document extraction tasks
# - sam: SAM.gov API operations
# - scrape: Web scraping and crawling
# - sharepoint: SharePoint sync operations
# - maintenance: Scheduled tasks, cleanup, recovery
app.conf.task_queues = (
    Queue("processing_priority", routing_key="processing_priority"),
    Queue("extraction", routing_key="extraction"),
    Queue("sam", routing_key="sam"),
    Queue("scrape", routing_key="scrape"),
    Queue("sharepoint", routing_key="sharepoint"),
    Queue("pipeline", routing_key="pipeline"),
    Queue("maintenance", routing_key="maintenance"),
)

# Core settings with sensible defaults, overridable via env
app.conf.update(
    task_acks_late=_bool(os.getenv("CELERY_ACKS_LATE", "true"), True),
    worker_prefetch_multiplier=int(os.getenv("CELERY_PREFETCH_MULTIPLIER", "1")),
    worker_max_tasks_per_child=int(os.getenv("CELERY_MAX_TASKS_PER_CHILD", "50")),
    task_soft_time_limit=int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "600")),
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", "900")),
    result_expires=int(os.getenv("CELERY_RESULT_EXPIRES", "259200")),  # 3 days
    task_default_queue=os.getenv("CELERY_DEFAULT_QUEUE", "extraction"),
    # Route tasks to dedicated queues for job-type isolation
    # This prevents one job type from blocking others
    task_routes={
        # =================================================================
        # EXTRACTION QUEUE - Document extraction with triage-based routing
        # =================================================================
        "app.tasks.execute_extraction_task": {"queue": "extraction"},
        # Index task runs after extraction, uses same queue
        "app.tasks.index_asset_task": {"queue": "extraction"},

        # =================================================================
        # SAM QUEUE - SAM.gov API operations
        # =================================================================
        "app.tasks.sam_pull_task": {"queue": "sam"},
        "app.tasks.sam_refresh_solicitation_task": {"queue": "sam"},
        "app.tasks.sam_auto_summarize_task": {"queue": "sam"},
        "app.tasks.sam_auto_summarize_notice_task": {"queue": "sam"},

        # =================================================================
        # SCRAPE QUEUE - Web scraping tasks
        # =================================================================
        "app.tasks.scrape_crawl_task": {"queue": "scrape"},
        "app.tasks.async_delete_scrape_collection_task": {"queue": "maintenance"},

        # =================================================================
        # SHAREPOINT QUEUE - SharePoint sync tasks
        # =================================================================
        "app.tasks.sharepoint_sync_task": {"queue": "sharepoint"},
        "app.tasks.sharepoint_import_task": {"queue": "sharepoint"},
        "app.tasks.async_delete_sync_config_task": {"queue": "maintenance"},

        # =================================================================
        # PIPELINE QUEUE - Multi-stage document processing
        # =================================================================
        "app.tasks.execute_pipeline_task": {"queue": "pipeline"},

        # =================================================================
        # MAINTENANCE QUEUE - System tasks, queue management, cleanup
        # =================================================================
        # Procedure execution (uses maintenance queue for lightweight execution)
        "app.tasks.execute_procedure_task": {"queue": "maintenance"},
        # Scheduled task system
        "app.tasks.check_scheduled_tasks": {"queue": "maintenance"},
        "app.tasks.execute_scheduled_task_async": {"queue": "maintenance"},
        # Recovery and maintenance
        "app.tasks.recover_orphaned_extractions": {"queue": "maintenance"},
        # Queue processors (lightweight, run frequently)
        "app.tasks.process_extraction_queue_task": {"queue": "maintenance"},
        "app.tasks.check_extraction_timeouts_task": {"queue": "maintenance"},
        "app.tasks.sam_process_queued_requests_task": {"queue": "maintenance"},
        # Cleanup tasks
        "app.tasks.cleanup_expired_files_task": {"queue": "maintenance"},

        # =================================================================
        # PRIORITY QUEUE - User-boosted tasks get priority processing
        # =================================================================
        # Priority extractions are routed here via queue_priority field
        # (handled by extraction_queue_service.submit_to_celery)
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

beat_schedule = {
    "cleanup-expired-files": {
        "task": "app.tasks.cleanup_expired_files_task",
        "schedule": cleanup_schedule,
        "options": {"queue": "maintenance"},
    },
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

# Add extraction queue processing task
# This task submits pending extractions to Celery based on available capacity
extraction_queue_enabled = _bool(os.getenv("EXTRACTION_QUEUE_ENABLED", "true"), True)
extraction_queue_interval = int(os.getenv("EXTRACTION_SUBMISSION_INTERVAL", "5"))  # 5 seconds

if extraction_queue_enabled:
    beat_schedule["process-extraction-queue"] = {
        "task": "app.tasks.process_extraction_queue_task",
        "schedule": extraction_queue_interval,  # Every N seconds (default: 5)
        "options": {"queue": "maintenance"},
    }

# Add extraction timeout checker task
# This task marks extractions that have exceeded their timeout as 'timed_out'
extraction_timeout_check_enabled = _bool(os.getenv("EXTRACTION_TIMEOUT_CHECK_ENABLED", "true"), True)
extraction_timeout_check_interval = int(os.getenv("EXTRACTION_TIMEOUT_CHECK_INTERVAL", "60"))  # 1 minute

if extraction_timeout_check_enabled:
    beat_schedule["check-extraction-timeouts"] = {
        "task": "app.tasks.check_extraction_timeouts_task",
        "schedule": extraction_timeout_check_interval,  # Every N seconds (default: 60)
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
    Handle worker startup - initialize services and trigger recovery.

    This runs when a Celery worker finishes initialization and is ready
    to process tasks. We:
    1. Initialize the queue registry
    2. Schedule orphaned extraction recovery
    """
    # Initialize queue registry
    try:
        from .services.queue_registry import initialize_queue_registry
        initialize_queue_registry()
        _recovery_logger.info("Queue registry initialized")
    except Exception as e:
        _recovery_logger.warning(f"Failed to initialize queue registry: {e}")

    # Schedule orphaned extraction recovery
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

