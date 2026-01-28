# backend/app/api/v1/routers/assets.py
"""
Assets API Router for Phase 0.

Provides endpoints for querying assets, extraction status, and related runs.
"""

import logging
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile

from ....database.models import User
from ....dependencies import get_current_user
from ....services.database_service import database_service
from ....services.asset_service import asset_service
from ....services.run_service import run_service
from ....services.extraction_result_service import extraction_result_service
from ....services.upload_integration_service import upload_integration_service
from ..models import (
    AssetResponse,
    AssetWithExtractionResponse,
    AssetVersionResponse,
    AssetVersionHistoryResponse,
    ExtractionResultResponse,
    RunResponse,
    AssetsListResponse,
    BulkUploadAnalysisResponse,
    BulkUploadFileInfo,
)

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
    status: Optional[str] = Query(None, description="Filter by status (pending, ready, failed)"),
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
            limit=limit,
            offset=offset,
        )

        total = await asset_service.count_assets_by_organization(
            session=session,
            organization_id=current_user.organization_id,
            source_type=source_type,
            status=status,
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
                )
                for a in assets
            ],
            total=total,
            limit=limit,
            offset=offset,
        )


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

        return [
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
            )
            for r in runs
        ]


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
            versions=[
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
                )
                for v in versions
            ],
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
    from ....services.bulk_upload_service import bulk_upload_service

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
