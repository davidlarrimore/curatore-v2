from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from ..deps import get_jobs
from ..models.schemas import JobCreate

# Create a new APIRouter instance for organizing job-related endpoints.
router = APIRouter()

@router.get("/jobs")
def list_jobs(jobs = Depends(get_jobs)):
    """
    Lists all currently active or completed processing jobs.
    
    Args:
        jobs: An instance of the jobs service, injected by FastAPI.
        
    Returns:
        A dictionary containing a list of all jobs.
    """
    return {"jobs": [j.dict() for j in jobs.list()]}

@router.get("/jobs/{job_id}")
def get_job(job_id: str, jobs = Depends(get_jobs)):
    """
    Retrieves the details of a specific processing job by its ID.
    
    Args:
        job_id: The unique identifier of the job to retrieve.
        jobs: An instance of the jobs service, injected by FastAPI.
        
    Returns:
        The job object if found, otherwise raises a 404 error.
    """
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return j

@router.post("/jobs")
async def create_job(payload: JobCreate, jobs = Depends(get_jobs)):
    """
    Creates a new processing job for a list of filenames.
    It takes processing parameters from the payload or uses sensible defaults.
    The job is created and immediately started in the background.
    """
    # Use thresholds and OCR settings from the payload, or fall back to defaults.
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
    # Return the new job's ID and initial status.
    return {"job_id": job.id, "status": job.status}