# backend/app/api/v1/routers/jobs.py
"""
Job management endpoints for Curatore v2 API (v1).

Provides endpoints for managing batch document processing jobs with
per-organization concurrency limits, retention policies, and detailed tracking.

Endpoints:
    POST /jobs - Create new batch job
    POST /jobs/{job_id}/start - Start a pending job
    POST /jobs/{job_id}/cancel - Cancel running job
    GET /jobs - List organization jobs (paginated, filtered)
    GET /jobs/{job_id} - Get job details
    GET /jobs/{job_id}/logs - Get job logs
    GET /jobs/{job_id}/documents - Get job documents
    DELETE /jobs/{job_id} - Delete job (admin only, terminal states)
    GET /jobs/stats/user - Get user's job statistics
    GET /jobs/stats/organization - Get organization job statistics

Security:
    - All endpoints require authentication
    - Jobs are organization-scoped
    - Users can only see/manage their own jobs (except org_admin)
    - Deletion requires org_admin role and terminal job state
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.v1.models import (
    CancelJobResponse,
    CreateJobRequest,
    JobDetailResponse,
    JobDocumentResponse,
    JobListResponse,
    JobLogResponse,
    JobResponse,
    OrganizationJobStatsResponse,
    UserJobStatsResponse,
)
from app.database.models import Job, JobDocument, JobLog, User
from app.dependencies import get_current_user, require_org_admin
from app.services.database_service import database_service
from app.services.job_service import (
    cancel_job,
    check_concurrency_limit,
    create_batch_job,
    enqueue_job,
    get_active_job_count,
    get_organization_jobs,
    get_user_active_jobs,
)

# Initialize router
router = APIRouter(prefix="/jobs", tags=["Jobs"])

# Initialize logger
logger = logging.getLogger("curatore.api.jobs")


# =========================================================================
# JOB CREATION & MANAGEMENT
# =========================================================================


@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create batch job",
    description="Create a new batch job for processing multiple documents."
)
async def create_job(
    request: CreateJobRequest,
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """
    Create new batch job.

    Creates a batch job for processing multiple documents with specified options.
    Checks organization concurrency limits before creation. Optionally starts
    the job immediately.

    Args:
        request: Job creation details (document IDs, options, etc.)
        current_user: Current authenticated user

    Returns:
        JobResponse: Created job summary

    Raises:
        HTTPException: 409 if concurrency limit exceeded
        HTTPException: 400 if document_ids is empty or invalid

    Example:
        POST /api/v1/jobs
        Authorization: Bearer <token>
        Content-Type: application/json

        {
            "document_ids": ["doc-123", "doc-456"],
            "options": {
                "conversion_threshold": 70,
                "optimize_for_rag": true
            },
            "name": "Q1 Reports Processing",
            "start_immediately": true
        }
    """
    logger.info(
        f"Job creation requested by {current_user.email} "
        f"({len(request.document_ids)} documents)"
    )

    # Check concurrency limit
    can_create, error_msg = await check_concurrency_limit(current_user.organization_id)
    if not can_create:
        logger.warning(f"Concurrency limit exceeded for org {current_user.organization_id}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_msg or "Organization concurrency limit exceeded"
        )

    try:
        # Create job
        job = await create_batch_job(
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            document_ids=request.document_ids,
            options=request.options or {},
            name=request.name,
            description=request.description,
        )

        logger.info(f"Job created: {job.name} (id: {job.id})")

        # Start immediately if requested
        if request.start_immediately:
            enqueue_result = await enqueue_job(job.id)
            logger.info(
                f"Job enqueued: {job.id} "
                f"({enqueue_result['tasks_created']} tasks created)"
            )

        return JobResponse(
            id=str(job.id),
            organization_id=str(job.organization_id),
            user_id=str(job.user_id) if job.user_id else None,
            name=job.name,
            description=job.description,
            job_type=job.job_type,
            status=job.status,
            celery_batch_id=job.celery_batch_id,
            total_documents=job.total_documents,
            completed_documents=job.completed_documents,
            failed_documents=job.failed_documents,
            created_at=job.created_at,
            queued_at=job.queued_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            cancelled_at=job.cancelled_at,
            expires_at=job.expires_at,
            error_message=job.error_message,
        )

    except ValueError as e:
        logger.error(f"Job creation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/{job_id}/start",
    response_model=JobResponse,
    summary="Start job",
    description="Start a pending job that was created without start_immediately."
)
async def start_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> JobResponse:
    """
    Start a pending job.

    Enqueues Celery tasks for all documents in the job. Only works for
    jobs in PENDING status.

    Args:
        job_id: Job UUID
        current_user: Current authenticated user

    Returns:
        JobResponse: Updated job summary

    Raises:
        HTTPException: 404 if job not found
        HTTPException: 409 if job not in PENDING status or concurrency limit exceeded

    Example:
        POST /api/v1/jobs/123e4567-e89b-12d3-a456-426614174000/start
        Authorization: Bearer <token>
    """
    logger.info(f"Job start requested for {job_id} by {current_user.email}")

    async with database_service.get_session() as session:
        # Get job and verify ownership
        result = await session.execute(
            select(Job)
            .where(Job.id == UUID(job_id))
            .where(Job.organization_id == current_user.organization_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found"
            )

        # Verify job owner (or admin)
        if job.user_id and job.user_id != current_user.id and current_user.role != "org_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: not job owner"
            )

        # Check status
        if job.status != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Job cannot be started: status is {job.status}"
            )

        # Check concurrency limit
        can_start, error_msg = await check_concurrency_limit(current_user.organization_id)
        if not can_start:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_msg or "Organization concurrency limit exceeded"
            )

        # Enqueue job
        enqueue_result = await enqueue_job(job.id)
        logger.info(
            f"Job enqueued: {job.id} "
            f"({enqueue_result['tasks_created']} tasks created)"
        )

        # Refresh job to get updated status
        await session.refresh(job)

        return JobResponse(
            id=str(job.id),
            organization_id=str(job.organization_id),
            user_id=str(job.user_id) if job.user_id else None,
            name=job.name,
            description=job.description,
            job_type=job.job_type,
            status=job.status,
            celery_batch_id=job.celery_batch_id,
            total_documents=job.total_documents,
            completed_documents=job.completed_documents,
            failed_documents=job.failed_documents,
            created_at=job.created_at,
            queued_at=job.queued_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            cancelled_at=job.cancelled_at,
            expires_at=job.expires_at,
            error_message=job.error_message,
        )


@router.post(
    "/{job_id}/cancel",
    response_model=CancelJobResponse,
    summary="Cancel job",
    description="Cancel a running job and terminate all associated tasks."
)
async def cancel_job_endpoint(
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> CancelJobResponse:
    """
    Cancel a running job.

    Revokes all Celery tasks with SIGKILL and verifies termination.
    Updates job status to CANCELLED and cleans up partial files.

    Args:
        job_id: Job UUID
        current_user: Current authenticated user

    Returns:
        CancelJobResponse: Cancellation results with verification

    Raises:
        HTTPException: 404 if job not found
        HTTPException: 403 if not job owner and not admin
        HTTPException: 409 if job cannot be cancelled (terminal state)

    Example:
        POST /api/v1/jobs/123e4567-e89b-12d3-a456-426614174000/cancel
        Authorization: Bearer <token>

        Response:
        {
            "job_id": "123e4567-e89b-12d3-a456-426614174000",
            "status": "CANCELLED",
            "tasks_revoked": 10,
            "tasks_stopped": 10,
            "verification_successful": true,
            "message": "Job cancelled successfully"
        }
    """
    logger.info(f"Job cancellation requested for {job_id} by {current_user.email}")

    try:
        # Cancel job (job_service handles verification and ownership)
        cancel_result = await cancel_job(UUID(job_id), current_user.id)

        logger.info(f"Job cancelled: {job_id} ({cancel_result['tasks_revoked']} tasks)")

        return CancelJobResponse(
            job_id=job_id,
            status=cancel_result["status"],
            tasks_revoked=cancel_result["tasks_revoked"],
            tasks_stopped=cancel_result.get("tasks_stopped", 0),
            verification_successful=cancel_result.get("verification_successful", False),
            message=cancel_result.get("message", "Job cancelled"),
            details=cancel_result.get("details"),
        )

    except ValueError as e:
        logger.error(f"Job cancellation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except PermissionError as e:
        logger.error(f"Job cancellation denied: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


# =========================================================================
# JOB RETRIEVAL
# =========================================================================


@router.get(
    "",
    response_model=JobListResponse,
    summary="List jobs",
    description="List organization jobs with pagination and filtering."
)
async def list_jobs(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_user),
) -> JobListResponse:
    """
    List organization jobs.

    Returns paginated list of jobs. Regular users see only their jobs,
    org_admin sees all organization jobs.

    Args:
        status_filter: Filter by status (PENDING, QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED)
        page: Page number (1-indexed)
        page_size: Items per page (max 100)
        current_user: Current authenticated user

    Returns:
        JobListResponse: Paginated job list with total count

    Example:
        GET /api/v1/jobs?status=RUNNING&page=1&page_size=20
        Authorization: Bearer <token>
    """
    logger.info(
        f"Jobs list requested by {current_user.email} "
        f"(status: {status_filter}, page: {page})"
    )

    # Calculate offset
    offset = (page - 1) * page_size

    # Get jobs (service handles org/user filtering based on role)
    jobs, total = await get_organization_jobs(
        organization_id=current_user.organization_id,
        user_id=current_user.id if current_user.role != "org_admin" else None,
        status_filter=status_filter,
        limit=page_size,
        offset=offset,
    )

    logger.info(f"Returning {len(jobs)} jobs (total: {total})")

    # Calculate total pages
    total_pages = (total + page_size - 1) // page_size

    return JobListResponse(
        jobs=[
            JobResponse(
                id=str(job.id),
                organization_id=str(job.organization_id),
                user_id=str(job.user_id) if job.user_id else None,
                name=job.name,
                description=job.description,
                job_type=job.job_type,
                status=job.status,
                celery_batch_id=job.celery_batch_id,
                total_documents=job.total_documents,
                completed_documents=job.completed_documents,
                failed_documents=job.failed_documents,
                created_at=job.created_at,
                queued_at=job.queued_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                cancelled_at=job.cancelled_at,
                expires_at=job.expires_at,
                error_message=job.error_message,
            )
            for job in jobs
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/{job_id}",
    response_model=JobDetailResponse,
    summary="Get job details",
    description="Get detailed job information including documents and recent logs."
)
async def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> JobDetailResponse:
    """
    Get job details.

    Returns comprehensive job information including document statuses
    and recent log entries.

    Args:
        job_id: Job UUID
        current_user: Current authenticated user

    Returns:
        JobDetailResponse: Detailed job information

    Raises:
        HTTPException: 404 if job not found
        HTTPException: 403 if not authorized to view job

    Example:
        GET /api/v1/jobs/123e4567-e89b-12d3-a456-426614174000
        Authorization: Bearer <token>
    """
    logger.info(f"Job details requested for {job_id} by {current_user.email}")

    async with database_service.get_session() as session:
        # Get job
        result = await session.execute(
            select(Job)
            .where(Job.id == UUID(job_id))
            .where(Job.organization_id == current_user.organization_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found"
            )

        # Check authorization (owner or admin)
        if job.user_id and job.user_id != current_user.id and current_user.role != "org_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: not job owner"
            )

        # Get job documents
        doc_result = await session.execute(
            select(JobDocument)
            .where(JobDocument.job_id == job.id)
            .order_by(JobDocument.created_at)
        )
        documents = doc_result.scalars().all()

        # Get recent logs (last 100)
        log_result = await session.execute(
            select(JobLog)
            .where(JobLog.job_id == job.id)
            .order_by(JobLog.timestamp.desc())
            .limit(100)
        )
        logs = log_result.scalars().all()

        return JobDetailResponse(
            id=str(job.id),
            organization_id=str(job.organization_id),
            user_id=str(job.user_id) if job.user_id else None,
            name=job.name,
            description=job.description,
            job_type=job.job_type,
            status=job.status,
            celery_batch_id=job.celery_batch_id,
            total_documents=job.total_documents,
            completed_documents=job.completed_documents,
            failed_documents=job.failed_documents,
            created_at=job.created_at,
            queued_at=job.queued_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            cancelled_at=job.cancelled_at,
            expires_at=job.expires_at,
            error_message=job.error_message,
            documents=[
                JobDocumentResponse(
                    id=str(doc.id),
                    job_id=str(doc.job_id),
                    document_id=doc.document_id,
                    filename=doc.filename,
                    file_path=doc.file_path,
                    file_hash=doc.file_hash,
                    file_size=doc.file_size,
                    status=doc.status,
                    celery_task_id=doc.celery_task_id,
                    conversion_score=doc.conversion_score,
                    quality_scores=doc.quality_scores,
                    is_rag_ready=doc.is_rag_ready,
                    error_message=doc.error_message,
                    created_at=doc.created_at,
                    started_at=doc.started_at,
                    completed_at=doc.completed_at,
                    processing_time_seconds=doc.processing_time_seconds,
                    processed_file_path=doc.processed_file_path,
                )
                for doc in documents
            ],
            recent_logs=[
                JobLogResponse(
                    id=str(log.id),
                    job_id=str(log.job_id),
                    document_id=log.document_id,
                    timestamp=log.timestamp,
                    level=log.level,
                    message=log.message,
                    metadata=log.log_metadata,
                )
                for log in logs
            ],
            processing_options=job.processing_options,
            results_summary=job.results_summary,
        )


@router.get(
    "/{job_id}/logs",
    response_model=List[JobLogResponse],
    summary="Get job logs",
    description="Get paginated job logs."
)
async def get_job_logs(
    job_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=500, description="Items per page"),
    current_user: User = Depends(get_current_user),
) -> List[JobLogResponse]:
    """
    Get job logs.

    Returns paginated log entries for a job, ordered by timestamp descending.

    Args:
        job_id: Job UUID
        page: Page number (1-indexed)
        page_size: Items per page (max 500)
        current_user: Current authenticated user

    Returns:
        List[JobLogResponse]: List of log entries

    Raises:
        HTTPException: 404 if job not found
        HTTPException: 403 if not authorized to view job

    Example:
        GET /api/v1/jobs/123e4567-e89b-12d3-a456-426614174000/logs?page=1&page_size=50
        Authorization: Bearer <token>
    """
    logger.info(f"Job logs requested for {job_id} by {current_user.email}")

    async with database_service.get_session() as session:
        # Verify job exists and user has access
        job_result = await session.execute(
            select(Job)
            .where(Job.id == UUID(job_id))
            .where(Job.organization_id == current_user.organization_id)
        )
        job = job_result.scalar_one_or_none()

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found"
            )

        # Check authorization
        if job.user_id and job.user_id != current_user.id and current_user.role != "org_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: not job owner"
            )

        # Get logs with pagination
        offset = (page - 1) * page_size
        log_result = await session.execute(
            select(JobLog)
            .where(JobLog.job_id == job.id)
            .order_by(JobLog.timestamp.desc())
            .offset(offset)
            .limit(page_size)
        )
        logs = log_result.scalars().all()

        return [
            JobLogResponse(
                id=str(log.id),
                job_id=str(log.job_id),
                document_id=log.document_id,
                timestamp=log.timestamp,
                level=log.level,
                message=log.message,
                metadata=log.log_metadata,
            )
            for log in logs
        ]


@router.get(
    "/{job_id}/documents",
    response_model=List[JobDocumentResponse],
    summary="Get job documents",
    description="Get all documents in a job with their processing status."
)
async def get_job_documents(
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> List[JobDocumentResponse]:
    """
    Get job documents.

    Returns all documents associated with a job and their processing status.

    Args:
        job_id: Job UUID
        current_user: Current authenticated user

    Returns:
        List[JobDocumentResponse]: List of job documents

    Raises:
        HTTPException: 404 if job not found
        HTTPException: 403 if not authorized to view job

    Example:
        GET /api/v1/jobs/123e4567-e89b-12d3-a456-426614174000/documents
        Authorization: Bearer <token>
    """
    logger.info(f"Job documents requested for {job_id} by {current_user.email}")

    async with database_service.get_session() as session:
        # Verify job exists and user has access
        job_result = await session.execute(
            select(Job)
            .where(Job.id == UUID(job_id))
            .where(Job.organization_id == current_user.organization_id)
        )
        job = job_result.scalar_one_or_none()

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found"
            )

        # Check authorization
        if job.user_id and job.user_id != current_user.id and current_user.role != "org_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: not job owner"
            )

        # Get documents
        doc_result = await session.execute(
            select(JobDocument)
            .where(JobDocument.job_id == job.id)
            .order_by(JobDocument.created_at)
        )
        documents = doc_result.scalars().all()

        return [
            JobDocumentResponse(
                id=str(doc.id),
                job_id=str(doc.job_id),
                document_id=doc.document_id,
                filename=doc.filename,
                file_path=doc.file_path,
                file_hash=doc.file_hash,
                file_size=doc.file_size,
                status=doc.status,
                celery_task_id=doc.celery_task_id,
                conversion_score=doc.conversion_score,
                quality_scores=doc.quality_scores,
                is_rag_ready=doc.is_rag_ready,
                error_message=doc.error_message,
                created_at=doc.created_at,
                started_at=doc.started_at,
                completed_at=doc.completed_at,
                processing_time_seconds=doc.processing_time_seconds,
                processed_file_path=doc.processed_file_path,
            )
            for doc in documents
        ]


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete job",
    description="Delete a job and its associated data. Requires org_admin role and terminal state."
)
async def delete_job(
    job_id: str,
    current_user: User = Depends(require_org_admin),
) -> None:
    """
    Delete job.

    Permanently deletes a job and all associated data (documents, logs).
    Only allowed for jobs in terminal states (COMPLETED, FAILED, CANCELLED).

    Args:
        job_id: Job UUID
        current_user: Current user (must be org_admin)

    Raises:
        HTTPException: 403 if user is not org_admin
        HTTPException: 404 if job not found
        HTTPException: 409 if job is not in terminal state

    Example:
        DELETE /api/v1/jobs/123e4567-e89b-12d3-a456-426614174000
        Authorization: Bearer <token>

    Warning:
        This permanently deletes the job and all associated data.
        Files are not deleted (managed by separate cleanup task).
    """
    logger.info(f"Job deletion requested for {job_id} by {current_user.email}")

    async with database_service.get_session() as session:
        # Get job
        result = await session.execute(
            select(Job)
            .where(Job.id == UUID(job_id))
            .where(Job.organization_id == current_user.organization_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found"
            )

        # Check terminal state
        terminal_states = ["COMPLETED", "FAILED", "CANCELLED"]
        if job.status not in terminal_states:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Job cannot be deleted: status is {job.status}. "
                       "Only terminal states (COMPLETED, FAILED, CANCELLED) can be deleted."
            )

        # Delete job (cascades to job_documents and job_logs)
        await session.delete(job)
        await session.commit()

        logger.info(f"Job deleted: {job.name} (id: {job_id})")


# =========================================================================
# JOB STATISTICS
# =========================================================================


@router.get(
    "/stats/user",
    response_model=UserJobStatsResponse,
    summary="Get user job statistics",
    description="Get job statistics for the current user."
)
async def get_user_stats(
    current_user: User = Depends(get_current_user),
) -> UserJobStatsResponse:
    """
    Get user job statistics.

    Returns job counts by status for the current user.

    Args:
        current_user: Current authenticated user

    Returns:
        UserJobStatsResponse: User's job statistics

    Example:
        GET /api/v1/jobs/stats/user
        Authorization: Bearer <token>

        Response:
        {
            "user_id": "123e4567-e89b-12d3-a456-426614174000",
            "active_jobs": 2,
            "queued_jobs": 1,
            "total_jobs": 45,
            "completed_jobs": 38,
            "failed_jobs": 3,
            "cancelled_jobs": 2
        }
    """
    logger.info(f"User job stats requested by {current_user.email}")

    # Get active jobs for user
    active_jobs_list = await get_user_active_jobs(current_user.id)

    async with database_service.get_session() as session:
        # Count jobs by status
        base_query = select(Job).where(Job.user_id == current_user.id)

        # Total jobs
        total_result = await session.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total_jobs = total_result.scalar() or 0

        # Completed jobs
        completed_result = await session.execute(
            select(func.count()).select_from(
                base_query.where(Job.status == "COMPLETED").subquery()
            )
        )
        completed_jobs = completed_result.scalar() or 0

        # Failed jobs
        failed_result = await session.execute(
            select(func.count()).select_from(
                base_query.where(Job.status == "FAILED").subquery()
            )
        )
        failed_jobs = failed_result.scalar() or 0

        # Cancelled jobs
        cancelled_result = await session.execute(
            select(func.count()).select_from(
                base_query.where(Job.status == "CANCELLED").subquery()
            )
        )
        cancelled_jobs = cancelled_result.scalar() or 0

        # Queued jobs
        queued_result = await session.execute(
            select(func.count()).select_from(
                base_query.where(Job.status == "QUEUED").subquery()
            )
        )
        queued_jobs = queued_result.scalar() or 0

        return UserJobStatsResponse(
            user_id=str(current_user.id),
            active_jobs=len(active_jobs_list),
            queued_jobs=queued_jobs,
            total_jobs=total_jobs,
            completed_jobs=completed_jobs,
            failed_jobs=failed_jobs,
            cancelled_jobs=cancelled_jobs,
        )


@router.get(
    "/stats/organization",
    response_model=OrganizationJobStatsResponse,
    summary="Get organization job statistics",
    description="Get job statistics for the organization. Requires org_admin role."
)
async def get_org_stats(
    current_user: User = Depends(require_org_admin),
) -> OrganizationJobStatsResponse:
    """
    Get organization job statistics.

    Returns job counts and metrics for the entire organization.
    Only accessible to org_admin users.

    Args:
        current_user: Current user (must be org_admin)

    Returns:
        OrganizationJobStatsResponse: Organization job statistics

    Raises:
        HTTPException: 403 if user is not org_admin

    Example:
        GET /api/v1/jobs/stats/organization
        Authorization: Bearer <token>

        Response:
        {
            "organization_id": "123e4567-e89b-12d3-a456-426614174000",
            "active_jobs": 5,
            "queued_jobs": 3,
            "concurrency_limit": 10,
            "total_jobs": 245,
            "completed_jobs": 220,
            "failed_jobs": 15,
            "cancelled_jobs": 5,
            "total_documents_processed": 15340
        }
    """
    logger.info(f"Organization job stats requested by {current_user.email}")

    # Get active job count
    active_count = await get_active_job_count(current_user.organization_id)

    async with database_service.get_session() as session:
        # Count jobs by status
        base_query = select(Job).where(Job.organization_id == current_user.organization_id)

        # Total jobs
        total_result = await session.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total_jobs = total_result.scalar() or 0

        # Completed jobs
        completed_result = await session.execute(
            select(func.count()).select_from(
                base_query.where(Job.status == "COMPLETED").subquery()
            )
        )
        completed_jobs = completed_result.scalar() or 0

        # Failed jobs
        failed_result = await session.execute(
            select(func.count()).select_from(
                base_query.where(Job.status == "FAILED").subquery()
            )
        )
        failed_jobs = failed_result.scalar() or 0

        # Cancelled jobs
        cancelled_result = await session.execute(
            select(func.count()).select_from(
                base_query.where(Job.status == "CANCELLED").subquery()
            )
        )
        cancelled_jobs = cancelled_result.scalar() or 0

        # Queued jobs
        queued_result = await session.execute(
            select(func.count()).select_from(
                base_query.where(Job.status == "QUEUED").subquery()
            )
        )
        queued_jobs = queued_result.scalar() or 0

        # Total documents processed (sum of completed_documents across all jobs)
        docs_result = await session.execute(
            select(func.sum(Job.completed_documents)).select_from(base_query.subquery())
        )
        total_documents = docs_result.scalar() or 0

        # Get concurrency limit from organization settings
        # TODO: This should come from organization.settings once that's implemented
        # For now, use environment variable default
        from app.config import settings
        concurrency_limit = int(settings.default_job_concurrency_limit)

        return OrganizationJobStatsResponse(
            organization_id=str(current_user.organization_id),
            active_jobs=active_count,
            queued_jobs=queued_jobs,
            concurrency_limit=concurrency_limit,
            total_jobs=total_jobs,
            completed_jobs=completed_jobs,
            failed_jobs=failed_jobs,
            cancelled_jobs=cancelled_jobs,
            total_documents_processed=total_documents,
        )
