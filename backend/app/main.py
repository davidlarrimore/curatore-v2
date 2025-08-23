# backend/app/main.py
import time
import uuid
import shutil
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .config import settings
from .models import (
    HealthStatus, FileUploadResponse, ProcessingResult, BatchProcessingRequest,
    BatchProcessingResult, LLMConnectionStatus, DocumentEditRequest,
    ProcessingOptions, QualityThresholds, OCRSettings, ErrorResponse
)
from .services.llm_service import llm_service
from .services.document_service import document_service

# Create FastAPI app
app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description="Curatore v2 - RAG Document Processing API"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for processing results (in production, use a database)
processing_results: dict[str, ProcessingResult] = {}
batch_results: dict[str, BatchProcessingResult] = {}


def clear_file_directories():
    """Clear uploaded and processed file directories on startup."""
    try:
        upload_dir = Path(settings.upload_dir)
        processed_dir = Path(settings.processed_dir)
        
        # Clear uploaded files
        if upload_dir.exists():
            for file_path in upload_dir.glob("*"):
                if file_path.is_file():
                    file_path.unlink()
                    print(f"Deleted uploaded file: {file_path}")
        
        # Clear processed files
        if processed_dir.exists():
            for file_path in processed_dir.glob("*"):
                if file_path.is_file():
                    file_path.unlink()
                    print(f"Deleted processed file: {file_path}")
        
        print("✅ File directories cleared on startup")
    except Exception as e:
        print(f"⚠️ Error clearing file directories: {e}")


# Clear directories on startup
@app.on_event("startup")
async def startup_event():
    """Application startup event handler."""
    print("🚀 Starting Curatore v2...")
    
    # Debug: Show current working directory and file paths
    import os
    print(f"📍 Current working directory: {os.getcwd()}")
    print(f"📁 Settings paths:")
    print(f"   FILES_ROOT: {settings.files_root}")
    print(f"   UPLOAD_DIR: {settings.upload_dir}")
    print(f"   PROCESSED_DIR: {settings.processed_dir}")
    print(f"   BATCH_DIR: {settings.batch_dir}")
    
    # Check if mounted directories exist
    for name, path in [
        ("Files root", settings.files_root),
        ("Upload dir", settings.upload_dir),
        ("Processed dir", settings.processed_dir),
        ("Batch dir", settings.batch_dir)
    ]:
        path_obj = Path(path)
        exists = path_obj.exists()
        is_dir = path_obj.is_dir() if exists else False
        print(f"   {name}: {path} - {'✅ EXISTS' if exists else '❌ MISSING'}{' (DIR)' if is_dir else ''}")
    
    # Clear uploaded and processed files only (not batch files)
    clear_file_directories()
    
    # Clear in-memory storage
    processing_results.clear()
    batch_results.clear()
    print("✅ In-memory storage cleared")
    
    # The DocumentService will handle directory creation in its __init__
    print("✅ Startup complete")


@app.get("/api/health", response_model=HealthStatus)
async def health_check():
    """Health check endpoint."""
    llm_status = await llm_service.test_connection()
    
    return HealthStatus(
        status="healthy",
        timestamp=datetime.now(),
        version=settings.api_version,
        llm_connected=llm_status.connected,
        storage_available=True  # Basic check - could be more sophisticated
    )


@app.get("/api/llm/status", response_model=LLMConnectionStatus)
async def get_llm_status():
    """Get LLM connection status."""
    return await llm_service.test_connection()


@app.post("/api/system/reset")
async def reset_system():
    """Reset the entire system - clear all files and data."""
    try:
        # Clear file directories
        clear_file_directories()
        
        # Clear in-memory storage
        processing_results.clear()
        batch_results.clear()
        
        # Ensure directories exist
        Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
        Path(settings.processed_dir).mkdir(parents=True, exist_ok=True)
        Path(settings.batch_dir).mkdir(parents=True, exist_ok=True)
        
        return {
            "success": True,
            "message": "System reset successfully",
            "timestamp": datetime.now()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")


@app.get("/api/config/supported-formats")
async def get_supported_formats():
    """Get list of supported file formats."""
    return {
        "supported_extensions": document_service.get_supported_extensions(),
        "max_file_size": settings.max_file_size
    }


@app.get("/api/config/defaults")
async def get_default_config():
    """Get default configuration values."""
    return {
        "quality_thresholds": {
            "conversion": settings.default_conversion_threshold,
            "clarity": settings.default_clarity_threshold,
            "completeness": settings.default_completeness_threshold,
            "relevance": settings.default_relevance_threshold,
            "markdown": settings.default_markdown_threshold
        },
        "ocr_settings": {
            "language": settings.ocr_lang,
            "psm": settings.ocr_psm
        },
        "auto_optimize": True
    }


@app.get("/api/documents/uploaded")
async def list_uploaded_files():
    """List all uploaded files."""
    try:
        files = document_service.list_uploaded_files()
        return {"files": files, "count": len(files)}
    except Exception as e:
        print(f"Error in list_uploaded_files: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")


@app.get("/api/documents/batch")
async def list_batch_files():
    """List all files in the batch_files directory for local processing."""
    try:
        files = document_service.list_batch_files()
        return {"files": files, "count": len(files)}
    except Exception as e:
        print(f"Error in list_batch_files: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to list batch files: {str(e)}")


@app.post("/api/documents/upload", response_model=FileUploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """Upload a document for processing."""
    try:
        # Validate file
        if not file.filename:
            raise HTTPException(status_code=400, detail="No filename provided")
        
        if not document_service.is_supported_file(file.filename):
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported file type. Supported: {document_service.get_supported_extensions()}"
            )
        
        # Read file content
        content = await file.read()
        
        # Check file size
        if len(content) > settings.max_file_size:
            raise HTTPException(
                status_code=413, 
                detail=f"File too large. Maximum size: {settings.max_file_size} bytes"
            )
        
        # Save file
        document_id, file_path = await document_service.save_uploaded_file(file.filename, content)
        
        # Log the upload
        print(f"File uploaded: {file.filename} -> {file_path} (ID: {document_id})")
        
        return FileUploadResponse(
            document_id=document_id,
            filename=file.filename,
            file_size=len(content),
            upload_time=datetime.now(),
            message="File uploaded successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Upload error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.post("/api/documents/{document_id}/process", response_model=ProcessingResult)
async def process_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    options: Optional[ProcessingOptions] = None
):
    """Process a single document."""
    try:
        if not options:
            options = ProcessingOptions()
        
        # Find the document file
        file_path = document_service._find_document_file(document_id)
        if not file_path:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Process the document
        result = await document_service.process_document(document_id, file_path, options)
        
        # Store result
        processing_results[document_id] = result
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Processing error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@app.post("/api/documents/batch/{filename}/process", response_model=ProcessingResult)
async def process_batch_file(
    filename: str,
    background_tasks: BackgroundTasks,
    options: Optional[ProcessingOptions] = None
):
    """Process a single file from the batch_files directory."""
    try:
        if not options:
            options = ProcessingOptions()
        
        # Find the batch file
        batch_file_path = document_service.find_batch_file(filename)
        if not batch_file_path:
            raise HTTPException(status_code=404, detail="Batch file not found")
        
        # Generate a document ID for the batch file
        document_id = str(uuid.uuid4())
        
        # Process the document
        result = await document_service.process_document(document_id, batch_file_path, options)
        
        # Store result
        processing_results[document_id] = result
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Batch processing error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Batch processing failed: {str(e)}")


@app.post("/api/documents/batch/process", response_model=BatchProcessingResult)
async def process_batch(
    request: BatchProcessingRequest,
    background_tasks: BackgroundTasks
):
    """Process multiple documents in batch."""
    try:
        batch_id = str(uuid.uuid4())
        start_time = time.time()
        
        # Process documents
        results = await document_service.process_batch(request.document_ids, request.options)
        
        # Calculate statistics
        successful = len([r for r in results if r.success])
        failed = len(results) - successful
        rag_ready = len([r for r in results if r.pass_all_thresholds])
        processing_time = time.time() - start_time
        
        batch_result = BatchProcessingResult(
            batch_id=batch_id,
            total_files=len(results),
            successful=successful,
            failed=failed,
            rag_ready=rag_ready,
            results=results,
            processing_time=processing_time,
            started_at=datetime.now(),
            completed_at=datetime.now()
        )
        
        # Store batch result
        batch_results[batch_id] = batch_result
        
        # Store individual results
        for result in results:
            processing_results[result.document_id] = result
        
        return batch_result
        
    except Exception as e:
        print(f"Batch processing error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Batch processing failed: {str(e)}")


@app.get("/api/documents/{document_id}/result", response_model=ProcessingResult)
async def get_processing_result(document_id: str):
    """Get processing result for a document."""
    if document_id not in processing_results:
        raise HTTPException(status_code=404, detail="Processing result not found")
    
    return processing_results[document_id]


@app.get("/api/documents/{document_id}/content")
async def get_document_content(document_id: str):
    """Get processed markdown content for a document."""
    try:
        content = document_service.get_processed_content(document_id)
        if not content:
            raise HTTPException(status_code=404, detail="Processed content not found")
        
        return {"content": content}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Get content error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get content: {str(e)}")


@app.put("/api/documents/{document_id}/content", response_model=ProcessingResult)
async def update_document_content(document_id: str, request: DocumentEditRequest):
    """Update document content with optional LLM improvements."""
    try:
        result = await document_service.update_document_content(
            document_id=document_id,
            content=request.content,
            improvement_prompt=request.improvement_prompt,
            apply_vector_optimization=request.apply_vector_optimization
        )
        
        if not result:
            raise HTTPException(status_code=404, detail="Document not found or update failed")
        
        # Update stored result
        processing_results[document_id] = result
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Update content error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Content update failed: {str(e)}")


@app.get("/api/documents/{document_id}/download")
async def download_document(document_id: str):
    """Download processed document."""
    try:
        # Find processed file
        for file_path in Path(settings.processed_dir).glob(f"*_{document_id}.md"):
            if file_path.exists():
                return FileResponse(
                    path=str(file_path),
                    filename=f"{file_path.stem}.md",
                    media_type="text/markdown"
                )
        
        raise HTTPException(status_code=404, detail="Processed document not found")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Download error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@app.get("/api/batch/{batch_id}/result", response_model=BatchProcessingResult)
async def get_batch_result(batch_id: str):
    """Get batch processing result."""
    if batch_id not in batch_results:
        raise HTTPException(status_code=404, detail="Batch result not found")
    
    return batch_results[batch_id]


@app.get("/api/documents", response_model=List[ProcessingResult])
async def list_processed_documents():
    """List all processed documents."""
    return list(processing_results.values())


@app.delete("/api/documents/{document_id}")
async def delete_document(document_id: str):
    """Delete a document and its processing results."""
    try:
        # Remove from processing results
        if document_id in processing_results:
            del processing_results[document_id]
        
        # Remove files
        upload_dir = Path(settings.upload_dir)
        processed_dir = Path(settings.processed_dir)
        
        for file_path in upload_dir.glob(f"{document_id}_*"):
            if file_path.exists():
                file_path.unlink()
        
        for file_path in processed_dir.glob(f"*_{document_id}.md"):
            if file_path.exists():
                file_path.unlink()
        
        return {"message": "Document deleted successfully"}
        
    except Exception as e:
        print(f"Delete error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Deletion failed: {str(e)}")


# Add the original endpoints from v1 for compatibility
@app.get("/api/items")
def list_items():
    """Legacy endpoint for frontend compatibility."""
    return [
        {"id": 1, "name": "Document Processing"},
        {"id": 2, "name": "LLM Integration"},
        {"id": 3, "name": "Quality Assessment"},
    ]


# Error handler
@app.exception_handler(ValidationError)
async def validation_exception_handler(request, exc):
    return HTTPException(
        status_code=422,
        detail=ErrorResponse(
            error="Validation Error",
            detail=str(exc),
            timestamp=datetime.now()
        ).dict()
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)