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
from ....models import FileInfo, FileListResponse  # ADD THIS LINE
from ....services.document_service import document_service
from ....services.storage_service import storage_service
from ....services.zip_service import zip_service
from ....tasks import update_document_content_task
from ....services.job_service import (
    set_active_job,
    replace_active_job,
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


# UPDATED: Parity endpoints with v1 for uploads and single-document processing
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

            # Create and enqueue the processing job
            job_id = str(uuid.uuid4())
            set_active_job(job_id, document_id, batch_id)
            
            # Find the file path
            file_path = document_service.find_uploaded_file(document_id)
            if not file_path:
                file_path = document_service.find_batch_file(document_id)
            
            if not file_path:
                record_job_status(job_id, "failed", f"File not found: {document_id}")
                conflicts.append({
                    "document_id": document_id,
                    "job_id": job_id,
                    "message": "File not found"
                })
                continue

            # Enqueue the celery task
            try:
                task = process_document_task.delay(
                    job_id=job_id,
                    document_id=document_id,
                    file_path=str(file_path),
                    options=request.options or {}
                )
                
                jobs.append({
                    "job_id": job_id,
                    "document_id": document_id,
                    "task_id": task.id,
                    "status": "queued",
                    "enqueued_at": datetime.now().isoformat()
                })
                
            except Exception as e:
                record_job_status(job_id, "failed", str(e))
                conflicts.append({
                    "document_id": document_id,
                    "job_id": job_id,
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
        # Check if document exists
        result = storage_service.get_processing_result(document_id)
        if not result:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Create job for content update
        job_id = str(uuid.uuid4())
        set_active_job(job_id, document_id)
        
        # Enqueue the content update task
        task = update_document_content_task.delay(
            job_id=job_id,
            document_id=document_id,
            new_content=request.content,
            improvement_prompt=request.improvement_prompt,
            apply_vector_optimization=request.apply_vector_optimization
        )
        
        return {
            "job_id": job_id,
            "document_id": document_id,
            "task_id": task.id,
            "status": "queued",
            "enqueued_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Content update failed: {str(e)}")


@router.post("/documents/download/bulk", tags=["Downloads"])
async def bulk_download(request: BulkDownloadRequest):
    """Create a bulk download archive."""
    try:
        if not request.document_ids:
            raise HTTPException(status_code=400, detail="No document IDs provided")
        
        # Get results for all requested documents
        results = []
        for doc_id in request.document_ids:
            result = storage_service.get_processing_result(doc_id)
            if result:
                results.append(result)
        
        if not results:
            raise HTTPException(status_code=404, detail="No processed documents found")
        
        # Create ZIP archive
        zip_path = zip_service.create_bulk_archive(
            results=results,
            download_type=request.download_type,
            custom_filename=request.custom_filename,
            include_summary=request.include_summary,
            include_combined=request.include_combined
        )
        
        return FileResponse(
            path=zip_path,
            filename=Path(zip_path).name,
            media_type="application/zip"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bulk download failed: {str(e)}")


@router.get("/documents/download/rag-ready", tags=["Downloads"])
async def download_rag_ready(
    zip_name: Optional[str] = Query(None),
    include_summary: bool = Query(True)
):
    """Download only RAG-ready documents."""
    try:
        # Get all processing results
        all_results = storage_service.get_all_processing_results()
        
        # Filter for RAG-ready documents
        rag_ready_results = [r for r in all_results if r.is_rag_ready]
        
        if not rag_ready_results:
            raise HTTPException(status_code=404, detail="No RAG-ready documents found")
        
        # Create ZIP archive
        zip_path = zip_service.create_rag_ready_archive(
            results=rag_ready_results,
            custom_filename=zip_name,
            include_summary=include_summary
        )
        
        return FileResponse(
            path=zip_path,
            filename=Path(zip_path).name,
            media_type="application/zip"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG-ready download failed: {str(e)}")