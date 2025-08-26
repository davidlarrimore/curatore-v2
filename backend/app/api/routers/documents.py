# backend/app/api/routers/documents.py
import time
import uuid
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import FileResponse

from ...config import settings
from ...models import (
    FileUploadResponse, ProcessingResult, BatchProcessingRequest,
    BatchProcessingResult, DocumentEditRequest, ProcessingOptions
)
from ...services.document_service import document_service
from ...services.storage_service import storage_service

router = APIRouter()

@router.get("/documents/uploaded", tags=["Documents"])
async def list_uploaded_files():
    """List all uploaded files."""
    try:
        files = document_service.list_uploaded_files()
        return {"files": files, "count": len(files)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")

@router.get("/documents/batch", tags=["Documents"])
async def list_batch_files():
    """List all files in the batch_files directory for local processing."""
    try:
        files = document_service.list_batch_files()
        return {"files": files, "count": len(files)}
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
    
    document_id, file_path = await document_service.save_uploaded_file(file.filename, content)
    
    return FileUploadResponse(
        document_id=document_id,
        filename=file.filename,
        file_size=len(content),
        upload_time=datetime.now(),
        message="File uploaded successfully"
    )

@router.post("/documents/{document_id}/process", response_model=ProcessingResult, tags=["Processing"])
async def process_document(
    document_id: str,
    options: Optional[ProcessingOptions] = None
):
    """Process a single document."""
    if not options:
        options = ProcessingOptions()
    
    file_path = document_service._find_document_file(document_id)
    if not file_path:
        raise HTTPException(status_code=404, detail="Document not found")
    
    result = await document_service.process_document(document_id, file_path, options)
    storage_service.save_processing_result(result)
    return result

@router.post("/documents/batch/{filename}/process", response_model=ProcessingResult, tags=["Processing"])
async def process_batch_file(
    filename: str,
    options: Optional[ProcessingOptions] = None
):
    """Process a single file from the batch_files directory."""
    if not options:
        options = ProcessingOptions()
    
    batch_file_path = document_service.find_batch_file(filename)
    if not batch_file_path:
        raise HTTPException(status_code=404, detail="Batch file not found")
    
    document_id = f"batch_{batch_file_path.stem}"
    
    result = await document_service.process_document(document_id, batch_file_path, options)
    storage_service.save_processing_result(result)
    return result

@router.post("/documents/batch/process", response_model=BatchProcessingResult, tags=["Processing"])
async def process_batch(request: BatchProcessingRequest):
    """Process multiple documents in batch."""
    batch_id = str(uuid.uuid4())
    start_time = time.time()
    
    results = await document_service.process_batch(request.document_ids, request.options)
    
    successful = len([r for r in results if r.success])
    failed = len(results) - successful
    rag_ready = len([r for r in results if r.pass_all_thresholds])
    
    batch_result = BatchProcessingResult(
        batch_id=batch_id,
        total_files=len(results),
        successful=successful,
        failed=failed,
        rag_ready=rag_ready,
        results=results,
        processing_time=time.time() - start_time,
        started_at=datetime.fromtimestamp(start_time),
        completed_at=datetime.now()
    )
    
    storage_service.save_batch_result(batch_result)
    return batch_result

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

@router.put("/documents/{document_id}/content", response_model=ProcessingResult, tags=["Results"])
async def update_document_content(
    document_id: str, 
    request: DocumentEditRequest,
    options: Optional[ProcessingOptions] = None
):
    """Update document content with optional LLM improvements."""
    if not options:
        options = ProcessingOptions()

    result = await document_service.update_document_content(
        document_id=document_id,
        content=request.content,
        options=options,
        improvement_prompt=request.improvement_prompt,
        apply_vector_optimization=request.apply_vector_optimization
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Document not found or update failed")
    
    storage_service.save_processing_result(result)
    return result

@router.get("/documents/{document_id}/download", tags=["Results"])
async def download_document(document_id: str):
    """Download processed document."""
    for file_path in Path(settings.processed_dir).glob(f"*_{document_id}.md"):
        if file_path.exists():
            return FileResponse(
                path=str(file_path),
                filename=f"{file_path.stem}.md",
                media_type="text/markdown"
            )
    raise HTTPException(status_code=404, detail="Processed document not found")

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