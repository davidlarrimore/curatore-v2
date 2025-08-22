from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from ..deps import get_jobs
from ..models.schemas import JobCreate

router = APIRouter()

@router.get("/jobs")
def list_jobs(jobs = Depends(get_jobs)):
    return {"jobs": [j.dict() for j in jobs.list()]}

@router.get("/jobs/{job_id}")
def get_job(job_id: str, jobs = Depends(get_jobs)):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return j

@router.post("/jobs")
async def create_job(payload: JobCreate, jobs = Depends(get_jobs)):
    # thresholds / OCR from payload or defaults
    th = payload.thresholds.dict()
    ocr_lang = payload.ocr_lang or "eng"
    ocr_psm = payload.ocr_psm or 3
    job = await jobs.create_and_run(
        filenames=payload.filenames,
        auto_optimize=payload.auto_optimize,
        thresholds=th,
        ocr_lang=ocr_lang,
        ocr_psm=ocr_psm
    )
    return {"job_id": job.id, "status": job.status}