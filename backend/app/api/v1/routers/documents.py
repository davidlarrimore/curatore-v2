# backend/app/api/v1/routers/documents.py
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, UploadFile, HTTPException, Query, Request, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ....config import settings
from ..models import (
    FileUploadResponse,
    DocumentEditRequest,
    ProcessingOptions,
    BulkDownloadRequest,
    ZipArchiveInfo,
    V1ProcessingOptions,
    V1BatchProcessingRequest,
    V1ProcessingResult,
    V1BatchProcessingResult,
)
from ....models import FileListResponse
from ....database.models import User
from ....dependencies import get_current_user
from ....services.document_service import document_service
from ....models import BatchProcessingResult
from ....services.job_service import (
    set_active_job,
    get_active_job_for_document,
    record_job_status,
    append_job_log,
)
from ....services.database_service import database_service
from ....celery_app import app as celery_app
from ....tasks import process_document_task
from ....services.storage_service import storage_service
from ....services.zip_service import zip_service

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/documents/uploaded", tags=["Documents"], response_model=FileListResponse)
async def list_uploaded_files():
    """List all uploaded files with complete metadata (v2 parity)."""
    try:
        files = document_service.list_uploaded_files_with_metadata()
        return FileListResponse(files=files, count=len(files))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")

@router.get("/documents/batch", tags=["Documents"], response_model=FileListResponse)
async def list_batch_files():
    """List all files in the batch_files directory with complete metadata (v2 parity)."""
    try:
        files = document_service.list_batch_files_with_metadata()
        return FileListResponse(files=files, count=len(files))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list batch files: {str(e)}")

@router.post("/documents/upload", response_model=FileUploadResponse, tags=["Documents"])
async def upload_document(file: UploadFile = File(...)):
    """Upload a document for processing."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    if not document_service.is_supported_file(file.filename):
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported file type. Supported: {document_service.get_supported_extensions()}"
        )
    
    content = await file.read()
    if len(content) > settings.max_file_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.max_file_size} bytes"
        )

    document_id, file_path, file_hash = await document_service.save_uploaded_file(file.filename, content)

    return FileUploadResponse(
        document_id=document_id,
        filename=file.filename,
        file_size=len(content),
        upload_time=datetime.now(),
        message="File uploaded successfully"
    )

# Ensure static batch routes are registered before dynamic '{document_id}' routes
@router.post("/documents/batch/process", tags=["Processing"])
async def process_batch(request: V1BatchProcessingRequest):
    """Enqueue processing jobs for multiple documents in batch."""
    batch_id = str(uuid.uuid4())
    ttl = int(os.getenv("JOB_LOCK_TTL_SECONDS", "3600"))
    enqueued = []
    conflicts = []
    for doc_id in request.document_ids:
        file_path = document_service.find_document_file_unified(doc_id)
        if not file_path:
            conflicts.append({"document_id": doc_id, "error": "Document not found"})
            continue
        opts = (request.options.model_dump() if request.options else {})
        async_result = process_document_task.apply_async(
            kwargs={
                "document_id": doc_id,
                "options": opts,
                "file_path": str(file_path)
            },
            queue=os.getenv("CELERY_DEFAULT_QUEUE", "processing")
        )
        if not set_active_job(doc_id, async_result.id, ttl):
            try:
                celery_app.control.revoke(async_result.id, terminate=False)
            except Exception:
                pass
            conflicts.append({"document_id": doc_id, "status": "conflict", "active_job_id": get_active_job_for_document(doc_id)})
            continue
        record_job_status(async_result.id, {
            "job_id": async_result.id,
            "document_id": doc_id,
            "status": "PENDING",
            "enqueued_at": datetime.utcnow().isoformat(),
            "batch_id": batch_id,
        })
        append_job_log(async_result.id, "info", f"Queued: {doc_id}")
        enqueued.append({"document_id": doc_id, "job_id": async_result.id, "status": "queued"})

    return {
        "batch_id": batch_id,
        "jobs": enqueued,
        "conflicts": conflicts,
        "total": len(request.document_ids)
    }

@router.post("/documents/{document_id}/process", tags=["Processing"])
async def process_document(
    document_id: str,
    options: Optional[V1ProcessingOptions] = None,
    request: Request = None,
    sync: bool = Query(False, description="Run synchronously (for tests only)"),
    user: User = Depends(get_current_user),
):
    """
    Enqueue processing for a single document (Celery) or run sync when requested.

    **DEPRECATED**: This endpoint is deprecated and will be removed in a future version.
    Use POST /api/v1/jobs to create batch jobs with proper tracking and management.

    Supports optional authentication for database connection lookup in synchronous mode.
    Async mode (Celery) currently uses environment variables for backward compatibility.

    When authentication is enabled, this endpoint creates a single-document batch job
    internally for proper tracking while maintaining backward compatibility.
    """
    # Validate file exists first (check uploaded and batch locations)
    file_path = document_service.find_document_file_unified(document_id)
    if not file_path:
        try:
            # Emit detailed debug info to API logs to help diagnose path issues
            from ....main import api_logger
            extra = {"request_id": getattr(getattr(request, 'state', object()), 'request_id', '-')}
            upload_dir = str(getattr(document_service, 'upload_dir', ''))
            batch_dir = str(getattr(document_service, 'batch_dir', ''))
            api_logger.warning(
                f"process_document: Document not found id=%s upload_dir=%s batch_dir=%s",
                document_id,
                upload_dir,
                batch_dir,
                extra=extra,
            )
        except Exception:
            pass
        raise HTTPException(status_code=404, detail="Document not found")

    # Synchronous path (optional)
    if sync and os.getenv("ALLOW_SYNC_PROCESS", "false").lower() in {"1", "true", "yes"}:
        domain_options = options.to_domain() if options else ProcessingOptions()
        async with database_service.get_session() as session:
            result = await document_service.process_document(
                document_id,
                file_path,
                domain_options,
                organization_id=user.organization_id,
                session=session
            )

        storage_service.save_processing_result(result)
        return V1ProcessingResult.model_validate(result)

    # NEW: If authentication is enabled and user exists, create database-backed job
    # Otherwise fall back to legacy Redis-based tracking
    if settings.enable_auth:
        from ....services.job_service import create_batch_job, enqueue_job, check_concurrency_limit

        # Check concurrency limit
        can_create, error_msg = await check_concurrency_limit(user.organization_id)
        if not can_create:
            raise HTTPException(
                status_code=409,
                detail=error_msg or "Organization concurrency limit exceeded"
            )

        try:
            # Create single-document batch job
            opts = (options.model_dump() if options else {})
            job = await create_batch_job(
                organization_id=user.organization_id,
                user_id=user.id,
                document_ids=[document_id],
                options=opts,
                name=f"Document {document_id}",
                description="Single document processing (legacy endpoint)",
            )

            # Enqueue job
            enqueue_result = await enqueue_job(job.id)

            # Return legacy response format
            return {
                "job_id": str(job.id),
                "document_id": document_id,
                "status": "queued",
                "enqueued_at": job.created_at,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Legacy path: Enqueue Celery task with Redis tracking
    opts = (options.model_dump() if options else {})
    async_result = process_document_task.apply_async(
        kwargs={
            "document_id": document_id,
            "options": opts,
            "file_path": str(file_path)
        },
        queue=os.getenv("CELERY_DEFAULT_QUEUE", "processing")
    )
    # Acquire per-document lock with real job id; if it fails, revoke and return 409
    ttl = int(os.getenv("JOB_LOCK_TTL_SECONDS", "3600"))
    if not set_active_job(document_id, async_result.id, ttl):
        try:
            celery_app.control.revoke(async_result.id, terminate=False)
        except Exception:
            pass
        active_job = get_active_job_for_document(document_id)
        raise HTTPException(status_code=409, detail={
            "error": "Another job is already running for this document",
            "active_job_id": active_job,
            "status": "conflict"
        })

    # Record initial job status
    record_job_status(async_result.id, {
        "job_id": async_result.id,
        "document_id": document_id,
        "status": "PENDING",
        "enqueued_at": datetime.utcnow().isoformat(),
    })
    append_job_log(async_result.id, "info", f"Queued: {document_id}")

    return {
        "job_id": async_result.id,
        "document_id": document_id,
        "status": "queued",
        "enqueued_at": datetime.utcnow(),
    }

@router.post("/documents/batch/{filename}/process", tags=["Processing"])
async def process_batch_file(
    filename: str,
    options: Optional[V1ProcessingOptions] = None,
):
    """Enqueue processing for a single file from the batch_files directory."""
    batch_file_path = document_service.find_batch_file(filename)
    if not batch_file_path:
        raise HTTPException(status_code=404, detail="Batch file not found")

    document_id = f"batch_{batch_file_path.stem}"

    opts = (options.model_dump() if options else {})
    async_result = process_document_task.apply_async(
        kwargs={
            "document_id": document_id,
            "options": opts,
            "file_path": str(batch_file_path)
        },
        queue=os.getenv("CELERY_DEFAULT_QUEUE", "processing")
    )
    ttl = int(os.getenv("JOB_LOCK_TTL_SECONDS", "3600"))
    if not set_active_job(document_id, async_result.id, ttl):
        try:
            celery_app.control.revoke(async_result.id, terminate=False)
        except Exception:
            pass
        active_job = get_active_job_for_document(document_id)
        raise HTTPException(status_code=409, detail={
            "error": "Another job is already running for this document",
            "active_job_id": active_job,
            "status": "conflict"
        })
    record_job_status(async_result.id, {
        "job_id": async_result.id,
        "document_id": document_id,
        "status": "PENDING",
        "enqueued_at": datetime.utcnow().isoformat(),
    })
    append_job_log(async_result.id, "info", f"Queued: {document_id}")
    return {
        "job_id": async_result.id,
        "document_id": document_id,
        "status": "queued",
        "enqueued_at": datetime.utcnow(),
    }

# (moved above to avoid shadowing by dynamic routes)

@router.get("/documents/{document_id}/result", response_model=V1ProcessingResult, tags=["Results"])
async def get_processing_result(document_id: str):
    """Get processing result for a document."""
    result = storage_service.get_processing_result(document_id)
    if not result:
        raise HTTPException(status_code=404, detail="Processing result not found")
    return result

@router.get("/documents/{document_id}/content", tags=["Results"])
async def get_document_content(document_id: str):
    """Get the content of a processed document (with storage and filesystem fallback)."""
    try:
        # Try storage first, then filesystem fallback
        result = storage_service.get_processing_result(document_id)
        path: Optional[Path] = None
        if result and getattr(result, 'markdown_path', None):
            path = Path(result.markdown_path)
        if not path or not path.exists():
            path = document_service.get_processed_markdown_path(document_id)
        if not path or not path.exists():
            raise HTTPException(status_code=404, detail="Processed content not found")

        content = path.read_text(encoding='utf-8')
        return {"content": content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get content: {str(e)}")

@router.put("/documents/{document_id}/content", tags=["Results"])
async def update_document_content(
    document_id: str,
    request: DocumentEditRequest,
    options: Optional[V1ProcessingOptions] = None,
):
    """Enqueue content update + re-evaluation as a background job."""
    payload = {
        "content": request.content,
        "options": (options.model_dump() if options else {}),
        "improvement_prompt": request.improvement_prompt,
        "apply_vector_optimization": request.apply_vector_optimization,
    }
    from ....tasks import update_document_content_task
    async_result = update_document_content_task.apply_async(args=[document_id, payload], queue=os.getenv("CELERY_DEFAULT_QUEUE", "processing"))
    ttl = int(os.getenv("JOB_LOCK_TTL_SECONDS", "3600"))
    if not set_active_job(document_id, async_result.id, ttl):
        try:
            celery_app.control.revoke(async_result.id, terminate=False)
        except Exception:
            pass
        active_job = get_active_job_for_document(document_id)
        raise HTTPException(status_code=409, detail={
            "error": "Another job is already running for this document",
            "active_job_id": active_job,
            "status": "conflict"
        })
    record_job_status(async_result.id, {
        "job_id": async_result.id,
        "document_id": document_id,
        "status": "PENDING",
        "enqueued_at": datetime.utcnow().isoformat(),
        "operation": "update_content",
    })
    append_job_log(async_result.id, "info", f"Queued content update: {document_id}")
    return {
        "job_id": async_result.id,
        "document_id": document_id,
        "status": "queued",
        "enqueued_at": datetime.utcnow(),
    }

@router.get("/documents/{document_id}/download", tags=["Results"])
async def download_document(document_id: str):
    """Download a processed document (with storage and filesystem fallback)."""
    try:
        result = storage_service.get_processing_result(document_id)
        path: Optional[Path] = None
        if result and getattr(result, 'markdown_path', None):
            path = Path(result.markdown_path)
        if not path or not path.exists():
            # Fallback to filesystem lookup (worker saved file, backend memory lacks result)
            path = document_service.get_processed_markdown_path(document_id)
        if not path or not path.exists():
            raise HTTPException(status_code=404, detail="Processed file not found")

        # Determine a sensible download filename (strip document_id prefix)
        download_name = None
        try:
            if result and getattr(result, 'filename', None):
                download_name = f"{Path(result.filename).stem}.md"
            else:
                # Files are stored as {document_id}_{original_name}.md
                # Strip the document_id prefix to get the original filename
                filename = path.name
                if '_' in filename:
                    download_name = filename.split('_', 1)[1]  # Get everything after first underscore
                else:
                    download_name = filename
        except Exception:
            # Fallback: try to strip prefix, otherwise use full name
            filename = path.name
            download_name = filename.split('_', 1)[1] if '_' in filename else filename

        return FileResponse(
            path=str(path),
            filename=download_name,
            media_type="text/markdown"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

@router.post("/documents/download/bulk", tags=["Downloads"])
async def download_bulk_documents(request: BulkDownloadRequest):
    """Download multiple documents as a ZIP archive (v2 parity)."""
    try:
        zip_info = await zip_service.create_bulk_download(
            document_ids=request.document_ids,
            download_type=request.download_type,
            custom_filename=getattr(request, 'custom_filename', None) or getattr(request, 'zip_name', None),
            include_summary=getattr(request, 'include_summary', True),
            include_combined=getattr(request, 'include_combined', request.download_type == 'combined')
        )

        if not zip_info.zip_path.exists():
            raise HTTPException(status_code=404, detail="Archive not found")

        return FileResponse(
            path=str(zip_info.zip_path),
            filename=zip_info.zip_path.name,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={zip_info.zip_path.name}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bulk download failed: {str(e)}")

@router.get("/documents/download/rag-ready", tags=["Downloads"])
async def download_rag_ready_documents(
    zip_name: Optional[str] = Query(None, description="Custom ZIP filename"),
    include_summary: bool = Query(True, description="Include processing summary")
):
    """Download all RAG-ready documents as a ZIP archive (v2 parity)."""
    try:
        zip_info = await zip_service.create_rag_ready_download(
            custom_filename=zip_name,
            include_summary=include_summary
        )

        if not zip_info.zip_path.exists():
            raise HTTPException(status_code=404, detail="No RAG-ready documents found")

        return FileResponse(
            path=str(zip_info.zip_path),
            filename=zip_info.zip_path.name,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={zip_info.zip_path.name}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG-ready download failed: {str(e)}")

@router.get("/batch/{batch_id}/result", response_model=V1BatchProcessingResult, tags=["Results"])
async def get_batch_result(batch_id: str):
    """Get batch processing result."""
    result = storage_service.get_batch_result(batch_id)
    if not result:
        raise HTTPException(status_code=404, detail="Batch result not found")
    return result

@router.get("/documents", response_model=List[V1ProcessingResult], tags=["Results"])
async def list_processed_documents():
    """List all processed documents."""
    return storage_service.get_all_processing_results()

@router.delete("/documents/{document_id}", tags=["Documents"])
async def delete_document(document_id: str):
    """Delete a document and its processing results."""
    storage_service.delete_processing_result(document_id)

    upload_dir = Path(settings.upload_dir)
    processed_dir = Path(settings.processed_dir)

    for file_path in upload_dir.glob(f"{document_id}_*"):
        if file_path.exists():
            file_path.unlink()

    for file_path in processed_dir.glob(f"*_{document_id}.md"):
        if file_path.exists():
            file_path.unlink()

    return {"success": True, "message": "Document deleted successfully"}
