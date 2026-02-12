"""
Maintenance, scheduled, and email Celery tasks for Curatore v2.

Extracted from the monolithic tasks.py. Each task preserves its original
``name="app.tasks.<function_name>"`` so that Celery beat schedules and
routing rules continue to work without changes.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict

from celery import shared_task

from app.celery_app import app as celery_app
from app.core.shared.database_service import database_service

# Logger for tasks
logger = logging.getLogger("curatore.tasks")


# ============================================================================
# EMAIL TASKS
# ============================================================================

@shared_task(bind=True, name="app.tasks.send_verification_email_task", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
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
    from app.core.auth.email_service import email_service

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


@shared_task(bind=True, name="app.tasks.send_password_reset_email_task", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
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
    from app.core.auth.email_service import email_service

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


@shared_task(bind=True, name="app.tasks.send_welcome_email_task", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def send_welcome_email_task(self, user_email: str, user_name: str) -> bool:
    """
    Send welcome email asynchronously.

    Args:
        user_email: User's email address
        user_name: User's name

    Returns:
        bool: True if sent successfully
    """
    from app.core.auth.email_service import email_service

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


@shared_task(bind=True, name="app.tasks.send_invitation_email_task", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
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
    from app.core.auth.email_service import email_service

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
# FILE CLEANUP TASK
# ============================================================================
# Note: File cleanup is now handled by S3 lifecycle policies.
#       This task is kept as a lightweight stub because it is referenced
#       in celery_app.py's beat_schedule.

@shared_task(bind=True, name="app.tasks.cleanup_expired_files_task")
def cleanup_expired_files_task(self) -> Dict[str, Any]:
    """
    Stub for expired-file cleanup.

    Actual file expiration is handled by S3/MinIO lifecycle policies.
    This task remains registered so that the Celery beat schedule entry
    in celery_app.py does not raise an unregistered-task error.

    Returns:
        Dict with status information.
    """
    logger = logging.getLogger("curatore.tasks.cleanup")
    logger.info("cleanup_expired_files_task invoked (no-op: handled by S3 lifecycle policies)")
    return {
        "status": "noop",
        "message": "File cleanup is handled by S3 lifecycle policies",
        "checked_at": datetime.utcnow().isoformat(),
    }


# ============================================================================
# PHASE 5: SCHEDULED TASK EXECUTION
# ============================================================================

@celery_app.task(bind=True, name="app.tasks.check_scheduled_tasks")
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
    from sqlalchemy import select

    from app.config import settings
    from app.core.database.models import Organization, Run, RunLogEvent
    from app.core.ops.scheduled_task_service import scheduled_task_service

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

                # CRITICAL: Advance next_run_at immediately to prevent duplicate triggers.
                # Without this, if the task takes a long time or fails, the checker will
                # keep finding it as "due" every minute and create duplicate runs.
                if task.enabled:
                    task.next_run_at = scheduled_task_service._calculate_next_run(
                        task.schedule_expression
                    )

                # Commit before dispatching Celery task to ensure Run is visible to worker
                # (Same fix as extraction queue race condition)
                await session.commit()

                # Enqueue the task for execution with explicit queue routing
                # Use apply_async instead of delay for reliable routing + task tracking
                celery_task = execute_scheduled_task_async.apply_async(
                    kwargs={
                        "task_id": str(task.id),
                        "run_id": str(run.id),
                    },
                    queue="maintenance",
                )

                # Update run with Celery task info (same pattern as extraction tasks)
                from datetime import datetime as dt
                now = dt.utcnow()
                run.status = "submitted"
                run.celery_task_id = celery_task.id
                run.submitted_to_celery_at = now
                run.last_activity_at = now
                await session.commit()

                triggered_tasks.append(task.name)
                logging.getLogger("curatore.tasks.scheduled").info(
                    f"Submitted scheduled task: {task.name} (run_id={run.id}, celery_task_id={celery_task.id})"
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


@celery_app.task(bind=True, name="app.tasks.execute_scheduled_task_async", max_retries=0, soft_time_limit=3600, time_limit=3900)  # 60 minute soft limit, 65 minute hard limit
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
    from sqlalchemy import select

    from app.core.database.models import Run, RunLogEvent
    from app.core.ops.scheduled_task_registry import discover_handlers, get_handler
    from app.core.ops.scheduled_task_service import scheduled_task_service
    from app.core.shared.lock_service import lock_service

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
            # Lock is held — check if there's a truly active run for this task.
            # Only a "running" run with recent activity (last 5 min) counts.
            # Runs in stale/submitted/pending states indicate the previous
            # execution is stuck and the lock should be cleared.
            activity_cutoff = datetime.utcnow() - timedelta(minutes=5)
            active_run_result = await session.execute(
                select(Run).where(
                    Run.run_type == "system_maintenance",
                    Run.status == "running",
                    Run.config["task_type"].astext == task.task_type,
                    Run.id != run.id,
                    Run.last_activity_at > activity_cutoff,
                ).limit(1)
            )
            active_run = active_run_result.scalar_one_or_none()

            if active_run is None:
                # No actively running task — lock is stale, force-clear and re-acquire
                logger.warning(
                    f"Stale lock detected for {task.name}: no active run found. "
                    "Force-clearing lock."
                )
                r = await lock_service._get_redis()
                await r.delete(f"{lock_service._lock_prefix}{lock_resource}")
                lock_id = await lock_service.acquire_lock(
                    lock_resource,
                    timeout=3600,
                    max_retries=0,
                )

        if not lock_id:
            logger.warning(f"Task already running (locked): {task.name}")
            run.status = "cancelled"
            run.error_message = "Task already running (locked)"
            run.completed_at = datetime.utcnow()

            # Still advance next_run_at to prevent duplicate runs
            from app.core.ops.scheduled_task_service import scheduled_task_service
            if task.enabled:
                task.next_run_at = scheduled_task_service._calculate_next_run(
                    task.schedule_expression
                )

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
            # IMPORTANT: Use commit() not flush() to release the row lock.
            # flush() keeps the transaction open, which blocks heartbeat
            # updates from other connections attempting to update the same row.
            run.status = "running"
            run.started_at = datetime.utcnow()
            await session.commit()

            # 5. Get the handler for this task type
            discover_handlers()
            handler = get_handler(task.task_type)
            if not handler:
                raise ValueError(f"Unknown task type: {task.task_type}")

            # 6. Execute the handler — use the Run's task_config (which includes
            #    any user-supplied config_overrides merged on top of the
            #    ScheduledTask's stored config) rather than the bare task.config.
            logger.info(f"Executing handler for task type: {task.task_type}")
            effective_config = (run.config or {}).get("task_config", task.config or {})
            result = await handler(session, run, effective_config)

            # 7. Update Run with success
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            run.results_summary = result

            # 8. Update task last_run
            task.last_run_id = run.id
            task.last_run_at = datetime.utcnow()
            task.last_run_status = "success"

            # Calculate next run
            from app.core.ops.scheduled_task_service import scheduled_task_service
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

            # IMPORTANT: Still advance next_run_at to prevent duplicate runs
            # Without this, failed tasks keep getting triggered every minute
            from app.core.ops.scheduled_task_service import scheduled_task_service
            if task.enabled:
                task.next_run_at = scheduled_task_service._calculate_next_run(
                    task.schedule_expression
                )

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
