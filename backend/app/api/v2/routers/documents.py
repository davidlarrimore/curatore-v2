# backend/app/api/v2/routers/documents.py
import time
import uuid
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from pydantic import BaseModel
from fastapi.responses import FileResponse

from ....config import settings
from ..models import (
    FileUploadResponse,
    ProcessingResult,
    BatchProcessingResult,
    DocumentEditRequest,
    ProcessingOptions,
    BulkDownloadRequest,
)
from ....services.document_service import document_service
from ....services.storage_service import storage_service
from ....services.zip_service import zip_service
from ....tasks import update_document_content_task
from ....services.job_service import (
    set_active_job,
    get_active_job_for_document,
    record_job_status,
    append_job_log,
)
import os
from datetime import datetime
from ....services.job_service import (
    set_active_job,
    get_active_job_for_document,
    record_job_status,
    append_job_log,
)
from ....tasks import process_document_task
import os
from datetime import datetime

router = APIRouter()


class V2BatchEnqueueRequest(BaseModel):
    document_ids: List[str]
    options: Optional[dict] = None


# Parity endpoints with v1 for uploads and single-document processing
@router.get("/documents/uploaded", tags=["Documents"])
async def list_uploaded_files():
    """List all uploaded files (v2 compatibility)."""
    try:
        files = document_service.list_uploaded_files()
        return {"files": files, "count": len(files)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")


@router.post("/documents/upload", tags=["Documents"], response_model=FileUploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """Upload a document for processing (v2 compatibility)."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    if not document_service.is_supported_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Supported: {document_service.get_supported_extensions()}",
        )

    content = await file.read()
    if len(content) > settings.max_file_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.max_file_size} bytes",
        )

    document_id, _ = await document_service.save_uploaded_file(file.filename, content)

    return FileUploadResponse(
        document_id=document_id,
        filename=file.filename,
        file_size=len(content),
        upload_time=datetime.now(),
        message="File uploaded successfully",
    )


@router.post("/documents/{document_id}/process", tags=["Processing"])
async def process_document(document_id: str, options: Optional[dict] = None):
    """Enqueue processing for a single document (v2).

    Mirrors v1 behavior but accepts plain dict options compatible with frontend types.
    """
    # Validate file exists first
    file_path = document_service._find_document_file(document_id)
    if not file_path:
        raise HTTPException(status_code=404, detail="Document not found")

    opts = options or {}
    async_result = process_document_task.apply_async(
        args=[document_id, opts], queue=os.getenv("CELERY_DEFAULT_QUEUE", "processing")
    )
    # Acquire per-document lock; if it fails, revoke and return 409
    ttl = int(os.getenv("JOB_LOCK_TTL_SECONDS", "3600"))
    if not set_active_job(document_id, async_result.id, ttl):
        try:
            from ....celery_app import app as celery_app  # local import to avoid cycles at import time
            celery_app.control.revoke(async_result.id, terminate=False)
        except Exception:
            pass
        active_job = get_active_job_for_document(document_id)
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Another job is already running for this document",
                "active_job_id": active_job,
                "status": "conflict",
            },
        )

    record_job_status(
        async_result.id,
        {
            "job_id": async_result.id,
            "document_id": document_id,
            "status": "PENDING",
            "enqueued_at": datetime.utcnow().isoformat(),
        },
    )
    append_job_log(async_result.id, "info", f"Queued: {document_id}")
    return {
        "job_id": async_result.id,
        "document_id": document_id,
        "status": "queued",
        "enqueued_at": datetime.utcnow(),
    }


# Place the static batch enqueue route before dynamic routes to avoid path shadowing
@router.get("/documents/batch", tags=["Documents"])
async def list_batch_files():
    """List all files in the batch_files directory for local processing."""
    try:
        files = document_service.list_batch_files()
        return {"files": files, "count": len(files)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list batch files: {str(e)}")

@router.post("/documents/batch/process", tags=["Processing"])
async def process_batch(request: V2BatchEnqueueRequest):
    """Enqueue multiple documents in batch (v2)."""
    batch_id = str(uuid.uuid4())
    ttl = int(os.getenv("JOB_LOCK_TTL_SECONDS", "3600"))
    enqueued = []
    conflicts = []
    for doc_id in request.document_ids:
        file_path = document_service._find_document_file(doc_id)
        if not file_path:
            conflicts.append({"document_id": doc_id, "error": "Document not found"})
            continue
        opts = request.options or {}
        async_result = process_document_task.apply_async(args=[doc_id, opts], queue=os.getenv("CELERY_DEFAULT_QUEUE", "processing"))
        if not set_active_job(doc_id, async_result.id, ttl):
            try:
                from ....celery_app import app as celery_app
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
        "total": len(request.document_ids),
    }



@router.get("/documents/{document_id}/result", response_model=ProcessingResult, tags=["Results"])
async def get_processing_result(document_id: str):
    """Get processing result for a document."""
    result = storage_service.get_processing_result(document_id)
    if not result:
        raise HTTPException(status_code=404, detail="Processing result not found")
    return result


@router.get("/documents/{document_id}/content", tags=["Results"])
async def get_document_content(document_id: str):
    """Get processed markdown content for a document."""
    content = document_service.get_processed_content(document_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Processed content not found")
    return {"content": content}


@router.put("/documents/{document_id}/content", tags=["Results"])
async def update_document_content(
    document_id: str, request: DocumentEditRequest, options: Optional[dict] = None
):
    """Enqueue content update + re-evaluation as a background job."""
    ttl = int(os.getenv("JOB_LOCK_TTL_SECONDS", "3600"))
    if not set_active_job(document_id, "PENDING", ttl):
        active_job = get_active_job_for_document(document_id)
        raise HTTPException(status_code=409, detail={
            "error": "Another job is already running for this document",
            "active_job_id": active_job,
            "status": "conflict",
        })

    payload = {
        "content": request.content,
        "options": (options or {}),
        "improvement_prompt": request.improvement_prompt,
        "apply_vector_optimization": request.apply_vector_optimization,
    }
    async_result = update_document_content_task.apply_async(args=[document_id, payload], queue=os.getenv("CELERY_DEFAULT_QUEUE", "processing"))
    set_active_job(document_id, async_result.id, ttl)
    record_job_status(async_result.id, {
        "job_id": async_result.id,
        "document_id": document_id,
        "status": "PENDING",
        "enqueued_at": datetime.utcnow().isoformat(),
        "operation": "update_content",
    })
    append_job_log(async_result.id, "info", f"Queued content update: {document_id}")
    append_job_log(async_result.id, "info", f"Queued: {document_id}")
    return {
        "job_id": async_result.id,
        "document_id": document_id,
        "status": "queued",
        "enqueued_at": datetime.utcnow(),
    }


@router.get("/documents/{document_id}/download", tags=["Results"])
async def download_document(document_id: str):
    """Download processed document."""
    for file_path in Path(settings.processed_dir).glob(f"*_{document_id}.md"):
        if file_path.exists():
            return FileResponse(
                path=str(file_path),
                filename=f"{file_path.stem}.md",
                media_type="text/markdown",
            )
    raise HTTPException(status_code=404, detail="Processed document not found")


@router.post("/documents/download/bulk", tags=["Results"])
async def download_bulk_documents(request: BulkDownloadRequest):
    """Download multiple documents as a ZIP archive."""
    if not request.document_ids:
        raise HTTPException(status_code=400, detail="No document IDs provided")

    # Get processing results for metadata (best-effort, don't fail if missing)
    results = []
    for doc_id in request.document_ids or []:
        try:
            result = storage_service.get_processing_result(doc_id)
            if result and getattr(result, 'success', False):
                results.append(result)
        except Exception:
            continue

    try:
        # Filter document IDs based on download type
        if request.download_type == "rag_ready":
            filtered_ids = [r.document_id for r in results if getattr(r, 'is_rag_ready', getattr(r, 'pass_all_thresholds', False))]
            if not filtered_ids:
                raise HTTPException(status_code=404, detail="No RAG-ready documents found")
        else:
            # For non-rag downloads, use the request IDs directly
            filtered_ids = request.document_ids

        # Create ZIP archive based on type
        if request.download_type == "combined":
            # For combined exports, proceed even if results metadata is partial; files on disk drive inclusion
            zip_path, file_count = zip_service.create_combined_markdown_zip(
                filtered_ids, results, getattr(request, 'zip_name', None)
            )
        else:
            zip_path, file_count = zip_service.create_zip_archive(
                filtered_ids, getattr(request, 'zip_name', None), request.include_summary
            )

        if file_count == 0:
            raise HTTPException(status_code=404, detail="No files found to archive")

        # Return the ZIP file
        return FileResponse(
            path=zip_path,
            filename=Path(zip_path).name,
            media_type="application/zip",
            background=lambda: zip_service.cleanup_zip_file(zip_path),  # Clean up after download
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create archive: {str(e)}")


@router.get("/documents/download/rag-ready", tags=["Results"])
async def download_rag_ready_documents(
    zip_name: Optional[str] = Query(None, description="Custom name for the ZIP file"),
    include_summary: bool = Query(True, description="Include processing summary"),
):
    """Download all RAG-ready documents as a ZIP archive."""
    all_results = storage_service.get_all_processing_results()
    rag_ready_results = [r for r in all_results if r.success and getattr(r, 'is_rag_ready', getattr(r, 'pass_all_thresholds', False))]

    if not rag_ready_results:
        raise HTTPException(status_code=404, detail="No RAG-ready documents found")

    try:
        rag_ready_ids = [r.document_id for r in rag_ready_results]
        zip_path, file_count = zip_service.create_zip_archive(
            rag_ready_ids, zip_name or "curatore_rag_ready_export.zip", include_summary
        )

        if file_count == 0:
            raise HTTPException(status_code=404, detail="No RAG-ready files found to archive")

        return FileResponse(
            path=zip_path,
            filename=Path(zip_path).name,
            media_type="application/zip",
            background=lambda: zip_service.cleanup_zip_file(zip_path),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create RAG-ready archive: {str(e)}")

# Dynamic batch-file route defined AFTER static '/documents/batch/process'
@router.post("/documents/batch/{filename}/process", tags=["Processing"])
async def process_batch_file(
    filename: str, options: Optional[dict] = None
):
    """Enqueue processing for a single file from the batch_files directory."""
    batch_file_path = document_service.find_batch_file(filename)
    if not batch_file_path:
        raise HTTPException(status_code=404, detail="Batch file not found")

    document_id = f"batch_{batch_file_path.stem}"
    opts = options or {}
    async_result = process_document_task.apply_async(args=[document_id, opts], queue=os.getenv("CELERY_DEFAULT_QUEUE", "processing"))
    ttl = int(os.getenv("JOB_LOCK_TTL_SECONDS", "3600"))
    if not set_active_job(document_id, async_result.id, ttl):
        try:
            from ....celery_app import app as celery_app
            celery_app.control.revoke(async_result.id, terminate=False)
        except Exception:
            pass
        active_job = get_active_job_for_document(document_id)
        raise HTTPException(status_code=409, detail={
            "error": "Another job is already running for this document",
            "active_job_id": active_job,
            "status": "conflict",
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


@router.get("/batch/{batch_id}/result", response_model=BatchProcessingResult, tags=["Results"])
async def get_batch_result(batch_id: str):
    """Get batch processing result."""
    result = storage_service.get_batch_result(batch_id)
    if not result:
        raise HTTPException(status_code=404, detail="Batch result not found")
    return result


@router.get("/documents", response_model=List[ProcessingResult], tags=["Results"])
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

    return {"message": "Document deleted successfully"}
