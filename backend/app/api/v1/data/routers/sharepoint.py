"""SharePoint inventory and download endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.data.schemas import (
    SharePointDownloadRequest,
    SharePointDownloadResponse,
    SharePointInventoryRequest,
    SharePointInventoryResponse,
)
from uuid import UUID

from app.connectors.sharepoint import sharepoint_service
from app.core.shared.database_service import database_service
from app.dependencies import get_effective_org_id

router = APIRouter()


@router.post("/sharepoint/inventory", response_model=SharePointInventoryResponse, tags=["SharePoint"])
async def sharepoint_inventory(
    request: SharePointInventoryRequest,
    organization_id: Optional[UUID] = Depends(get_effective_org_id),
) -> SharePointInventoryResponse:
    """
    List SharePoint folder contents with metadata.

    Supports optional authentication for database connection lookup.
    Falls back to environment variables if not authenticated.
    """
    try:
        if organization_id:
            async with database_service.get_session() as session:
                payload = await sharepoint_service.sharepoint_inventory(
                    folder_url=request.folder_url,
                    recursive=request.recursive,
                    include_folders=request.include_folders,
                    page_size=request.page_size,
                    max_items=request.max_items,
                    organization_id=organization_id,
                    session=session,
                )
        else:
            payload = await sharepoint_service.sharepoint_inventory(
                folder_url=request.folder_url,
                recursive=request.recursive,
                include_folders=request.include_folders,
                page_size=request.page_size,
                max_items=request.max_items,
            )

        return SharePointInventoryResponse(**payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sharepoint/download", response_model=SharePointDownloadResponse, tags=["SharePoint"])
async def sharepoint_download(
    request: SharePointDownloadRequest,
    organization_id: Optional[UUID] = Depends(get_effective_org_id),
) -> SharePointDownloadResponse:
    """
    Download selected SharePoint files to the batch directory.

    Supports optional authentication for database connection lookup.
    Falls back to environment variables if not authenticated.
    """
    try:
        if organization_id:
            async with database_service.get_session() as session:
                payload = await sharepoint_service.sharepoint_download(
                    folder_url=request.folder_url,
                    indices=request.indices,
                    download_all=request.download_all,
                    recursive=request.recursive,
                    page_size=request.page_size,
                    max_items=request.max_items,
                    preserve_folders=request.preserve_folders,
                    organization_id=organization_id,
                    session=session,
                )
        else:
            payload = await sharepoint_service.sharepoint_download(
                folder_url=request.folder_url,
                indices=request.indices,
                download_all=request.download_all,
                recursive=request.recursive,
                page_size=request.page_size,
                max_items=request.max_items,
                preserve_folders=request.preserve_folders,
            )

        return SharePointDownloadResponse(**payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
