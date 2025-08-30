from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ....services.job_service import (
    get_job_status,
    get_active_job_for_document,
    get_last_job_for_document,
)


class JobLogEntry(BaseModel):
    ts: Optional[datetime] = None
    level: Optional[str] = None
    message: Optional[str] = None


class JobStatusResponse(BaseModel):
    job_id: str
    document_id: Optional[str] = None
    status: str
    enqueued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    retries: Optional[int] = None
    error: Optional[str] = None
    result: Optional[dict] = None
    logs: Optional[List[JobLogEntry]] = None


router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobStatusResponse, tags=["Processing"])
async def get_job(job_id: str):
    data = get_job_status(job_id)
    if not data:
        raise HTTPException(status_code=404, detail="Job not found")
    return data


@router.get("/jobs/by-document/{document_id}", tags=["Processing"])
async def get_job_by_document(document_id: str):
    active = get_active_job_for_document(document_id)
    if active:
        data = get_job_status(active)
        if data:
            return data
    last_job = get_last_job_for_document(document_id)
    if last_job:
        data = get_job_status(last_job)
        if data:
            return data
    raise HTTPException(status_code=404, detail="No job found for document")
