"""SharePoint inventory and download endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models import (
    SharePointDownloadRequest,
    SharePointDownloadResponse,
    SharePointInventoryRequest,
    SharePointInventoryResponse,
)
from ....services import sharepoint_service

router = APIRouter()


@router.post("/sharepoint/inventory", response_model=SharePointInventoryResponse, tags=["SharePoint"])
async def sharepoint_inventory(request: SharePointInventoryRequest) -> SharePointInventoryResponse:
    """List SharePoint folder contents with metadata."""
    try:
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
async def sharepoint_download(request: SharePointDownloadRequest) -> SharePointDownloadResponse:
    """Download selected SharePoint files to the batch directory."""
    try:
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
