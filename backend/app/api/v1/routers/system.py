# backend/app/api/v1/routers/system.py
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
from ....services.zip_service import zip_service
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
        storage_available=True
    )

@router.get("/llm/status", response_model=LLMConnectionStatus, tags=["System"])
async def get_llm_status():
    """Get LLM connection status."""
    return await llm_service.test_connection()

@router.get("/extractor/status", tags=["System"])
async def get_extractor_status():
    """Report extraction service connectivity/status (backend -> extractor)."""
    try:
        status = await document_service.extractor_health()
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extractor status check failed: {str(e)}")

@router.post("/system/reset", tags=["System"])
async def reset_system():
    """Reset the entire system - cancel jobs, clear files and data."""
    try:
        # Best-effort: cancel running and queued Celery tasks
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

        # Clear temp ZIPs, runtime files (uploaded + processed) and storage; keep batch files
        try:
            zip_deleted = zip_service.cleanup_all_temp_archives()
        except Exception:
            zip_deleted = 0
        document_service.clear_runtime_files()
        storage_service.clear_all()

        # Clear job status keys and locks in Redis
        try:
            from ....services.job_service import clear_all_jobs_and_locks
            jobs_cleared = clear_all_jobs_and_locks()
        except Exception:
            jobs_cleared = {"jobs": 0, "active_locks": 0, "last_job_keys": 0}

        document_service._ensure_directories()

        return {
            "success": True,
            "message": "System reset successfully",
            "timestamp": datetime.now(),
            "queue": {"revoked": revoked, "purged": purged},
            "jobs_cleared": jobs_cleared,
            "temp_zips_deleted": zip_deleted,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")

@router.get("/config/supported-formats", tags=["Configuration"])
async def get_supported_formats():
    """Get list of supported file formats."""
    return {
        "supported_extensions": document_service.get_supported_extensions(),
        "max_file_size": settings.max_file_size
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
            "markdown": settings.default_markdown_threshold
        },
        "ocr_settings": {
            "language": settings.ocr_lang,
            "psm": settings.ocr_psm
        },
        "auto_optimize": True
    }

@router.get("/config/extraction-services", tags=["Configuration"])
async def get_extraction_services() -> Dict[str, Any]:
    """List available document extraction services and which one is active.

    - Always includes the default extraction microservice (if configured).
    - Includes Docling when the service is reachable within the network.
    """
    try:
        return await document_service.available_extraction_services()
    except Exception as e:
        # Return a best-effort structure even on error
        return {"active": getattr(document_service, "extractor_engine", "default"), "services": [], "error": str(e)}

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

    # Redis status and rough pending count
    try:
        r = get_redis_client()
        info["redis_ok"] = bool(r.ping())
        # Attempt to read LLEN for configured queue and default 'celery'
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
            # Maintain backward compat key name 'processed' for UI
            info["processed"] = completed
        except Exception:
            pass
    except Exception:
        pass

    # Workers via celery inspect (best-effort)
    try:
        insp = celery_app.control.inspect(timeout=1.0)
        p = insp.ping() or {}
        info["workers"] = len(p)
        # Count active tasks across workers
        try:
            active = insp.active() or {}
            info["running"] = sum(len(tasks or []) for tasks in active.values())
        except Exception:
            pass
    except Exception:
        # leave workers at 0 if unreachable
        pass
    # Total = completed + running + pending
    info["total"] = int(info.get("processed", 0)) + int(info.get("running", 0)) + int(info.get("pending", 0))
    return info


@router.get("/system/queues/summary", tags=["System"])
async def queue_summary(
    batch_id: Optional[str] = Query(None),
    job_ids: Optional[str] = Query(None, description="Comma-separated job IDs"),
) -> Dict[str, Any]:
    """Summarize status for a requested set of jobs (parity with v2).

    - If `batch_id` is provided, inspects all jobs with that batch_id.
    - Else if `job_ids` is provided, inspects that explicit list.
    - Otherwise returns 400.
    """
    if not batch_id and not job_ids:
        raise HTTPException(status_code=400, detail="batch_id or job_ids required")

    r = get_redis_client()
    target_job_ids: List[str] = []

    if job_ids:
        target_job_ids = [j.strip() for j in job_ids.split(",") if j.strip()]
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


@router.get("/system/health/backend", tags=["System"])
async def health_check_backend() -> Dict[str, Any]:
    """Health check for backend API component."""
    return {
        "status": "healthy",
        "message": "API is responding",
        "version": settings.api_version
    }


@router.get("/system/health/redis", tags=["System"])
async def health_check_redis() -> Dict[str, Any]:
    """Health check for Redis component."""
    try:
        r = get_redis_client()
        ping_result = r.ping()
        return {
            "status": "healthy" if ping_result else "unhealthy",
            "message": "Redis connection successful" if ping_result else "Redis ping failed",
            "broker_url": os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
            "result_backend": os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Redis connection error: {str(e)}"
        }


@router.get("/system/health/celery", tags=["System"])
async def health_check_celery() -> Dict[str, Any]:
    """Health check for Celery worker component."""
    try:
        insp = celery_app.control.inspect(timeout=2.0)
        ping_result = insp.ping() or {}
        worker_count = len(ping_result)

        active_tasks = {}
        try:
            active = insp.active() or {}
            active_tasks = {worker: len(tasks or []) for worker, tasks in active.items()}
        except Exception:
            pass

        return {
            "status": "healthy" if worker_count > 0 else "unhealthy",
            "message": f"{worker_count} worker(s) active" if worker_count > 0 else "No workers responding",
            "worker_count": worker_count,
            "active_tasks": active_tasks,
            "queue": os.getenv("CELERY_DEFAULT_QUEUE", "processing")
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Worker check error: {str(e)}",
            "worker_count": 0
        }


@router.get("/system/health/extraction", tags=["System"])
async def health_check_extraction() -> Dict[str, Any]:
    """Health check for extraction service component."""
    try:
        extractor_status = await document_service.extractor_health()
        is_connected = extractor_status.get("connected", False)

        if is_connected:
            return {
                "status": "healthy",
                "message": "Extraction service is responding",
                "url": extractor_status.get("endpoint"),
                "engine": extractor_status.get("engine", "default"),
                "response": extractor_status.get("response", {})
            }
        elif extractor_status.get("error") == "not_configured":
            return {
                "status": "not_configured",
                "message": "Extraction service not configured",
                "engine": extractor_status.get("engine", "default")
            }
        else:
            error_msg = extractor_status.get("error", "Service check failed")
            return {
                "status": "unhealthy",
                "message": f"Extraction service unreachable: {error_msg}",
                "url": extractor_status.get("endpoint"),
                "engine": extractor_status.get("engine", "default")
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Extraction service error: {str(e)}"
        }


@router.get("/system/health/docling", tags=["System"])
async def health_check_docling() -> Dict[str, Any]:
    """Health check for Docling service component."""
    import httpx

    docling_url = getattr(settings, "docling_service_url", "").rstrip("/")
    if not docling_url:
        return {
            "status": "not_configured",
            "message": "Docling service not configured"
        }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            health_url = f"{docling_url}/health"
            try:
                resp = await client.get(health_url)
                if resp.status_code == 200:
                    return {
                        "status": "healthy",
                        "message": "Docling service is responding",
                        "url": docling_url
                    }
                else:
                    return {
                        "status": "degraded",
                        "message": f"Docling returned status {resp.status_code}",
                        "url": docling_url
                    }
            except httpx.HTTPStatusError:
                return {
                    "status": "unknown",
                    "message": "Docling service configured but health endpoint not available",
                    "url": docling_url
                }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Docling service error: {str(e)}",
            "url": docling_url
        }


@router.get("/system/health/llm", tags=["System"])
async def health_check_llm() -> Dict[str, Any]:
    """Health check for LLM connection component."""
    try:
        llm_status = await llm_service.test_connection()
        if llm_status.connected:
            return {
                "status": "healthy",
                "message": f"Connected to {llm_status.model}",
                "model": llm_status.model,
                "endpoint": llm_status.endpoint
            }
        else:
            error_msg = llm_status.error or "Connection failed"
            return {
                "status": "unhealthy",
                "message": error_msg,
                "model": llm_status.model,
                "endpoint": llm_status.endpoint
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"LLM check error: {str(e)}"
        }


@router.get("/system/health/comprehensive", tags=["System"])
async def comprehensive_health() -> Dict[str, Any]:
    """Comprehensive health check for all system components.

    Checks the health of:
    - Backend API
    - Extraction Service (default microservice)
    - Docling Service (if configured)
    - Celery Worker
    - Redis (broker and backend)
    - LLM Connection

    Returns detailed status for each component with timestamps and error messages.
    """
    import httpx
    from datetime import datetime

    health_report: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "overall_status": "healthy",
        "components": {}
    }

    issues = []

    # 1. Backend API (self)
    health_report["components"]["backend"] = {
        "status": "healthy",
        "message": "API is responding",
        "version": settings.api_version
    }

    # 2. Redis Connection
    try:
        r = get_redis_client()
        ping_result = r.ping()
        health_report["components"]["redis"] = {
            "status": "healthy" if ping_result else "unhealthy",
            "message": "Redis connection successful" if ping_result else "Redis ping failed",
            "broker_url": os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
            "result_backend": os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
        }
        if not ping_result:
            issues.append("Redis connection failed")
    except Exception as e:
        health_report["components"]["redis"] = {
            "status": "unhealthy",
            "message": f"Redis connection error: {str(e)}"
        }
        issues.append(f"Redis: {str(e)}")

    # 3. Celery Worker
    try:
        insp = celery_app.control.inspect(timeout=2.0)
        ping_result = insp.ping() or {}
        worker_count = len(ping_result)

        active_tasks = {}
        try:
            active = insp.active() or {}
            active_tasks = {worker: len(tasks or []) for worker, tasks in active.items()}
        except Exception:
            pass

        health_report["components"]["celery_worker"] = {
            "status": "healthy" if worker_count > 0 else "unhealthy",
            "message": f"{worker_count} worker(s) active" if worker_count > 0 else "No workers responding",
            "worker_count": worker_count,
            "active_tasks": active_tasks,
            "queue": os.getenv("CELERY_DEFAULT_QUEUE", "processing")
        }

        if worker_count == 0:
            issues.append("No Celery workers available")
    except Exception as e:
        health_report["components"]["celery_worker"] = {
            "status": "unhealthy",
            "message": f"Worker check error: {str(e)}",
            "worker_count": 0
        }
        issues.append(f"Celery Worker: {str(e)}")

    # 4. Extraction Service (default microservice)
    try:
        extractor_status = await document_service.extractor_health()
        is_connected = extractor_status.get("connected", False)

        if is_connected:
            health_report["components"]["extraction_service"] = {
                "status": "healthy",
                "message": "Extraction service is responding",
                "url": extractor_status.get("endpoint"),
                "engine": extractor_status.get("engine", "default"),
                "response": extractor_status.get("response", {})
            }
        elif extractor_status.get("error") == "not_configured":
            health_report["components"]["extraction_service"] = {
                "status": "not_configured",
                "message": "Extraction service not configured",
                "engine": extractor_status.get("engine", "default")
            }
        else:
            error_msg = extractor_status.get("error", "Service check failed")
            health_report["components"]["extraction_service"] = {
                "status": "unhealthy",
                "message": f"Extraction service unreachable: {error_msg}",
                "url": extractor_status.get("endpoint"),
                "engine": extractor_status.get("engine", "default")
            }
            issues.append(f"Extraction service: {error_msg}")
    except Exception as e:
        health_report["components"]["extraction_service"] = {
            "status": "unhealthy",
            "message": f"Extraction service error: {str(e)}"
        }
        issues.append(f"Extraction Service: {str(e)}")

    # 5. Docling Service (if configured)
    docling_url = getattr(settings, "docling_service_url", "").rstrip("/")
    if docling_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Docling health check endpoint (trying common patterns)
                health_url = f"{docling_url}/health"
                try:
                    resp = await client.get(health_url)
                    if resp.status_code == 200:
                        health_report["components"]["docling"] = {
                            "status": "healthy",
                            "message": "Docling service is responding",
                            "url": docling_url
                        }
                    else:
                        health_report["components"]["docling"] = {
                            "status": "degraded",
                            "message": f"Docling returned status {resp.status_code}",
                            "url": docling_url
                        }
                        issues.append(f"Docling service returned {resp.status_code}")
                except httpx.HTTPStatusError:
                    # Try alternate endpoint
                    health_report["components"]["docling"] = {
                        "status": "unknown",
                        "message": "Docling service configured but health endpoint not available",
                        "url": docling_url
                    }
        except Exception as e:
            health_report["components"]["docling"] = {
                "status": "unhealthy",
                "message": f"Docling service error: {str(e)}",
                "url": docling_url
            }
            issues.append(f"Docling: {str(e)}")
    else:
        health_report["components"]["docling"] = {
            "status": "not_configured",
            "message": "Docling service not configured"
        }

    # 6. LLM Connection
    try:
        llm_status = await llm_service.test_connection()
        if llm_status.connected:
            health_report["components"]["llm"] = {
                "status": "healthy",
                "message": f"Connected to {llm_status.model}",
                "model": llm_status.model,
                "endpoint": llm_status.endpoint
            }
        else:
            error_msg = llm_status.error or "Connection failed"
            health_report["components"]["llm"] = {
                "status": "unhealthy",
                "message": error_msg,
                "model": llm_status.model,
                "endpoint": llm_status.endpoint
            }
            issues.append(f"LLM connection failed: {error_msg}")
    except Exception as e:
        health_report["components"]["llm"] = {
            "status": "unhealthy",
            "message": f"LLM check error: {str(e)}"
        }
        issues.append(f"LLM: {str(e)}")

    # Determine overall status
    component_statuses = [c.get("status") for c in health_report["components"].values()]

    if any(s == "unhealthy" for s in component_statuses):
        health_report["overall_status"] = "unhealthy"
    elif any(s in ["degraded", "unknown"] for s in component_statuses):
        health_report["overall_status"] = "degraded"
    else:
        health_report["overall_status"] = "healthy"

    # Add issues summary
    if issues:
        health_report["issues"] = issues

    return health_report
