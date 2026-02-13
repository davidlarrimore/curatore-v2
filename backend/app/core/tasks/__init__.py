"""
Celery tasks package for Curatore v2.

Re-exports all task functions for backward compatibility.
Celery discovers tasks via the include= list in celery_app.py,
which references each submodule directly.
"""

# Collection tasks
from app.core.tasks.collections import (
    populate_collection_fresh_task,
)

# Extraction tasks
from app.core.tasks.extraction import (
    check_extraction_timeouts_task,
    enhance_extraction_task,
    execute_extraction_task,
    index_asset_task,
    process_extraction_queue_task,
    recover_orphaned_extractions,
    reindex_organization_task,
)

# Forecast tasks
from app.core.tasks.forecasts import (
    forecast_sync_task,
)

# Maintenance/Scheduled tasks
from app.core.tasks.maintenance import (
    check_scheduled_tasks,
    cleanup_expired_files_task,
    execute_scheduled_task_async,
    send_invitation_email_task,
    send_password_reset_email_task,
    send_verification_email_task,
    send_welcome_email_task,
)

# Procedure/Pipeline tasks
from app.core.tasks.procedures import (
    execute_pipeline_task,
    execute_procedure_task,
)

# Salesforce tasks
from app.core.tasks.salesforce import (
    reindex_salesforce_organization_task,
    salesforce_import_task,
)

# SAM.gov tasks
from app.core.tasks.sam import (
    reindex_sam_organization_task,
    sam_auto_summarize_notice_task,
    sam_auto_summarize_task,
    sam_batch_summarize_task,
    sam_download_attachment_task,
    sam_process_queued_requests_task,
    sam_pull_task,
    sam_refresh_notice_task,
    sam_refresh_solicitation_task,
    sam_summarize_task,
)

# Scrape tasks
from app.core.tasks.scrape import (
    async_delete_scrape_collection_task,
    scrape_crawl_task,
)

# SharePoint tasks
from app.core.tasks.sharepoint import (
    async_delete_sync_config_task,
    sharepoint_import_task,
    sharepoint_sync_task,
)

__all__ = [
    # Collections
    "populate_collection_fresh_task",
    # Extraction
    "execute_extraction_task",
    "recover_orphaned_extractions",
    "process_extraction_queue_task",
    "check_extraction_timeouts_task",
    "index_asset_task",
    "reindex_organization_task",
    "enhance_extraction_task",
    # SAM.gov
    "reindex_sam_organization_task",
    "sam_pull_task",
    "sam_refresh_solicitation_task",
    "sam_refresh_notice_task",
    "sam_download_attachment_task",
    "sam_summarize_task",
    "sam_batch_summarize_task",
    "sam_auto_summarize_task",
    "sam_auto_summarize_notice_task",
    "sam_process_queued_requests_task",
    # Salesforce
    "reindex_salesforce_organization_task",
    "salesforce_import_task",
    # SharePoint
    "sharepoint_sync_task",
    "sharepoint_import_task",
    "async_delete_sync_config_task",
    # Scrape
    "scrape_crawl_task",
    "async_delete_scrape_collection_task",
    # Procedures/Pipelines
    "execute_procedure_task",
    "execute_pipeline_task",
    # Forecasts
    "forecast_sync_task",
    # Maintenance
    "send_verification_email_task",
    "send_password_reset_email_task",
    "send_welcome_email_task",
    "send_invitation_email_task",
    "check_scheduled_tasks",
    "execute_scheduled_task_async",
    "cleanup_expired_files_task",
]
