# backend/app/api/v1/routers/documents.py
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ....config import settings
from ..models import (
    DocumentEditRequest,
    ProcessingOptions,
    BulkDownloadRequest,
    ZipArchiveInfo,
    V1ProcessingOptions,
    V1ProcessingResult,
)
from ....models import FileListResponse
from ....database.models import User
from ....dependencies import get_current_user, validate_document_id_param
from ....services.document_service import document_service
from ....models import BatchProcessingResult
from ....services.database_service import database_service
from ....celery_app import app as celery_app
from ....services.storage_service import storage_service
from ....services.zip_service import zip_service

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/documents/{document_id}/result", response_model=V1ProcessingResult, tags=["Results"])
async def get_processing_result(document_id: str = Depends(validate_document_id_param)):
    """Get processing result for a document."""
    result = storage_service.get_processing_result(document_id)
    if not result:
        raise HTTPException(status_code=404, detail="Processing result not found")
    return result

@router.get("/documents/content", tags=["Results"])
async def get_document_content_by_query(
    document_id: str = Query(..., description="Document ID or file path"),
    job_id: Optional[str] = Query(None, description="Optional job ID to retrieve job-specific processed content")
):
    """Get the content of a processed document from object storage using query parameters.

    This endpoint accepts document_id as a query parameter, making it compatible with
    file paths that contain slashes (e.g., 'folder/file.pdf').

    If job_id is provided, retrieves the processed content from that specific job's folder.
    This ensures the correct version is returned when a document has been processed by multiple jobs.
    """
    import logging
    logger = logging.getLogger("curatore.api")

    try:
        from ....services.minio_service import get_minio_service
        from ....services.artifact_service import artifact_service
        from uuid import UUID
        minio = get_minio_service()
        if not minio:
            raise HTTPException(status_code=503, detail="Object storage not available")

        # Get the processed artifact for this document
        async with database_service.get_session() as session:
            artifact = None

            # If job_id is provided, query by both document_id and job_id
            if job_id:
                try:
                    artifact = await artifact_service.get_artifact_by_document_and_job(
                        session=session,
                        document_id=document_id,
                        job_id=UUID(job_id),
                        artifact_type="processed",
                    )
                    if artifact:
                        logger.info(f"Found artifact for document {document_id} and job {job_id}")
                    else:
                        logger.warning(f"No artifact found for document {document_id} and job {job_id}, trying fallback")
                        # Fallback: try to find any processed artifact for this document
                        artifact = await artifact_service.get_artifact_by_document(
                            session=session,
                            document_id=document_id,
                            artifact_type="processed",
                        )
                        if artifact:
                            logger.info(f"Found fallback artifact for document {document_id} (job_id: {artifact.job_id})")
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid job_id format")
            else:
                # Fall back to document_id only (may return latest artifact if multiple exist)
                artifact = await artifact_service.get_artifact_by_document(
                    session=session,
                    document_id=document_id,
                    artifact_type="processed",
                )

            if not artifact:
                logger.error(f"No processed artifact found for document {document_id}")
                raise HTTPException(status_code=404, detail="Processed content not found in object storage")

        # Download content from object storage
        try:
            content_io = minio.get_object(artifact.bucket, artifact.object_key)
            content = content_io.getvalue().decode('utf-8')
            return {"content": content}
        except Exception as e:
            logger.error(f"Failed to download from object storage: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to download from object storage: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving document content: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving document content: {str(e)}")


@router.get("/documents/{document_id}/content", tags=["Results"])
async def get_document_content(
    document_id: str = Depends(validate_document_id_param),
    job_id: Optional[str] = Query(None, description="Optional job ID to retrieve job-specific processed content")
):
    """Get the content of a processed document from object storage (legacy path parameter version).

    NOTE: This endpoint does not work with document IDs that contain slashes (file paths).
    Use GET /documents/content?document_id=...&job_id=... instead for file paths.

    If job_id is provided, retrieves the processed content from that specific job's folder.
    This ensures the correct version is returned when a document has been processed by multiple jobs.
    """
    import logging
    logger = logging.getLogger("curatore.api")

    try:
        from ....services.minio_service import get_minio_service
        from ....services.artifact_service import artifact_service
        from uuid import UUID
        minio = get_minio_service()
        if not minio:
            raise HTTPException(status_code=503, detail="Object storage not available")

        # Get the processed artifact for this document
        async with database_service.get_session() as session:
            artifact = None

            # If job_id is provided, query by both document_id and job_id
            if job_id:
                try:
                    artifact = await artifact_service.get_artifact_by_document_and_job(
                        session=session,
                        document_id=document_id,
                        job_id=UUID(job_id),
                        artifact_type="processed",
                    )
                    if artifact:
                        logger.info(f"Found artifact for document {document_id} and job {job_id}")
                    else:
                        logger.warning(f"No artifact found for document {document_id} and job {job_id}, trying fallback")
                        # Fallback: try to find any processed artifact for this document
                        artifact = await artifact_service.get_artifact_by_document(
                            session=session,
                            document_id=document_id,
                            artifact_type="processed",
                        )
                        if artifact:
                            logger.info(f"Found fallback artifact for document {document_id} (job_id: {artifact.job_id})")
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid job_id format")
            else:
                # Fall back to document_id only (may return latest artifact if multiple exist)
                artifact = await artifact_service.get_artifact_by_document(
                    session=session,
                    document_id=document_id,
                    artifact_type="processed",
                )

            if not artifact:
                logger.error(f"No processed artifact found for document {document_id}")
                raise HTTPException(status_code=404, detail="Processed content not found in object storage")

        # Download content from object storage
        try:
            content_io = minio.get_object(artifact.bucket, artifact.object_key)
            content = content_io.getvalue().decode('utf-8')
            return {"content": content}
        except Exception as e:
            logger.error(f"Failed to download processed content from object storage: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to download content: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document content: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get content: {str(e)}")

def _strip_hash_prefix(filename: str) -> str:
    """Strip 32-character hex hash prefix from filename if present."""
    if not filename:
        return filename
    match = re.match(r'^[0-9a-f]{32}_(.+)$', filename, re.IGNORECASE)
    return match.group(1) if match else filename


@router.get("/documents/download", tags=["Results"])
async def download_document_by_query(
    document_id: str = Query(..., description="Document ID or file path"),
    job_id: Optional[str] = Query(None, description="Optional job ID to download job-specific processed file")
):
    """Download a processed document from object storage using query parameters.

    This endpoint accepts document_id as a query parameter, making it compatible with
    file paths that contain slashes (e.g., 'folder/file.pdf').

    If job_id is provided, downloads the processed file from that specific job's folder.
    This ensures the correct version is downloaded when a document has been processed by multiple jobs.
    """
    import io
    from fastapi.responses import StreamingResponse
    import logging
    from uuid import UUID
    logger = logging.getLogger("curatore.api")

    try:
        from ....services.minio_service import get_minio_service
        from ....services.artifact_service import artifact_service

        minio = get_minio_service()
        if not minio:
            raise HTTPException(status_code=503, detail="Object storage not available")

        # Get the processed artifact for this document
        async with database_service.get_session() as session:
            artifact = None

            # If job_id is provided, query by both document_id and job_id
            if job_id:
                try:
                    artifact = await artifact_service.get_artifact_by_document_and_job(
                        session=session,
                        document_id=document_id,
                        job_id=UUID(job_id),
                        artifact_type="processed",
                    )
                    if artifact:
                        logger.info(f"Found artifact for document {document_id} and job {job_id}")
                    else:
                        logger.warning(f"No artifact found for document {document_id} and job {job_id}, trying fallback")
                        # Fallback: try to find any processed artifact for this document
                        artifact = await artifact_service.get_artifact_by_document(
                            session=session,
                            document_id=document_id,
                            artifact_type="processed",
                        )
                        if artifact:
                            logger.info(f"Found fallback artifact for document {document_id} (job_id: {artifact.job_id})")
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid job_id format")
            else:
                # Fall back to document_id only (may return latest artifact if multiple exist)
                artifact = await artifact_service.get_artifact_by_document(
                    session=session,
                    document_id=document_id,
                    artifact_type="processed",
                )

            if not artifact:
                logger.error(f"No processed artifact found for document {document_id}")
                raise HTTPException(status_code=404, detail="Processed file not found in object storage")

        # Determine download filename
        original_filename = artifact.original_filename or f"{document_id}.md"
        clean_filename = _strip_hash_prefix(original_filename)
        download_name = f"{Path(clean_filename).stem}.md"

        # Download content from object storage
        try:
            content_io = minio.get_object(artifact.bucket, artifact.object_key)
            content = content_io.getvalue()

            return StreamingResponse(
                io.BytesIO(content),
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f'attachment; filename="{download_name}"',
                    "Content-Length": str(len(content)),
                }
            )
        except Exception as e:
            logger.error(f"Failed to download processed file from object storage: {e}")
            raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading document: {e}")
        raise HTTPException(status_code=500, detail=f"Error downloading document: {str(e)}")


@router.get("/documents/{document_id}/download", tags=["Results"])
async def download_document(
    document_id: str = Depends(validate_document_id_param),
    job_id: Optional[str] = Query(None, description="Optional job ID to download job-specific processed file")
):
    """Download a processed document from object storage (legacy path parameter version).

    NOTE: This endpoint does not work with document IDs that contain slashes (file paths).
    Use GET /documents/download?document_id=...&job_id=... instead for file paths.

    If job_id is provided, downloads the processed file from that specific job's folder.
    This ensures the correct version is downloaded when a document has been processed by multiple jobs.
    """
    import io
    from fastapi.responses import StreamingResponse
    import logging
    from uuid import UUID
    logger = logging.getLogger("curatore.api")

    try:
        from ....services.minio_service import get_minio_service
        from ....services.artifact_service import artifact_service

        minio = get_minio_service()
        if not minio:
            raise HTTPException(status_code=503, detail="Object storage not available")

        # Get the processed artifact for this document
        async with database_service.get_session() as session:
            artifact = None

            # If job_id is provided, query by both document_id and job_id
            if job_id:
                try:
                    artifact = await artifact_service.get_artifact_by_document_and_job(
                        session=session,
                        document_id=document_id,
                        job_id=UUID(job_id),
                        artifact_type="processed",
                    )
                    if artifact:
                        logger.info(f"Found artifact for document {document_id} and job {job_id}")
                    else:
                        logger.warning(f"No artifact found for document {document_id} and job {job_id}, trying fallback")
                        # Fallback: try to find any processed artifact for this document
                        artifact = await artifact_service.get_artifact_by_document(
                            session=session,
                            document_id=document_id,
                            artifact_type="processed",
                        )
                        if artifact:
                            logger.info(f"Found fallback artifact for document {document_id} (job_id: {artifact.job_id})")
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid job_id format")
            else:
                # Fall back to document_id only (may return latest artifact if multiple exist)
                artifact = await artifact_service.get_artifact_by_document(
                    session=session,
                    document_id=document_id,
                    artifact_type="processed",
                )

            if not artifact:
                logger.error(f"No processed artifact found for document {document_id}")
                raise HTTPException(status_code=404, detail="Processed file not found in object storage")

        # Determine download filename
        original_filename = artifact.original_filename or f"{document_id}.md"
        clean_filename = _strip_hash_prefix(original_filename)
        download_name = f"{Path(clean_filename).stem}.md"

        # Download content from object storage
        try:
            content_io = minio.get_object(artifact.bucket, artifact.object_key)
            content = content_io.getvalue()

            return StreamingResponse(
                io.BytesIO(content),
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f'attachment; filename="{download_name}"',
                    "Content-Length": str(len(content)),
                }
            )
        except Exception as e:
            logger.error(f"Failed to download processed file from object storage: {e}")
            raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

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

@router.get("/batch/{batch_id}/result", response_model=BatchProcessingResult, tags=["Results"])
async def get_batch_result(batch_id: str):
    """Get batch processing result."""
    result = storage_service.get_batch_result(batch_id)
    if not result:
        raise HTTPException(status_code=404, detail="Batch result not found")
    return result

@router.get("/documents/search", tags=["Documents"])
async def search_documents_by_filename(
    filename: str = Query(..., description="Filename to search for (partial match)"),
    artifact_type: Optional[str] = Query(None, description="Filter by artifact type (uploaded, processed, temp)"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of results (1-100)"),
    user: User = Depends(get_current_user)
):
    """
    Search for documents by filename.

    This endpoint provides a way to search for documents using their original filename
    instead of document_id. This is useful when you only know the filename and need
    to find the associated document_id.

    **Security**: Results are scoped to the current user's organization.

    **Example**:
    ```
    GET /api/v1/documents/search?filename=report.pdf&artifact_type=uploaded
    ```

    Returns:
    ```json
    {
        "results": [
            {
                "document_id": "550e8400-e29b-41d4-a716-446655440000",
                "filename": "annual_report.pdf",
                "artifact_type": "uploaded",
                "file_size": 1048576,
                "created_at": "2026-01-27T10:30:00Z"
            }
        ],
        "count": 1
    }
    ```
    """
    from ....services.artifact_service import artifact_service

    async with database_service.get_session() as session:
        # Search artifacts by filename (scoped to organization)
        artifacts = await artifact_service.search_by_filename(
            session=session,
            organization_id=user.organization_id,
            filename=filename,
            artifact_type=artifact_type,
            limit=limit
        )

        # Format results
        results = [
            {
                "document_id": artifact.document_id,
                "filename": artifact.original_filename,
                "artifact_type": artifact.artifact_type,
                "file_size": artifact.file_size,
                "content_type": artifact.content_type,
                "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
                "artifact_id": str(artifact.id)
            }
            for artifact in artifacts
        ]

        return {
            "results": results,
            "count": len(results),
            "query": {
                "filename": filename,
                "artifact_type": artifact_type,
                "limit": limit
            }
        }

@router.get("/documents", response_model=List[V1ProcessingResult], tags=["Results"])
async def list_processed_documents():
    """List all processed documents."""
    return storage_service.get_all_processing_results()

@router.delete("/documents/{document_id}", tags=["Documents"])
async def delete_document(document_id: str = Depends(validate_document_id_param)):
    """Delete a document and its processing results from object storage."""
    # Clear in-memory storage cache
    storage_service.delete_processing_result(document_id)

    # Delete artifacts from object storage
    try:
        from ....services.minio_service import get_minio_service
        from ....services.artifact_service import artifact_service
        from ....services.database_service import database_service

        minio = get_minio_service()
        deleted_count = 0

        if minio and minio.enabled:
            # Get all artifacts for this document
            async with database_service.get_session() as session:
                artifacts = await artifact_service.get_artifacts_by_document(session, document_id)

                for artifact in artifacts:
                    # Delete from MinIO
                    try:
                        minio.delete_object(artifact.bucket, artifact.object_key)
                        deleted_count += 1
                    except Exception:
                        pass  # Continue deleting other artifacts

                # Delete artifact records from database
                for artifact in artifacts:
                    try:
                        await artifact_service.delete_artifact(session, artifact.id)
                    except Exception:
                        pass

                # Commit deletions
                await session.commit()

        return {
            "success": True,
            "message": f"Document deleted successfully ({deleted_count} files removed from storage)"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")
