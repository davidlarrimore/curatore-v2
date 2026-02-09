# backend/app/api/v1/routers/assets.py
"""
Assets API Router for Phase 0.

Provides endpoints for querying assets, extraction status, and related runs.
"""

import io
import logging
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select, func

from app.core.database.models import User, Asset
from app.dependencies import get_current_user
from app.core.shared.database_service import database_service
from app.core.shared.asset_service import asset_service
from app.core.shared.run_service import run_service
from app.core.ingestion.extraction_result_service import extraction_result_service
from app.core.ingestion.upload_integration_service import upload_integration_service
from app.core.ingestion.extraction_queue_service import extraction_queue_service
from app.core.shared.artifact_service import artifact_service
from app.core.storage.zip_service import zip_service
from app.api.v1.data.schemas import (
    AssetResponse,
    AssetWithExtractionResponse,
    AssetVersionResponse,
    AssetVersionHistoryResponse,
    ExtractionResultResponse,
    RunResponse,
    AssetsListResponse,
    BulkUploadAnalysisResponse,
    BulkUploadFileInfo,
    BulkUploadApplyResponse,
    # Metadata models
    AssetMetadataResponse,
    AssetMetadataCreateRequest,
    AssetMetadataUpdateRequest,
    AssetMetadataListResponse,
)
from app.api.v1.ops.schemas import AssetQueueInfoResponse
from app.core.shared.status_mapper import get_unified_status, UnifiedStatus

logger = logging.getLogger("curatore.api.assets")

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get(
    "",
    response_model=AssetsListResponse,
    summary="List assets",
    description="List assets for the organization with optional filters.",
)
async def list_assets(
    source_type: Optional[str] = Query(None, description="Filter by source type (upload, sharepoint, etc.)"),
    status: Optional[str] = Query(None, description="Filter by status (pending, ready, failed, deleted)"),
    include_deleted: bool = Query(False, description="Include deleted assets (default: False)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
    current_user: User = Depends(get_current_user),
) -> AssetsListResponse:
    """List assets for the organization."""
    async with database_service.get_session() as session:
        assets = await asset_service.get_assets_by_organization(
            session=session,
            organization_id=current_user.organization_id,
            source_type=source_type,
            status=status,
            include_deleted=include_deleted,
            limit=limit,
            offset=offset,
        )

        total = await asset_service.count_assets_by_organization(
            session=session,
            organization_id=current_user.organization_id,
            source_type=source_type,
            status=status,
            include_deleted=include_deleted,
        )

        return AssetsListResponse(
            items=[
                AssetResponse(
                    id=str(a.id),
                    organization_id=str(a.organization_id),
                    source_type=a.source_type,
                    source_metadata=a.source_metadata or {},
                    original_filename=a.original_filename,
                    content_type=a.content_type,
                    file_size=a.file_size,
                    file_hash=a.file_hash,
                    raw_bucket=a.raw_bucket,
                    raw_object_key=a.raw_object_key,
                    status=a.status,
                    current_version_number=a.current_version_number,
                    created_at=a.created_at,
                    updated_at=a.updated_at,
                    created_by=str(a.created_by) if a.created_by else None,
                    extraction_tier=a.extraction_tier,
                    indexed_at=a.indexed_at,
                )
                for a in assets
            ],
            total=total,
            limit=limit,
            offset=offset,
        )


@router.get(
    "/health",
    summary="Get collection health metrics",
    description="Get organization-wide collection health metrics (Phase 2).",
)
async def get_collection_health(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Get collection health metrics for the organization.

    Returns organization-wide statistics including:
    - Total assets
    - Extraction coverage (percentage of assets with successful extraction)
    - Failed extractions count
    - Inactive assets count
    - Version distribution
    - Last updated timestamp

    Args:
        current_user: Authenticated user making the request

    Returns:
        Dict with collection health metrics

    Example:
        GET /api/v1/assets/health

        Response:
        {
            "total_assets": 150,
            "extraction_coverage": 92.0,
            "status_breakdown": {
                "ready": 138,
                "pending": 5,
                "failed": 2,
                "inactive": 5
            },
            "version_stats": {
                "multi_version_assets": 25,
                "total_versions": 180
            },
            "last_updated": "2026-01-28T12:00:00Z"
        }
    """
    async with database_service.get_session() as session:
        organization_id = current_user.organization_id

        # Total assets
        stmt = select(func.count(Asset.id)).where(
            Asset.organization_id == organization_id
        )
        result = await session.execute(stmt)
        total_assets = result.scalar() or 0

        # Status breakdown
        stmt = select(
            Asset.status,
            func.count(Asset.id)
        ).where(
            Asset.organization_id == organization_id
        ).group_by(Asset.status)
        result = await session.execute(stmt)
        status_counts = {row[0]: row[1] for row in result}

        # Version stats
        stmt = select(func.count(Asset.id)).where(
            Asset.organization_id == organization_id,
            Asset.current_version_number > 1
        )
        result = await session.execute(stmt)
        multi_version_assets = result.scalar() or 0

        stmt = select(func.sum(Asset.current_version_number)).where(
            Asset.organization_id == organization_id
        )
        result = await session.execute(stmt)
        total_versions = result.scalar() or 0

        # Last updated
        stmt = select(func.max(Asset.updated_at)).where(
            Asset.organization_id == organization_id
        )
        result = await session.execute(stmt)
        last_updated = result.scalar()

        # Calculate extraction coverage
        ready_count = status_counts.get('ready', 0)
        extraction_coverage = (ready_count / total_assets * 100) if total_assets > 0 else 0

        return {
            "total_assets": total_assets,
            "extraction_coverage": round(extraction_coverage, 1),
            "status_breakdown": {
                "ready": status_counts.get('ready', 0),
                "pending": status_counts.get('pending', 0),
                "failed": status_counts.get('failed', 0),
                "inactive": status_counts.get('inactive', 0),
            },
            "version_stats": {
                "multi_version_assets": multi_version_assets,
                "total_versions": int(total_versions) if total_versions else 0,
            },
            "last_updated": last_updated.isoformat() if last_updated else None,
        }


@router.get(
    "/{asset_id}",
    response_model=AssetResponse,
    summary="Get asset",
    description="Get asset details by ID.",
)
async def get_asset(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
) -> AssetResponse:
    """Get asset by ID."""
    async with database_service.get_session() as session:
        asset = await asset_service.get_asset(session=session, asset_id=asset_id)

        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        # Verify asset belongs to user's organization
        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        return AssetResponse(
            id=str(asset.id),
            organization_id=str(asset.organization_id),
            source_type=asset.source_type,
            source_metadata=asset.source_metadata or {},
            original_filename=asset.original_filename,
            content_type=asset.content_type,
            file_size=asset.file_size,
            file_hash=asset.file_hash,
            raw_bucket=asset.raw_bucket,
            raw_object_key=asset.raw_object_key,
            status=asset.status,
            current_version_number=asset.current_version_number,
            created_at=asset.created_at,
            updated_at=asset.updated_at,
            created_by=str(asset.created_by) if asset.created_by else None,
            extraction_tier=asset.extraction_tier,
            indexed_at=asset.indexed_at,
        )


@router.get(
    "/{asset_id}/extraction",
    response_model=AssetWithExtractionResponse,
    summary="Get asset with extraction",
    description="Get asset with its latest extraction result.",
)
async def get_asset_with_extraction(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
) -> AssetWithExtractionResponse:
    """Get asset with latest extraction result."""
    async with database_service.get_session() as session:
        result = await asset_service.get_asset_with_latest_extraction(
            session=session,
            asset_id=asset_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Asset not found")

        asset, extraction = result

        # Verify asset belongs to user's organization
        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        return AssetWithExtractionResponse(
            asset=AssetResponse(
                id=str(asset.id),
                organization_id=str(asset.organization_id),
                source_type=asset.source_type,
                source_metadata=asset.source_metadata or {},
                original_filename=asset.original_filename,
                content_type=asset.content_type,
                file_size=asset.file_size,
                file_hash=asset.file_hash,
                raw_bucket=asset.raw_bucket,
                raw_object_key=asset.raw_object_key,
                status=asset.status,
                current_version_number=asset.current_version_number,
                created_at=asset.created_at,
                updated_at=asset.updated_at,
                created_by=str(asset.created_by) if asset.created_by else None,
            ),
            extraction=ExtractionResultResponse(
                id=str(extraction.id),
                asset_id=str(extraction.asset_id),
                run_id=str(extraction.run_id),
                extractor_version=extraction.extractor_version,
                status=extraction.status,
                extracted_bucket=extraction.extracted_bucket,
                extracted_object_key=extraction.extracted_object_key,
                structure_metadata=extraction.structure_metadata,
                warnings=extraction.warnings or [],
                errors=extraction.errors or [],
                extraction_time_seconds=extraction.extraction_time_seconds,
                created_at=extraction.created_at,
            ) if extraction else None,
        )


@router.get(
    "/{asset_id}/runs",
    response_model=List[RunResponse],
    summary="Get runs for asset",
    description="Get all runs that operated on this asset.",
)
async def get_runs_for_asset(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
) -> List[RunResponse]:
    """Get runs for an asset."""
    async with database_service.get_session() as session:
        # Verify asset exists and belongs to user's organization
        asset = await asset_service.get_asset(session=session, asset_id=asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Get runs
        runs = await run_service.get_runs_by_asset(session=session, asset_id=asset_id)

        # Build responses with queue info
        responses = []
        for r in runs:
            # Get queue position for pending extraction runs
            queue_position = None
            if r.status == "pending" and r.run_type in ("extraction", "extraction_enhancement"):
                pos_info = await extraction_queue_service.get_queue_position(session, r.id)
                queue_position = pos_info.get("queue_position")

            responses.append(
                RunResponse(
                    id=str(r.id),
                    organization_id=str(r.organization_id),
                    run_type=r.run_type,
                    origin=r.origin,
                    status=r.status,
                    input_asset_ids=[str(aid) for aid in (r.input_asset_ids or [])],
                    config=r.config or {},
                    progress=r.progress,
                    results_summary=r.results_summary,
                    error_message=r.error_message,
                    created_at=r.created_at,
                    started_at=r.started_at,
                    completed_at=r.completed_at,
                    created_by=str(r.created_by) if r.created_by else None,
                    queue_position=queue_position,
                    queue_priority=r.queue_priority,
                )
            )

        return responses


@router.post(
    "/{asset_id}/reextract",
    response_model=RunResponse,
    summary="Re-extract asset",
    description="Manually trigger re-extraction for an asset (Phase 1).",
    status_code=202,
)
async def reextract_asset(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
) -> RunResponse:
    """
    Manually trigger re-extraction for an asset.

    Creates a new extraction run with origin="user" to track that this
    was a manual re-extraction request. The extraction will be queued
    for async processing via Celery.

    Args:
        asset_id: Asset UUID to re-extract
        current_user: Authenticated user making the request

    Returns:
        RunResponse with the new extraction run details

    Raises:
        404: Asset not found
        403: User doesn't have access to the asset
        400: Asset is not in a valid state for re-extraction
    """
    async with database_service.get_session() as session:
        # Verify asset exists and belongs to user's organization
        asset = await asset_service.get_asset(session=session, asset_id=asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Pre-check: Verify the raw file exists in object storage
        from app.core.storage.minio_service import get_minio_service
        from datetime import datetime
        minio = get_minio_service()
        if minio and asset.raw_bucket and asset.raw_object_key:
            if not minio.object_exists(asset.raw_bucket, asset.raw_object_key):
                # Mark asset as failed with clear error
                asset.status = "failed"
                asset.source_metadata = {
                    **(asset.source_metadata or {}),
                    "missing_file_detected_at": datetime.utcnow().isoformat(),
                    "missing_file_error": f"Raw file not found: {asset.raw_bucket}/{asset.raw_object_key}",
                }
                await session.commit()
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot re-extract: Raw file not found in storage. "
                           f"The file may have been deleted. Asset has been marked as failed."
                )

        # Trigger re-extraction
        try:
            run, extraction = await upload_integration_service.trigger_reextraction(
                session=session,
                asset_id=asset_id,
                user_id=current_user.id,
                extractor_version="markitdown-1.0",
            )

            logger.info(
                f"Manual re-extraction triggered for asset {asset_id} by user {current_user.id}: "
                f"run={run.id}, extraction={extraction.id}"
            )

            # Manually construct response with UUID to string conversion
            return RunResponse(
                id=str(run.id),
                organization_id=str(run.organization_id),
                run_type=run.run_type,
                origin=run.origin,
                status=run.status,
                input_asset_ids=[str(aid) for aid in (run.input_asset_ids or [])],
                config=run.config or {},
                progress=run.progress,
                results_summary=run.results_summary,
                error_message=run.error_message,
                created_at=run.created_at,
                started_at=run.started_at,
                completed_at=run.completed_at,
                created_by=str(run.created_by) if run.created_by else None,
            )

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/{asset_id}/versions",
    response_model=AssetVersionHistoryResponse,
    summary="Get asset version history",
    description="Get all versions for an asset (Phase 1).",
)
async def get_asset_versions(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
) -> AssetVersionHistoryResponse:
    """
    Get version history for an asset.

    Returns the asset along with all its versions, ordered by version number
    (newest first). Each version represents an immutable snapshot of the asset's
    raw content at a point in time.

    Args:
        asset_id: Asset UUID
        current_user: Authenticated user making the request

    Returns:
        AssetVersionHistoryResponse with asset and version list

    Raises:
        404: Asset not found
        403: User doesn't have access to the asset
    """
    async with database_service.get_session() as session:
        # Verify asset exists and belongs to user's organization
        asset = await asset_service.get_asset(session=session, asset_id=asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Get version history
        versions = await asset_service.get_asset_versions(session=session, asset_id=asset_id)

        # Get extraction results for each version
        # Build a map of version_id -> extraction_result for efficient lookup
        extraction_map = {}
        for v in versions:
            extraction = await extraction_result_service.get_latest_extraction_for_version(
                session=session,
                asset_version_id=v.id,
            )
            if extraction:
                extraction_map[v.id] = extraction

        # Build version responses with extraction info
        version_responses = []
        for v in versions:
            extraction = extraction_map.get(v.id)
            version_responses.append(
                AssetVersionResponse(
                    id=str(v.id),
                    asset_id=str(v.asset_id),
                    version_number=v.version_number,
                    raw_bucket=v.raw_bucket,
                    raw_object_key=v.raw_object_key,
                    file_size=v.file_size,
                    file_hash=v.file_hash,
                    content_type=v.content_type,
                    is_current=v.is_current,
                    created_at=v.created_at,
                    created_by=str(v.created_by) if v.created_by else None,
                    # Extraction info (permanent data from extraction_results)
                    extraction_status=extraction.status if extraction else None,
                    extraction_tier=extraction.extraction_tier if extraction else None,
                    extractor_version=extraction.extractor_version if extraction else None,
                    extraction_time_seconds=extraction.extraction_time_seconds if extraction else None,
                    extraction_created_at=extraction.created_at if extraction else None,
                    # Run link (may be null if run was purged)
                    extraction_run_id=str(extraction.run_id) if extraction and extraction.run_id else None,
                )
            )

        return AssetVersionHistoryResponse(
            asset=AssetResponse(
                id=str(asset.id),
                organization_id=str(asset.organization_id),
                source_type=asset.source_type,
                source_metadata=asset.source_metadata or {},
                original_filename=asset.original_filename,
                content_type=asset.content_type,
                file_size=asset.file_size,
                file_hash=asset.file_hash,
                raw_bucket=asset.raw_bucket,
                raw_object_key=asset.raw_object_key,
                status=asset.status,
                current_version_number=asset.current_version_number,
                created_at=asset.created_at,
                updated_at=asset.updated_at,
                created_by=str(asset.created_by) if asset.created_by else None,
            ),
            versions=version_responses,
            total_versions=len(versions),
        )


@router.get(
    "/{asset_id}/versions/{version_number}",
    response_model=AssetVersionResponse,
    summary="Get specific asset version",
    description="Get a specific version of an asset (Phase 1).",
)
async def get_asset_version(
    asset_id: UUID,
    version_number: int,
    current_user: User = Depends(get_current_user),
) -> AssetVersionResponse:
    """
    Get a specific version of an asset.

    Retrieves a specific version by its version number. Versions are numbered
    sequentially starting from 1.

    Args:
        asset_id: Asset UUID
        version_number: Version number to retrieve (1, 2, 3, ...)
        current_user: Authenticated user making the request

    Returns:
        AssetVersionResponse with version details

    Raises:
        404: Asset or version not found
        403: User doesn't have access to the asset
    """
    async with database_service.get_session() as session:
        # Verify asset exists and belongs to user's organization
        asset = await asset_service.get_asset(session=session, asset_id=asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Get specific version
        version = await asset_service.get_asset_version(
            session=session,
            asset_id=asset_id,
            version_number=version_number,
        )

        if not version:
            raise HTTPException(status_code=404, detail=f"Version {version_number} not found")

        return AssetVersionResponse(
            id=str(version.id),
            asset_id=str(version.asset_id),
            version_number=version.version_number,
            raw_bucket=version.raw_bucket,
            raw_object_key=version.raw_object_key,
            file_size=version.file_size,
            file_hash=version.file_hash,
            content_type=version.content_type,
            is_current=version.is_current,
            created_at=version.created_at,
            created_by=str(version.created_by) if version.created_by else None,
        )


# =========================================================================
# BULK UPLOAD ENDPOINTS (Phase 2)
# =========================================================================

@router.post(
    "/bulk-upload/preview",
    response_model=BulkUploadAnalysisResponse,
    summary="Preview bulk upload changes",
    description="Analyze bulk file upload and preview changes without persisting (Phase 2).",
)
async def preview_bulk_upload(
    files: List[UploadFile],
    source_type: str = Query("upload", description="Source type for the upload"),
    current_user: User = Depends(get_current_user),
) -> BulkUploadAnalysisResponse:
    """
    Preview bulk upload changes.

    Analyzes uploaded files and categorizes them as:
    - Unchanged: Files that match existing assets (same filename + content hash)
    - Updated: Files with same filename but different content
    - New: Files not seen before in organization
    - Missing: Assets in database but not in upload batch

    This endpoint does not persist any changes. Use the apply endpoint
    after reviewing the preview.

    Args:
        files: List of files to analyze
        source_type: Source type filter for matching existing assets
        current_user: Authenticated user making the request

    Returns:
        BulkUploadAnalysisResponse with categorized files and counts

    Example:
        POST /api/v1/assets/bulk-upload/preview
        Content-Type: multipart/form-data

        files: [file1.pdf, file2.pdf, file3.pdf]
        source_type: upload

        Response:
        {
            "unchanged": [...],
            "updated": [...],
            "new": [...],
            "missing": [...],
            "counts": {
                "unchanged": 5,
                "updated": 2,
                "new": 3,
                "missing": 1,
                "total_uploaded": 10
            }
        }
    """
    from app.core.ingestion.bulk_upload_service import bulk_upload_service

    # Read file contents
    file_list = []
    for file in files:
        content = await file.read()
        file_list.append((file.filename, content))
        await file.seek(0)  # Reset file pointer

    async with database_service.get_session() as session:
        analysis = await bulk_upload_service.analyze_bulk_upload(
            session=session,
            organization_id=current_user.organization_id,
            files=file_list,
            source_type=source_type,
        )

        # Convert analysis to response model
        return BulkUploadAnalysisResponse(
            unchanged=[BulkUploadFileInfo(**item) for item in analysis.unchanged],
            updated=[BulkUploadFileInfo(**item) for item in analysis.updated],
            new=[BulkUploadFileInfo(**item) for item in analysis.new],
            missing=[BulkUploadFileInfo(**item) for item in analysis.missing],
            counts=analysis.to_dict()["counts"],
        )


@router.post(
    "/bulk-upload/apply",
    response_model=BulkUploadApplyResponse,
    summary="Apply bulk upload changes",
    description="Apply bulk upload changes: create new assets, update existing, mark missing inactive (Phase 2).",
)
async def apply_bulk_upload(
    files: List[UploadFile],
    source_type: str = Query("upload", description="Source type for the upload"),
    mark_missing_inactive: bool = Query(True, description="Mark missing files as inactive"),
    current_user: User = Depends(get_current_user),
) -> BulkUploadApplyResponse:
    """
    Apply bulk upload changes.

    This endpoint:
    1. Creates new assets for new files (uploads to object storage + triggers extraction)
    2. Creates new asset versions for updated files (triggers re-extraction)
    3. Marks missing assets as inactive (optional, non-destructive)

    Unlike the preview endpoint, this persists all changes.

    Args:
        files: List of files to upload
        source_type: Source type for the upload
        mark_missing_inactive: Whether to mark missing assets as inactive
        current_user: Authenticated user making the request

    Returns:
        BulkUploadApplyResponse with analysis and applied changes

    Example:
        POST /api/v1/assets/bulk-upload/apply
        Content-Type: multipart/form-data

        files: [file1.pdf, file2.pdf, file3.pdf]
        source_type: upload
        mark_missing_inactive: true

        Response:
        {
            "analysis": {...},
            "created_assets": ["uuid1", "uuid2", "uuid3"],
            "updated_assets": ["uuid4", "uuid5"],
            "marked_inactive": ["uuid6"],
            "summary": {
                "created_count": 3,
                "updated_count": 2,
                "marked_inactive_count": 1
            }
        }
    """
    from app.core.ingestion.bulk_upload_service import bulk_upload_service
    from app.core.storage.minio_service import get_minio_service
    from app.core.shared.artifact_service import artifact_service
    from app.core.ingestion.upload_integration_service import upload_integration_service
    from app.config import settings
    from datetime import datetime, timedelta
    import io
    import uuid as uuid_lib

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="MinIO service unavailable")

    organization_id = current_user.organization_id

    # Read file contents
    file_list = []
    files_by_name = {}
    for file in files:
        content = await file.read()
        file_list.append((file.filename, content))
        files_by_name[file.filename] = {
            "content": content,
            "content_type": file.content_type,
        }
        await file.seek(0)  # Reset file pointer

    async with database_service.get_session() as session:
        # Analyze the upload
        analysis = await bulk_upload_service.analyze_bulk_upload(
            session=session,
            organization_id=organization_id,
            files=file_list,
            source_type=source_type,
        )

        created_assets = []
        updated_assets = []
        marked_inactive = []

        # Get bucket name from settings
        bucket = settings.minio_bucket_uploads
        expires_at = datetime.utcnow() + timedelta(days=settings.file_retention_uploaded_days)

        # Process NEW files
        for file_info in analysis.new:
            try:
                filename = file_info["filename"]
                file_data = files_by_name[filename]
                file_content = file_data["content"]
                file_size = len(file_content)
                content_type = file_data["content_type"]

                # Generate IDs
                document_id = str(uuid_lib.uuid4())
                object_key = f"{organization_id}/uploads/{document_id}-{filename}"

                # Create artifact record
                artifact = await artifact_service.create_artifact(
                    session=session,
                    organization_id=organization_id,
                    document_id=document_id,
                    artifact_type="uploaded",
                    bucket=bucket,
                    object_key=object_key,
                    original_filename=filename,
                    content_type=content_type,
                    file_size=file_size,
                    status="pending",
                    expires_at=expires_at,
                )
                await session.commit()
                await session.refresh(artifact)

                # Upload to MinIO
                minio.put_object(
                    bucket=bucket,
                    key=object_key,
                    data=io.BytesIO(file_content),
                    length=file_size,
                    content_type=content_type or "application/octet-stream",
                )

                # Update artifact status
                artifact = await artifact_service.update_artifact_status(
                    session=session,
                    artifact_id=artifact.id,
                    status="available",
                    file_size=file_size,
                )

                # Create Asset and trigger extraction
                asset, run, extraction = await upload_integration_service.create_asset_and_trigger_extraction(
                    session=session,
                    artifact=artifact,
                    uploader_id=current_user.id,
                    additional_metadata={
                        "upload_type": "bulk_upload",
                        "document_id": document_id,
                    },
                )
                await session.commit()

                created_assets.append(str(asset.id))
                logger.info(f"Created asset {asset.id} for new file {filename}")

            except Exception as e:
                logger.error(f"Failed to create asset for {filename}: {e}")
                # Continue with other files

        # Process UPDATED files (create new versions)
        for file_info in analysis.updated:
            try:
                filename = file_info["filename"]
                asset_id = UUID(file_info["asset_id"])
                file_data = files_by_name[filename]
                file_content = file_data["content"]
                file_size = len(file_content)
                content_type = file_data["content_type"]

                # Get existing asset
                asset = await asset_service.get_asset(session=session, asset_id=asset_id)
                if not asset:
                    logger.warning(f"Asset {asset_id} not found for update")
                    continue

                # Generate new object key
                document_id = str(asset_id)
                object_key = f"{organization_id}/uploads/{document_id}-{filename}"

                # Upload to MinIO
                minio.put_object(
                    bucket=bucket,
                    key=object_key,
                    data=io.BytesIO(file_content),
                    length=file_size,
                    content_type=content_type or "application/octet-stream",
                )

                # Create new asset version
                new_version = await asset_service.create_asset_version(
                    session=session,
                    asset_id=asset_id,
                    raw_bucket=bucket,
                    raw_object_key=object_key,
                    file_size=file_size,
                    file_hash=file_info["file_hash"],
                    content_type=content_type,
                    created_by=current_user.id,
                )
                await session.commit()

                # Trigger extraction for new version
                # TODO: Implement extraction trigger for new version
                # For now, we'll just log it
                logger.info(f"Created version {new_version.version_number} for asset {asset_id}")

                updated_assets.append(str(asset_id))

            except Exception as e:
                logger.error(f"Failed to update asset for {filename}: {e}")
                # Continue with other files

        # Process MISSING files
        if mark_missing_inactive:
            missing_asset_ids = [UUID(f["asset_id"]) for f in analysis.missing]
            marked = await bulk_upload_service.mark_assets_inactive(
                session=session,
                asset_ids=missing_asset_ids,
            )
            marked_inactive = [str(aid) for aid in marked]
            await session.commit()

        # Build response
        return BulkUploadApplyResponse(
            analysis=BulkUploadAnalysisResponse(
                unchanged=[BulkUploadFileInfo(**item) for item in analysis.unchanged],
                updated=[BulkUploadFileInfo(**item) for item in analysis.updated],
                new=[BulkUploadFileInfo(**item) for item in analysis.new],
                missing=[BulkUploadFileInfo(**item) for item in analysis.missing],
                counts=analysis.to_dict()["counts"],
            ),
            created_assets=created_assets,
            updated_assets=updated_assets,
            marked_inactive=marked_inactive,
            summary={
                "created_count": len(created_assets),
                "updated_count": len(updated_assets),
                "marked_inactive_count": len(marked_inactive),
            },
        )


# =========================================================================
# ASSET METADATA ENDPOINTS
# =========================================================================

@router.get(
    "/{asset_id}/metadata",
    response_model=AssetMetadataListResponse,
    summary="Get asset metadata",
    description="Get all metadata for an asset.",
)
async def get_asset_metadata(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
) -> AssetMetadataListResponse:
    """
    Get all metadata for an asset.

    Returns canonical metadata records (one per type) and available metadata types.
    """
    from app.core.shared.asset_metadata_service import asset_metadata_service

    async with database_service.get_session() as session:
        asset = await asset_service.get_asset(session=session, asset_id=asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        canonical = await asset_metadata_service.get_canonical_metadata(
            session=session, asset_id=asset_id
        )

        metadata_types = await asset_metadata_service.get_metadata_types_for_asset(
            session=session, asset_id=asset_id
        )

        def to_response(m):
            return AssetMetadataResponse(
                id=str(m.id),
                asset_id=str(m.asset_id),
                metadata_type=m.metadata_type,
                schema_version=m.schema_version,
                producer_run_id=str(m.producer_run_id) if m.producer_run_id else None,
                is_canonical=m.is_canonical,
                metadata_content=m.metadata_content or {},
                metadata_object_ref=m.metadata_object_ref,
                created_at=m.created_at,
                updated_at=m.updated_at,
            )

        return AssetMetadataListResponse(
            canonical=[to_response(m) for m in canonical],
            total_canonical=len(canonical),
            metadata_types=metadata_types,
        )


@router.post(
    "/{asset_id}/metadata",
    response_model=AssetMetadataResponse,
    summary="Create or update asset metadata",
    description="Create or update metadata for an asset. If canonical metadata of the same type exists, it is updated in place.",
    status_code=201,
)
async def create_asset_metadata(
    asset_id: UUID,
    request: AssetMetadataCreateRequest,
    current_user: User = Depends(get_current_user),
) -> AssetMetadataResponse:
    """
    Create or update metadata for an asset.

    Uses upsert semantics: if canonical metadata of the same type already exists,
    the existing record is updated in place.
    """
    from app.core.shared.asset_metadata_service import asset_metadata_service

    async with database_service.get_session() as session:
        asset = await asset_service.get_asset(session=session, asset_id=asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        try:
            producer_run_id = UUID(request.producer_run_id) if request.producer_run_id else None

            metadata = await asset_metadata_service.create_metadata(
                session=session,
                asset_id=asset_id,
                metadata_type=request.metadata_type,
                metadata_content=request.metadata_content,
                producer_run_id=producer_run_id,
                is_canonical=request.is_canonical,
                schema_version=request.schema_version,
            )

            logger.info(
                f"Created/updated metadata {metadata.id} for asset {asset_id} "
                f"(type: {request.metadata_type})"
            )

            return AssetMetadataResponse(
                id=str(metadata.id),
                asset_id=str(metadata.asset_id),
                metadata_type=metadata.metadata_type,
                schema_version=metadata.schema_version,
                producer_run_id=str(metadata.producer_run_id) if metadata.producer_run_id else None,
                is_canonical=metadata.is_canonical,
                metadata_content=metadata.metadata_content or {},
                metadata_object_ref=metadata.metadata_object_ref,
                created_at=metadata.created_at,
                updated_at=metadata.updated_at,
            )

        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/{asset_id}/metadata/{metadata_id}",
    response_model=AssetMetadataResponse,
    summary="Get specific metadata",
    description="Get a specific metadata record by ID.",
)
async def get_specific_metadata(
    asset_id: UUID,
    metadata_id: UUID,
    current_user: User = Depends(get_current_user),
) -> AssetMetadataResponse:
    """Get a specific metadata record."""
    from app.core.shared.asset_metadata_service import asset_metadata_service

    async with database_service.get_session() as session:
        asset = await asset_service.get_asset(session=session, asset_id=asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        metadata = await asset_metadata_service.get_metadata(
            session=session, metadata_id=metadata_id
        )

        if not metadata:
            raise HTTPException(status_code=404, detail="Metadata not found")

        if metadata.asset_id != asset_id:
            raise HTTPException(status_code=404, detail="Metadata not found for this asset")

        return AssetMetadataResponse(
            id=str(metadata.id),
            asset_id=str(metadata.asset_id),
            metadata_type=metadata.metadata_type,
            schema_version=metadata.schema_version,
            producer_run_id=str(metadata.producer_run_id) if metadata.producer_run_id else None,
            is_canonical=metadata.is_canonical,
            metadata_content=metadata.metadata_content or {},
            metadata_object_ref=metadata.metadata_object_ref,
            created_at=metadata.created_at,
            updated_at=metadata.updated_at,
        )


@router.delete(
    "/{asset_id}/metadata/{metadata_id}",
    summary="Delete metadata",
    description="Delete a metadata record.",
)
async def delete_metadata(
    asset_id: UUID,
    metadata_id: UUID,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Delete a metadata record."""
    from app.core.shared.asset_metadata_service import asset_metadata_service

    async with database_service.get_session() as session:
        asset = await asset_service.get_asset(session=session, asset_id=asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        metadata = await asset_metadata_service.get_metadata(
            session=session, metadata_id=metadata_id
        )

        if not metadata:
            raise HTTPException(status_code=404, detail="Metadata not found")

        if metadata.asset_id != asset_id:
            raise HTTPException(status_code=404, detail="Metadata not found for this asset")

        await asset_metadata_service.delete_metadata(
            session=session, metadata_id=metadata_id
        )
        logger.info(f"User {current_user.id} deleted metadata {metadata_id}")
        return {"message": "Metadata deleted", "metadata_id": str(metadata_id)}


# =============================================================================
# Priority Boost Endpoint
# =============================================================================


@router.get(
    "/{asset_id}/queue-info",
    response_model=AssetQueueInfoResponse,
    summary="Get queue position and extraction info",
    description="Get queue position and extraction service info for a pending asset.",
)
async def get_asset_queue_info(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
) -> AssetQueueInfoResponse:
    """
    Get queue position and extraction service information for an asset.

    Returns enhanced queue information including:
    - unified_status: Canonical status (queued, submitted, processing, completed, failed, timed_out, cancelled)
    - run_id: Current extraction run ID
    - in_queue: Whether extraction is queued/processing
    - queue_position: Position in queue (if pending)
    - total_pending: Total items in queue
    - estimated_wait_seconds: Rough estimate of wait time
    - submitted_to_celery: Whether task has been sent to Celery
    - timeout_at: When the task will be considered timed out
    - celery_task_id: Celery task ID (if submitted)
    - extractor_version: Extraction service being used

    Use this when displaying processing status in the UI.
    """
    from app.core.ingestion.extraction_queue_service import extraction_queue_service
    from app.core.database.models import Run, ExtractionResult
    from sqlalchemy import select, and_

    async with database_service.get_session() as session:
        # Verify asset belongs to user's organization
        asset = await asset_service.get_asset(session=session, asset_id=asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # If asset is already ready or failed, return simple response
        if asset.status == "ready":
            return AssetQueueInfoResponse(
                unified_status=UnifiedStatus.COMPLETED.value,
                asset_id=str(asset_id),
                in_queue=False,
            )

        if asset.status == "failed":
            return AssetQueueInfoResponse(
                unified_status=UnifiedStatus.FAILED.value,
                asset_id=str(asset_id),
                in_queue=False,
            )

        # Find the most recent extraction run for this asset
        asset_id_str = str(asset_id)
        result = await session.execute(
            select(Run)
            .where(and_(
                Run.run_type == "extraction",
                Run.input_asset_ids.contains([asset_id_str]),
            ))
            .order_by(Run.created_at.desc())
            .limit(1)
        )
        run = result.scalar_one_or_none()

        if not run:
            return AssetQueueInfoResponse(
                unified_status=UnifiedStatus.QUEUED.value,
                asset_id=str(asset_id),
                in_queue=False,
            )

        # Get extraction result for extractor version
        ext_result = await session.execute(
            select(ExtractionResult)
            .where(and_(
                ExtractionResult.run_id == run.id,
                ExtractionResult.asset_id == asset_id,
            ))
            .limit(1)
        )
        extraction = ext_result.scalar_one_or_none()

        extractor_version = None
        if extraction:
            extractor_version = extraction.extractor_version
        elif run.config:
            extractor_version = run.config.get("extractor_version")

        # Get unified status using the status mapper
        unified_status = get_unified_status(asset=asset, run=run, extraction_result=extraction)

        # Build response
        queue_position = None
        total_pending = None
        estimated_wait_seconds = None

        # Add queue position if still pending
        if run.status == "pending":
            queue_info = await extraction_queue_service.get_queue_position(session, run.id)
            queue_position = queue_info.get("queue_position")
            total_pending = queue_info.get("total_pending")
            estimated_wait_seconds = queue_info.get("estimated_wait_seconds")

        return AssetQueueInfoResponse(
            unified_status=unified_status.value,
            asset_id=str(asset_id),
            run_id=str(run.id),
            in_queue=run.status in ("pending", "submitted", "running"),
            queue_position=queue_position,
            total_pending=total_pending,
            estimated_wait_seconds=estimated_wait_seconds,
            submitted_to_celery=run.status in ("submitted", "running"),
            timeout_at=run.timeout_at.isoformat() if run.timeout_at else None,
            celery_task_id=run.celery_task_id,
            extractor_version=extractor_version,
        )


# =========================================================================
# CONTENT & DOWNLOAD ENDPOINTS (migrated from documents router)
# =========================================================================


def _strip_hash_prefix(filename: str) -> str:
    """Strip 32-character hex hash prefix from filename if present."""
    if not filename:
        return filename
    match = re.match(r'^[0-9a-f]{32}_(.+)$', filename, re.IGNORECASE)
    return match.group(1) if match else filename


async def _get_processed_artifact(session, asset_id: UUID, organization_id):
    """Look up the processed artifact for an asset via its extraction result."""
    # Get asset to find its document-id trail
    asset = await asset_service.get_asset(session=session, asset_id=asset_id)
    if not asset:
        return None, None

    if asset.organization_id != organization_id:
        return None, None

    # Try to find a processed artifact linked to this asset
    # The extraction result stores the extracted_bucket and extracted_object_key
    extraction_result = await extraction_result_service.get_latest_extraction_for_asset(
        session=session, asset_id=asset_id
    )

    if extraction_result and extraction_result.extracted_bucket and extraction_result.extracted_object_key:
        return asset, extraction_result

    return asset, None


@router.get(
    "/{asset_id}/content",
    summary="Get asset processed content",
    description="Get the processed markdown content for an asset.",
)
async def get_asset_content(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
):
    """Get processed markdown content for an asset.

    Returns the extracted markdown content from object storage.
    """
    from app.core.storage.minio_service import get_minio_service

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="Object storage not available")

    async with database_service.get_session() as session:
        asset, extraction = await _get_processed_artifact(
            session, asset_id, current_user.organization_id
        )

        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        if not extraction:
            raise HTTPException(
                status_code=404,
                detail="No processed content found for this asset",
            )

        try:
            content_io = minio.get_object(
                extraction.extracted_bucket, extraction.extracted_object_key
            )
            content = content_io.getvalue().decode("utf-8")
            return {"content": content}
        except Exception as e:
            logger.error(f"Failed to download content for asset {asset_id}: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to retrieve content: {str(e)}"
            )


@router.get(
    "/{asset_id}/download",
    summary="Download asset processed content",
    description="Download the processed markdown file for an asset.",
)
async def download_asset_content(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
):
    """Download processed markdown file for an asset.

    Streams the extracted markdown as a downloadable file.
    """
    from app.core.storage.minio_service import get_minio_service

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="Object storage not available")

    async with database_service.get_session() as session:
        asset, extraction = await _get_processed_artifact(
            session, asset_id, current_user.organization_id
        )

        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        if not extraction:
            raise HTTPException(
                status_code=404,
                detail="No processed content found for this asset",
            )

        # Determine download filename
        original_filename = asset.original_filename or f"{asset_id}.md"
        clean_filename = _strip_hash_prefix(original_filename)
        download_name = f"{Path(clean_filename).stem}.md"

        try:
            content_io = minio.get_object(
                extraction.extracted_bucket, extraction.extracted_object_key
            )
            content = content_io.getvalue()

            return StreamingResponse(
                io.BytesIO(content),
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f'attachment; filename="{download_name}"',
                    "Content-Length": str(len(content)),
                },
            )
        except Exception as e:
            logger.error(f"Failed to download asset {asset_id}: {e}")
            raise HTTPException(
                status_code=500, detail=f"Download failed: {str(e)}"
            )


@router.get(
    "/{asset_id}/original",
    summary="Download asset original file",
    description="Download the original uploaded file for an asset.",
)
async def download_asset_original(
    asset_id: UUID,
    inline: bool = Query(False, description="If true, set Content-Disposition to inline for preview; otherwise attachment for download"),
    current_user: User = Depends(get_current_user),
):
    """Download the original uploaded file for an asset.

    Streams the original file from raw_bucket/raw_object_key.
    """
    from app.core.storage.minio_service import get_minio_service

    minio = get_minio_service()
    if not minio:
        raise HTTPException(status_code=503, detail="Object storage not available")

    async with database_service.get_session() as session:
        asset = await asset_service.get_asset(session=session, asset_id=asset_id)

        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=404, detail="Asset not found")

        if not asset.raw_bucket or not asset.raw_object_key:
            raise HTTPException(
                status_code=404,
                detail="No original file found for this asset",
            )

        original_filename = asset.original_filename or f"{asset_id}"
        clean_filename = _strip_hash_prefix(original_filename)
        content_type = asset.content_type or "application/octet-stream"

        disposition = "inline" if inline else "attachment"

        try:
            content_io = minio.get_object(asset.raw_bucket, asset.raw_object_key)
            content = content_io.getvalue()

            return StreamingResponse(
                io.BytesIO(content),
                media_type=content_type,
                headers={
                    "Content-Disposition": f'{disposition}; filename="{clean_filename}"',
                    "Content-Length": str(len(content)),
                },
            )
        except Exception as e:
            logger.error(f"Failed to download original for asset {asset_id}: {e}")
            raise HTTPException(
                status_code=500, detail=f"Download failed: {str(e)}"
            )


@router.post(
    "/download/bulk",
    summary="Bulk download assets as ZIP",
    description="Download multiple processed assets as a ZIP archive.",
)
async def download_bulk_assets(
    request: Dict[str, Any],
    current_user: User = Depends(get_current_user),
):
    """Download multiple processed documents as a ZIP archive.

    Accepts:
        document_ids: List of document IDs
        download_type: 'individual', 'combined', or 'rag_ready'
        custom_filename: Optional ZIP filename
        include_summary: Whether to include a processing summary
    """
    document_ids = request.get("document_ids", [])
    download_type = request.get("download_type", "individual")
    custom_filename = request.get("custom_filename") or request.get("zip_name")
    include_summary = request.get("include_summary", True)
    include_combined = request.get("include_combined", download_type == "combined")

    try:
        zip_info = await zip_service.create_bulk_download(
            document_ids=document_ids,
            download_type=download_type,
            custom_filename=custom_filename,
            include_summary=include_summary,
            include_combined=include_combined,
        )

        if not zip_info.zip_path.exists():
            raise HTTPException(status_code=404, detail="Archive not found")

        return FileResponse(
            path=str(zip_info.zip_path),
            filename=zip_info.zip_path.name,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={zip_info.zip_path.name}"
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Bulk download failed: {str(e)}"
        )


@router.delete(
    "/{asset_id}",
    summary="Delete an asset and its artifacts",
    description="Delete an asset, its artifacts from object storage, and related records.",
)
async def delete_asset(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
):
    """Delete an asset and all associated artifacts from storage."""
    from app.core.storage.minio_service import get_minio_service

    async with database_service.get_session() as session:
        asset = await asset_service.get_asset(session=session, asset_id=asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        if asset.organization_id != current_user.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")

        minio = get_minio_service()
        deleted_count = 0

        if minio and minio.enabled:
            artifacts = await artifact_service.get_artifacts_by_document(
                session, str(asset_id)
            )
            for artifact in artifacts:
                try:
                    minio.delete_object(artifact.bucket, artifact.object_key)
                    deleted_count += 1
                except Exception:
                    pass
            for artifact in artifacts:
                try:
                    await artifact_service.delete_artifact(session, artifact.id)
                except Exception:
                    pass

        # Delete the asset record itself
        await session.delete(asset)
        await session.commit()

        return {
            "success": True,
            "message": f"Asset deleted successfully ({deleted_count} files removed from storage)",
        }


@router.get(
    "/download/rag-ready",
    summary="Download RAG-ready assets as ZIP",
    description="Download all RAG-ready processed documents as a ZIP archive.",
)
async def download_rag_ready_assets(
    zip_name: Optional[str] = Query(None, description="Custom ZIP filename"),
    include_summary: bool = Query(True, description="Include processing summary"),
    current_user: User = Depends(get_current_user),
):
    """Download all RAG-ready documents as a ZIP archive."""
    try:
        zip_info = await zip_service.create_rag_ready_download(
            custom_filename=zip_name,
            include_summary=include_summary,
        )

        if not zip_info.zip_path.exists():
            raise HTTPException(status_code=404, detail="No RAG-ready documents found")

        return FileResponse(
            path=str(zip_info.zip_path),
            filename=zip_info.zip_path.name,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={zip_info.zip_path.name}"
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"RAG-ready download failed: {str(e)}"
        )
