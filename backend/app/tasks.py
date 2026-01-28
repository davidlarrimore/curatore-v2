"""
Celery tasks wrapping the existing document processing pipeline.

REQUIRES object storage (S3/MinIO) - no filesystem fallback.

Object Storage Mode (REQUIRED):
- artifact_id is REQUIRED for all processing tasks
- Source files are downloaded from object storage to temporary directory
- Processed results are uploaded back to object storage
- Artifact records are created in the database for tracking
- Task fails if artifact_id is not provided
- S3 lifecycle policies handle file retention and cleanup
"""
import asyncio
import logging
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

from celery import shared_task, Task
from sqlalchemy import select, and_

from .services.document_service import document_service
from .services.storage_service import storage_service
from .services.job_service import (
    record_job_status,
    clear_active_job,
    append_job_log,
)
from .services.database_service import database_service
from .services.extraction_orchestrator import extraction_orchestrator
from .database.models import Job, JobDocument, JobLog
from .config import settings


class BaseTask(Task):
    def on_success(self, retval: Any, task_id: str, args: Any, kwargs: Any):
        try:
            # Legacy Redis tracking
            record_job_status(task_id, {
                "job_id": task_id,
                "document_id": kwargs.get("document_id") or (args[0] if args else None),
                "status": "SUCCESS",
                "finished_at": datetime.utcnow().isoformat(),
                "result": retval,
            })

            # Database job tracking (Phase 2+)
            job_document_id = kwargs.get("job_document_id")
            if job_document_id:
                asyncio.run(_update_job_document_success(job_document_id, retval))
        finally:
            doc_id = kwargs.get("document_id") or (args[0] if args else None)
            if doc_id:
                clear_active_job(doc_id, task_id)

    def on_failure(self, exc: Exception, task_id: str, args: Any, kwargs: Any, einfo):
        try:
            # Legacy Redis tracking
            record_job_status(task_id, {
                "job_id": task_id,
                "document_id": kwargs.get("document_id") or (args[0] if args else None),
                "status": "FAILURE",
                "finished_at": datetime.utcnow().isoformat(),
                "error": str(exc),
            })

            # Database job tracking (Phase 2+)
            job_document_id = kwargs.get("job_document_id")
            if job_document_id:
                asyncio.run(_update_job_document_failure(job_document_id, str(exc)))
        finally:
            doc_id = kwargs.get("document_id") or (args[0] if args else None)
            if doc_id:
                clear_active_job(doc_id, task_id)


@shared_task(bind=True, base=BaseTask, autoretry_for=(), retry_backoff=True, retry_kwargs={"max_retries": 0})
def process_document_task(
    self,
    document_id: str,
    options: Dict[str, Any],
    file_path: Optional[str] = None,
    job_id: Optional[str] = None,
    job_document_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Process a document with optional job tracking.

    REQUIRES object storage (S3/MinIO) - artifact_id is mandatory.

    Processing flow:
    - Downloads source file from object storage using artifact_id
    - Processes document through extraction and quality evaluation pipeline
    - Uploads processed result back to object storage
    - Creates artifact records in database for tracking

    Args:
        document_id: Document ID to process
        options: Processing options dict
        file_path: Deprecated (object storage uses artifact_id)
        job_id: Optional job ID for database tracking
        job_document_id: Optional job document ID for database tracking
        artifact_id: REQUIRED - artifact ID for object storage download
        organization_id: Optional organization ID for multi-tenant isolation

    Returns:
        Dict with processing result including markdown content and quality scores

    Raises:
        RuntimeError: If artifact_id is not provided
        RuntimeError: If file cannot be downloaded from object storage
    """
    # Legacy Redis tracking
    record_job_status(self.request.id, {
        "job_id": self.request.id,
        "document_id": document_id,
        "status": "STARTED",
        "started_at": datetime.utcnow().isoformat(),
    })

    append_job_log(self.request.id, "info", f"Job started for document '{document_id}'")

    # Database job tracking (Phase 2+)
    if job_document_id:
        asyncio.run(_update_job_document_started(job_document_id, self.request.id, document_id, file_path))
    # Prepare domain options from incoming API shape
    from .api.v1.models import V1ProcessingOptions, V1ProcessingResult
    domain_options = V1ProcessingOptions(**(options or {})).to_domain()

    logger = logging.getLogger("curatore.api")
    # Log which extraction engine will be used
    try:
        engine = (domain_options.extraction_engine or "extraction-service").lower()
        has_docling = bool(getattr(document_service, "docling_base", None))
        has_extraction = bool(getattr(document_service, "extract_base", None))

        if engine == "docling":
            base = getattr(document_service, "docling_base", "").rstrip("/")
            path = "/v1/convert/file"
            timeout = getattr(document_service, "docling_timeout", 60)
            if has_docling:
                append_job_log(self.request.id, "info", f"Extractor: Docling at {base}{path} (timeout {timeout}s)")
                try:
                    logger.info("Extractor selected: Docling %s%s (timeout %ss)", base, path, timeout)
                except Exception:
                    pass
            else:
                append_job_log(self.request.id, "warning", "Extractor: Docling selected (not configured)")
        elif engine in {"default", "extraction", "extraction-service", "legacy"}:
            base = getattr(document_service, "extract_base", "")
            timeout = getattr(document_service, "extract_timeout", 60)
            if has_extraction:
                append_job_log(self.request.id, "info", f"Extractor: extraction-service at {base} (timeout {timeout}s)")
                try:
                    logger.info("Extractor selected: extraction-service %s (timeout %ss)", base, timeout)
                except Exception:
                    pass
            else:
                append_job_log(self.request.id, "warning", "Extractor: extraction-service selected (not configured)")
        elif engine == "none":
            append_job_log(self.request.id, "info", "Extractor: none (no external extraction)")
        else:
            append_job_log(self.request.id, "warning", f"Extractor: unsupported selection '{engine}'")
    except Exception:
        # Non-fatal; continue processing
        pass

    # Locate file: object storage REQUIRED
    resolved_path = None
    temp_dir = None  # Track temp directory for cleanup

    # Enforce artifact_id requirement
    if not artifact_id:
        append_job_log(self.request.id, "error", "Missing artifact_id - object storage is required")
        raise RuntimeError("artifact_id is required for object storage")

    # Download from object storage
    try:
        append_job_log(self.request.id, "info", f"Fetching file from object storage (artifact={artifact_id[:8]}...)")
        resolved_path, temp_dir = asyncio.run(_fetch_from_object_storage(artifact_id))
        if resolved_path:
            append_job_log(self.request.id, "info", f"Downloaded file to temp: {resolved_path.name}")
        else:
            append_job_log(self.request.id, "error", "Failed to download file from object storage")
            raise RuntimeError("Failed to download file from object storage")
    except Exception as e:
        append_job_log(self.request.id, "error", f"Object storage fetch failed: {e}")
        raise

    # Get organization_id from parameter or job if available (for connection resolution and storage uploads)
    org_id_resolved = organization_id  # Use parameter if provided
    if not org_id_resolved and (job_document_id or job_id):
        async def _get_organization_id():
            async with database_service.get_session() as session:
                if job_document_id:
                    # Get organization_id from JobDocument -> Job
                    result = await session.execute(
                        select(Job.organization_id)
                        .join(JobDocument, JobDocument.job_id == Job.id)
                        .where(JobDocument.id == job_document_id)
                    )
                    return result.scalar_one_or_none()
                elif job_id:
                    # Get organization_id directly from Job
                    result = await session.execute(
                        select(Job.organization_id).where(Job.id == job_id)
                    )
                    return result.scalar_one_or_none()
                return None

        try:
            org_id_resolved = asyncio.run(_get_organization_id())
        except Exception as e:
            logging.getLogger("curatore.tasks").warning(f"Failed to get organization_id: {e}")

    # Run the existing async pipeline with organization context
    try:
        append_job_log(self.request.id, "info", "Conversion started")

        async def _process_with_session():
            async with database_service.get_session() as session:
                return await document_service.process_document(
                    document_id,
                    resolved_path,
                    domain_options,
                    organization_id=org_id_resolved,
                    session=session
                )

        result = asyncio.run(_process_with_session())
        # Post-extraction confirmation log: which extractor actually produced content
        try:
            meta = getattr(result, 'processing_metadata', {}) or {}
            ex = meta.get('extractor') if isinstance(meta, dict) else None
            if isinstance(ex, dict) and ex:
                eng = ex.get('engine') or ex.get('requested_engine') or 'unknown'
                url = ex.get('url') or ''
                ok = ex.get('ok')
                err = ex.get('error')
                status_txt = "ok" if ok else f"failed{f': {err}' if err else ''}"
                msg = f"Extractor used: {eng}{' - ' + url if url else ''} ({status_txt})"
                append_job_log(self.request.id, "info", msg)
                if err:
                    append_job_log(self.request.id, "warning", f"Extractor error detail: {err}")
                # Docling-specific status/error reporting for Processing Panel visibility
                if eng == 'docling':
                    status_txt = ex.get('status')
                    errors_list = ex.get('errors') or []
                    ptime = ex.get('processing_time')
                    if status_txt:
                        append_job_log(self.request.id, "info", f"Docling status: {status_txt}{f', time: {ptime:.2f}s' if isinstance(ptime, (int, float)) else ''}")
                    if isinstance(errors_list, list) and errors_list:
                        first_err = errors_list[0]
                        append_job_log(self.request.id, "warning", f"Docling reported {len(errors_list)} error(s); first: {first_err}")
        except Exception:
            pass
        if result and getattr(result, 'conversion_result', None):
            append_job_log(self.request.id, "success", f"Conversion complete (score {result.conversion_result.conversion_score}/100)")
        append_job_log(self.request.id, "success", "Completed processing")

        # Persist result via storage service (so existing endpoints work)
        storage_service.save_processing_result(result)

        # Upload processed result to object storage if enabled
        if settings.use_object_storage and org_id_resolved and result:
            try:
                # Get markdown content from result attributes or read from file
                markdown_content = getattr(result, 'optimized_markdown', None) or getattr(result, 'markdown', None)

                # If not in memory, read from the markdown_path
                if not markdown_content and hasattr(result, 'markdown_path') and result.markdown_path:
                    markdown_path = Path(result.markdown_path)
                    if markdown_path.exists():
                        markdown_content = markdown_path.read_text(encoding='utf-8')

                if markdown_content:
                    append_job_log(self.request.id, "info", "Uploading processed result to object storage...")
                    original_filename = resolved_path.name if resolved_path else f"{document_id}.txt"
                    processed_artifact_id = asyncio.run(
                        _upload_processed_to_object_storage(
                            document_id=document_id,
                            organization_id=str(org_id_resolved),
                            markdown_content=markdown_content,
                            original_filename=original_filename,
                            job_id=job_id,
                        )
                    )
                    if processed_artifact_id:
                        append_job_log(self.request.id, "info", f"Uploaded to storage (artifact={processed_artifact_id[:8]}...)")
                else:
                    append_job_log(self.request.id, "warning", "No markdown content available to upload to object storage")
            except Exception as e:
                # Log but don't fail - filesystem result is already saved
                append_job_log(self.request.id, "warning", f"Object storage upload failed: {e}")
                logging.getLogger("curatore.tasks").warning(f"Object storage upload failed: {e}")

        # Return a JSON-serializable V1ProcessingResult dict
        return V1ProcessingResult.model_validate(result).model_dump()
    except Exception as e:
        append_job_log(self.request.id, "error", f"Processing error: {str(e)}")
        raise
    finally:
        # Clean up temp directory if we downloaded from object storage
        if temp_dir:
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass


@shared_task(bind=True, base=BaseTask, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def update_document_content_task(self, document_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    # payload: { content, options, improvement_prompt, apply_vector_optimization }
    record_job_status(self.request.id, {
        "job_id": self.request.id,
        "document_id": document_id,
        "status": "STARTED",
        "started_at": datetime.utcnow().isoformat(),
    })

    from .api.v1.models import V1ProcessingOptions, V1ProcessingResult

    options_dict = payload.get("options") or {}
    content = payload.get("content") or ""
    improvement_prompt = payload.get("improvement_prompt")
    apply_vector_optimization = bool(payload.get("apply_vector_optimization") or False)

    domain_options = V1ProcessingOptions(**options_dict).to_domain()

    try:
        append_job_log(self.request.id, "info", "Content update started")
        result = asyncio.run(
            document_service.update_document_content(
                document_id=document_id,
                content=content,
                options=domain_options,
                improvement_prompt=improvement_prompt,
                apply_vector_optimization=apply_vector_optimization,
            )
        )
        if not result:
            append_job_log(self.request.id, "error", "Document not found or update failed")
            raise RuntimeError("Document not found or update failed")
        append_job_log(self.request.id, "success", "Content saved and re-evaluated")
        append_job_log(self.request.id, "success", "Update complete")
    except Exception as e:
        append_job_log(self.request.id, "error", f"Update failed: {str(e)}")
        raise

    storage_service.save_processing_result(result)
    return V1ProcessingResult.model_validate(result).model_dump()


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

@shared_task(bind=True)
def cleanup_expired_jobs_task(self, dry_run: bool = False) -> Dict[str, Any]:
    """
    Scheduled task for cleaning up expired jobs.

    This task runs daily (default: 3 AM UTC) to delete jobs that have exceeded
    their retention period based on organization settings.

    Args:
        dry_run: If True, only report what would be deleted without actual deletion

    Returns:
        Dict with cleanup statistics:
            {
                "deleted_jobs": int,
                "deleted_files": int,
                "errors": int,
                "completed_at": str
            }
    """
    from .services.job_service import cleanup_expired_jobs

    logger = logging.getLogger("curatore.jobs")
    logger.info(f"Starting scheduled job cleanup task (dry_run={dry_run})")

    try:
        if dry_run:
            logger.info("[DRY RUN] Would execute job cleanup (not implemented)")
            return {
                "deleted_jobs": 0,
                "deleted_files": 0,
                "errors": 0,
                "completed_at": datetime.utcnow().isoformat(),
                "dry_run": True,
            }

        result = asyncio.run(cleanup_expired_jobs())

        logger.info(
            f"Job cleanup completed: deleted {result['deleted_jobs']} jobs, "
            f"{result['deleted_files']} files, {result['errors']} errors"
        )

        return result

    except Exception as e:
        logger.error(f"Error in job cleanup task: {e}")
        raise


# ============================================================================
# OBJECT STORAGE HELPERS (Phase 6)
# ============================================================================

async def _fetch_from_object_storage(artifact_id: str) -> tuple[Optional[Path], Optional[Path]]:
    """
    Download a file from object storage to a temporary directory.

    Args:
        artifact_id: Artifact UUID string

    Returns:
        Tuple of (file_path, temp_dir_path) - temp_dir should be cleaned up after use
        Returns (None, None) if artifact not found or download fails
    """
    from .services.minio_service import get_minio_service
    from .services.artifact_service import artifact_service

    minio = get_minio_service()
    if not minio:
        logger = logging.getLogger("curatore.tasks")
        logger.warning("Object storage not enabled, cannot fetch artifact")
        return None, None

    async with database_service.get_session() as session:
        artifact = await artifact_service.get_artifact(session, uuid.UUID(artifact_id))
        if not artifact:
            logger = logging.getLogger("curatore.tasks")
            logger.warning(f"Artifact {artifact_id} not found in database")
            return None, None

        # Download object content using get_object which returns BytesIO
        try:
            content_io = minio.get_object(artifact.bucket, artifact.object_key)
            content = content_io.getvalue()  # Get bytes from BytesIO
        except Exception as e:
            logger = logging.getLogger("curatore.tasks")
            logger.error(f"Failed to download artifact {artifact_id}: {e}")
            return None, None

        # Write to temp directory
        temp_dir = Path(tempfile.mkdtemp(prefix="curatore_storage_"))
        temp_file = temp_dir / artifact.original_filename
        temp_file.write_bytes(content)

        return temp_file, temp_dir


async def _upload_processed_to_object_storage(
    document_id: str,
    organization_id: str,
    markdown_content: str,
    original_filename: str,
    job_id: Optional[str] = None,
) -> Optional[str]:
    """
    Upload processed markdown content to object storage.

    Args:
        document_id: Document identifier
        organization_id: Organization UUID string
        markdown_content: Processed markdown content
        original_filename: Original source filename
        job_id: Optional job UUID string

    Returns:
        Artifact ID string if successful, None on failure
    """
    from io import BytesIO
    from .services.minio_service import get_minio_service
    from .services.artifact_service import artifact_service
    from .database.models import Job

    minio = get_minio_service()
    if not minio:
        logger = logging.getLogger("curatore.tasks")
        logger.warning("Object storage not enabled, cannot upload processed result")
        return None

    def _slugify(value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9-_]+", "-", value.strip())
        return cleaned.strip("-").lower()

    job_folder = None
    if job_id:
        try:
            async with database_service.get_session() as session:
                result = await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
                job = result.scalar_one_or_none()
                if job:
                    job_folder = job.processed_folder
        except Exception:
            job_folder = None

    if not job_folder:
        slug = _slugify(f"job-{job_id}" if job_id else "job")
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        job_folder = f"{slug}_{ts}"

    # Build object key: org_id/{job_name_timestamp}/filename.md
    base_filename = Path(original_filename).stem
    safe_document_id = _slugify(document_id) or "document"
    processed_filename = f"{safe_document_id}_{base_filename}.md"
    object_key = f"{organization_id}/{job_folder}/{processed_filename}"
    bucket = minio.bucket_processed

    try:
        # Upload content
        content_bytes = markdown_content.encode("utf-8")
        data_stream = BytesIO(content_bytes)
        etag = minio.put_object(
            bucket=bucket,
            key=object_key,
            data=data_stream,
            length=len(content_bytes),
            content_type="text/markdown",
        )

        # Create artifact record
        async with database_service.get_session() as session:
            artifact = await artifact_service.create_artifact(
                session=session,
                organization_id=uuid.UUID(organization_id),
                document_id=document_id,
                artifact_type="processed",
                bucket=bucket,
                object_key=object_key,
                original_filename=processed_filename,
                content_type="text/markdown",
                file_size=len(content_bytes),
                etag=etag,
                job_id=uuid.UUID(job_id) if job_id else None,
                status="available",
            )
            await session.commit()
            return str(artifact.id)

    except Exception as e:
        logger = logging.getLogger("curatore.tasks")
        logger.error(f"Failed to upload processed result: {e}")
        return None


# ============================================================================
# JOB DOCUMENT TRACKING HELPERS (Phase 2)
# ============================================================================

async def _update_job_document_started(
    job_document_id: str,
    celery_task_id: str,
    document_id: str,
    file_path: Optional[str] = None,
) -> None:
    """
    Update job document status to RUNNING when task starts.

    Args:
        job_document_id: JobDocument UUID
        celery_task_id: Celery task ID
        document_id: Document ID
        file_path: Optional file path
    """
    try:
        async with database_service.get_session() as session:
            result = await session.execute(
                select(JobDocument).where(JobDocument.id == uuid.UUID(job_document_id))
            )
            job_doc = result.scalar_one_or_none()

            if job_doc:
                job_doc.status = "RUNNING"
                job_doc.started_at = datetime.utcnow()
                job_doc.celery_task_id = celery_task_id

                # Update file info if available
                if file_path:
                    from pathlib import Path
                    p = Path(file_path)
                    job_doc.file_path = str(p)

                    # Extract original filename from pattern: {document_id}_{original_filename}
                    # Only update if the current filename is just the document_id (initial placeholder)
                    if job_doc.filename == document_id:
                        filename = p.name
                        if filename.startswith(f"{document_id}_"):
                            # Extract original filename by removing the document_id prefix
                            job_doc.filename = filename[len(document_id) + 1:]
                        else:
                            job_doc.filename = filename

                    if p.exists():
                        job_doc.file_size = p.stat().st_size

                # Log start
                log_entry = JobLog(
                    id=uuid.uuid4(),
                    job_id=job_doc.job_id,
                    document_id=document_id,
                    level="INFO",
                    message=f"Document processing started: {document_id}",
                    log_metadata={"celery_task_id": celery_task_id},
                )
                session.add(log_entry)

                await session.commit()

                # Update job status to RUNNING if still QUEUED
                await _update_job_status_if_needed(job_doc.job_id)

    except Exception as e:
        logging.getLogger("curatore.jobs").error(
            f"Failed to update job document started: {e}"
        )


async def _update_job_document_success(
    job_document_id: str, result: Dict[str, Any]
) -> None:
    """
    Update job document status to COMPLETED on success.

    Args:
        job_document_id: JobDocument UUID
        result: Processing result dict
    """
    from sqlalchemy import update as sql_update

    try:
        async with database_service.get_session() as session:
            result_obj = await session.execute(
                select(JobDocument).where(JobDocument.id == uuid.UUID(job_document_id))
            )
            job_doc = result_obj.scalar_one_or_none()

            if job_doc:
                job_doc.status = "COMPLETED"
                job_doc.completed_at = datetime.utcnow()

                # Calculate processing time
                if job_doc.started_at:
                    processing_time = (job_doc.completed_at - job_doc.started_at).total_seconds()
                    job_doc.processing_time_seconds = processing_time

                # Extract quality metrics from result
                if result and isinstance(result, dict):
                    conversion_result = result.get("conversion_result", {})
                    if isinstance(conversion_result, dict):
                        job_doc.conversion_score = conversion_result.get("conversion_score")

                    quality_scores = result.get("llm_evaluation", {})
                    if isinstance(quality_scores, dict):
                        job_doc.quality_scores = quality_scores

                    # Store processed file path
                    if result.get("markdown_path"):
                        job_doc.processed_file_path = result["markdown_path"]

                # Log success
                log_entry = JobLog(
                    id=uuid.uuid4(),
                    job_id=job_doc.job_id,
                    document_id=job_doc.document_id,
                    level="SUCCESS",
                    message=f"Document processed successfully: {job_doc.document_id}",
                    log_metadata={
                        "conversion_score": job_doc.conversion_score,
                    },
                )
                session.add(log_entry)

                job_id = job_doc.job_id

                # Use atomic SQL increment to prevent race conditions
                # This ensures concurrent workers don't lose increments
                await session.execute(
                    sql_update(Job)
                    .where(Job.id == job_id)
                    .values(completed_documents=Job.completed_documents + 1)
                )
                await session.commit()

                # Check if job is complete
                await _check_job_completion(job_id)

    except Exception as e:
        logging.getLogger("curatore.jobs").error(
            f"Failed to update job document success: {e}"
        )


async def _update_job_document_failure(
    job_document_id: str, error_message: str
) -> None:
    """
    Update job document status to FAILED on error.

    Args:
        job_document_id: JobDocument UUID
        error_message: Error message
    """
    from sqlalchemy import update as sql_update

    try:
        async with database_service.get_session() as session:
            result = await session.execute(
                select(JobDocument).where(JobDocument.id == uuid.UUID(job_document_id))
            )
            job_doc = result.scalar_one_or_none()

            if job_doc:
                job_doc.status = "FAILED"
                job_doc.completed_at = datetime.utcnow()
                job_doc.error_message = error_message

                # Calculate processing time
                if job_doc.started_at:
                    processing_time = (job_doc.completed_at - job_doc.started_at).total_seconds()
                    job_doc.processing_time_seconds = processing_time

                # Log failure
                log_entry = JobLog(
                    id=uuid.uuid4(),
                    job_id=job_doc.job_id,
                    document_id=job_doc.document_id,
                    level="ERROR",
                    message=f"Document processing failed: {job_doc.document_id}",
                    log_metadata={"error": error_message},
                )
                session.add(log_entry)

                job_id = job_doc.job_id

                # Use atomic SQL increment to prevent race conditions
                # This ensures concurrent workers don't lose increments
                await session.execute(
                    sql_update(Job)
                    .where(Job.id == job_id)
                    .values(failed_documents=Job.failed_documents + 1)
                )
                await session.commit()

                # Check if job is complete
                await _check_job_completion(job_id)

    except Exception as e:
        logging.getLogger("curatore.jobs").error(
            f"Failed to update job document failure: {e}"
        )


async def _update_job_status_if_needed(job_id: uuid.UUID) -> None:
    """
    Update job status to RUNNING if it's still QUEUED and has started documents.

    Args:
        job_id: Job UUID
    """
    try:
        async with database_service.get_session() as session:
            result = await session.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()

            if job and job.status == "QUEUED":
                job.status = "RUNNING"
                job.started_at = datetime.utcnow()

                log_entry = JobLog(
                    id=uuid.uuid4(),
                    job_id=job.id,
                    level="INFO",
                    message="Job processing started",
                )
                session.add(log_entry)

                await session.commit()

    except Exception as e:
        logging.getLogger("curatore.jobs").error(
            f"Failed to update job status: {e}"
        )


async def _check_job_completion(job_id: uuid.UUID) -> None:
    """
    Check if all documents in a job are complete and update job status accordingly.

    Uses actual document status counts rather than relying solely on job counters
    to handle race conditions and ensure accuracy.

    Args:
        job_id: Job UUID
    """
    from sqlalchemy import func, and_
    from sqlalchemy import update as sql_update

    try:
        async with database_service.get_session() as session:
            # Get job
            result = await session.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()

            if not job:
                return

            # If job is already in terminal state, skip
            if job.status in ["COMPLETED", "FAILED", "CANCELLED"]:
                return

            # Count actual document statuses from job_documents table
            # This is more reliable than counters in case of race conditions
            completed_count_result = await session.execute(
                select(func.count(JobDocument.id)).where(
                    and_(
                        JobDocument.job_id == job_id,
                        JobDocument.status == "COMPLETED"
                    )
                )
            )
            actual_completed = completed_count_result.scalar() or 0

            failed_count_result = await session.execute(
                select(func.count(JobDocument.id)).where(
                    and_(
                        JobDocument.job_id == job_id,
                        JobDocument.status == "FAILED"
                    )
                )
            )
            actual_failed = failed_count_result.scalar() or 0

            # Reconcile counters if they're out of sync
            if job.completed_documents != actual_completed or job.failed_documents != actual_failed:
                logging.getLogger("curatore.jobs").warning(
                    f"Job {job_id} counter mismatch: "
                    f"counters=({job.completed_documents}/{job.failed_documents}), "
                    f"actual=({actual_completed}/{actual_failed}). Reconciling."
                )
                await session.execute(
                    sql_update(Job)
                    .where(Job.id == job_id)
                    .values(
                        completed_documents=actual_completed,
                        failed_documents=actual_failed
                    )
                )
                # Refresh job to get updated values
                await session.refresh(job)

            # Check if all documents are complete using actual counts
            total_done = actual_completed + actual_failed
            if total_done >= job.total_documents:
                # Job is complete
                if actual_failed > 0 and actual_completed == 0:
                    # All failed
                    job.status = "FAILED"
                    job.error_message = f"All {actual_failed} documents failed"
                elif actual_failed > 0:
                    # Partial success
                    job.status = "COMPLETED"
                    job.error_message = f"{actual_failed}/{job.total_documents} documents failed"
                else:
                    # All succeeded
                    job.status = "COMPLETED"

                job.completed_at = datetime.utcnow()

                # Log completion
                log_entry = JobLog(
                    id=uuid.uuid4(),
                    job_id=job.id,
                    level="SUCCESS" if job.status == "COMPLETED" else "ERROR",
                    message=f"Job completed: {actual_completed} succeeded, {actual_failed} failed",
                    log_metadata={
                        "total_documents": job.total_documents,
                        "completed_documents": actual_completed,
                        "failed_documents": actual_failed,
                    },
                )
                session.add(log_entry)

                await session.commit()

                logging.getLogger("curatore.jobs").info(
                    f"Job {job.id} completed: {actual_completed}/{job.total_documents} succeeded"
                )

    except Exception as e:
        logging.getLogger("curatore.jobs").error(
            f"Failed to check job completion: {e}"
        )
