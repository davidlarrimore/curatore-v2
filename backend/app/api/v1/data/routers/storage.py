# ============================================================================
# backend/app/api/v1/routers/storage.py
# ============================================================================
"""
Object Storage Router for File Operations.

Provides endpoints for:
- Storage browsing and management
- Artifact tracking and management
- File/folder management operations

Uses integrated MinIO service (no separate microservice needed).
All file operations are proxied through the backend for security and simplicity.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

import fastapi
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.v1.data.schemas import (
    ArtifactResponse,
    BrowseResponse,
    BucketInfo,
    BucketsListResponse,
    BulkDeleteArtifactsRequest,
    BulkDeleteArtifactsResponse,
    BulkDeleteResultItem,
    ConfirmUploadResponse,
    CreateFolderRequest,
    CreateFolderResponse,
    DeleteFileResponse,
    DeleteFolderResponse,
    MoveFilesRequest,
    MoveFilesResponse,
    ProtectedBucketsResponse,
    RenameFileRequest,
    RenameFileResponse,
    StorageObjectInfo,
)
from app.config import settings
from app.core.database.models import Asset, User
from app.core.ingestion.upload_integration_service import upload_integration_service
from app.core.shared.artifact_service import artifact_service
from app.core.shared.database_service import database_service
from app.core.storage.minio_service import get_minio_service
from app.dependencies import get_current_user

logger = logging.getLogger("curatore.api.storage")

router = APIRouter(prefix="/storage", tags=["storage"])


def _is_storage_enabled() -> bool:
    """Check if object storage is enabled."""
    return settings.use_object_storage


def _require_storage_enabled():
    """Raise 400 if object storage is not enabled."""
    if not _is_storage_enabled():
        raise HTTPException(
            status_code=400,
            detail="Object storage is not enabled. Set USE_OBJECT_STORAGE=true to enable."
        )


# =========================================================================
# HEALTH CHECK (delegates to system health helper)
# =========================================================================

@router.get(
    "/health",
    summary="Check storage health",
    description="Check the health of the object storage service.",
)
async def get_storage_health():
    """Check object storage service health.

    Delegates to the system health helper for consistency.
    """
    from app.api.v1.admin.routers.system import _check_storage

    result = await _check_storage()
    # Map to the response shape the frontend expects
    status = result.get("status", "unhealthy")
    return {
        "status": status,
        "enabled": status not in ("not_enabled",),
        "provider_connected": result.get("provider_connected"),
        "buckets": result.get("buckets"),
        "error": result.get("error"),
    }


# =========================================================================
# UPLOAD
# =========================================================================

@router.post(
    "/upload/proxy",
    response_model=ConfirmUploadResponse,
    summary="Upload file through backend",
    description="Upload a file through the backend which stores it in object storage, "
                "creates an asset, and triggers extraction.",
)
async def proxy_upload(
    file: fastapi.UploadFile,
    current_user: User = Depends(get_current_user),
) -> ConfirmUploadResponse:
    """Upload file proxied through backend.

    Receives the file, uploads to MinIO, creates an asset record,
    and triggers extraction via the Run system.
    """
    _require_storage_enabled()

    import io

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="MinIO service unavailable")

    organization_id = current_user.organization_id

    document_id = str(uuid.uuid4())
    filename = file.filename or "unknown"
    object_key = f"{organization_id}/uploads/{document_id}-{filename}"

    bucket = settings.minio_bucket_uploads
    expires_at = datetime.utcnow() + timedelta(days=settings.file_retention_uploaded_days)

    try:
        async with database_service.get_session() as session:
            file_content = await file.read()
            file_size = len(file_content)

            artifact = await artifact_service.create_artifact(
                session=session,
                organization_id=organization_id,
                document_id=document_id,
                artifact_type="uploaded",
                bucket=bucket,
                object_key=object_key,
                original_filename=filename,
                content_type=file.content_type,
                file_size=file_size,
                status="pending",
                expires_at=expires_at,
            )
            await session.commit()
            await session.refresh(artifact)

            minio.put_object(
                bucket=bucket,
                key=object_key,
                data=io.BytesIO(file_content),
                length=file_size,
                content_type=file.content_type or "application/octet-stream",
            )

            info = minio.get_object_info(bucket, object_key)

            artifact = await artifact_service.update_artifact_status(
                session=session,
                artifact_id=artifact.id,
                status="available",
                file_size=info.get("size") if info else file_size,
                etag=info.get("etag") if info else None,
            )

            try:
                asset, run, extraction = await upload_integration_service.create_asset_and_trigger_extraction(
                    session=session,
                    artifact=artifact,
                    uploader_id=current_user.id,
                    additional_metadata={
                        "upload_type": "proxy",
                        "document_id": document_id,
                    },
                )
                await session.commit()

                logger.info(
                    f"Created asset {asset.id}, run {run.id}, "
                    f"extraction {extraction.id} for document {document_id}"
                )
            except Exception as e:
                logger.error(f"Asset creation failed for document {document_id}: {e}")

            logger.info(
                f"Upload complete for document={document_id}, "
                f"artifact={artifact.id}, size={file_size}"
            )

            return ConfirmUploadResponse(
                document_id=document_id,
                artifact_id=str(artifact.id),
                status=artifact.status,
                filename=filename,
                file_size=file_size,
                etag=artifact.etag,
            )

    except Exception as e:
        logger.error(f"Error uploading: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# ARTIFACT MANAGEMENT
# =========================================================================

@router.get(
    "/artifacts/{artifact_id}",
    response_model=ArtifactResponse,
    summary="Get artifact details",
    description="Get details of a specific artifact.",
)
async def get_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
) -> ArtifactResponse:
    """Get artifact details by ID."""
    _require_storage_enabled()

    try:
        artifact_uuid = UUID(artifact_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid artifact_id format")

    async with database_service.get_session() as session:
        artifact = await artifact_service.get_artifact(session, artifact_uuid)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

        # Verify organization access
        if artifact.organization_id != current_user.organization_id:
            raise HTTPException(status_code=404, detail="Artifact not found")

        return ArtifactResponse(
            id=str(artifact.id),
            organization_id=str(artifact.organization_id),
            document_id=artifact.document_id,
            job_id=str(artifact.job_id) if artifact.job_id else None,
            artifact_type=artifact.artifact_type,
            bucket=artifact.bucket,
            object_key=artifact.object_key,
            original_filename=artifact.original_filename,
            content_type=artifact.content_type,
            file_size=artifact.file_size,
            etag=artifact.etag,
            status=artifact.status,
            created_at=artifact.created_at,
            updated_at=artifact.updated_at,
            expires_at=artifact.expires_at,
        )


@router.get(
    "/artifacts",
    response_model=list[ArtifactResponse],
    summary="List all artifacts",
    description="List all artifacts for the current organization.",
)
async def list_artifacts(
    artifact_type: Optional[str] = Query(None, description="Filter by artifact type (uploaded, processed, temp)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of artifacts to return"),
    offset: int = Query(0, ge=0, description="Number of artifacts to skip"),
    current_user: User = Depends(get_current_user),
) -> list[ArtifactResponse]:
    """List all artifacts for the current organization."""
    _require_storage_enabled()

    organization_id = current_user.organization_id

    async with database_service.get_session() as session:
        artifacts = await artifact_service.list_artifacts_by_organization(
            session=session,
            organization_id=organization_id,
            artifact_type=artifact_type,
            limit=limit,
            offset=offset,
        )

        return [
            ArtifactResponse(
                id=str(a.id),
                organization_id=str(a.organization_id),
                document_id=a.document_id,
                job_id=str(a.job_id) if a.job_id else None,
                artifact_type=a.artifact_type,
                bucket=a.bucket,
                object_key=a.object_key,
                original_filename=a.original_filename,
                content_type=a.content_type,
                file_size=a.file_size,
                etag=a.etag,
                status=a.status,
                created_at=a.created_at,
                updated_at=a.updated_at,
                expires_at=a.expires_at,
            )
            for a in artifacts
        ]


@router.get(
    "/artifacts/document/{document_id}",
    response_model=list[ArtifactResponse],
    summary="List artifacts for document",
    description="List all artifacts associated with a document.",
)
async def list_document_artifacts(
    document_id: str,
    current_user: User = Depends(get_current_user),
) -> list[ArtifactResponse]:
    """List all artifacts for a document."""
    _require_storage_enabled()

    organization_id = current_user.organization_id

    async with database_service.get_session() as session:
        artifacts = await artifact_service.get_artifacts_by_document(
            session=session,
            document_id=document_id,
            organization_id=organization_id,
        )

        return [
            ArtifactResponse(
                id=str(a.id),
                organization_id=str(a.organization_id),
                document_id=a.document_id,
                job_id=str(a.job_id) if a.job_id else None,
                artifact_type=a.artifact_type,
                bucket=a.bucket,
                object_key=a.object_key,
                original_filename=a.original_filename,
                content_type=a.content_type,
                file_size=a.file_size,
                etag=a.etag,
                status=a.status,
                created_at=a.created_at,
                updated_at=a.updated_at,
                expires_at=a.expires_at,
            )
            for a in artifacts
        ]


@router.delete(
    "/artifacts/{artifact_id}",
    summary="Delete artifact",
    description="Delete an artifact and its storage object.",
)
async def delete_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Delete an artifact and its storage object."""
    _require_storage_enabled()

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="MinIO service unavailable")

    try:
        artifact_uuid = UUID(artifact_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid artifact_id format")

    async with database_service.get_session() as session:
        artifact = await artifact_service.get_artifact(session, artifact_uuid)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

        # Verify organization access
        if artifact.organization_id != current_user.organization_id:
            raise HTTPException(status_code=404, detail="Artifact not found")

        try:
            # Delete from storage
            minio.delete_object(artifact.bucket, artifact.object_key)

            # Mark as deleted in database
            await artifact_service.update_artifact_status(
                session=session,
                artifact_id=artifact_uuid,
                status="deleted",
            )
            await session.commit()

            logger.info(f"Deleted artifact {artifact_id} for document {artifact.document_id}")

            return {
                "deleted": True,
                "artifact_id": artifact_id,
                "document_id": artifact.document_id,
            }

        except Exception as e:
            logger.error(f"Error deleting artifact: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/artifacts/bulk-delete",
    response_model=BulkDeleteArtifactsResponse,
    summary="Bulk delete artifacts",
    description="Delete multiple artifacts and their storage objects in a single request.",
)
async def bulk_delete_artifacts(
    request: BulkDeleteArtifactsRequest,
    current_user: User = Depends(get_current_user),
) -> BulkDeleteArtifactsResponse:
    """Delete multiple artifacts and their storage objects."""
    _require_storage_enabled()

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="MinIO service unavailable")

    results: List[BulkDeleteResultItem] = []
    succeeded = 0
    failed = 0

    async with database_service.get_session() as session:
        for artifact_id_str in request.artifact_ids:
            try:
                # Validate UUID format
                try:
                    artifact_uuid = UUID(artifact_id_str)
                except ValueError:
                    results.append(BulkDeleteResultItem(
                        artifact_id=artifact_id_str,
                        document_id=None,
                        success=False,
                        error="Invalid artifact_id format"
                    ))
                    failed += 1
                    continue

                # Get artifact
                artifact = await artifact_service.get_artifact(session, artifact_uuid)
                if not artifact:
                    results.append(BulkDeleteResultItem(
                        artifact_id=artifact_id_str,
                        document_id=None,
                        success=False,
                        error="Artifact not found"
                    ))
                    failed += 1
                    continue

                # Verify organization access
                if artifact.organization_id != current_user.organization_id:
                    results.append(BulkDeleteResultItem(
                        artifact_id=artifact_id_str,
                        document_id=artifact.document_id,
                        success=False,
                        error="Access denied"
                    ))
                    failed += 1
                    continue

                # Delete from storage
                try:
                    minio.delete_object(artifact.bucket, artifact.object_key)
                except Exception as storage_error:
                    logger.warning(f"Storage deletion failed for {artifact_id_str}: {storage_error}")
                    # Continue with database update even if storage delete fails

                # Mark as deleted in database
                await artifact_service.update_artifact_status(
                    session=session,
                    artifact_id=artifact_uuid,
                    status="deleted",
                )

                results.append(BulkDeleteResultItem(
                    artifact_id=artifact_id_str,
                    document_id=artifact.document_id,
                    success=True,
                    error=None
                ))
                succeeded += 1

                logger.info(f"Deleted artifact {artifact_id_str} for document {artifact.document_id}")

            except Exception as e:
                logger.error(f"Error deleting artifact {artifact_id_str}: {e}")
                results.append(BulkDeleteResultItem(
                    artifact_id=artifact_id_str,
                    document_id=None,
                    success=False,
                    error=str(e)
                ))
                failed += 1

        # Commit all database changes
        await session.commit()

    return BulkDeleteArtifactsResponse(
        total=len(request.artifact_ids),
        succeeded=succeeded,
        failed=failed,
        results=results
    )


# =========================================================================
# STORAGE BROWSING
# =========================================================================

@router.get(
    "/browse",
    response_model=BucketsListResponse,
    summary="List accessible buckets",
    description="List all storage buckets accessible to the user with display names.",
)
async def list_buckets(
    current_user: User = Depends(get_current_user),
) -> BucketsListResponse:
    """List all accessible storage buckets with metadata."""
    _require_storage_enabled()

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="MinIO service unavailable")

    try:
        bucket_list = minio.list_accessible_buckets()

        buckets = [
            BucketInfo(
                name=b["name"],
                display_name=b["display_name"],
                is_protected=b["is_protected"],
                is_default=b["is_default"],
            )
            for b in bucket_list
        ]

        return BucketsListResponse(
            buckets=buckets,
            default_bucket=minio.bucket_uploads,
        )

    except Exception as e:
        logger.error(f"Error listing buckets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/browse/{bucket}",
    response_model=BrowseResponse,
    summary="Browse bucket contents",
    description="List folders and files at a specific path within a bucket.",
)
async def browse_bucket(
    bucket: str,
    prefix: str = Query(default="", description="Folder prefix to browse (e.g., 'org_123/workspace/')"),
    current_user: User = Depends(get_current_user),
) -> BrowseResponse:
    """Browse bucket contents at a specific path."""
    _require_storage_enabled()

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="MinIO service unavailable")

    # Verify bucket exists
    if not minio.bucket_exists(bucket):
        raise HTTPException(status_code=404, detail=f"Bucket not found: {bucket}")

    # Validate that non-admin users can only browse within their organization prefix
    organization_id = str(current_user.organization_id)
    if current_user.role != "org_admin" and prefix and not prefix.startswith(f"{organization_id}/"):
        raise HTTPException(
            status_code=403,
            detail=f"You can only browse within your organization prefix: {organization_id}/"
        )

    # If browsing root (empty prefix), automatically scope to user's organization for non-admins
    scoped_prefix = prefix
    if current_user.role != "org_admin" and not prefix:
        scoped_prefix = f"{organization_id}/"

    try:
        result = minio.browse_bucket(bucket, scoped_prefix)

        # Convert ObjectInfo to StorageObjectInfo
        files = []
        file_keys = []
        for obj in result.objects:
            # Extract filename from key
            filename = obj.key.split("/")[-1] if "/" in obj.key else obj.key
            if not filename:
                continue  # Skip folder markers

            files.append(StorageObjectInfo(
                key=obj.key,
                filename=filename,
                size=obj.size,
                content_type=obj.content_type,
                etag=obj.etag,
                last_modified=obj.last_modified,
                is_folder=obj.is_folder,
            ))
            file_keys.append(obj.key)

        # Look up asset IDs for files in this folder
        if file_keys:
            async with database_service.get_session() as session:
                asset_result = await session.execute(
                    select(Asset.id, Asset.raw_object_key).where(
                        Asset.raw_bucket == bucket,
                        Asset.raw_object_key.in_(file_keys),
                    )
                )
                key_to_asset = {row.raw_object_key: str(row.id) for row in asset_result}
                for f in files:
                    f.asset_id = key_to_asset.get(f.key)

        return BrowseResponse(
            bucket=result.bucket,
            prefix=result.prefix,
            folders=result.folders,
            files=files,
            is_protected=result.is_protected,
            parent_path=result.parent_prefix,
        )

    except Exception as e:
        logger.error(f"Error browsing bucket {bucket}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/buckets/protected",
    response_model=ProtectedBucketsResponse,
    summary="List protected buckets",
    description="Get list of bucket names that are protected (read-only).",
)
async def get_protected_buckets(
    current_user: User = Depends(get_current_user),
) -> ProtectedBucketsResponse:
    """Get list of protected bucket names."""
    _require_storage_enabled()

    from app.core.storage.minio_service import PROTECTED_BUCKETS

    return ProtectedBucketsResponse(
        protected_buckets=list(PROTECTED_BUCKETS)
    )


# =========================================================================
# FOLDER MANAGEMENT
# =========================================================================

@router.post(
    "/folders",
    response_model=CreateFolderResponse,
    summary="Create folder",
    description="Create a new folder (virtual prefix) in a bucket.",
)
async def create_folder(
    request: CreateFolderRequest,
    current_user: User = Depends(get_current_user),
) -> CreateFolderResponse:
    """Create a new folder in storage."""
    _require_storage_enabled()

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="MinIO service unavailable")

    # Verify bucket exists
    if not minio.bucket_exists(request.bucket):
        raise HTTPException(status_code=404, detail=f"Bucket not found: {request.bucket}")

    # Check if bucket is protected
    if minio.is_bucket_protected(request.bucket):
        raise HTTPException(
            status_code=403,
            detail=f"Cannot create folders in protected bucket: {request.bucket}"
        )

    # Validate that path starts with user's organization prefix
    organization_id = str(current_user.organization_id)
    if not request.path.startswith(f"{organization_id}/"):
        raise HTTPException(
            status_code=403,
            detail=f"You can only create folders within your organization prefix: {organization_id}/"
        )

    try:
        logger.info(f"Creating folder in bucket={request.bucket}, path={request.path!r}")
        minio.create_folder(request.bucket, request.path)

        # Ensure path ends with /
        folder_path = request.path if request.path.endswith("/") else request.path + "/"

        logger.info(f"Created folder {request.bucket}/{folder_path}")

        return CreateFolderResponse(
            success=True,
            bucket=request.bucket,
            path=folder_path,
        )

    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating folder: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/folders/{bucket}/{path:path}",
    response_model=DeleteFolderResponse,
    summary="Delete folder",
    description="Delete a folder and optionally its contents.",
)
async def delete_folder(
    bucket: str,
    path: str,
    recursive: bool = Query(default=False, description="Delete folder contents recursively"),
    current_user: User = Depends(get_current_user),
) -> DeleteFolderResponse:
    """Delete a folder from storage."""
    _require_storage_enabled()

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="MinIO service unavailable")

    # Verify bucket exists
    if not minio.bucket_exists(bucket):
        raise HTTPException(status_code=404, detail=f"Bucket not found: {bucket}")

    # Check if bucket is protected
    if minio.is_bucket_protected(bucket):
        raise HTTPException(
            status_code=403,
            detail=f"Cannot delete folders in protected bucket: {bucket}"
        )

    # Validate that path starts with user's organization prefix
    organization_id = str(current_user.organization_id)
    if not path.startswith(f"{organization_id}/"):
        raise HTTPException(
            status_code=403,
            detail=f"You can only delete folders within your organization prefix: {organization_id}/"
        )

    try:
        deleted_count, failed_count = minio.delete_folder(bucket, path, recursive=recursive)

        # Ensure path ends with /
        folder_path = path if path.endswith("/") else path + "/"

        logger.info(f"Deleted folder {bucket}/{folder_path}: {deleted_count} deleted, {failed_count} failed")

        return DeleteFolderResponse(
            success=failed_count == 0,
            bucket=bucket,
            path=folder_path,
            deleted_count=deleted_count,
            failed_count=failed_count,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting folder: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/files/{bucket}/{key:path}",
    response_model=DeleteFileResponse,
    summary="Delete file",
    description="Delete a file from storage by bucket and key.",
)
async def delete_file(
    bucket: str,
    key: str,
    current_user: User = Depends(get_current_user),
) -> DeleteFileResponse:
    """Delete a file from storage by bucket and key."""
    _require_storage_enabled()

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="MinIO service unavailable")

    # Verify bucket exists
    if not minio.bucket_exists(bucket):
        raise HTTPException(status_code=404, detail=f"Bucket not found: {bucket}")

    # Check if bucket is protected
    if minio.is_bucket_protected(bucket):
        raise HTTPException(
            status_code=403,
            detail=f"Cannot delete files in protected bucket: {bucket}"
        )

    # Validate that file path starts with user's organization prefix
    organization_id = str(current_user.organization_id)
    if not key.startswith(f"{organization_id}/"):
        raise HTTPException(
            status_code=403,
            detail=f"You can only delete files within your organization prefix: {organization_id}/"
        )

    artifact_deleted = False

    async with database_service.get_session() as session:
        try:
            # Try to find artifact by object_key
            artifacts = await artifact_service.list_artifacts_by_organization(
                session=session,
                organization_id=current_user.organization_id,
                artifact_type=None,
                limit=1000,
                offset=0,
            )

            # Find artifact with matching object_key
            matching_artifact = None
            for artifact in artifacts:
                if artifact.object_key == key and artifact.bucket == bucket:
                    matching_artifact = artifact
                    break

            # Get the parent folder path before deleting
            parent_folder = None
            if "/" in key:
                parent_folder = key.rsplit("/", 1)[0] + "/"

            # Check if this is the last file in the folder (if in a folder)
            preserve_folder = False
            if parent_folder:
                # List all objects in the parent folder
                folder_objects = list(minio.client.list_objects(
                    bucket,
                    prefix=parent_folder,
                    recursive=False
                ))

                # Count non-folder files (excluding the one being deleted and folder markers)
                remaining_files = [
                    obj for obj in folder_objects
                    if not obj.is_dir
                    and obj.object_name != key
                    and not obj.object_name.endswith("/")
                ]

                # If this is the last file, preserve the folder
                if len(remaining_files) == 0:
                    preserve_folder = True
                    logger.info(f"Last file in folder {parent_folder}, will preserve folder marker")

            # Delete from storage
            minio.delete_object(bucket, key)

            # If this was the last file in a folder, ensure folder marker exists
            if preserve_folder and parent_folder:
                try:
                    # Check if folder marker exists
                    folder_exists = minio.object_exists(bucket, parent_folder)
                    if not folder_exists:
                        # Create folder marker to preserve the folder structure
                        from io import BytesIO
                        minio.client.put_object(
                            bucket_name=bucket,
                            object_name=parent_folder,
                            data=BytesIO(b""),
                            length=0,
                            content_type="application/x-directory",
                        )
                        logger.info(f"Created folder marker to preserve folder: {bucket}/{parent_folder}")
                except Exception as folder_error:
                    logger.warning(f"Failed to preserve folder marker: {folder_error}")

            # If artifact exists, mark as deleted
            if matching_artifact:
                await artifact_service.update_artifact_status(
                    session=session,
                    artifact_id=matching_artifact.id,
                    status="deleted",
                )
                await session.commit()
                artifact_deleted = True
                logger.info(f"Deleted artifact {matching_artifact.id} for file {bucket}/{key}")

            logger.info(f"Deleted file {bucket}/{key}, artifact_deleted={artifact_deleted}")

            return DeleteFileResponse(
                success=True,
                bucket=bucket,
                key=key,
                artifact_deleted=artifact_deleted,
            )

        except Exception as e:
            logger.error(f"Error deleting file {bucket}/{key}: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/folders/upload",
    response_model=Dict[str, Any],
    summary="Upload file to folder",
    description="Upload a file directly to a specific folder path (simple upload without artifact tracking).",
)
async def upload_to_folder(
    bucket: str = fastapi.Form(...),
    prefix: str = fastapi.Form(default=""),
    file: fastapi.UploadFile = fastapi.File(...),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Upload a file directly to a folder path.

    Unlike the document upload, this creates a simple file in storage
    without creating artifact records. Used for general file management.
    """
    _require_storage_enabled()

    import io

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="MinIO service unavailable")

    # Verify bucket exists
    if not minio.bucket_exists(bucket):
        raise HTTPException(status_code=404, detail=f"Bucket not found: {bucket}")

    # Check if bucket is protected
    if minio.is_bucket_protected(bucket):
        raise HTTPException(
            status_code=403,
            detail=f"Cannot upload to protected bucket: {bucket}"
        )

    filename = file.filename or "unknown"

    # Normalize prefix (ensure trailing slash if not empty)
    if prefix and not prefix.endswith("/"):
        prefix = prefix + "/"

    # Build object key
    object_key = f"{prefix}{filename}"

    try:
        # Read file content
        file_content = await file.read()
        file_size = len(file_content)

        # Upload to MinIO
        minio.put_object(
            bucket=bucket,
            key=object_key,
            data=io.BytesIO(file_content),
            length=file_size,
            content_type=file.content_type or "application/octet-stream",
        )

        logger.info(f"Uploaded file to {bucket}/{object_key} ({file_size} bytes)")

        artifact_id = None
        document_id = None

        if bucket == settings.minio_bucket_uploads:
            try:
                expires_at = datetime.utcnow() + timedelta(days=settings.file_retention_uploaded_days)
                content_type = file.content_type or "application/octet-stream"

                async with database_service.get_session() as session:
                    # Check if an artifact already exists for this object_key
                    # (in case someone re-uploads to the same path)
                    artifacts = await artifact_service.list_artifacts_by_organization(
                        session=session,
                        organization_id=current_user.organization_id,
                        artifact_type="uploaded",
                        limit=1000,
                        offset=0,
                    )
                    existing = None
                    for artifact in artifacts:
                        if artifact.object_key == object_key and artifact.bucket == bucket:
                            existing = artifact
                            break

                    if existing:
                        # Reuse existing document_id for same path
                        document_id = existing.document_id
                        artifact = await artifact_service.update_artifact_status(
                            session=session,
                            artifact_id=existing.id,
                            status="available",
                            bucket=bucket,
                            object_key=object_key,
                            original_filename=filename,
                            content_type=content_type,
                            file_size=file_size,
                            expires_at=expires_at,
                        )
                    else:
                        # Generate a new UUID for new documents
                        document_id = str(uuid.uuid4())
                        artifact = await artifact_service.create_artifact(
                            session=session,
                            organization_id=current_user.organization_id,
                            document_id=document_id,
                            artifact_type="uploaded",
                            bucket=bucket,
                            object_key=object_key,
                            original_filename=filename,
                            content_type=content_type,
                            file_size=file_size,
                            status="available",
                            expires_at=expires_at,
                        )
                    await session.commit()
                    await session.refresh(artifact)
                    artifact_id = str(artifact.id)

                logger.info(
                    f"Registered upload artifact for document={document_id}, "
                    f"artifact={artifact_id}, org={current_user.organization_id}"
                )
            except Exception as e:
                logger.error(f"Failed to register upload artifact for {bucket}/{object_key}: {e}")

        return {
            "success": True,
            "bucket": bucket,
            "prefix": prefix,
            "filename": filename,
            "object_key": object_key,
            "file_size": file_size,
            "document_id": document_id,
            "artifact_id": artifact_id,
        }

    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# FILE OPERATIONS
# =========================================================================

@router.post(
    "/files/move",
    response_model=MoveFilesResponse,
    summary="Move files",
    description="Move files to a different folder.",
)
async def move_files(
    request: MoveFilesRequest,
    current_user: User = Depends(get_current_user),
) -> MoveFilesResponse:
    """Move files to a different location."""
    _require_storage_enabled()

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="MinIO service unavailable")

    # Verify destination bucket exists
    if not minio.bucket_exists(request.destination_bucket):
        raise HTTPException(
            status_code=404,
            detail=f"Destination bucket not found: {request.destination_bucket}"
        )

    # Check if destination bucket is protected
    if minio.is_bucket_protected(request.destination_bucket):
        raise HTTPException(
            status_code=403,
            detail=f"Cannot move files to protected bucket: {request.destination_bucket}"
        )

    # Validate that destination prefix starts with user's organization prefix
    organization_id = str(current_user.organization_id)
    dest_prefix = request.destination_prefix or ""
    if dest_prefix and not dest_prefix.startswith(f"{organization_id}/"):
        raise HTTPException(
            status_code=403,
            detail=f"You can only move files to destinations within your organization prefix: {organization_id}/"
        )

    moved_artifacts = []
    failed_artifacts = []

    async with database_service.get_session() as session:
        for artifact_id in request.artifact_ids:
            try:
                artifact_uuid = UUID(artifact_id)
                artifact = await artifact_service.get_artifact(session, artifact_uuid)

                if not artifact:
                    failed_artifacts.append(artifact_id)
                    continue

                # Verify organization access
                if artifact.organization_id != current_user.organization_id:
                    failed_artifacts.append(artifact_id)
                    continue

                # Build new key
                dest_prefix = request.destination_prefix
                if dest_prefix and not dest_prefix.endswith("/"):
                    dest_prefix = dest_prefix + "/"
                new_key = dest_prefix + artifact.original_filename

                # Move object in storage
                minio.move_object(artifact.bucket, artifact.object_key, new_key)

                # Update artifact in database
                artifact.bucket = request.destination_bucket
                artifact.object_key = new_key
                await session.commit()

                moved_artifacts.append(artifact_id)
                logger.info(f"Moved artifact {artifact_id} to {request.destination_bucket}/{new_key}")

            except Exception as e:
                logger.error(f"Failed to move artifact {artifact_id}: {e}")
                failed_artifacts.append(artifact_id)

    return MoveFilesResponse(
        moved_count=len(moved_artifacts),
        failed_count=len(failed_artifacts),
        moved_artifacts=moved_artifacts,
        failed_artifacts=failed_artifacts,
    )


@router.post(
    "/files/rename",
    response_model=RenameFileResponse,
    summary="Rename file",
    description="Rename a file in storage.",
)
async def rename_file(
    request: RenameFileRequest,
    current_user: User = Depends(get_current_user),
) -> RenameFileResponse:
    """Rename a file in storage."""
    _require_storage_enabled()

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="MinIO service unavailable")

    try:
        artifact_uuid = UUID(request.artifact_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid artifact_id format")

    async with database_service.get_session() as session:
        artifact = await artifact_service.get_artifact(session, artifact_uuid)

        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")

        # Verify organization access
        if artifact.organization_id != current_user.organization_id:
            raise HTTPException(status_code=404, detail="Artifact not found")

        # Check if bucket is protected
        if minio.is_bucket_protected(artifact.bucket):
            raise HTTPException(
                status_code=403,
                detail=f"Cannot rename files in protected bucket: {artifact.bucket}"
            )

        try:
            old_name = artifact.original_filename
            old_key = artifact.object_key

            # Build new key (same directory, new filename)
            key_parts = old_key.rsplit("/", 1)
            if len(key_parts) > 1:
                new_key = key_parts[0] + "/" + request.new_name
            else:
                new_key = request.new_name

            # Rename in storage
            minio.rename_object(artifact.bucket, old_key, new_key)

            # Update artifact
            artifact.object_key = new_key
            artifact.original_filename = request.new_name
            await session.commit()

            logger.info(f"Renamed artifact {request.artifact_id}: {old_name} -> {request.new_name}")

            return RenameFileResponse(
                success=True,
                artifact_id=request.artifact_id,
                old_name=old_name,
                new_name=request.new_name,
                new_key=new_key,
            )

        except Exception as e:
            logger.error(f"Error renaming file: {e}")
            raise HTTPException(status_code=500, detail=str(e))




