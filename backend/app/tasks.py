"""
Celery tasks for Curatore v2.

Handles extraction, scheduled tasks, SAM.gov integration, and web scraping.
"""
import asyncio
import logging
import re
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from celery import shared_task
from sqlalchemy import select

from .services.database_service import database_service
from .services.extraction_orchestrator import extraction_orchestrator
from .services.config_loader import config_loader
from .config import settings


# Logger for tasks
logger = logging.getLogger("curatore.tasks")


def _is_opensearch_enabled() -> bool:
    """Check if OpenSearch is enabled via config.yml or environment variables."""
    opensearch_config = config_loader.get_opensearch_config()
    if opensearch_config:
        return opensearch_config.enabled
    return False


# ============================================================================
# PHASE 0: EXTRACTION TASKS
# ============================================================================

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def execute_extraction_task(
    self,
    asset_id: str,
    run_id: str,
    extraction_id: str,
) -> Dict[str, Any]:
    """
    Execute automatic extraction for an Asset (Phase 0).

    This task is triggered when an Asset is uploaded and orchestrates
    the extraction process using extraction_orchestrator.

    Args:
        asset_id: Asset UUID string
        run_id: Run UUID string
        extraction_id: ExtractionResult UUID string

    Returns:
        Dict with extraction result details
    """
    from uuid import UUID

    logger = logging.getLogger("curatore.tasks.extraction")
    logger.info(f"Starting extraction task for asset {asset_id}")

    try:
        result = asyncio.run(
            _execute_extraction_async(
                asset_id=UUID(asset_id),
                run_id=UUID(run_id),
                extraction_id=UUID(extraction_id),
            )
        )

        logger.info(f"Extraction completed for asset {asset_id}: {result.get('status')}")
        return result

    except Exception as e:
        logger.error(f"Extraction task failed for asset {asset_id}: {e}", exc_info=True)
        raise


async def _execute_extraction_async(
    asset_id,
    run_id,
    extraction_id,
) -> Dict[str, Any]:
    """
    Async wrapper for extraction orchestrator.

    Args:
        asset_id: Asset UUID
        run_id: Run UUID
        extraction_id: ExtractionResult UUID

    Returns:
        Dict with extraction result
    """
    async with database_service.get_session() as session:
        result = await extraction_orchestrator.execute_extraction(
            session=session,
            asset_id=asset_id,
            run_id=run_id,
            extraction_id=extraction_id,
        )
        await session.commit()
        return result


# ============================================================================
# STARTUP RECOVERY TASK - Recover orphaned extractions after restart
# ============================================================================


@shared_task(bind=True)
def recover_orphaned_extractions(
    self,
    max_age_hours: int = 24,
    limit: int = 100,
) -> Dict[str, Any]:
    """
    Recover orphaned extractions after service restart.

    This task finds extractions that were in "pending" or "running" state
    when the service crashed/restarted and re-queues them for processing.

    Should be called:
    1. On worker startup (via celery signal)
    2. Periodically via scheduled task (as backup)

    Args:
        max_age_hours: Only recover extractions created within this window
        limit: Maximum number of extractions to recover per invocation

    Returns:
        Dict with recovery statistics
    """
    logger = logging.getLogger("curatore.tasks.recovery")
    logger.info(f"Starting orphaned extraction recovery (max_age={max_age_hours}h, limit={limit})")

    try:
        result = asyncio.run(
            _recover_orphaned_extractions_async(max_age_hours, limit)
        )
        logger.info(f"Recovery complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Recovery failed: {e}", exc_info=True)
        return {"status": "failed", "error": str(e)}


async def _recover_orphaned_extractions_async(
    max_age_hours: int,
    limit: int,
) -> Dict[str, Any]:
    """
    Async implementation of orphaned extraction recovery.
    """
    from .database.models import Run, ExtractionResult, Asset
    from .services.upload_integration_service import upload_integration_service
    from sqlalchemy import or_

    logger = logging.getLogger("curatore.tasks.recovery")
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)

    recovered = 0
    skipped = 0
    errors = []

    async with database_service.get_session() as session:
        # Find orphaned extractions (pending/running but old enough to be stuck)
        # We check extractions older than 10 minutes to avoid recovering tasks
        # that are legitimately still processing
        stale_cutoff = datetime.utcnow() - timedelta(minutes=10)

        result = await session.execute(
            select(ExtractionResult)
            .where(
                and_(
                    ExtractionResult.status.in_(["pending", "running"]),
                    ExtractionResult.created_at >= cutoff,  # Within recovery window
                    ExtractionResult.created_at < stale_cutoff,  # But old enough to be stuck
                )
            )
            .limit(limit)
        )
        orphaned_extractions = result.scalars().all()

        logger.info(f"Found {len(orphaned_extractions)} potentially orphaned extractions")

        for extraction in orphaned_extractions:
            try:
                # Get the associated asset
                asset = await session.execute(
                    select(Asset).where(Asset.id == extraction.asset_id)
                )
                asset = asset.scalar_one_or_none()

                if not asset:
                    logger.warning(f"Asset not found for extraction {extraction.id}, skipping")
                    skipped += 1
                    continue

                # Check if asset already has a completed extraction
                if asset.status == "ready":
                    logger.info(f"Asset {asset.id} already ready, marking extraction as completed")
                    extraction.status = "completed"
                    skipped += 1
                    continue

                # Re-queue the extraction task
                logger.info(f"Re-queuing extraction for asset {asset.id} (extraction={extraction.id})")

                # Import here to avoid circular imports
                execute_extraction_task.delay(
                    asset_id=str(asset.id),
                    run_id=str(extraction.run_id),
                    extraction_id=str(extraction.id),
                )

                recovered += 1

            except Exception as e:
                logger.error(f"Failed to recover extraction {extraction.id}: {e}")
                errors.append({"extraction_id": str(extraction.id), "error": str(e)})

        await session.commit()

    return {
        "status": "success",
        "recovered": recovered,
        "skipped": skipped,
        "errors": len(errors),
        "error_details": errors[:10],  # Limit error details
    }


# ============================================================================
# OPENSEARCH INDEXING TASKS (Phase 6)
# ============================================================================


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def index_asset_task(
    self,
    asset_id: str,
) -> Dict[str, Any]:
    """
    Index an asset to OpenSearch after extraction (Phase 6).

    This task is triggered when an asset's extraction completes successfully.
    It downloads the extracted markdown from MinIO and indexes it to OpenSearch
    for full-text search.

    Args:
        asset_id: Asset UUID string

    Returns:
        Dict with indexing result:
        {
            "asset_id": str,
            "status": "indexed" | "skipped" | "failed",
            "message": str
        }
    """
    from uuid import UUID

    logger = logging.getLogger("curatore.tasks.indexing")

    # Check if OpenSearch is enabled
    if not _is_opensearch_enabled():
        logger.debug(f"OpenSearch disabled, skipping index for asset {asset_id}")
        return {
            "asset_id": asset_id,
            "status": "skipped",
            "message": "OpenSearch is disabled",
        }

    logger.info(f"Starting index task for asset {asset_id}")

    try:
        result = asyncio.run(_index_asset_async(UUID(asset_id)))

        if result:
            logger.info(f"Indexed asset {asset_id} to OpenSearch")
            return {
                "asset_id": asset_id,
                "status": "indexed",
                "message": "Successfully indexed to OpenSearch",
            }
        else:
            logger.warning(f"Failed to index asset {asset_id}")
            return {
                "asset_id": asset_id,
                "status": "failed",
                "message": "Indexing returned False",
            }

    except Exception as e:
        logger.error(f"Index task failed for asset {asset_id}: {e}", exc_info=True)
        raise


async def _index_asset_async(asset_id) -> bool:
    """
    Async wrapper for index service.

    Args:
        asset_id: Asset UUID

    Returns:
        True if indexed successfully
    """
    from .services.index_service import index_service

    async with database_service.get_session() as session:
        return await index_service.index_asset(session, asset_id)


@shared_task(bind=True, autoretry_for=(), retry_kwargs={"max_retries": 0})
def reindex_organization_task(
    self,
    organization_id: str,
    batch_size: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Reindex all assets for an organization (Phase 6).

    This task is triggered manually by admins to rebuild the search index
    for an organization. Useful for migrations and recovery.

    Args:
        organization_id: Organization UUID string
        batch_size: Optional batch size for bulk indexing

    Returns:
        Dict with reindex statistics:
        {
            "status": "completed" | "disabled" | "failed",
            "total": int,
            "indexed": int,
            "failed": int,
            "errors": list
        }
    """
    from uuid import UUID

    logger = logging.getLogger("curatore.tasks.indexing")

    # Check if OpenSearch is enabled
    if not _is_opensearch_enabled():
        logger.info("OpenSearch disabled, skipping reindex")
        return {
            "status": "disabled",
            "message": "OpenSearch is disabled",
            "total": 0,
            "indexed": 0,
            "failed": 0,
        }

    logger.info(f"Starting reindex task for organization {organization_id}")

    try:
        result = asyncio.run(
            _reindex_organization_async(UUID(organization_id), batch_size)
        )

        logger.info(
            f"Reindex completed for org {organization_id}: "
            f"{result.get('indexed', 0)}/{result.get('total', 0)} indexed"
        )
        return result

    except Exception as e:
        logger.error(f"Reindex task failed for org {organization_id}: {e}", exc_info=True)
        return {
            "status": "failed",
            "message": str(e),
            "total": 0,
            "indexed": 0,
            "failed": 0,
        }


async def _reindex_organization_async(
    organization_id,
    batch_size: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Async wrapper for organization reindex.

    Args:
        organization_id: Organization UUID
        batch_size: Optional batch size

    Returns:
        Dict with reindex results
    """
    from .services.index_service import index_service

    async with database_service.get_session() as session:
        return await index_service.reindex_organization(
            session, organization_id, batch_size
        )


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def reindex_sam_organization_task(
    self,
    organization_id: str,
) -> Dict[str, Any]:
    """
    Reindex all SAM.gov data for an organization (Phase 7.6).

    This task indexes all existing SAM notices and solicitations to OpenSearch
    for unified search. Useful for initial setup or recovery.

    Args:
        organization_id: Organization UUID string

    Returns:
        Dict with reindex statistics
    """
    from uuid import UUID

    logger = logging.getLogger("curatore.tasks.sam_indexing")

    # Check if OpenSearch is enabled
    if not _is_opensearch_enabled():
        logger.info("OpenSearch disabled, skipping SAM reindex")
        return {
            "status": "disabled",
            "message": "OpenSearch is disabled",
            "solicitations_indexed": 0,
            "notices_indexed": 0,
        }

    logger.info(f"Starting SAM reindex task for organization {organization_id}")

    try:
        result = asyncio.run(
            _reindex_sam_organization_async(UUID(organization_id))
        )

        logger.info(
            f"SAM reindex completed for org {organization_id}: "
            f"{result.get('solicitations_indexed', 0)} solicitations, "
            f"{result.get('notices_indexed', 0)} notices indexed"
        )
        return result

    except Exception as e:
        logger.error(f"SAM reindex task failed for org {organization_id}: {e}", exc_info=True)
        return {
            "status": "failed",
            "message": str(e),
            "solicitations_indexed": 0,
            "notices_indexed": 0,
        }


async def _reindex_sam_organization_async(
    organization_id,
) -> Dict[str, Any]:
    """
    Async wrapper for SAM organization reindex.

    Args:
        organization_id: Organization UUID

    Returns:
        Dict with reindex results
    """
    from .services.opensearch_service import opensearch_service
    from .services.sam_service import sam_service

    logger = logging.getLogger("curatore.tasks.sam_indexing")

    solicitations_indexed = 0
    notices_indexed = 0
    errors = []

    async with database_service.get_session() as session:
        # Get all solicitations for the organization
        solicitations, total_count = await sam_service.list_solicitations(
            session=session,
            organization_id=organization_id,
            limit=10000,  # Get all
        )

        logger.info(f"Found {total_count} solicitations to index")

        for solicitation in solicitations:
            try:
                # Index solicitation
                success = await opensearch_service.index_sam_solicitation(
                    organization_id=organization_id,
                    solicitation_id=solicitation.id,
                    solicitation_number=solicitation.solicitation_number,
                    title=solicitation.title,
                    description=solicitation.description,
                    notice_type=solicitation.notice_type,
                    agency=solicitation.agency_name,
                    sub_agency=solicitation.bureau_name,
                    office=solicitation.office_name,
                    posted_date=solicitation.posted_date,
                    response_deadline=solicitation.response_deadline,
                    naics_codes=[solicitation.naics_code] if solicitation.naics_code else None,
                    psc_codes=[solicitation.psc_code] if solicitation.psc_code else None,
                    set_aside=solicitation.set_aside_code,
                    place_of_performance=_extract_place_of_performance(solicitation.place_of_performance),
                    notice_count=solicitation.notice_count or 0,
                    attachment_count=solicitation.attachment_count or 0,
                    summary_status=solicitation.summary_status,
                    is_active=(solicitation.status == "active"),
                    created_at=solicitation.created_at,
                )
                if success:
                    solicitations_indexed += 1

                # Get and index notices for this solicitation
                notices = await sam_service.list_notices(
                    session=session,
                    solicitation_id=solicitation.id,
                )

                for notice in notices:
                    try:
                        success = await opensearch_service.index_sam_notice(
                            organization_id=organization_id,
                            notice_id=notice.id,
                            sam_notice_id=notice.sam_notice_id,
                            solicitation_id=solicitation.id,
                            solicitation_number=solicitation.solicitation_number,
                            title=notice.title,
                            description=notice.description,
                            notice_type=notice.notice_type,
                            agency=solicitation.agency_name,
                            sub_agency=solicitation.bureau_name,
                            office=solicitation.office_name,
                            posted_date=notice.posted_date,
                            response_deadline=notice.response_deadline,
                            naics_codes=[solicitation.naics_code] if solicitation.naics_code else None,
                            psc_codes=[solicitation.psc_code] if solicitation.psc_code else None,
                            set_aside=solicitation.set_aside_code,
                            place_of_performance=_extract_place_of_performance(solicitation.place_of_performance),
                            version_number=notice.version_number,
                            created_at=notice.created_at,
                        )
                        if success:
                            notices_indexed += 1
                    except Exception as e:
                        errors.append(f"Notice {notice.id}: {str(e)}")

            except Exception as e:
                errors.append(f"Solicitation {solicitation.id}: {str(e)}")

    return {
        "status": "completed",
        "solicitations_indexed": solicitations_indexed,
        "notices_indexed": notices_indexed,
        "errors": errors[:10] if errors else [],
    }


# ============================================================================
# EMAIL TASKS
# ============================================================================

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def send_verification_email_task(self, user_email: str, user_name: str, verification_token: str) -> bool:
    """
    Send email verification email asynchronously.

    Args:
        user_email: User's email address
        user_name: User's name
        verification_token: Verification token

    Returns:
        bool: True if sent successfully
    """
    from .services.email_service import email_service

    logger = logging.getLogger("curatore.email")
    logger.info(f"Sending verification email to {user_email}")

    try:
        result = asyncio.run(
            email_service.send_verification_email(user_email, user_name, verification_token)
        )
        if result:
            logger.info(f"Verification email sent successfully to {user_email}")
        else:
            logger.error(f"Failed to send verification email to {user_email}")
        return result
    except Exception as e:
        logger.error(f"Error sending verification email to {user_email}: {e}")
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def send_password_reset_email_task(self, user_email: str, user_name: str, reset_token: str) -> bool:
    """
    Send password reset email asynchronously.

    Args:
        user_email: User's email address
        user_name: User's name
        reset_token: Password reset token

    Returns:
        bool: True if sent successfully
    """
    from .services.email_service import email_service

    logger = logging.getLogger("curatore.email")
    logger.info(f"Sending password reset email to {user_email}")

    try:
        result = asyncio.run(
            email_service.send_password_reset_email(user_email, user_name, reset_token)
        )
        if result:
            logger.info(f"Password reset email sent successfully to {user_email}")
        else:
            logger.error(f"Failed to send password reset email to {user_email}")
        return result
    except Exception as e:
        logger.error(f"Error sending password reset email to {user_email}: {e}")
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def send_welcome_email_task(self, user_email: str, user_name: str) -> bool:
    """
    Send welcome email asynchronously.

    Args:
        user_email: User's email address
        user_name: User's name

    Returns:
        bool: True if sent successfully
    """
    from .services.email_service import email_service

    logger = logging.getLogger("curatore.email")
    logger.info(f"Sending welcome email to {user_email}")

    try:
        result = asyncio.run(
            email_service.send_welcome_email(user_email, user_name)
        )
        if result:
            logger.info(f"Welcome email sent successfully to {user_email}")
        else:
            logger.error(f"Failed to send welcome email to {user_email}")
        return result
    except Exception as e:
        logger.error(f"Error sending welcome email to {user_email}: {e}")
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def send_invitation_email_task(
    self,
    user_email: str,
    user_name: str,
    invitation_token: str,
    invited_by: str,
    organization_name: str,
) -> bool:
    """
    Send user invitation email asynchronously.

    Args:
        user_email: User's email address
        user_name: User's name
        invitation_token: Invitation/setup token
        invited_by: Name of person who invited the user
        organization_name: Organization name

    Returns:
        bool: True if sent successfully
    """
    from .services.email_service import email_service

    logger = logging.getLogger("curatore.email")
    logger.info(f"Sending invitation email to {user_email} for organization {organization_name}")

    try:
        result = asyncio.run(
            email_service.send_invitation_email(
                user_email, user_name, invitation_token, invited_by, organization_name
            )
        )
        if result:
            logger.info(f"Invitation email sent successfully to {user_email}")
        else:
            logger.error(f"Failed to send invitation email to {user_email}")
        return result
    except Exception as e:
        logger.error(f"Error sending invitation email to {user_email}: {e}")
        raise


# ============================================================================
# JOB CLEANUP TASK
# ============================================================================
# Note: File cleanup is now handled by S3 lifecycle policies.
#       Only job cleanup remains as a scheduled task.

# ============================================================================
# PHASE 5: SCHEDULED TASK EXECUTION
# ============================================================================

@shared_task(bind=True)
def check_scheduled_tasks(self) -> Dict[str, Any]:
    """
    Periodic task to check for due scheduled tasks (Phase 5).

    This task runs every minute (configurable via SCHEDULED_TASK_CHECK_INTERVAL)
    and checks the database for ScheduledTasks that are due to run.

    For each due task:
    1. Creates a Run with origin="scheduled"
    2. Enqueues execute_scheduled_task_async

    Returns:
        Dict with check statistics:
        {
            "checked_at": str,
            "due_tasks": int,
            "triggered_tasks": list[str]
        }
    """
    logger = logging.getLogger("curatore.tasks.scheduled")
    logger.debug("Checking for due scheduled tasks...")

    try:
        result = asyncio.run(_check_scheduled_tasks())
        if result.get("due_tasks", 0) > 0:
            logger.info(f"Triggered {result['due_tasks']} scheduled tasks")
        return result
    except Exception as e:
        logger.error(f"Error checking scheduled tasks: {e}")
        return {"error": str(e), "checked_at": datetime.utcnow().isoformat()}


async def _check_scheduled_tasks() -> Dict[str, Any]:
    """
    Async implementation of scheduled task checker.

    Returns:
        Dict with check results
    """
    from .services.scheduled_task_service import scheduled_task_service
    from .database.models import Run, RunLogEvent, Organization
    from .config import settings
    from sqlalchemy import select

    now = datetime.utcnow()
    triggered_tasks = []

    async with database_service.get_session() as session:
        # Get default organization for global tasks
        default_org_id = None
        if settings.default_org_id:
            try:
                default_org_id = uuid.UUID(settings.default_org_id)
            except ValueError:
                pass

        # If no default org in settings, get the first organization
        if not default_org_id:
            result = await session.execute(
                select(Organization).limit(1)
            )
            first_org = result.scalar_one_or_none()
            if first_org:
                default_org_id = first_org.id

        # Find all due tasks
        due_tasks = await scheduled_task_service.list_due_tasks(session, as_of=now)

        for task in due_tasks:
            try:
                # For global tasks, use the default organization
                run_org_id = task.organization_id or default_org_id
                if not run_org_id:
                    logging.getLogger("curatore.tasks.scheduled").warning(
                        f"Skipping task {task.name}: no organization available"
                    )
                    continue

                # Create a Run for this scheduled execution
                run = Run(
                    id=uuid.uuid4(),
                    organization_id=run_org_id,
                    run_type="system_maintenance",
                    origin="scheduled",  # Scheduled trigger (vs "user" for manual)
                    status="pending",
                    config={
                        "scheduled_task_id": str(task.id),
                        "scheduled_task_name": task.name,
                        "task_type": task.task_type,
                        "task_config": task.config,
                    },
                )
                session.add(run)

                # Log the trigger
                log_event = RunLogEvent(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    level="INFO",
                    event_type="start",
                    message=f"Scheduled task '{task.display_name}' triggered by scheduler",
                    context={
                        "task_id": str(task.id),
                        "task_name": task.name,
                        "scheduled_time": task.next_run_at.isoformat() if task.next_run_at else None,
                    },
                )
                session.add(log_event)

                await session.flush()

                # Enqueue the task for execution
                execute_scheduled_task_async.delay(
                    task_id=str(task.id),
                    run_id=str(run.id),
                )

                triggered_tasks.append(task.name)
                logging.getLogger("curatore.tasks.scheduled").info(
                    f"Enqueued scheduled task: {task.name} (run_id={run.id})"
                )

            except Exception as e:
                logging.getLogger("curatore.tasks.scheduled").error(
                    f"Failed to trigger task {task.name}: {e}"
                )

        await session.commit()

    return {
        "checked_at": now.isoformat(),
        "due_tasks": len(triggered_tasks),
        "triggered_tasks": triggered_tasks,
    }


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def execute_scheduled_task_async(
    self,
    task_id: str,
    run_id: str,
) -> Dict[str, Any]:
    """
    Execute a scheduled maintenance task (Phase 5).

    This task is the main entry point for scheduled task execution.
    It handles:
    1. Looking up the ScheduledTask
    2. Acquiring a distributed lock
    3. Updating Run status
    4. Dispatching to the appropriate handler
    5. Logging summary and updating task last_run

    Args:
        task_id: ScheduledTask UUID string
        run_id: Run UUID string

    Returns:
        Dict with execution results
    """
    from uuid import UUID

    logger = logging.getLogger("curatore.tasks.scheduled")
    logger.info(f"Starting scheduled task execution: task={task_id}, run={run_id}")

    try:
        result = asyncio.run(
            _execute_scheduled_task(
                task_id=UUID(task_id),
                run_id=UUID(run_id),
            )
        )
        logger.info(f"Scheduled task completed: task={task_id}, status={result.get('status')}")
        return result

    except Exception as e:
        logger.error(f"Scheduled task failed: task={task_id}, error={e}", exc_info=True)
        raise


async def _execute_scheduled_task(
    task_id,
    run_id,
) -> Dict[str, Any]:
    """
    Async implementation of scheduled task execution.

    Args:
        task_id: ScheduledTask UUID
        run_id: Run UUID

    Returns:
        Dict with execution results
    """
    from .services.scheduled_task_service import scheduled_task_service
    from .services.lock_service import lock_service
    from .services.maintenance_handlers import MAINTENANCE_HANDLERS
    from .database.models import Run, RunLogEvent, ScheduledTask
    from sqlalchemy import select

    start_time = datetime.utcnow()
    logger = logging.getLogger("curatore.tasks.scheduled")

    async with database_service.get_session() as session:
        # 1. Look up the ScheduledTask
        task = await scheduled_task_service.get_task(session, task_id)
        if not task:
            logger.error(f"ScheduledTask not found: {task_id}")
            return {"status": "failed", "error": "Task not found"}

        # 2. Look up the Run
        run_result = await session.execute(
            select(Run).where(Run.id == run_id)
        )
        run = run_result.scalar_one_or_none()
        if not run:
            logger.error(f"Run not found: {run_id}")
            return {"status": "failed", "error": "Run not found"}

        # 3. Acquire distributed lock
        lock_resource = f"scheduled_task:{task.name}"
        lock_id = await lock_service.acquire_lock(
            lock_resource,
            timeout=3600,  # 1 hour timeout
            max_retries=0,  # Don't retry, skip if locked
        )

        if not lock_id:
            logger.warning(f"Task already running (locked): {task.name}")
            run.status = "cancelled"
            run.error_message = "Task already running (locked)"
            run.completed_at = datetime.utcnow()

            log_event = RunLogEvent(
                id=uuid.uuid4(),
                run_id=run.id,
                level="WARN",
                event_type="error",
                message="Task execution skipped - already running",
                context={"lock_resource": lock_resource},
            )
            session.add(log_event)
            await session.commit()
            return {"status": "skipped", "reason": "locked"}

        try:
            # 4. Update Run status to running
            run.status = "running"
            run.started_at = datetime.utcnow()
            await session.flush()

            # 5. Get the handler for this task type
            handler = MAINTENANCE_HANDLERS.get(task.task_type)
            if not handler:
                raise ValueError(f"Unknown task type: {task.task_type}")

            # 6. Execute the handler
            logger.info(f"Executing handler for task type: {task.task_type}")
            result = await handler(session, run, task.config or {})

            # 7. Update Run with success
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            run.results_summary = result

            # 8. Update task last_run
            task.last_run_id = run.id
            task.last_run_at = datetime.utcnow()
            task.last_run_status = "success"

            # Calculate next run
            from .services.scheduled_task_service import scheduled_task_service
            if task.enabled:
                task.next_run_at = scheduled_task_service._calculate_next_run(
                    task.schedule_expression
                )

            await session.commit()

            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(f"Task completed successfully: {task.name} in {duration:.2f}s")

            return {
                "status": "completed",
                "task_name": task.name,
                "task_type": task.task_type,
                "duration_seconds": duration,
                "results": result,
            }

        except Exception as e:
            # Update Run with failure
            run.status = "failed"
            run.completed_at = datetime.utcnow()
            run.error_message = str(e)

            # Update task last_run
            task.last_run_id = run.id
            task.last_run_at = datetime.utcnow()
            task.last_run_status = "failed"

            # Log the error
            log_event = RunLogEvent(
                id=uuid.uuid4(),
                run_id=run.id,
                level="ERROR",
                event_type="error",
                message=f"Task execution failed: {str(e)}",
            )
            session.add(log_event)

            await session.commit()
            raise

        finally:
            # Always release the lock
            await lock_service.release_lock(lock_resource, lock_id)



# ============================================================================
# SAM.GOV TASKS (Phase 7)
# ============================================================================


def _extract_place_of_performance(place_of_performance: Optional[Dict]) -> Optional[str]:
    """
    Extract place of performance as a string from the JSON structure.

    The place_of_performance field has structure like:
    {
        "state": {"code": "VA", "name": "Virginia"},
        "zip": "20146",
        "country": {"code": "USA", "name": "UNITED STATES"}
    }

    Returns a formatted string like "Virginia, USA" or just the state/country name.
    """
    if not place_of_performance:
        return None

    parts = []

    # Try to get state name
    if "state" in place_of_performance and isinstance(place_of_performance["state"], dict):
        state_name = place_of_performance["state"].get("name")
        if state_name:
            parts.append(state_name)

    # Try to get country name
    if "country" in place_of_performance and isinstance(place_of_performance["country"], dict):
        country_name = place_of_performance["country"].get("name")
        if country_name and country_name != "UNITED STATES":  # Don't append if just USA
            parts.append(country_name)

    # Fallback to zip if nothing else
    if not parts and "zip" in place_of_performance:
        return place_of_performance["zip"]

    return ", ".join(parts) if parts else None


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def sam_pull_task(
    self,
    search_id: str,
    organization_id: str,
    max_pages: int = 10,
    page_size: int = 100,
    auto_download_attachments: bool = True,
) -> Dict[str, Any]:
    """
    Celery task to pull opportunities from SAM.gov API.

    This task fetches opportunities matching a search configuration and
    creates/updates solicitations, notices, and attachments in the database.

    Args:
        search_id: SamSearch UUID string
        organization_id: Organization UUID string
        max_pages: Maximum pages to fetch (default 10)
        page_size: Results per page (default 100)
        auto_download_attachments: Whether to download attachments after pull (default True)

    Returns:
        Dict containing:
            - search_id: The search UUID
            - status: success, partial, or failed
            - total_fetched: Number of opportunities fetched
            - new_solicitations: Number of new solicitations created
            - updated_solicitations: Number of solicitations updated
            - new_notices: Number of notices created
            - new_attachments: Number of attachments discovered
            - attachment_downloads: Attachment download results (if auto_download enabled)
            - errors: List of error details
    """
    from .services.sam_pull_service import sam_pull_service
    from .services.sam_service import sam_service
    from .database.models import Run

    logger = logging.getLogger("curatore.sam")
    logger.info(f"Starting SAM pull task for search {search_id}")

    run_id = None

    try:
        async def _create_run_and_pull():
            nonlocal run_id
            async with database_service.get_session() as session:
                # Create a Run record for this pull
                run = Run(
                    organization_id=uuid.UUID(organization_id),
                    run_type="sam_pull",
                    origin="system",
                    status="running",
                    config={
                        "search_id": search_id,
                        "max_pages": max_pages,
                        "page_size": page_size,
                        "auto_download_attachments": auto_download_attachments,
                    },
                    started_at=datetime.utcnow(),
                )
                session.add(run)
                await session.flush()
                run_id = run.id

                # Update the search with the run_id
                search = await sam_service.get_search(session, uuid.UUID(search_id))
                if search:
                    search.last_pull_run_id = run.id
                    await session.commit()

                # Perform the pull
                result = await sam_pull_service.pull_opportunities(
                    session=session,
                    search_id=uuid.UUID(search_id),
                    organization_id=uuid.UUID(organization_id),
                    max_pages=max_pages,
                    page_size=page_size,
                    auto_download_attachments=auto_download_attachments,
                )

                # Update Run with results
                run.status = "completed" if result.get("status") == "success" else "completed"
                run.completed_at = datetime.utcnow()
                run.results_summary = {
                    "total_fetched": result.get("total_fetched", 0),
                    "new_solicitations": result.get("new_solicitations", 0),
                    "updated_solicitations": result.get("updated_solicitations", 0),
                    "new_notices": result.get("new_notices", 0),
                    "new_attachments": result.get("new_attachments", 0),
                    "status": result.get("status"),
                }
                if result.get("errors"):
                    run.error_message = "; ".join(str(e) for e in result["errors"][:5])
                await session.commit()

                return result

        result = asyncio.run(_create_run_and_pull())

        logger.info(
            f"SAM pull completed: {result.get('new_solicitations', 0)} new, "
            f"{result.get('updated_solicitations', 0)} updated"
        )

        if "attachment_downloads" in result:
            ad = result["attachment_downloads"]
            logger.info(
                f"Attachment downloads: {ad.get('downloaded', 0)} downloaded, "
                f"{ad.get('failed', 0)} failed"
            )

        return result

    except Exception as e:
        logger.error(f"SAM pull task failed: {e}")

        # Update Run status to failed if we have a run_id
        if run_id:
            try:
                async def _mark_failed():
                    async with database_service.get_session() as session:
                        from sqlalchemy import select
                        result = await session.execute(
                            select(Run).where(Run.id == run_id)
                        )
                        run = result.scalar_one_or_none()
                        if run:
                            run.status = "failed"
                            run.completed_at = datetime.utcnow()
                            run.error_message = str(e)
                            await session.commit()
                asyncio.run(_mark_failed())
            except Exception as inner_e:
                logger.error(f"Failed to update run status: {inner_e}")

        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def sam_download_attachment_task(
    self,
    attachment_id: str,
    organization_id: str,
) -> Dict[str, Any]:
    """
    Celery task to download a single attachment from SAM.gov.

    Downloads the attachment and creates an Asset for extraction.

    Args:
        attachment_id: SamAttachment UUID string
        organization_id: Organization UUID string

    Returns:
        Dict containing:
            - attachment_id: The attachment UUID
            - asset_id: Created Asset UUID (if successful)
            - status: downloaded or failed
            - error: Error message (if failed)
    """
    from .services.sam_pull_service import sam_pull_service

    logger = logging.getLogger("curatore.sam")
    logger.info(f"Starting SAM attachment download task for {attachment_id}")

    try:
        async def _download():
            async with database_service.get_session() as session:
                asset = await sam_pull_service.download_attachment(
                    session=session,
                    attachment_id=uuid.UUID(attachment_id),
                    organization_id=uuid.UUID(organization_id),
                )
                return asset

        asset = asyncio.run(_download())

        if asset:
            logger.info(f"Attachment {attachment_id} downloaded -> Asset {asset.id}")
            return {
                "attachment_id": attachment_id,
                "asset_id": str(asset.id),
                "status": "downloaded",
            }
        else:
            return {
                "attachment_id": attachment_id,
                "status": "failed",
                "error": "Download failed - check attachment record for details",
            }

    except Exception as e:
        logger.error(f"SAM attachment download task failed: {e}")
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def sam_summarize_task(
    self,
    solicitation_id: str,
    organization_id: str,
    summary_type: str = "executive",
    model: Optional[str] = None,
    include_attachments: bool = True,
) -> Dict[str, Any]:
    """
    Celery task to generate an LLM summary for a solicitation.

    Args:
        solicitation_id: SamSolicitation UUID string
        organization_id: Organization UUID string
        summary_type: Type of summary (executive, technical, compliance, full)
        model: LLM model to use (None = default)
        include_attachments: Whether to include extracted attachment content

    Returns:
        Dict containing:
            - solicitation_id: The solicitation UUID
            - summary_id: Created summary UUID (if successful)
            - summary_type: Type of summary generated
            - status: success or failed
            - error: Error message (if failed)
    """
    from .services.sam_summarization_service import sam_summarization_service

    logger = logging.getLogger("curatore.sam")
    logger.info(f"Starting SAM summarize task for solicitation {solicitation_id}")

    try:
        async def _summarize():
            async with database_service.get_session() as session:
                return await sam_summarization_service.summarize_solicitation(
                    session=session,
                    solicitation_id=uuid.UUID(solicitation_id),
                    organization_id=uuid.UUID(organization_id),
                    summary_type=summary_type,
                    model=model,
                    include_attachments=include_attachments,
                )

        summary = asyncio.run(_summarize())

        if summary:
            logger.info(f"Summary {summary.id} generated for solicitation {solicitation_id}")
            return {
                "solicitation_id": solicitation_id,
                "summary_id": str(summary.id),
                "summary_type": summary_type,
                "status": "success",
            }
        else:
            return {
                "solicitation_id": solicitation_id,
                "summary_type": summary_type,
                "status": "failed",
                "error": "Summary generation failed",
            }

    except Exception as e:
        logger.error(f"SAM summarize task failed: {e}")
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def sam_batch_summarize_task(
    self,
    search_id: str,
    organization_id: str,
    summary_type: str = "executive",
    model: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Celery task to generate summaries for multiple solicitations.

    Args:
        search_id: SamSearch UUID string
        organization_id: Organization UUID string
        summary_type: Type of summary to generate
        model: LLM model to use (None = default)
        limit: Maximum solicitations to summarize

    Returns:
        Dict containing:
            - search_id: The search UUID
            - summary_type: Type of summary generated
            - total_candidates: Total solicitations eligible
            - processed: Number processed
            - success: Number successfully summarized
            - failed: Number failed
            - errors: List of error details
    """
    from .services.sam_summarization_service import sam_summarization_service

    logger = logging.getLogger("curatore.sam")
    logger.info(f"Starting SAM batch summarize task for search {search_id}")

    try:
        async def _batch_summarize():
            async with database_service.get_session() as session:
                return await sam_summarization_service.batch_summarize(
                    session=session,
                    search_id=uuid.UUID(search_id),
                    organization_id=uuid.UUID(organization_id),
                    summary_type=summary_type,
                    model=model,
                    limit=limit,
                )

        result = asyncio.run(_batch_summarize())

        logger.info(
            f"Batch summarize completed: {result.get('success', 0)} succeeded, "
            f"{result.get('failed', 0)} failed"
        )

        return {
            "search_id": search_id,
            "summary_type": summary_type,
            **result,
        }

    except Exception as e:
        logger.error(f"SAM batch summarize task failed: {e}")
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def sam_auto_summarize_task(
    self,
    solicitation_id: str,
    organization_id: str,
    is_update: bool = False,
    wait_for_assets: bool = True,
    _retry_count: int = 0,
) -> Dict[str, Any]:
    """
    Celery task to auto-generate a summary for a solicitation after pull.

    This task is triggered automatically after a SAM pull to generate
    BD-focused summaries using LLM. If no LLM is configured, falls back
    to using the notice description.

    Priority Queue Behavior:
    - This task runs on the 'processing_priority' queue
    - If attachments have pending extractions, it boosts their priority
    - Task will retry until all assets are ready (up to 5 retries)

    Args:
        solicitation_id: SamSolicitation UUID string
        organization_id: Organization UUID string
        is_update: Whether this is an update (new notice added)
        wait_for_assets: Whether to wait for pending asset extractions
        _retry_count: Internal retry counter for asset waiting

    Returns:
        Dict containing:
            - solicitation_id: The solicitation UUID
            - status: pending, ready, failed, no_llm, or waiting_for_assets
            - summary_preview: First 200 chars of summary (if generated)
    """
    from datetime import datetime
    from .services.sam_summarization_service import sam_summarization_service
    from .services.sam_service import sam_service

    logger = logging.getLogger("curatore.sam")
    logger.info(f"Starting SAM auto-summarize task for solicitation {solicitation_id}")

    try:
        async def _check_and_boost_pending_assets():
            """Check for pending assets and boost their priority using the priority queue service."""
            from .services.priority_queue_service import (
                priority_queue_service,
                BoostReason,
            )

            async with database_service.get_session() as session:
                # Get all attachment assets for this solicitation
                asset_ids = await priority_queue_service.get_solicitation_attachment_assets(
                    session=session,
                    solicitation_id=uuid.UUID(solicitation_id),
                )

                if not asset_ids:
                    return True, []  # No assets to wait for

                # Check which are ready
                all_ready, ready_ids, pending_ids = await priority_queue_service.check_assets_ready(
                    session=session,
                    asset_ids=asset_ids,
                )

                if all_ready:
                    return True, []

                # Boost pending assets
                boost_result = await priority_queue_service.boost_multiple_extractions(
                    session=session,
                    asset_ids=pending_ids,
                    reason=BoostReason.SAM_SUMMARIZATION,
                    organization_id=uuid.UUID(organization_id),
                )

                logger.info(
                    f"Solicitation {solicitation_id}: {len(pending_ids)} pending assets, "
                    f"boosted {boost_result['boosted']} extractions"
                )

                return False, pending_ids

        # Check for pending assets if configured to wait
        if wait_for_assets:
            all_ready, pending_ids = asyncio.run(_check_and_boost_pending_assets())

            if not all_ready and _retry_count < 10:  # Max 10 retries (about 5 minutes total)
                logger.info(
                    f"Waiting for {len(pending_ids)} assets to complete extraction, "
                    f"retry {_retry_count + 1}/10"
                )
                # Update status to indicate waiting
                async def _update_waiting_status():
                    async with database_service.get_session() as session:
                        await sam_service.update_solicitation_summary_status(
                            session=session,
                            solicitation_id=uuid.UUID(solicitation_id),
                            status="generating",  # Still show generating
                        )
                asyncio.run(_update_waiting_status())

                # Retry after 30 seconds
                sam_auto_summarize_task.apply_async(
                    kwargs={
                        "solicitation_id": solicitation_id,
                        "organization_id": organization_id,
                        "is_update": is_update,
                        "wait_for_assets": True,
                        "_retry_count": _retry_count + 1,
                    },
                    countdown=30,
                    queue="processing_priority",
                )
                return {
                    "solicitation_id": solicitation_id,
                    "status": "waiting_for_assets",
                    "pending_assets": len(pending_ids),
                    "retry_count": _retry_count + 1,
                }

        async def _generate_summary():
            async with database_service.get_session() as session:
                # Generate the summary
                summary = await sam_summarization_service.generate_auto_summary(
                    session=session,
                    solicitation_id=uuid.UUID(solicitation_id),
                    organization_id=uuid.UUID(organization_id),
                    is_update=is_update,
                )

                if summary:
                    # Determine status based on whether LLM was used
                    # Check if it's a fallback (no LLM)
                    # Check both database connection and environment variable
                    from .services.connection_service import connection_service
                    llm_conn = await connection_service.get_default_connection(
                        session, uuid.UUID(organization_id), "llm"
                    )
                    has_llm = (
                        (llm_conn and llm_conn.is_active and llm_conn.config.get("api_key"))
                        or settings.openai_api_key
                    )
                    status = "ready" if has_llm else "no_llm"

                    # Update solicitation with summary and status
                    await sam_service.update_solicitation_summary_status(
                        session=session,
                        solicitation_id=uuid.UUID(solicitation_id),
                        status=status,
                        summary_generated_at=datetime.utcnow() if status == "ready" else None,
                    )

                    # Also update the description field if we have a summary
                    from sqlalchemy import update
                    from .database.models import SamSolicitation
                    await session.execute(
                        update(SamSolicitation)
                        .where(SamSolicitation.id == uuid.UUID(solicitation_id))
                        .values(description=summary)
                    )
                    await session.commit()

                    return {
                        "solicitation_id": solicitation_id,
                        "status": status,
                        "summary_preview": summary[:200] + "..." if len(summary) > 200 else summary,
                    }
                else:
                    # Mark as failed
                    await sam_service.update_solicitation_summary_status(
                        session=session,
                        solicitation_id=uuid.UUID(solicitation_id),
                        status="failed",
                    )

                    return {
                        "solicitation_id": solicitation_id,
                        "status": "failed",
                        "error": "Summary generation returned None",
                    }

        result = asyncio.run(_generate_summary())
        logger.info(f"Auto-summarize completed for {solicitation_id}: status={result.get('status')}")
        return result

    except Exception as e:
        logger.error(f"SAM auto-summarize task failed: {e}")

        # Mark as failed in DB
        try:
            async def _mark_failed():
                async with database_service.get_session() as session:
                    await sam_service.update_solicitation_summary_status(
                        session=session,
                        solicitation_id=uuid.UUID(solicitation_id),
                        status="failed",
                    )

            asyncio.run(_mark_failed())
        except Exception as inner_e:
            logger.error(f"Failed to mark solicitation as failed: {inner_e}")

        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def sam_auto_summarize_notice_task(
    self,
    notice_id: str,
    organization_id: str,
    wait_for_assets: bool = True,
    _retry_count: int = 0,
) -> Dict[str, Any]:
    """
    Celery task to auto-generate a summary for a notice.

    Works for both standalone notices (Special Notices without solicitation)
    and solicitation-linked notices. Uses the notice's metadata, description,
    and any attached documents to generate a comprehensive summary.

    Args:
        notice_id: SamNotice UUID string
        organization_id: Organization UUID string
        wait_for_assets: If True, retry if attachments are still processing
        _retry_count: Internal retry counter for asset waiting

    Returns:
        Dict containing:
            - notice_id: The notice UUID
            - status: pending, ready, failed, no_llm, or waiting_for_assets
            - summary_preview: First 200 chars of summary (if generated)
    """
    from datetime import datetime
    from .services.sam_service import sam_service
    from .services.llm_service import LLMService
    from .services.connection_service import connection_service
    from .database.models import SamNotice, SamAttachment, ExtractionResult

    logger = logging.getLogger("curatore.sam")
    logger.info(f"Starting SAM auto-summarize task for notice {notice_id}")

    MAX_ASSET_WAIT_RETRIES = 10

    try:
        async def _generate_notice_summary():
            async with database_service.get_session() as session:
                # Get the notice with attachments
                notice = await sam_service.get_notice(session, uuid.UUID(notice_id))
                if not notice:
                    logger.error(f"Notice not found: {notice_id}")
                    return {"notice_id": notice_id, "status": "failed", "error": "Notice not found"}

                # Check if we should wait for asset processing
                if wait_for_assets and notice.attachments:
                    pending_assets = [
                        att for att in notice.attachments
                        if att.download_status == "downloaded" and att.asset_id
                    ]

                    if pending_assets:
                        # Check if any extractions are still pending
                        from sqlalchemy import select, and_
                        pending_extractions = await session.execute(
                            select(ExtractionResult)
                            .where(
                                and_(
                                    ExtractionResult.asset_id.in_([a.asset_id for a in pending_assets]),
                                    ExtractionResult.status.in_(["pending", "running"])
                                )
                            )
                        )
                        if pending_extractions.scalars().first() and _retry_count < MAX_ASSET_WAIT_RETRIES:
                            logger.info(f"Notice {notice_id} has pending extractions, retrying in 30s...")
                            notice.summary_status = "pending"
                            await session.commit()

                            # Schedule retry
                            sam_auto_summarize_notice_task.apply_async(
                                kwargs={
                                    "notice_id": notice_id,
                                    "organization_id": organization_id,
                                    "wait_for_assets": True,
                                    "_retry_count": _retry_count + 1,
                                },
                                countdown=30,
                                queue="processing_priority",
                            )
                            return {"notice_id": notice_id, "status": "waiting_for_assets"}

                # Check for LLM availability - first try database connection
                org_id = uuid.UUID(organization_id)
                llm_conn = await connection_service.get_default_connection(session, org_id, "llm")

                has_llm = (
                    (llm_conn and llm_conn.is_active and llm_conn.config.get("api_key"))
                    or settings.openai_api_key
                )

                if not has_llm:
                    # No LLM - mark as no_llm, keep original description
                    notice.summary_status = "no_llm"
                    await session.commit()
                    logger.info(f"No LLM available for notice {notice_id}, using original description")
                    return {"notice_id": notice_id, "status": "no_llm"}

                # Update status to generating
                notice.summary_status = "generating"
                await session.commit()

                # Get extracted content from attachments
                attachment_content = ""
                if notice.attachments:
                    from .services.minio_service import get_minio_service
                    minio = get_minio_service()

                    content_parts = []
                    for att in notice.attachments:
                        if att.download_status == "downloaded" and att.asset_id:
                            # Get extraction result
                            extraction = await session.execute(
                                select(ExtractionResult)
                                .where(ExtractionResult.asset_id == att.asset_id)
                                .where(ExtractionResult.status == "completed")
                                .order_by(ExtractionResult.created_at.desc())
                                .limit(1)
                            )
                            ext_result = extraction.scalar_one_or_none()

                            if ext_result and ext_result.extracted_object_key:
                                try:
                                    content = await minio.download_text(
                                        bucket=ext_result.extracted_bucket,
                                        object_key=ext_result.extracted_object_key,
                                    )
                                    if content:
                                        content_parts.append(f"\n--- Attachment: {att.filename} ---\n{content[:5000]}")
                                except Exception as e:
                                    logger.warning(f"Failed to fetch attachment content: {e}")

                    if content_parts:
                        attachment_content = "\n".join(content_parts)

                # Build the prompt
                notice_type_name = {
                    "o": "Solicitation",
                    "p": "Presolicitation",
                    "k": "Combined Synopsis/Solicitation",
                    "r": "Sources Sought",
                    "s": "Special Notice",
                    "a": "Amendment",
                    "i": "Intent to Bundle",
                    "g": "Sale of Surplus Property",
                }.get(notice.notice_type, notice.notice_type or "Notice")

                prompt = f"""You are a Business Development analyst at a government contracting company.
Analyze this SAM.gov {notice_type_name} and provide a comprehensive summary.

NOTICE INFORMATION:
Title: {notice.title or 'Untitled'}
Type: {notice_type_name}
Agency: {notice.agency_name or 'Unknown'}
Sub-Agency/Bureau: {notice.bureau_name or 'N/A'}
Office: {notice.office_name or 'N/A'}
NAICS Code: {notice.naics_code or 'N/A'}
PSC Code: {notice.psc_code or 'N/A'}
Set-Aside: {notice.set_aside_code or 'None'}
Posted Date: {notice.posted_date.strftime('%Y-%m-%d') if notice.posted_date else 'Unknown'}
Response Deadline: {notice.response_deadline.strftime('%Y-%m-%d %H:%M') if notice.response_deadline else 'N/A'}

NOTICE DESCRIPTION:
{notice.description or 'No description available'}

{f"ATTACHMENT CONTENT:{attachment_content}" if attachment_content else ""}

Provide your analysis in the following JSON format:
{{
    "summary": "A 2-3 paragraph summary explaining: (1) What this notice is about and its purpose; (2) Key requirements, information, or announcements; (3) Important dates and action items",
    "notice_purpose": "Brief one-line description of the notice's primary purpose",
    "key_information": [
        {{"item": "Important detail or requirement", "category": "Requirements/Dates/Contacts/Action Items"}}
    ],
    "dates": {{
        "posted": "Date posted",
        "response_deadline": "Response deadline or 'N/A'",
        "other_dates": ["Any other relevant dates mentioned"]
    }},
    "contacts": [
        {{"name": "Contact name", "email": "Email", "phone": "Phone"}}
    ],
    "recommendation": "pursue/monitor/pass",
    "recommendation_rationale": "Brief explanation of why BD team should take this action"
}}

Respond ONLY with valid JSON, no additional text."""

                # Create LLM client from database connection or use default
                llm_service = LLMService()
                client = None
                model = settings.openai_model or "gpt-4o-mini"

                if llm_conn and llm_conn.is_active and llm_conn.config.get("api_key"):
                    client = await llm_service._create_client_from_config(llm_conn.config)
                    model = llm_conn.config.get("model", model)
                    logger.info(f"Using database LLM connection for notice summary: {llm_conn.name}")

                if not client:
                    client = llm_service._client

                if not client:
                    logger.error(f"No LLM client available for notice {notice_id}")
                    notice.summary_status = "failed"
                    await session.commit()
                    return {"notice_id": notice_id, "status": "failed", "error": "No LLM client available"}

                # Call LLM
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a Business Development analyst at a government contracting company. Provide accurate, professional analysis of federal notices.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.3,
                        max_tokens=4000,
                    )

                    response_text = response.choices[0].message.content
                    if not response_text:
                        notice.summary_status = "failed"
                        await session.commit()
                        return {"notice_id": notice_id, "status": "failed", "error": "LLM returned empty response"}

                    # Parse JSON response
                    import json
                    import re

                    parsed = None
                    try:
                        parsed = json.loads(response_text)
                    except json.JSONDecodeError:
                        # Try to extract JSON from markdown
                        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_text)
                        if json_match:
                            try:
                                parsed = json.loads(json_match.group(1))
                            except json.JSONDecodeError:
                                pass
                        if not parsed:
                            json_match = re.search(r"\{[\s\S]*\}", response_text)
                            if json_match:
                                try:
                                    parsed = json.loads(json_match.group(0))
                                except json.JSONDecodeError:
                                    pass

                    if parsed:
                        summary = parsed.get("summary", "")
                        recommendation = parsed.get("recommendation", "")
                        rationale = parsed.get("recommendation_rationale", "")
                        if recommendation and rationale:
                            summary += f"\n\n**Recommendation: {recommendation.upper()}** - {rationale}"
                    else:
                        summary = response_text[:2000]

                    # Update notice with generated summary
                    notice.description = summary
                    notice.summary_status = "ready"
                    notice.summary_generated_at = datetime.utcnow()
                    await session.commit()

                    logger.info(f"Generated summary for notice {notice_id}")
                    return {
                        "notice_id": notice_id,
                        "status": "ready",
                        "summary_preview": summary[:200] + "..." if len(summary) > 200 else summary,
                    }

                except Exception as e:
                    logger.error(f"LLM error for notice {notice_id}: {e}")
                    notice.summary_status = "failed"
                    await session.commit()
                    return {"notice_id": notice_id, "status": "failed", "error": str(e)}

        result = asyncio.run(_generate_notice_summary())
        logger.info(f"Auto-summarize completed for notice {notice_id}: status={result.get('status')}")
        return result

    except Exception as e:
        logger.error(f"SAM notice auto-summarize task failed: {e}")

        # Mark as failed in DB
        try:
            async def _mark_failed():
                async with database_service.get_session() as session:
                    from .services.sam_service import sam_service
                    notice = await sam_service.get_notice(session, uuid.UUID(notice_id))
                    if notice:
                        notice.summary_status = "failed"
                        await session.commit()

            asyncio.run(_mark_failed())
        except Exception as inner_e:
            logger.error(f"Failed to mark notice as failed: {inner_e}")

        raise


@shared_task(bind=True)
def sam_process_queued_requests_task(
    self,
    organization_id: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Celery task to process queued SAM.gov API requests.

    When API rate limits are exceeded, requests are queued for later execution.
    This task processes pending requests that are past their scheduled time.

    Should be scheduled to run regularly (e.g., every 5 minutes or hourly).

    Args:
        organization_id: Optional org to process (None = all orgs)
        limit: Maximum requests to process in this run

    Returns:
        Dict containing:
            - processed: Number of requests processed
            - succeeded: Number that succeeded
            - failed: Number that failed
            - remaining: Number still pending
            - errors: List of error details
    """
    from .services.sam_api_usage_service import sam_api_usage_service
    from .services.sam_pull_service import sam_pull_service

    logger = logging.getLogger("curatore.sam")
    logger.info("Starting SAM queue processing task")

    results = {
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "remaining": 0,
        "errors": [],
    }

    try:
        async def _process_queue():
            async with database_service.get_session() as session:
                org_uuid = uuid.UUID(organization_id) if organization_id else None

                # Get pending requests
                pending = await sam_api_usage_service.get_pending_requests(
                    session, org_uuid, limit
                )

                if not pending:
                    logger.info("No pending SAM requests to process")
                    return results

                for request in pending:
                    # Check rate limit before processing
                    can_call, remaining = await sam_api_usage_service.check_limit(
                        session, request.organization_id
                    )

                    if not can_call:
                        logger.info(
                            f"Rate limit still exceeded for org {request.organization_id}, "
                            f"skipping request {request.id}"
                        )
                        continue

                    # Mark as processing
                    await sam_api_usage_service.mark_request_processing(
                        session, request.id
                    )
                    results["processed"] += 1

                    try:
                        if request.request_type == "search":
                            # Re-execute the search
                            # This would typically be handled by re-triggering sam_pull_task
                            # For now, we'll mark it completed with a note
                            await sam_api_usage_service.mark_request_completed(
                                session, request.id,
                                result={"note": "Queued search should be re-triggered manually"}
                            )
                            results["succeeded"] += 1

                        elif request.request_type == "attachment":
                            # Process attachment download
                            attachment_id = request.attachment_id or request.request_params.get("attachment_id")
                            if attachment_id:
                                asset = await sam_pull_service.download_attachment(
                                    session=session,
                                    attachment_id=uuid.UUID(str(attachment_id)),
                                    organization_id=request.organization_id,
                                    check_rate_limit=True,  # Will record the call
                                )
                                if asset:
                                    await sam_api_usage_service.mark_request_completed(
                                        session, request.id,
                                        result={"asset_id": str(asset.id)}
                                    )
                                    results["succeeded"] += 1
                                else:
                                    await sam_api_usage_service.mark_request_failed(
                                        session, request.id,
                                        error="Attachment download failed"
                                    )
                                    results["failed"] += 1
                            else:
                                await sam_api_usage_service.mark_request_failed(
                                    session, request.id,
                                    error="No attachment_id in request params"
                                )
                                results["failed"] += 1

                        elif request.request_type == "detail":
                            # Detail requests are typically retried inline
                            await sam_api_usage_service.mark_request_completed(
                                session, request.id,
                                result={"note": "Detail request should be re-triggered manually"}
                            )
                            results["succeeded"] += 1

                        else:
                            await sam_api_usage_service.mark_request_failed(
                                session, request.id,
                                error=f"Unknown request type: {request.request_type}"
                            )
                            results["failed"] += 1

                    except Exception as e:
                        logger.error(f"Error processing queued request {request.id}: {e}")
                        await sam_api_usage_service.mark_request_failed(
                            session, request.id,
                            error=str(e)
                        )
                        results["failed"] += 1
                        results["errors"].append({
                            "request_id": str(request.id),
                            "error": str(e),
                        })

                # Get remaining count
                remaining_requests = await sam_api_usage_service.get_pending_requests(
                    session, org_uuid, limit=1000
                )
                results["remaining"] = len(remaining_requests)

                return results

        result = asyncio.run(_process_queue())

        logger.info(
            f"SAM queue processing completed: {result['succeeded']} succeeded, "
            f"{result['failed']} failed, {result['remaining']} remaining"
        )

        return result

    except Exception as e:
        logger.error(f"SAM queue processing task failed: {e}")
        raise


# ============================================================================
# TIERED EXTRACTION: ENHANCEMENT TASK (Phase 2)
# ============================================================================

# File types that benefit from Docling enhancement (structured documents)
ENHANCEMENT_ELIGIBLE_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"
}


def is_enhancement_eligible(filename: str) -> bool:
    """Check if file type is eligible for Docling enhancement."""
    from pathlib import Path
    ext = Path(filename).suffix.lower()
    return ext in ENHANCEMENT_ELIGIBLE_EXTENSIONS


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def enhance_extraction_task(
    self,
    asset_id: str,
    run_id: str,
    extraction_id: str,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Background task to enhance extraction quality using Docling.

    This task runs after basic extraction completes successfully. It attempts
    to extract the same asset using Docling and compares results. If Docling
    produces significantly better output, the extraction is upgraded.

    Args:
        asset_id: Asset UUID string
        run_id: Run UUID string (for the enhancement run)
        extraction_id: ExtractionResult UUID string (for the enhancement result)
        force: If True, always replace even if Docling output is not better

    Returns:
        Dict with enhancement result details:
            - status: "enhanced", "skipped", "failed", "no_improvement"
            - basic_length: Length of basic extraction
            - enhanced_length: Length of Docling extraction
            - improvement_percent: Percentage improvement in content length
    """
    logger = logging.getLogger("curatore.tasks.enhancement")
    logger.info(f"Starting extraction enhancement for asset {asset_id}")

    try:
        result = asyncio.run(
            _enhance_extraction_async(
                asset_id=uuid.UUID(asset_id),
                run_id=uuid.UUID(run_id),
                extraction_id=uuid.UUID(extraction_id),
                force=force,
            )
        )

        logger.info(f"Enhancement completed for asset {asset_id}: {result.get('status')}")
        return result

    except Exception as e:
        logger.error(f"Enhancement task failed for asset {asset_id}: {e}", exc_info=True)
        raise


async def _enhance_extraction_async(
    asset_id,
    run_id,
    extraction_id,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Async implementation of extraction enhancement.

    Enhancement logic:
    1. Get the basic extraction content
    2. Extract using Docling
    3. Compare results (length, structure)
    4. If Docling is significantly better (>20% more content), upgrade
    5. Update asset.extraction_tier to "enhanced"
    """
    from io import BytesIO
    from pathlib import Path

    from .database.models import Asset, ExtractionResult, Run
    from .services.asset_service import asset_service
    from .services.run_service import run_service
    from .services.extraction_result_service import extraction_result_service
    from .services.run_log_service import run_log_service
    from .services.minio_service import get_minio_service
    from .services.document_service import document_service
    from .services.storage_path_service import storage_paths

    logger = logging.getLogger("curatore.tasks.enhancement")

    IMPROVEMENT_THRESHOLD = 0.20  # 20% more content required for enhancement

    async with database_service.get_session() as session:
        # Get models
        asset = await asset_service.get_asset(session, asset_id)
        run = await run_service.get_run(session, run_id)
        extraction = await extraction_result_service.get_extraction_result(session, extraction_id)

        if not asset or not run or not extraction:
            error = f"Asset, Run, or Extraction not found: {asset_id}, {run_id}, {extraction_id}"
            logger.error(error)
            return {"status": "failed", "error": error}

        # Skip if already enhanced
        if asset.extraction_tier == "enhanced" and not force:
            logger.info(f"Asset {asset_id} already enhanced, skipping")
            return {"status": "skipped", "reason": "already_enhanced"}

        # Get basic extraction content for comparison
        minio = get_minio_service()
        if not minio:
            return {"status": "failed", "error": "MinIO service unavailable"}

        # Find the latest successful basic extraction
        from sqlalchemy import select, and_
        basic_extraction_result = await session.execute(
            select(ExtractionResult)
            .where(and_(
                ExtractionResult.asset_id == asset_id,
                ExtractionResult.status == "completed",
                ExtractionResult.extraction_tier == "basic",
            ))
            .order_by(ExtractionResult.created_at.desc())
            .limit(1)
        )
        basic_extraction = basic_extraction_result.scalar_one_or_none()

        if not basic_extraction:
            return {"status": "skipped", "reason": "no_basic_extraction"}

        # Get basic extraction content
        try:
            basic_content_io = minio.get_object(
                basic_extraction.extracted_bucket,
                basic_extraction.extracted_object_key
            )
            basic_content = basic_content_io.getvalue().decode('utf-8')
            basic_length = len(basic_content)
        except Exception as e:
            logger.error(f"Failed to read basic extraction: {e}")
            return {"status": "failed", "error": f"Cannot read basic extraction: {e}"}

        # Start the enhancement run
        await run_service.start_run(session, run_id)
        await extraction_result_service.update_extraction_status(session, extraction_id, "running")

        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="progress",
            message=f"Starting Docling enhancement for {asset.original_filename}",
            context={
                "asset_id": str(asset_id),
                "basic_length": basic_length,
            },
        )

        # Download asset to temp file for Docling processing
        import tempfile
        import shutil
        import time

        temp_dir = Path(tempfile.mkdtemp(prefix="curatore_enhance_"))
        temp_input_file = temp_dir / asset.original_filename

        try:
            file_data = minio.get_object(asset.raw_bucket, asset.raw_object_key)
            temp_input_file.write_bytes(file_data.getvalue())

            # Extract using Docling specifically
            # Find the first enabled Docling engine from config
            start_time = time.time()

            try:
                # Get enabled Docling engine name from config
                docling_engine_name = None
                extraction_config = config_loader.get_extraction_config()
                if extraction_config:
                    engines = getattr(extraction_config, 'engines', [])
                    for engine in engines:
                        if hasattr(engine, 'engine_type') and engine.engine_type == 'docling':
                            if hasattr(engine, 'enabled') and engine.enabled:
                                docling_engine_name = engine.name
                                break

                if not docling_engine_name:
                    logger.warning(f"No enabled Docling engine found in config, skipping enhancement")
                    await extraction_result_service.record_extraction_failure(
                        session=session,
                        extraction_id=extraction_id,
                        errors=["No Docling engine configured for enhancement"],
                    )
                    await run_service.fail_run(session, run_id, "No Docling engine configured")
                    await session.commit()
                    return {"status": "failed", "error": "No Docling engine configured"}

                enhanced_content = await document_service._extract_content(
                    temp_input_file,
                    engine=docling_engine_name,  # Use actual Docling engine name from config
                )
                enhanced_length = len(enhanced_content) if enhanced_content else 0
            except Exception as e:
                logger.warning(f"Docling extraction failed: {e}")
                await run_log_service.log_event(
                    session=session,
                    run_id=run_id,
                    level="WARN",
                    event_type="error",
                    message=f"Docling extraction failed: {e}",
                )
                await extraction_result_service.record_extraction_failure(
                    session=session,
                    extraction_id=extraction_id,
                    errors=[str(e)],
                )
                await run_service.fail_run(session, run_id, str(e))
                await session.commit()
                return {"status": "failed", "error": str(e)}

            extraction_time = time.time() - start_time

            # Compare results
            improvement = (enhanced_length - basic_length) / basic_length if basic_length > 0 else 0
            improvement_percent = improvement * 100

            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="progress",
                message=f"Enhancement comparison: basic={basic_length}, enhanced={enhanced_length}, improvement={improvement_percent:.1f}%",
            )

            # Decide whether to upgrade
            should_upgrade = force or (improvement >= IMPROVEMENT_THRESHOLD)

            if should_upgrade and enhanced_content:
                # Upload enhanced content
                extracted_bucket = settings.minio_bucket_processed
                extracted_key = storage_paths.upload(
                    str(asset.organization_id),
                    str(asset_id),
                    asset.original_filename,
                    extracted=True
                )

                minio.put_object(
                    bucket=extracted_bucket,
                    key=extracted_key,
                    data=BytesIO(enhanced_content.encode('utf-8')),
                    length=len(enhanced_content.encode('utf-8')),
                    content_type="text/markdown",
                )

                # Record successful enhancement
                await extraction_result_service.record_extraction_success(
                    session=session,
                    extraction_id=extraction_id,
                    bucket=extracted_bucket,
                    key=extracted_key,
                    extraction_time_seconds=extraction_time,
                    warnings=[],
                )

                # Update extraction tier on the extraction result
                extraction.extraction_tier = "enhanced"

                # Update asset's extraction tier
                asset.extraction_tier = "enhanced"

                # Complete the run
                await run_service.complete_run(
                    session=session,
                    run_id=run_id,
                    results_summary={
                        "status": "enhanced",
                        "basic_length": basic_length,
                        "enhanced_length": enhanced_length,
                        "improvement_percent": improvement_percent,
                    },
                )

                await run_log_service.log_summary(
                    session=session,
                    run_id=run_id,
                    message=f"Enhancement successful: {improvement_percent:.1f}% improvement",
                    context={
                        "basic_length": basic_length,
                        "enhanced_length": enhanced_length,
                        "improvement_percent": improvement_percent,
                    },
                )

                await session.commit()

                logger.info(f"Asset {asset_id} enhanced: {improvement_percent:.1f}% improvement")

                return {
                    "status": "enhanced",
                    "basic_length": basic_length,
                    "enhanced_length": enhanced_length,
                    "improvement_percent": improvement_percent,
                }

            else:
                # No significant improvement, mark as completed but don't upgrade
                await extraction_result_service.record_extraction_success(
                    session=session,
                    extraction_id=extraction_id,
                    bucket=basic_extraction.extracted_bucket,
                    key=basic_extraction.extracted_object_key,
                    extraction_time_seconds=extraction_time,
                    warnings=["Enhancement did not produce significant improvement"],
                )

                await run_service.complete_run(
                    session=session,
                    run_id=run_id,
                    results_summary={
                        "status": "no_improvement",
                        "basic_length": basic_length,
                        "enhanced_length": enhanced_length,
                        "improvement_percent": improvement_percent,
                        "threshold": IMPROVEMENT_THRESHOLD * 100,
                    },
                )

                await run_log_service.log_summary(
                    session=session,
                    run_id=run_id,
                    message=f"Enhancement completed: only {improvement_percent:.1f}% improvement (threshold: {IMPROVEMENT_THRESHOLD * 100}%)",
                )

                await session.commit()

                return {
                    "status": "no_improvement",
                    "basic_length": basic_length,
                    "enhanced_length": enhanced_length,
                    "improvement_percent": improvement_percent,
                    "threshold_percent": IMPROVEMENT_THRESHOLD * 100,
                }

        finally:
            # Cleanup temp directory
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp directory: {e}")


# ============================================================================
# PHASE 8: SHAREPOINT SYNC TASKS
# ============================================================================

@shared_task(bind=True)
def sharepoint_sync_task(
    self,
    sync_config_id: str,
    organization_id: str,
    run_id: str,
    full_sync: bool = False,
) -> Dict[str, Any]:
    """
    Execute SharePoint folder synchronization.

    This task:
    1. Gets folder inventory from SharePoint
    2. Compares with existing synced documents
    3. Downloads new/updated files and creates Assets
    4. Detects deleted files and marks them
    5. Triggers extraction for new assets

    Args:
        sync_config_id: SharePointSyncConfig UUID string
        organization_id: Organization UUID string
        run_id: Run UUID string
        full_sync: If True, re-download all files regardless of etag

    Returns:
        Dict with sync results
    """
    logger = logging.getLogger("curatore.tasks.sharepoint_sync")
    logger.info(f"Starting SharePoint sync for config {sync_config_id}")

    try:
        result = asyncio.run(
            _sharepoint_sync_async(
                sync_config_id=uuid.UUID(sync_config_id),
                organization_id=uuid.UUID(organization_id),
                run_id=uuid.UUID(run_id),
                full_sync=full_sync,
            )
        )

        logger.info(f"SharePoint sync completed for config {sync_config_id}: {result}")
        return result

    except Exception as e:
        logger.error(f"SharePoint sync failed for config {sync_config_id}: {e}", exc_info=True)
        # Mark run as failed
        asyncio.run(_fail_sharepoint_sync_run(uuid.UUID(run_id), str(e)))
        raise


async def _sharepoint_sync_async(
    sync_config_id,
    organization_id,
    run_id,
    full_sync: bool,
) -> Dict[str, Any]:
    """
    Async implementation of SharePoint sync.
    """
    from .services.sharepoint_sync_service import sharepoint_sync_service
    from .services.run_service import run_service
    from .services.run_log_service import run_log_service
    from .services.upload_integration_service import upload_integration_service
    from .database.models import SharePointSyncedDocument, Asset

    logger = logging.getLogger("curatore.tasks.sharepoint_sync")

    async with database_service.get_session() as session:
        # Start the run
        await run_service.start_run(session, run_id)
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="start",
            message=f"Starting SharePoint sync (full_sync={full_sync})",
        )
        await session.commit()

        try:
            # Execute sync
            result = await sharepoint_sync_service.execute_sync(
                session=session,
                sync_config_id=sync_config_id,
                organization_id=organization_id,
                run_id=run_id,
                full_sync=full_sync,
            )

            # Get newly created assets for extraction
            new_docs_result = await session.execute(
                select(SharePointSyncedDocument).where(
                    SharePointSyncedDocument.sync_config_id == sync_config_id,
                    SharePointSyncedDocument.last_sync_run_id == run_id,
                )
            )
            new_docs = list(new_docs_result.scalars().all())

            # Trigger extraction for new/updated assets
            extraction_count = 0
            for doc in new_docs:
                asset_result = await session.execute(
                    select(Asset).where(Asset.id == doc.asset_id)
                )
                asset = asset_result.scalar_one_or_none()
                if asset and asset.status == "pending":
                    try:
                        await upload_integration_service.trigger_extraction(
                            session=session,
                            asset_id=asset.id,
                        )
                        extraction_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to trigger extraction for asset {asset.id}: {e}")

            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="INFO",
                event_type="progress",
                message=f"Triggered extraction for {extraction_count} assets",
            )

            # Complete the run
            await run_service.complete_run(
                session=session,
                run_id=run_id,
                results_summary=result,
            )

            await run_log_service.log_summary(
                session=session,
                run_id=run_id,
                message=(
                    f"Sync completed: {result.get('new_files', 0)} new, "
                    f"{result.get('updated_files', 0)} updated, "
                    f"{result.get('unchanged_files', 0)} unchanged, "
                    f"{result.get('deleted_detected', 0)} deleted"
                ),
            )

            await session.commit()

            return result

        except Exception as e:
            logger.error(f"SharePoint sync error: {e}")
            await run_log_service.log_event(
                session=session,
                run_id=run_id,
                level="ERROR",
                event_type="error",
                message=str(e),
            )
            await run_service.fail_run(session, run_id, str(e))
            await session.commit()
            raise


async def _fail_sharepoint_sync_run(run_id, error_message: str):
    """Mark a sync run as failed."""
    from .services.run_service import run_service

    async with database_service.get_session() as session:
        await run_service.fail_run(session, run_id, error_message)
        await session.commit()


@shared_task(bind=True)
def sharepoint_import_task(
    self,
    connection_id: Optional[str],
    organization_id: str,
    folder_url: str,
    selected_items: list,
    sync_config_id: Optional[str],
    run_id: str,
) -> Dict[str, Any]:
    """
    Import selected files from SharePoint (wizard import).

    This task:
    1. Downloads each selected file from SharePoint
    2. Creates Assets with source_type='sharepoint'
    3. Creates SharePointSyncedDocument records if sync_config_id provided
    4. Triggers extraction for each asset

    Args:
        connection_id: SharePoint connection UUID string (optional)
        organization_id: Organization UUID string
        folder_url: SharePoint folder URL
        selected_items: List of items to import with their metadata
        sync_config_id: Optional sync config UUID to link documents to
        run_id: Run UUID string

    Returns:
        Dict with import results
    """
    logger = logging.getLogger("curatore.tasks.sharepoint_import")
    logger.info(f"Starting SharePoint import for {len(selected_items)} files")

    try:
        result = asyncio.run(
            _sharepoint_import_async(
                connection_id=uuid.UUID(connection_id) if connection_id else None,
                organization_id=uuid.UUID(organization_id),
                folder_url=folder_url,
                selected_items=selected_items,
                sync_config_id=uuid.UUID(sync_config_id) if sync_config_id else None,
                run_id=uuid.UUID(run_id),
            )
        )

        logger.info(f"SharePoint import completed: {result}")
        return result

    except Exception as e:
        logger.error(f"SharePoint import failed: {e}", exc_info=True)
        asyncio.run(_fail_sharepoint_sync_run(uuid.UUID(run_id), str(e)))
        raise


async def _sharepoint_import_async(
    connection_id: Optional[uuid.UUID],
    organization_id: uuid.UUID,
    folder_url: str,
    selected_items: list,
    sync_config_id: Optional[uuid.UUID],
    run_id: uuid.UUID,
) -> Dict[str, Any]:
    """
    Async implementation of SharePoint import.
    """
    import hashlib
    import tempfile
    from pathlib import Path

    import httpx

    from .services.sharepoint_sync_service import sharepoint_sync_service
    from .services.sharepoint_service import _get_sharepoint_credentials, _graph_base_url
    from .services.run_service import run_service
    from .services.run_log_service import run_log_service
    from .services.asset_service import asset_service
    from .services.minio_service import minio_service
    from .services.upload_integration_service import upload_integration_service
    from .services.storage_path_service import storage_paths

    logger = logging.getLogger("curatore.tasks.sharepoint_import")

    async with database_service.get_session() as session:
        # Start the run
        await run_service.start_run(session, run_id)
        await run_log_service.log_event(
            session=session,
            run_id=run_id,
            level="INFO",
            event_type="start",
            message=f"Starting import of {len(selected_items)} files",
        )
        await session.commit()

        # Get sync config if provided
        sync_config = None
        sync_slug = "import"
        if sync_config_id:
            sync_config = await sharepoint_sync_service.get_sync_config(session, sync_config_id)
            if sync_config:
                sync_slug = sync_config.slug

        # Get SharePoint credentials
        credentials = await _get_sharepoint_credentials(organization_id, session)
        tenant_id = credentials["tenant_id"]
        client_id = credentials["client_id"]
        client_secret = credentials["client_secret"]

        token_payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        }

        graph_base = _graph_base_url()

        results = {
            "imported": 0,
            "failed": 0,
            "errors": [],
        }

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            # Get token
            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            token_resp = await client.post(token_url, data=token_payload)
            token_resp.raise_for_status()
            token = token_resp.json().get("access_token")
            headers = {"Authorization": f"Bearer {token}"}

            for item in selected_items:
                item_id = item.get("id")
                name = item.get("name", "unknown")
                folder_path = item.get("folder", "").strip("/")
                drive_id = item.get("drive_id")
                size = item.get("size")
                web_url = item.get("web_url")
                mime_type = item.get("mime") or item.get("file_type")

                try:
                    # Download file
                    if not drive_id:
                        # Try to get drive_id from sync config or folder inventory
                        if sync_config and sync_config.folder_drive_id:
                            drive_id = sync_config.folder_drive_id
                        else:
                            raise ValueError("drive_id is required for import")

                    download_url = f"{graph_base}/drives/{drive_id}/items/{item_id}/content"

                    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                        async with client.stream("GET", download_url, headers=headers) as response:
                            response.raise_for_status()
                            async for chunk in response.aiter_bytes():
                                tmp_file.write(chunk)
                        tmp_path = tmp_file.name

                    # Calculate content hash
                    content_hash = None
                    try:
                        with open(tmp_path, "rb") as f:
                            content_hash = hashlib.sha256(f.read()).hexdigest()
                    except:
                        pass

                    # Generate storage path
                    org_id_str = str(organization_id)
                    storage_key = storage_paths.sharepoint_sync(
                        org_id=org_id_str,
                        sync_slug=sync_slug,
                        relative_path=folder_path,
                        filename=name,
                        extracted=False,
                    )

                    # Upload to MinIO
                    uploads_bucket = minio_service.uploads_bucket
                    await minio_service.upload_file(
                        bucket=uploads_bucket,
                        object_key=storage_key,
                        file_path=tmp_path,
                        content_type=mime_type,
                    )

                    # Cleanup temp file
                    try:
                        Path(tmp_path).unlink()
                    except:
                        pass

                    # Create asset
                    asset = await asset_service.create_asset(
                        session=session,
                        organization_id=organization_id,
                        source_type="sharepoint",
                        source_metadata={
                            "sync_config_id": str(sync_config_id) if sync_config_id else None,
                            "sharepoint_item_id": item_id,
                            "sharepoint_drive_id": drive_id,
                            "sharepoint_path": folder_path,
                            "sharepoint_web_url": web_url,
                            "folder_url": folder_url,
                            "import_run_id": str(run_id),
                        },
                        original_filename=name,
                        raw_bucket=uploads_bucket,
                        raw_object_key=storage_key,
                        content_type=mime_type,
                        file_size=size,
                        file_hash=content_hash,
                        status="pending",
                    )

                    # Create synced document record if sync config exists
                    if sync_config_id:
                        await sharepoint_sync_service.create_synced_document(
                            session=session,
                            sync_config_id=sync_config_id,
                            asset_id=asset.id,
                            sharepoint_item_id=item_id,
                            sharepoint_drive_id=drive_id,
                            sharepoint_path=folder_path,
                            sharepoint_web_url=web_url,
                            file_size=size,
                            content_hash=content_hash,
                            run_id=run_id,
                        )

                    # Trigger extraction
                    try:
                        await upload_integration_service.trigger_extraction(
                            session=session,
                            asset_id=asset.id,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to trigger extraction for {name}: {e}")

                    results["imported"] += 1

                    await run_log_service.log_event(
                        session=session,
                        run_id=run_id,
                        level="INFO",
                        event_type="progress",
                        message=f"Imported: {name}",
                    )

                except Exception as e:
                    logger.error(f"Failed to import {name}: {e}")
                    results["failed"] += 1
                    results["errors"].append({"file": name, "error": str(e)})

                    await run_log_service.log_event(
                        session=session,
                        run_id=run_id,
                        level="ERROR",
                        event_type="error",
                        message=f"Failed to import {name}: {e}",
                    )

        # Complete the run
        await run_service.complete_run(
            session=session,
            run_id=run_id,
            results_summary=results,
        )

        await run_log_service.log_summary(
            session=session,
            run_id=run_id,
            message=f"Import completed: {results['imported']} imported, {results['failed']} failed",
        )

        await session.commit()

        return results
