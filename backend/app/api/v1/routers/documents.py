# backend/app/api/v1/routers/documents.py
import time
import uuid
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException, Query
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
from ....services.document_service import document_service
from ....models import BatchProcessingResult
from ....services.storage_service import storage_service
from ....services.zip_service import zip_service

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

@router.post("/documents/{document_id}/process", response_model=V1ProcessingResult, tags=["Processing"])
async def process_document(
    document_id: str,
    options: Optional[V1ProcessingOptions] = None,
):
    """Process a single document."""
    domain_options: ProcessingOptions
    if not options:
        domain_options = ProcessingOptions()
    else:
        domain_options = options.to_domain()
    
    file_path = document_service._find_document_file(document_id)
    if not file_path:
        raise HTTPException(status_code=404, detail="Document not found")
    
    result = await document_service.process_document(document_id, file_path, domain_options)
    storage_service.save_processing_result(result)
    return result

@router.post("/documents/batch/{filename}/process", response_model=V1ProcessingResult, tags=["Processing"])
async def process_batch_file(
    filename: str,
    options: Optional[V1ProcessingOptions] = None,
):
    """Process a single file from the batch_files directory."""
    domain_options: ProcessingOptions
    if not options:
        domain_options = ProcessingOptions()
    else:
        domain_options = options.to_domain()
    
    batch_file_path = document_service.find_batch_file(filename)
    if not batch_file_path:
        raise HTTPException(status_code=404, detail="Batch file not found")
    
    document_id = f"batch_{batch_file_path.stem}"
    
    result = await document_service.process_document(document_id, batch_file_path, domain_options)
    storage_service.save_processing_result(result)
    return result

@router.post("/documents/batch/process", response_model=V1BatchProcessingResult, tags=["Processing"])
async def process_batch(request: V1BatchProcessingRequest):
    """Process multiple documents in batch."""
    batch_id = str(uuid.uuid4())
    start_time = time.time()
    
    domain_options = request.options.to_domain() if request.options else None
    results = await document_service.process_batch(request.document_ids, domain_options)
    
    successful = len([r for r in results if r.success])
    failed = len(results) - successful
    rag_ready = len([r for r in results if getattr(r, 'is_rag_ready', getattr(r, 'pass_all_thresholds', False))])
    
    batch_result = V1BatchProcessingResult(
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

@router.get("/documents/{document_id}/result", response_model=V1ProcessingResult, tags=["Results"])
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

@router.put("/documents/{document_id}/content", response_model=V1ProcessingResult, tags=["Results"])
async def update_document_content(
    document_id: str,
    request: DocumentEditRequest,
    options: Optional[V1ProcessingOptions] = None,
):
    """Update document content with optional LLM improvements."""
    domain_options: ProcessingOptions
    if not options:
        domain_options = ProcessingOptions()
    else:
        domain_options = options.to_domain()

    result = await document_service.update_document_content(
        document_id=document_id,
        content=request.content,
        options=domain_options,
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

@router.post("/documents/download/bulk", tags=["Results"])
async def download_bulk_documents(request: BulkDownloadRequest):
    """Download multiple documents as a ZIP archive."""
    if not request.document_ids:
        raise HTTPException(status_code=400, detail="No document IDs provided")
    
    # Get processing results for metadata
    results = []
    for doc_id in request.document_ids:
        result = storage_service.get_processing_result(doc_id)
        if result and result.success:
            results.append(result)
    
    if not results:
        raise HTTPException(status_code=404, detail="No processed documents found for the provided IDs")
    
    try:
        # Filter document IDs based on download type
        if request.download_type == "rag_ready":
            filtered_ids = [r.document_id for r in results if getattr(r, 'is_rag_ready', getattr(r, 'pass_all_thresholds', False))]
            if not filtered_ids:
                raise HTTPException(status_code=404, detail="No RAG-ready documents found")
        else:
            filtered_ids = [r.document_id for r in results]
        
        # Create ZIP archive based on type
        if request.download_type == "combined":
            zip_path, file_count = zip_service.create_combined_markdown_zip(
                filtered_ids, 
                results, 
                request.zip_name
            )
        else:
            zip_path, file_count = zip_service.create_zip_archive(
                filtered_ids, 
                request.zip_name,
                request.include_summary
            )
        
        if file_count == 0:
            raise HTTPException(status_code=404, detail="No files found to archive")
        
        # Return the ZIP file
        return FileResponse(
            path=zip_path,
            filename=Path(zip_path).name,
            media_type="application/zip",
            background=lambda: zip_service.cleanup_zip_file(zip_path)  # Clean up after download
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create archive: {str(e)}")

@router.get("/documents/download/rag-ready", tags=["Results"])
async def download_rag_ready_documents(
    zip_name: Optional[str] = Query(None, description="Custom name for the ZIP file"),
    include_summary: bool = Query(True, description="Include processing summary")
):
    """Download all RAG-ready documents as a ZIP archive."""
    all_results = storage_service.get_all_processing_results()
    rag_ready_results = [r for r in all_results if r.success and getattr(r, 'is_rag_ready', getattr(r, 'pass_all_thresholds', False))]
    
    if not rag_ready_results:
        raise HTTPException(status_code=404, detail="No RAG-ready documents found")
    
    try:
        rag_ready_ids = [r.document_id for r in rag_ready_results]
        zip_path, file_count = zip_service.create_zip_archive(
            rag_ready_ids,
            zip_name or "curatore_rag_ready_export.zip",
            include_summary
        )
        
        if file_count == 0:
            raise HTTPException(status_code=404, detail="No RAG-ready files found to archive")
        
        return FileResponse(
            path=zip_path,
            filename=Path(zip_path).name,
            media_type="application/zip",
            background=lambda: zip_service.cleanup_zip_file(zip_path)
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create RAG-ready archive: {str(e)}")

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
    
    return {"message": "Document deleted successfully"}
