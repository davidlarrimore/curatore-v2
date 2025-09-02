# backend/app/api/v2/routers/documents.py
import time
import uuid
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException, Query, Request
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
from ....models import FileInfo, FileListResponse
from ....services.document_service import document_service
from ....services.storage_service import storage_service
from ....services.zip_service import zip_service
from ....tasks import update_document_content_task, process_document_task
from ....services.job_service import (
    set_active_job,
    replace_active_job,
    get_active_job_for_document,
    record_job_status,
    append_job_log,
)
import os
from datetime import datetime

router = APIRouter()


class V2BatchEnqueueRequest(BaseModel):
    document_ids: List[str]
    options: Optional[dict] = None


# ==================== DOCUMENT LISTING ENDPOINTS ====================

@router.get("/documents/uploaded", tags=["Documents"], response_model=FileListResponse)
async def list_uploaded_files():
    """List all uploaded files with complete metadata (v2 compatibility)."""
    try:
        files = document_service.list_uploaded_files_with_metadata()
        return FileListResponse(files=files, count=len(files))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")


@router.get("/documents/batch", tags=["Documents"], response_model=FileListResponse)
async def list_batch_files():
    """List all files in the batch_files directory for local processing with complete metadata (v2)."""
    try:
        files = document_service.list_batch_files_with_metadata()
        return FileListResponse(files=files, count=len(files))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list batch files: {str(e)}")


# ==================== UPLOAD & DELETE ENDPOINTS ====================

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


@router.delete("/documents/{document_id}", tags=["Documents"])
async def delete_document(document_id: str):
    """Delete an uploaded document by ID."""
    try:
        success = document_service.delete_uploaded_file(document_id)
        if success:
            return {"success": True, "message": f"Document {document_id} deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Document not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")


# ==================== BATCH PROCESSING ENDPOINT ====================
# Place the static batch enqueue route before dynamic routes to avoid path shadowing

@router.post("/documents/batch/process", tags=["Processing"])
async def process_batch(request: V2BatchEnqueueRequest):
    """Enqueue multiple documents in batch (v2)."""
    try:
        if not request.document_ids:
            raise HTTPException(status_code=400, detail="No document IDs provided")

        batch_id = str(uuid.uuid4())
        jobs = []
        conflicts = []

        for document_id in request.document_ids:
            # Check if there's already an active job for this document
            existing_job = get_active_job_for_document(document_id)
            if existing_job:
                conflicts.append({
                    "document_id": document_id,
                    "existing_job_id": existing_job,
                    "message": "Document already has an active processing job"
                })
                continue

            # Find the file path - check both uploaded and batch files
            file_path = document_service.find_uploaded_file(document_id)
            if not file_path:
                file_path = document_service.find_batch_file(document_id)
            
            if not file_path:
                conflicts.append({
                    "document_id": document_id,
                    "message": "File not found"
                })
                continue

            # Enqueue the celery task
            try:
                async_result = process_document_task.apply_async(
                    args=[document_id, request.options or {}], 
                    queue=os.getenv("CELERY_DEFAULT_QUEUE", "processing")
                )
                
                # Acquire per-document lock with job ID
                ttl = int(os.getenv("JOB_LOCK_TTL_SECONDS", "3600"))
                if not set_active_job(document_id, async_result.id, ttl):
                    try:
                        from ....celery_app import celery_app
                        celery_app.control.revoke(async_result.id, terminate=False)
                    except Exception:
                        pass
                    active_job = get_active_job_for_document(document_id)
                    conflicts.append({
                        "document_id": document_id,
                        "existing_job_id": active_job,
                        "message": "Another job is already running for this document"
                    })
                    continue
                
                # Record job status
                record_job_status(async_result.id, {
                    "job_id": async_result.id,
                    "document_id": document_id,
                    "status": "PENDING",
                    "enqueued_at": datetime.utcnow().isoformat(),
                    "batch_id": batch_id,
                })
                append_job_log(async_result.id, "info", f"Queued: {document_id}")
                
                jobs.append({
                    "job_id": async_result.id,
                    "document_id": document_id,
                    "status": "queued",
                    "enqueued_at": datetime.utcnow().isoformat()
                })
                
            except Exception as e:
                conflicts.append({
                    "document_id": document_id,
                    "message": f"Failed to enqueue: {str(e)}"
                })

        return {
            "batch_id": batch_id,
            "total": len(request.document_ids),
            "jobs": jobs,
            "conflicts": conflicts
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch processing failed: {str(e)}")


# ==================== SINGLE DOCUMENT PROCESSING ENDPOINT ====================
# CRITICAL: This was missing and causing 404 errors!

@router.post("/documents/{document_id}/process", tags=["Processing"])
async def process_document(
    document_id: str,
    options: Optional[ProcessingOptions] = None,
    request: Request = None,
    sync: bool = Query(False, description="Run synchronously (for tests only)"),
):
    """Enqueue processing for a single document (Celery) or run sync when requested.
    
    This endpoint was missing from v2 and causing 404 errors when the frontend
    tried to process individual documents.
    """
    # Validate file exists first - check both uploaded and batch files
    file_path = document_service.find_uploaded_file(document_id)
    if not file_path:
        file_path = document_service.find_batch_file(document_id)
    
    if not file_path:
        raise HTTPException(status_code=404, detail="Document not found")

    # Synchronous path (optional for testing)
    if sync and os.getenv("ALLOW_SYNC_PROCESS", "false").lower() in {"1", "true", "yes"}:
        from ....core.models import ProcessingOptions as DomainProcessingOptions
        domain_options = options.to_domain() if options else DomainProcessingOptions()
        result = await document_service.process_document(document_id, file_path, domain_options)
        storage_service.save_processing_result(result)
        return ProcessingResult.model_validate(result)

    # Enqueue Celery task
    opts = (options.model_dump() if options else {})
    async_result = process_document_task.apply_async(
        args=[document_id, opts], 
        queue=os.getenv("CELERY_DEFAULT_QUEUE", "processing")
    )
    
    # Acquire per-document lock with real job id; if it fails, revoke and return 409
    ttl = int(os.getenv("JOB_LOCK_TTL_SECONDS", "3600"))
    if not set_active_job(document_id, async_result.id, ttl):
        try:
            from ....celery_app import celery_app
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


# ==================== RESULT & CONTENT ENDPOINTS ====================

@router.get("/documents/{document_id}/result", tags=["Results"])
async def get_processing_result(document_id: str):
    """Get processing result for a document."""
    try:
        result = storage_service.get_processing_result(document_id)
        if not result:
            raise HTTPException(status_code=404, detail="Processing result not found")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get result: {str(e)}")


@router.get("/documents/{document_id}/download", tags=["Documents"])
async def download_document(document_id: str):
    """Download a processed document."""
    try:
        result = storage_service.get_processing_result(document_id)
        if not result:
            raise HTTPException(status_code=404, detail="Document not found")
        
        if not result.markdown_path or not Path(result.markdown_path).exists():
            raise HTTPException(status_code=404, detail="Processed file not found")
        
        return FileResponse(
            path=result.markdown_path,
            filename=f"{Path(result.filename).stem}.md",
            media_type="text/markdown"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@router.get("/documents/{document_id}/content", tags=["Results"])
async def get_document_content(document_id: str):
    """Get the content of a processed document."""
    try:
        result = storage_service.get_processing_result(document_id)
        if not result:
            raise HTTPException(status_code=404, detail="Document not found")
        
        if not result.markdown_path or not Path(result.markdown_path).exists():
            raise HTTPException(status_code=404, detail="Processed content not found")
        
        content = Path(result.markdown_path).read_text(encoding='utf-8')
        return {"content": content}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get content: {str(e)}")


@router.put("/documents/{document_id}/content", tags=["Results"])
async def update_document_content(document_id: str, request: DocumentEditRequest):
    """Update the content of a processed document."""
    try:
        # Validate document exists
        result = storage_service.get_processing_result(document_id)
        if not result:
            raise HTTPException(status_code=404, detail="Document not found")

        # Prepare payload for the update task
        payload = {
            "content": request.content,
            "options": request.options or {},
            "improvement_prompt": getattr(request, 'improvement_prompt', None),
            "apply_vector_optimization": getattr(request, 'apply_vector_optimization', True),
        }
        
        # Enqueue update task
        async_result = update_document_content_task.apply_async(
            args=[document_id, payload], 
            queue=os.getenv("CELERY_DEFAULT_QUEUE", "processing")
        )
        
        # Acquire per-document lock
        ttl = int(os.getenv("JOB_LOCK_TTL_SECONDS", "3600"))
        if not set_active_job(document_id, async_result.id, ttl):
            try:
                from ....celery_app import celery_app
                celery_app.control.revoke(async_result.id, terminate=False)
            except Exception:
                pass
            active_job = get_active_job_for_document(document_id)
            raise HTTPException(status_code=409, detail={
                "error": "Another job is already running for this document",
                "active_job_id": active_job,
                "status": "conflict"
            })
        
        # Record job status
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
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update content: {str(e)}")


# ==================== DOWNLOAD & EXPORT ENDPOINTS ====================

@router.post("/documents/download/bulk", tags=["Downloads"])
async def download_bulk_documents(request: BulkDownloadRequest):
    """Download multiple documents as a ZIP archive."""
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
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bulk download failed: {str(e)}")


@router.get("/documents/download/rag-ready", tags=["Downloads"])
async def download_rag_ready_documents(
    zip_name: Optional[str] = Query(None, description="Custom ZIP filename"),
    include_summary: bool = Query(True, description="Include processing summary")
):
    """Download all RAG-ready documents as a ZIP archive."""
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
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG-ready download failed: {str(e)}")