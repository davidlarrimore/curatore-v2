"""
Job tracking and management service for Celery tasks.

Provides both Redis-backed (legacy) and database-backed (Phase 2+) job tracking:
- Redis: Fast per-document active job locks and status caching
- Database: Persistent batch job tracking, history, and audit logs

Responsibilities:
- Create and manage batch jobs with multiple documents
- Track job progress and document-level status
- Enforce per-organization concurrency limits
- Handle job cancellation with verification
- Cleanup expired jobs based on retention policies
- Legacy Redis-based per-document tracking (backward compatibility)
"""
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import redis
from sqlalchemy import select, func, and_, or_
from sqlalchemy.exc import SQLAlchemyError

from ..database.models import Job, JobDocument, JobLog
from .database_service import database_service
from .path_service import path_service


def get_redis_client() -> redis.Redis:
    url = os.getenv("JOB_REDIS_URL") or os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
    return redis.Redis.from_url(url)


def _get_original_filename(document_id: str, organization_id: Optional[uuid.UUID] = None) -> str:
    """
    Get the original filename for a document by searching the file system.

    Files are stored as {document_id}_{original_filename} in the uploaded directory.
    This function extracts the original_filename portion.

    Args:
        document_id: The document UUID
        organization_id: Optional organization UUID for hierarchical storage

    Returns:
        Original filename if found, otherwise returns document_id as fallback
    """
    from ..config import settings

    try:
        # Check shared/adhoc/uploaded directory (for individual document uploads)
        if settings.use_hierarchical_storage:
            shared_adhoc = Path(settings.files_root) / "shared" / "adhoc" / "uploaded"
            if shared_adhoc.exists():
                for file in shared_adhoc.iterdir():
                    if file.is_file() and file.name.startswith(f"{document_id}_"):
                        return file.name[len(document_id) + 1:]

        # Check organization-specific adhoc directory if using hierarchical storage
        if organization_id and settings.use_hierarchical_storage:
            org_adhoc = Path(settings.files_root) / "organizations" / str(organization_id) / "adhoc" / "uploaded"
            if org_adhoc.exists():
                for file in org_adhoc.iterdir():
                    if file.is_file() and file.name.startswith(f"{document_id}_"):
                        return file.name[len(document_id) + 1:]

        # Check organization-specific batch directory if using hierarchical storage
        if organization_id and settings.use_hierarchical_storage:
            org_batch_dir = Path(settings.files_root) / "organizations" / str(organization_id) / "batches"
            if org_batch_dir.exists():
                for batch_path in org_batch_dir.iterdir():
                    if batch_path.is_dir():
                        uploaded_dir = batch_path / "uploaded"
                        if uploaded_dir.exists():
                            for file in uploaded_dir.iterdir():
                                if file.name.startswith(f"{document_id}_"):
                                    return file.name[len(document_id) + 1:]

        # Check flat batch directory
        batch_dir = Path(settings.batch_files_dir)
        if batch_dir.exists():
            for file in batch_dir.iterdir():
                if file.is_file() and file.name.startswith(f"{document_id}_"):
                    return file.name[len(document_id) + 1:]

    except Exception as e:
        logging.getLogger("curatore.jobs").debug(
            f"Could not find original filename for {document_id}: {e}"
        )

    # Fallback to document_id if we can't find the file
    return document_id


JOB_KEY = "job:{job_id}"
DOC_ACTIVE_KEY = "doc:{doc_id}:active_job"
DOC_LAST_KEY = "doc:{doc_id}:last_job"


def _now_ts() -> float:
    return time.time()


def set_active_job(document_id: str, job_id: str, ttl: Optional[int] = None) -> bool:
    r = get_redis_client()
    key = DOC_ACTIVE_KEY.format(doc_id=document_id)
    # NX = only set if not exists
    ok = r.set(key, job_id, nx=True, ex=ttl)
    if ok:
        r.set(DOC_LAST_KEY.format(doc_id=document_id), job_id, ex=max(ttl or 0, int(os.getenv("JOB_STATUS_TTL_SECONDS", "259200"))))
        return True
    return False

def replace_active_job(document_id: str, job_id: str, ttl: Optional[int] = None) -> bool:
    """Replace the existing active job lock value without releasing it.

    Uses Redis XX semantics to only set the value if the key already exists,
    updating the TTL. This is intended to transition a provisional lock (e.g.,
    "PENDING") to the actual job id in a single atomic operation, avoiding the
    delete-then-set race.
    """
    r = get_redis_client()
    key = DOC_ACTIVE_KEY.format(doc_id=document_id)
    ok = r.set(key, job_id, xx=True, ex=ttl)
    if ok:
        r.set(
            DOC_LAST_KEY.format(doc_id=document_id),
            job_id,
            ex=max(ttl or 0, int(os.getenv("JOB_STATUS_TTL_SECONDS", "259200"))),
        )
        return True
    return False


def clear_active_job(document_id: str, job_id: Optional[str] = None):
    r = get_redis_client()
    key = DOC_ACTIVE_KEY.format(doc_id=document_id)
    if job_id:
        try:
            current = r.get(key)
            if current and current.decode() != job_id:
                return
        except Exception:
            pass
    r.delete(key)


def record_job_status(job_id: str, payload: Dict[str, Any], ttl: Optional[int] = None):
    """Merge status payload into existing job record while preserving logs."""
    r = get_redis_client()
    key = JOB_KEY.format(job_id=job_id)
    if ttl is None:
        ttl = int(os.getenv("JOB_STATUS_TTL_SECONDS", "259200"))
    try:
        existing_raw = r.get(key)
        data: Dict[str, Any] = json.loads(existing_raw) if existing_raw else {}
    except Exception:
        data = {}
    # Preserve and merge logs
    existing_logs = data.get("logs", []) if isinstance(data.get("logs"), list) else []
    incoming_logs = payload.get("logs", []) if isinstance(payload.get("logs"), list) else []
    # Shallow merge other fields
    for k, v in payload.items():
        if k == "logs":
            continue
        data[k] = v
    if incoming_logs:
        existing_logs.extend(incoming_logs)
    if existing_logs:
        data["logs"] = existing_logs
    # Always ensure job_id set
    data.setdefault("job_id", job_id)
    r.set(key, json.dumps(data, default=str), ex=ttl)


def append_job_log(job_id: str, level: str, message: str, ts: Optional[str] = None):
    """Append a log entry to the job's log list."""
    r = get_redis_client()
    key = JOB_KEY.format(job_id=job_id)
    try:
        existing_raw = r.get(key)
        data: Dict[str, Any] = json.loads(existing_raw) if existing_raw else {"job_id": job_id}
    except Exception:
        data = {"job_id": job_id}
    logs = data.get("logs") if isinstance(data.get("logs"), list) else []
    entry = {"ts": ts or datetime.utcnow().isoformat(), "level": level, "message": message}
    logs.append(entry)
    data["logs"] = logs
    r.set(key, json.dumps(data, default=str), ex=int(os.getenv("JOB_STATUS_TTL_SECONDS", "259200")))


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    r = get_redis_client()
    raw = r.get(JOB_KEY.format(job_id=job_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def get_active_job_for_document(document_id: str) -> Optional[str]:
    r = get_redis_client()
    val = r.get(DOC_ACTIVE_KEY.format(doc_id=document_id))
    return val.decode() if val else None


def get_last_job_for_document(document_id: str) -> Optional[str]:
    r = get_redis_client()
    val = r.get(DOC_LAST_KEY.format(doc_id=document_id))
    return val.decode() if val else None


def _scan_and_delete(pattern: str) -> int:
    r = get_redis_client()
    total = 0
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor=cursor, match=pattern, count=500)
        if keys:
            total += r.delete(*keys)
        if cursor == 0:
            break
    return total


def clear_all_jobs_and_locks() -> Dict[str, int]:
    """Delete all job status keys and per-document lock/index keys from Redis."""
    deleted_jobs = _scan_and_delete("job:*")
    deleted_active = _scan_and_delete("doc:*:active_job")
    deleted_last = _scan_and_delete("doc:*:last_job")
    return {
        "jobs": deleted_jobs,
        "active_locks": deleted_active,
        "last_job_keys": deleted_last,
    }


# ============================================================================
# DATABASE-BACKED BATCH JOB MANAGEMENT (Phase 2)
# ============================================================================

logger = logging.getLogger("curatore.jobs")


async def create_batch_job(
    organization_id: uuid.UUID,
    user_id: Optional[uuid.UUID],
    document_ids: List[str],
    options: Dict[str, Any],
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Job:
    """
    Create a new batch job for processing multiple documents.

    This method:
    1. Checks organization concurrency limits
    2. Creates job record in database
    3. Creates job_documents entries (bulk insert)
    4. Calculates expires_at based on org retention policy
    5. Returns job object

    Args:
        organization_id: Organization UUID
        user_id: User UUID (nullable for system jobs)
        document_ids: List of document IDs to process
        options: Processing options dict
        name: Optional job name (auto-generated if not provided)
        description: Optional job description

    Returns:
        Job: Created job instance

    Raises:
        ValueError: If concurrency limit exceeded or validation fails
        SQLAlchemyError: Database operation errors
    """
    logger.info(
        f"Creating batch job for org {organization_id} with {len(document_ids)} documents"
    )

    # Check concurrency limit
    can_create, error_msg = await check_concurrency_limit(organization_id)
    if not can_create:
        logger.warning(f"Concurrency limit exceeded for org {organization_id}: {error_msg}")
        raise ValueError(error_msg or "Concurrency limit exceeded")

    # Validate inputs
    if not document_ids:
        raise ValueError("At least one document ID required")

    # Auto-generate name if not provided
    if not name:
        name = f"Batch Job {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"

    # Calculate expiration based on org settings (default 30 days)
    retention_days = await _get_org_retention_days(organization_id)
    expires_at = datetime.utcnow() + timedelta(days=retention_days)

    async with database_service.get_session() as session:
        # Create job record
        job = Job(
            id=uuid.uuid4(),
            organization_id=organization_id,
            user_id=user_id,
            name=name,
            description=description,
            job_type="batch_processing",
            status="PENDING",
            total_documents=len(document_ids),
            completed_documents=0,
            failed_documents=0,
            processing_options=options,
            expires_at=expires_at,
        )
        session.add(job)
        await session.flush()  # Get job.id

        # Create job_documents entries (bulk)
        job_documents = []
        for doc_id in document_ids:
            # Look up original filename from file system
            original_filename = _get_original_filename(doc_id, organization_id)

            job_doc = JobDocument(
                id=uuid.uuid4(),
                job_id=job.id,
                document_id=doc_id,
                filename=original_filename,  # Use original filename
                file_path="",  # Will be updated when task starts
                status="PENDING",
            )
            job_documents.append(job_doc)

        session.add_all(job_documents)

        # Create initial log entry
        log_entry = JobLog(
            id=uuid.uuid4(),
            job_id=job.id,
            level="INFO",
            message=f"Job created with {len(document_ids)} documents",
            log_metadata={"document_count": len(document_ids), "retention_days": retention_days},
        )
        session.add(log_entry)

        await session.commit()
        await session.refresh(job)

        logger.info(f"Created batch job {job.id} with {len(document_ids)} documents, expires {expires_at}")
        return job


async def enqueue_job(job_id: uuid.UUID) -> Dict[str, Any]:
    """
    Enqueue a batch job for processing by creating Celery tasks.

    This method:
    1. Re-checks concurrency limit
    2. Creates Celery tasks for each document
    3. Updates job status to QUEUED
    4. Sets active job locks in Redis
    5. Returns enqueue results

    Args:
        job_id: Job UUID to enqueue

    Returns:
        Dict with enqueue results:
            {
                "job_id": str,
                "status": "QUEUED",
                "task_count": int,
                "celery_batch_id": str
            }

    Raises:
        ValueError: If job not found or already running
        RuntimeError: If enqueueing fails
    """
    logger.info(f"Enqueueing job {job_id}")

    async with database_service.get_session() as session:
        # Get job and documents
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()

        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status not in ["PENDING", "FAILED"]:
            raise ValueError(f"Job {job_id} is already {job.status}, cannot enqueue")

        # Re-check concurrency limit
        can_enqueue, error_msg = await check_concurrency_limit(job.organization_id)
        if not can_enqueue:
            logger.warning(f"Concurrency limit exceeded for job {job_id}: {error_msg}")
            raise ValueError(error_msg or "Concurrency limit exceeded")

        # Get job documents
        result = await session.execute(
            select(JobDocument).where(JobDocument.job_id == job_id)
        )
        job_documents = result.scalars().all()

        # Create Celery tasks for each document
        from ..tasks import process_document_task

        celery_batch_id = str(uuid.uuid4())
        task_count = 0

        for job_doc in job_documents:
            try:
                # Enqueue Celery task
                task = process_document_task.apply_async(
                    args=[job_doc.document_id, job.processing_options],
                    kwargs={"job_id": str(job_id), "job_document_id": str(job_doc.id)},
                )

                # Update job document with Celery task ID
                job_doc.celery_task_id = task.id
                task_count += 1

                # Set Redis lock for backward compatibility
                set_active_job(job_doc.document_id, task.id, ttl=86400)  # 24 hour TTL

            except Exception as e:
                logger.error(f"Failed to enqueue task for document {job_doc.document_id}: {e}")
                job_doc.status = "FAILED"
                job_doc.error_message = f"Failed to enqueue: {str(e)}"

        # Update job status
        job.status = "QUEUED"
        job.queued_at = datetime.utcnow()
        job.celery_batch_id = celery_batch_id

        # Log enqueueing
        log_entry = JobLog(
            id=uuid.uuid4(),
            job_id=job.id,
            level="INFO",
            message=f"Job queued with {task_count} tasks",
            log_metadata={"celery_batch_id": celery_batch_id, "task_count": task_count},
        )
        session.add(log_entry)

        await session.commit()

        logger.info(f"Enqueued job {job_id} with {task_count} tasks, batch ID: {celery_batch_id}")

        return {
            "job_id": str(job.id),
            "status": job.status,
            "task_count": task_count,
            "celery_batch_id": celery_batch_id,
        }


async def cancel_job(job_id: uuid.UUID, user_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
    """
    Cancel a running job and terminate all associated Celery tasks.

    This method:
    1. Verifies job ownership (if user_id provided)
    2. Gets all Celery task IDs
    3. Revokes tasks with terminate=True, signal=SIGKILL
    4. Polls for termination (max 30s)
    5. Updates job status to CANCELLED
    6. Cleans up partial files
    7. Clears Redis locks
    8. Logs cancellation
    9. Returns verification report

    Args:
        job_id: Job UUID to cancel
        user_id: Optional user ID for ownership verification

    Returns:
        Dict with cancellation results:
            {
                "job_id": str,
                "status": "CANCELLED",
                "tasks_revoked": int,
                "tasks_verified_stopped": int,
                "verification_timeout": bool,
                "cancelled_at": str
            }

    Raises:
        ValueError: If job not found or permission denied
        RuntimeError: If cancellation fails
    """
    logger.info(f"Cancelling job {job_id}")

    async with database_service.get_session() as session:
        # Get job
        result = await session.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()

        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Verify ownership if user_id provided
        if user_id and job.user_id and job.user_id != user_id:
            raise ValueError("Permission denied: not job owner")

        if job.status in ["COMPLETED", "CANCELLED"]:
            logger.info(f"Job {job_id} already {job.status}")
            return {
                "job_id": str(job.id),
                "status": job.status,
                "message": f"Job already {job.status}",
            }

        # Get all job documents with Celery task IDs
        result = await session.execute(
            select(JobDocument).where(
                and_(
                    JobDocument.job_id == job_id,
                    JobDocument.celery_task_id.isnot(None),
                    JobDocument.status.in_(["PENDING", "RUNNING"]),
                )
            )
        )
        job_documents = result.scalars().all()

        task_ids = [doc.celery_task_id for doc in job_documents if doc.celery_task_id]

        # Revoke Celery tasks
        from celery import current_app

        tasks_revoked = 0
        for task_id in task_ids:
            try:
                current_app.control.revoke(task_id, terminate=True, signal="SIGKILL")
                tasks_revoked += 1
                logger.debug(f"Revoked task {task_id}")
            except Exception as e:
                logger.error(f"Failed to revoke task {task_id}: {e}")

        # Verify tasks stopped (30s timeout)
        verification_timeout = False
        if task_ids:
            stopped = await verify_tasks_stopped(task_ids, timeout=30)
            verification_timeout = not stopped

        # Update job and documents status
        job.status = "CANCELLED"
        job.cancelled_at = datetime.utcnow()

        for doc in job_documents:
            doc.status = "CANCELLED"
            doc.completed_at = datetime.utcnow()
            # Clear Redis lock
            if doc.document_id:
                clear_active_job(doc.document_id, doc.celery_task_id)

        # Log cancellation
        log_entry = JobLog(
            id=uuid.uuid4(),
            job_id=job.id,
            level="WARNING",
            message=f"Job cancelled by user, {tasks_revoked} tasks revoked",
            log_metadata={
                "tasks_revoked": tasks_revoked,
                "verification_timeout": verification_timeout,
                "cancelled_by": str(user_id) if user_id else None,
            },
        )
        session.add(log_entry)

        await session.commit()

        logger.info(
            f"Cancelled job {job_id}: {tasks_revoked} tasks revoked, "
            f"verification_timeout={verification_timeout}"
        )

        return {
            "job_id": str(job.id),
            "status": "CANCELLED",
            "tasks_revoked": tasks_revoked,
            "tasks_verified_stopped": len(task_ids) if not verification_timeout else 0,
            "verification_timeout": verification_timeout,
            "cancelled_at": job.cancelled_at.isoformat() if job.cancelled_at else None,
        }


async def get_active_job_count(organization_id: uuid.UUID) -> int:
    """
    Get count of active jobs for an organization.

    Active jobs are those with status QUEUED or RUNNING.

    Args:
        organization_id: Organization UUID

    Returns:
        int: Count of active jobs
    """
    async with database_service.get_session() as session:
        result = await session.execute(
            select(func.count(Job.id)).where(
                and_(
                    Job.organization_id == organization_id,
                    Job.status.in_(["QUEUED", "RUNNING"]),
                )
            )
        )
        count = result.scalar() or 0
        return count


async def get_user_active_jobs(user_id: uuid.UUID) -> List[Job]:
    """
    Get list of active jobs for a user.

    Args:
        user_id: User UUID

    Returns:
        List[Job]: List of active jobs
    """
    async with database_service.get_session() as session:
        result = await session.execute(
            select(Job)
            .where(
                and_(
                    Job.user_id == user_id,
                    Job.status.in_(["QUEUED", "RUNNING"]),
                )
            )
            .order_by(Job.created_at.desc())
        )
        jobs = result.scalars().all()
        return list(jobs)


async def get_organization_jobs(
    org_id: uuid.UUID,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Job], int]:
    """
    Get paginated list of jobs for an organization.

    Args:
        org_id: Organization UUID
        status: Optional status filter
        limit: Page size (default 50)
        offset: Offset for pagination (default 0)

    Returns:
        Tuple[List[Job], int]: (jobs list, total count)
    """
    async with database_service.get_session() as session:
        # Build query
        query = select(Job).where(Job.organization_id == org_id)

        if status:
            query = query.where(Job.status == status)

        # Get total count
        count_query = select(func.count(Job.id)).where(Job.organization_id == org_id)
        if status:
            count_query = count_query.where(Job.status == status)

        result = await session.execute(count_query)
        total = result.scalar() or 0

        # Get paginated results
        query = query.order_by(Job.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(query)
        jobs = result.scalars().all()

        return list(jobs), total


async def check_concurrency_limit(organization_id: uuid.UUID) -> Tuple[bool, Optional[str]]:
    """
    Check if organization can create/enqueue a new job.

    Checks against per-org concurrency limit from settings.

    Args:
        organization_id: Organization UUID

    Returns:
        Tuple[bool, Optional[str]]: (can_proceed, error_message)
    """
    # Get org concurrency limit from settings (default 3)
    limit = await _get_org_concurrency_limit(organization_id)

    # Get current active job count
    active_count = await get_active_job_count(organization_id)

    if active_count >= limit:
        return False, f"Concurrency limit reached ({active_count}/{limit} active jobs)"

    return True, None


async def verify_tasks_stopped(task_ids: List[str], timeout: int = 30) -> bool:
    """
    Verify that Celery tasks have actually stopped.

    Polls Celery for task status with timeout.

    Args:
        task_ids: List of Celery task IDs
        timeout: Max wait time in seconds (default 30)

    Returns:
        bool: True if all tasks stopped, False if timeout
    """
    from celery.result import AsyncResult

    start_time = time.time()

    while time.time() - start_time < timeout:
        all_stopped = True

        for task_id in task_ids:
            result = AsyncResult(task_id)
            # Check if task is in terminal state
            if result.state not in ["SUCCESS", "FAILURE", "REVOKED"]:
                all_stopped = False
                break

        if all_stopped:
            logger.info(f"All {len(task_ids)} tasks verified stopped")
            return True

        # Wait a bit before checking again
        await asyncio_sleep(1)

    logger.warning(f"Task verification timeout after {timeout}s")
    return False


async def cleanup_expired_jobs() -> Dict[str, Any]:
    """
    Clean up expired jobs based on retention policy.

    This method:
    1. Finds jobs where expires_at < NOW()
    2. Deletes associated files (if any)
    3. Deletes database records (cascade to job_documents, job_logs)
    4. Returns cleanup stats

    Returns:
        Dict with cleanup statistics:
            {
                "deleted_jobs": int,
                "deleted_files": int,
                "errors": int,
                "completed_at": str
            }
    """
    logger.info("Starting cleanup of expired jobs")

    deleted_jobs = 0
    deleted_files = 0
    errors = 0

    try:
        async with database_service.get_session() as session:
            # Find expired jobs
            result = await session.execute(
                select(Job).where(
                    and_(
                        Job.expires_at.isnot(None),
                        Job.expires_at < datetime.utcnow(),
                        Job.status.in_(["COMPLETED", "FAILED", "CANCELLED"]),
                    )
                )
            )
            expired_jobs = result.scalars().all()

            logger.info(f"Found {len(expired_jobs)} expired jobs to clean up")

            for job in expired_jobs:
                try:
                    # Get job documents for file cleanup
                    result = await session.execute(
                        select(JobDocument).where(JobDocument.job_id == job.id)
                    )
                    job_documents = result.scalars().all()

                    # Delete processed files
                    for doc in job_documents:
                        if doc.processed_file_path:
                            try:
                                file_path = Path(doc.processed_file_path)
                                if file_path.exists():
                                    file_path.unlink()
                                    deleted_files += 1
                            except Exception as e:
                                logger.error(f"Failed to delete file {doc.processed_file_path}: {e}")
                                errors += 1

                    # Delete job (cascades to job_documents and job_logs)
                    await session.delete(job)
                    deleted_jobs += 1

                except Exception as e:
                    logger.error(f"Failed to clean up job {job.id}: {e}")
                    errors += 1

            await session.commit()

    except Exception as e:
        logger.error(f"Cleanup task failed: {e}")
        errors += 1

    result = {
        "deleted_jobs": deleted_jobs,
        "deleted_files": deleted_files,
        "errors": errors,
        "completed_at": datetime.utcnow().isoformat(),
    }

    logger.info(
        f"Cleanup completed: {deleted_jobs} jobs deleted, "
        f"{deleted_files} files deleted, {errors} errors"
    )

    return result


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


async def _get_org_retention_days(organization_id: uuid.UUID) -> int:
    """
    Get job retention days from organization settings.

    Args:
        organization_id: Organization UUID

    Returns:
        int: Retention days (default 30)
    """
    try:
        from ..database.models import Organization

        async with database_service.get_session() as session:
            result = await session.execute(
                select(Organization.settings).where(Organization.id == organization_id)
            )
            settings = result.scalar_one_or_none()

            if settings and isinstance(settings, dict):
                return settings.get("job_retention_days", 30)

    except Exception as e:
        logger.warning(f"Failed to get retention days for org {organization_id}: {e}")

    return 30  # Default


async def _get_org_concurrency_limit(organization_id: uuid.UUID) -> int:
    """
    Get concurrency limit from organization settings.

    Args:
        organization_id: Organization UUID

    Returns:
        int: Concurrency limit (default 3)
    """
    try:
        from ..database.models import Organization

        async with database_service.get_session() as session:
            result = await session.execute(
                select(Organization.settings).where(Organization.id == organization_id)
            )
            settings = result.scalar_one_or_none()

            if settings and isinstance(settings, dict):
                return settings.get("job_concurrency_limit", 3)

    except Exception as e:
        logger.warning(f"Failed to get concurrency limit for org {organization_id}: {e}")

    return 3  # Default


async def asyncio_sleep(seconds: float):
    """Helper to sleep asynchronously."""
    import asyncio

    await asyncio.sleep(seconds)
