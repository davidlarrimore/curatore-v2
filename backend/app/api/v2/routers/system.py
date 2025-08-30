# backend/app/api/v2/routers/system.py
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
import os
from typing import Dict, Any, Optional, List
import json

from ....config import settings
from ..models import HealthStatus, LLMConnectionStatus
from ....services.llm_service import llm_service
from ....services.document_service import document_service
from ....services.storage_service import storage_service
from ....services.job_service import clear_all_jobs_and_locks
from ....services.job_service import get_redis_client
from ....celery_app import app as celery_app

router = APIRouter()


@router.get("/health", response_model=HealthStatus, tags=["System"])
async def health_check():
    """Health check endpoint."""
    llm_status = await llm_service.test_connection()

    return HealthStatus(
        status="healthy",
        timestamp=datetime.now(),
        version=settings.api_version,
        llm_connected=llm_status.connected,
        storage_available=True,
    )


@router.get("/llm/status", response_model=LLMConnectionStatus, tags=["System"])
async def get_llm_status():
    """Get LLM connection status."""
    return await llm_service.test_connection()


@router.post("/system/reset", tags=["System"])
async def reset_system():
    """Reset the entire system - cancel jobs, clear files and data."""
    try:
        revoked = 0
        purged = 0
        try:
            insp = celery_app.control.inspect(timeout=1.0)
            active = insp.active() or {}
            for tasks in active.values():
                for t in tasks or []:
                    tid = (t.get('id') if isinstance(t, dict) else None) or getattr(t, 'id', None)
                    if tid:
                        celery_app.control.revoke(tid, terminate=True)
                        revoked += 1
            reserved = insp.reserved() or {}
            for tasks in reserved.values():
                for t in tasks or []:
                    tid = (t.get('id') if isinstance(t, dict) else None) or getattr(t, 'id', None)
                    if tid:
                        celery_app.control.revoke(tid, terminate=False)
                        revoked += 1
            scheduled = insp.scheduled() or {}
            for tasks in scheduled.values():
                for t in tasks or []:
                    tid = None
                    if isinstance(t, dict):
                        tid = (t.get('request') or {}).get('id') or t.get('id')
                    if tid:
                        celery_app.control.revoke(tid, terminate=False)
                        revoked += 1
            purged = celery_app.control.purge() or 0
        except Exception:
            pass

        document_service.clear_all_files()
        storage_service.clear_all()
        jobs_cleared = clear_all_jobs_and_locks()
        document_service._ensure_directories()

        return {
            "success": True,
            "message": "System reset successfully",
            "timestamp": datetime.now(),
            "queue": {"revoked": revoked, "purged": purged},
            "jobs_cleared": jobs_cleared,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")


@router.get("/config/supported-formats", tags=["Configuration"])
async def get_supported_formats():
    """Get list of supported file formats."""
    return {
        "supported_extensions": document_service.get_supported_extensions(),
        "max_file_size": settings.max_file_size,
    }


@router.get("/config/defaults", tags=["Configuration"])
async def get_default_config():
    """Get default configuration values."""
    return {
        "quality_thresholds": {
            "conversion": settings.default_conversion_threshold,
            "clarity": settings.default_clarity_threshold,
            "completeness": settings.default_completeness_threshold,
            "relevance": settings.default_relevance_threshold,
            "markdown": settings.default_markdown_threshold,
        },
        "ocr_settings": {
            "language": settings.ocr_lang,
            "psm": settings.ocr_psm,
        },
        "auto_optimize": True,
    }


@router.get("/items", tags=["Legacy"])
def list_items():
    """Legacy endpoint for frontend compatibility."""
    return [
        {"id": 1, "name": "Document Processing"},
        {"id": 2, "name": "LLM Integration"},
        {"id": 3, "name": "Quality Assessment"},
    ]


@router.get("/system/queues", tags=["System"])
async def queue_health() -> Dict[str, Any]:
    """Minimal Celery/Redis queue health endpoint."""
    enabled = os.getenv("USE_CELERY", "true").lower() in {"1", "true", "yes"}
    broker = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
    queue = os.getenv("CELERY_DEFAULT_QUEUE", "processing")

    info: Dict[str, Any] = {
        "enabled": enabled,
        "broker": broker,
        "result_backend": backend,
        "queue": queue,
        "redis_ok": False,
        "pending": 0,
        "workers": 0,
        "running": 0,
        "processed": 0,
        "total": 0,
    }

    try:
        r = get_redis_client()
        info["redis_ok"] = bool(r.ping())
        keys = [queue, "celery"] if queue != "celery" else ["celery"]
        total = 0
        for k in keys:
            try:
                total += int(r.llen(k))
            except Exception:
                continue
        info["pending"] = total
        # Derive running/completed by scanning job:* status payloads
        try:
            cursor = 0
            running = 0
            completed = 0
            while True:
                cursor, keys = r.scan(cursor=cursor, match="job:*", count=500)
                for k in keys or []:
                    try:
                        raw = r.get(k)
                        if not raw:
                            continue
                        data = json.loads(raw)
                        status = str(data.get("status", "")).upper()
                        if status == "STARTED":
                            running += 1
                        elif status in ("SUCCESS", "FAILURE"):
                            completed += 1
                    except Exception:
                        continue
                if cursor == 0:
                    break
            info["running"] = running
            info["processed"] = completed
        except Exception:
            pass
    except Exception:
        pass

    try:
        insp = celery_app.control.inspect(timeout=1.0)
        p = insp.ping() or {}
        info["workers"] = len(p)
        try:
            active = insp.active() or {}
            info["running"] = sum(len(tasks or []) for tasks in active.values())
        except Exception:
            pass
    except Exception:
        pass
    info["total"] = int(info.get("processed", 0)) + int(info.get("running", 0)) + int(info.get("pending", 0))
    return info


@router.get("/system/queues/summary", tags=["System"])
async def queue_summary(
    batch_id: Optional[str] = Query(None),
    job_ids: Optional[str] = Query(None, description="Comma-separated job IDs")
) -> Dict[str, Any]:
    """Summarize status for a requested set of jobs.

    - If `batch_id` is provided, inspects all jobs with that batch_id.
    - Else if `job_ids` is provided, inspects that explicit list.
    - Otherwise returns 400.
    """
    if not batch_id and not job_ids:
        raise HTTPException(status_code=400, detail="batch_id or job_ids required")

    r = get_redis_client()
    target_job_ids: List[str] = []

    if job_ids:
        target_job_ids = [j.strip() for j in job_ids.split(',') if j.strip()]
    else:
        # Collect jobs by batch_id
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor=cursor, match="job:*", count=500)
            for k in keys or []:
                try:
                    raw = r.get(k)
                    if not raw:
                        continue
                    data = json.loads(raw)
                    if data.get("batch_id") == batch_id and data.get("job_id"):
                        target_job_ids.append(str(data.get("job_id")))
                except Exception:
                    continue
            if cursor == 0:
                break

    requested = len(target_job_ids)
    running = 0
    done = 0
    started_ids = set()
    completed_ids = set()

    for jid in target_job_ids:
        try:
            raw = r.get(f"job:{jid}")
            if not raw:
                continue
            data = json.loads(raw)
            status = str(data.get("status", "")).upper()
            if status == "STARTED":
                running += 1
                started_ids.add(jid)
            elif status in ("SUCCESS", "FAILURE"):
                done += 1
                completed_ids.add(jid)
        except Exception:
            continue

    queued = max(requested - running - done, 0)
    return {
        "batch_id": batch_id,
        "requested": requested,
        "queued": queued,
        "running": running,
        "done": done,
        "total": requested,
    }
