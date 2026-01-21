# backend/app/api/v1/routers/system.py
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends
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
from ....services.database_service import database_service
from ....services.config_loader import config_loader
from ....celery_app import app as celery_app
from ....dependencies import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

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
        if getattr(document_service, 'extract_base', ''):
            active = "extraction-service"
        elif getattr(document_service, 'docling_base', ''):
            active = "docling"
        else:
            active = None
        return {"active": active, "services": [], "error": str(e)}

@router.get("/config/extraction-engines", tags=["Configuration"])
async def get_extraction_engines() -> Dict[str, Any]:
    """List extraction engines configured in config.yml.

    These are system-default engines that can be used when no custom
    connections are configured. Returns enabled engines with their
    configuration details.

    Returns:
        {
            "engines": [
                {
                    "id": "extraction-service",  # Use as connection_id
                    "name": "extraction-service",
                    "display_name": "Internal Extraction Service",
                    "description": "Built-in extraction...",
                    "engine_type": "extraction-service",
                    "service_url": "http://extraction:8010",
                    "timeout": 300,
                    "is_default": true,  # Computed from default_engine setting
                    "is_system": true  # Indicates this is from config.yml
                }
            ],
            "default_engine": "extraction-service"
        }
    """
    try:
        enabled_engines = config_loader.get_enabled_extraction_engines()
        default_engine = config_loader.get_default_extraction_engine()

        # Convert engines to dict format
        engines_list = []
        for engine in enabled_engines:
            # Determine if this engine is the default based on default_engine setting
            is_default = (default_engine and engine.name.lower() == default_engine.name.lower())

            engines_list.append({
                "id": engine.name,  # Use name as ID for config.yml engines
                "name": engine.name,
                "display_name": engine.display_name,
                "description": engine.description,
                "engine_type": engine.engine_type,
                "service_url": engine.service_url,
                "timeout": engine.timeout,
                "is_default": is_default,
                "is_system": True  # Mark as system engine from config.yml
            })

        return {
            "engines": engines_list,
            "default_engine": default_engine.name if default_engine else None,
            "default_engine_source": "config.yml" if config_loader.has_default_engine_in_config() else None
        }
    except Exception as e:
        # Return empty list if config.yml not found or invalid
        return {
            "engines": [],
            "default_engine": None,
            "default_engine_source": None,
            "error": str(e)
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


@router.get("/system/health/database", tags=["System"])
async def health_check_database() -> Dict[str, Any]:
    """
    Health check for database component.

    Returns database status including table counts, migration version, and size.
    """
    try:
        db_health = await database_service.health_check()

        if db_health["status"] == "healthy":
            # Get sanitized database URL (hide credentials)
            database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/curatore.db")
            safe_url = database_url.split("@")[-1].split("?")[0]

            response = {
                "status": "healthy",
                "message": "Database connection successful",
                "database_type": db_health.get("database_type", "unknown"),
                "database_url": safe_url,
                "connected": True,
                "tables": db_health.get("tables", {}),
                "migration_version": db_health.get("migration_version", "unknown"),
            }

            # Add database size if available (SQLite only)
            if "database_size_mb" in db_health:
                response["database_size_mb"] = db_health["database_size_mb"]

            return response
        else:
            return {
                "status": "unhealthy",
                "message": f"Database connection error: {db_health.get('error', 'unknown')}",
                "connected": False
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Database health check failed: {str(e)}",
            "connected": False
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


@router.get("/system/health/sharepoint", tags=["System"])
async def health_check_sharepoint() -> Dict[str, Any]:
    """Health check for SharePoint / Microsoft Graph API connectivity.

    Verifies:
    - Required environment variables are configured
    - Can authenticate with Azure AD
    - Can access Microsoft Graph API
    """
    import httpx

    # Check if SharePoint is configured
    tenant_id = os.getenv("MS_TENANT_ID", "").strip()
    client_id = os.getenv("MS_CLIENT_ID", "").strip()
    client_secret = os.getenv("MS_CLIENT_SECRET", "").strip()

    if not tenant_id or not client_id or not client_secret:
        return {
            "status": "not_configured",
            "message": "SharePoint integration not configured (missing MS_TENANT_ID, MS_CLIENT_ID, or MS_CLIENT_SECRET)",
            "configured": False
        }

    # Try to authenticate and get a token
    try:
        graph_base = os.getenv("MS_GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")
        token_url = os.getenv(
            "MS_GRAPH_TOKEN_URL",
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        )
        scope = os.getenv("MS_GRAPH_SCOPE", "https://graph.microsoft.com/.default")

        token_payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": scope,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Request access token
            token_resp = await client.post(token_url, data=token_payload)
            token_resp.raise_for_status()
            token_data = token_resp.json()
            access_token = token_data.get("access_token")

            if not access_token:
                return {
                    "status": "unhealthy",
                    "message": "Failed to obtain access token from Microsoft identity platform",
                    "configured": True,
                    "authenticated": False
                }

            # Test Graph API access by querying /me endpoint (or a simple endpoint)
            # Since we're using app-only auth, /me won't work. Try /sites/root instead
            headers = {"Authorization": f"Bearer {access_token}"}
            try:
                # Try a minimal query that should work with Sites.Read.All permission
                graph_resp = await client.get(f"{graph_base}/sites/root", headers=headers, timeout=5.0)
                graph_resp.raise_for_status()

                return {
                    "status": "healthy",
                    "message": "Successfully authenticated with Microsoft Graph API",
                    "configured": True,
                    "authenticated": True,
                    "tenant_id": tenant_id,
                    "graph_endpoint": graph_base
                }
            except httpx.HTTPStatusError as graph_error:
                # Token works but might not have proper permissions
                if graph_error.response.status_code == 403:
                    return {
                        "status": "degraded",
                        "message": "Authenticated but missing required permissions (Sites.Read.All or Files.Read.All)",
                        "configured": True,
                        "authenticated": True,
                        "tenant_id": tenant_id,
                        "graph_endpoint": graph_base,
                        "error": "Permission denied"
                    }
                else:
                    return {
                        "status": "unhealthy",
                        "message": f"Graph API request failed: {graph_error.response.status_code}",
                        "configured": True,
                        "authenticated": True,
                        "tenant_id": tenant_id,
                        "graph_endpoint": graph_base
                    }

    except httpx.HTTPStatusError as e:
        return {
            "status": "unhealthy",
            "message": f"Authentication failed: {e.response.status_code} - Check client credentials",
            "configured": True,
            "authenticated": False,
            "error": str(e)
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"SharePoint health check error: {str(e)}",
            "configured": True,
            "authenticated": False,
            "error": str(e)
        }


@router.get("/system/health/comprehensive", tags=["System"])
async def comprehensive_health() -> Dict[str, Any]:
    """Comprehensive health check for all system components.

    Checks the health of:
    - Backend API
    - Database (SQLite/PostgreSQL)
    - Redis (broker and backend)
    - Celery Worker
    - Extraction Service (default microservice)
    - Docling Service (if configured)
    - LLM Connection
    - SharePoint / Microsoft Graph (if configured)

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

    # 2. Database Connection
    try:
        db_health = await database_service.health_check()
        health_report["components"]["database"] = {
            "status": db_health["status"],
            "message": db_health.get("error", "Database connection successful") if db_health["status"] == "unhealthy" else "Database connection successful",
            "database_type": db_health.get("database_type", "unknown"),
            "connected": db_health.get("connected", False)
        }
        if db_health["status"] == "unhealthy":
            issues.append(f"Database: {db_health.get('error', 'connection failed')}")
    except Exception as e:
        health_report["components"]["database"] = {
            "status": "unhealthy",
            "message": f"Database health check failed: {str(e)}",
            "connected": False
        }
        issues.append(f"Database: {str(e)}")

    # 3. Redis Connection
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

    # 4. Celery Worker
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

    # 7. SharePoint / Microsoft Graph
    sharepoint_status = await health_check_sharepoint()
    health_report["components"]["sharepoint"] = sharepoint_status
    if sharepoint_status.get("status") in ["unhealthy", "degraded"]:
        issues.append(f"SharePoint: {sharepoint_status.get('message')}")

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


# ============================================================================
# STORAGE MANAGEMENT & DEDUPLICATION ENDPOINTS
# ============================================================================

@router.get("/storage/stats", tags=["System", "Storage"])
async def get_storage_stats(organization_id: Optional[str] = None):
    """
    Get storage usage statistics by organization.

    Returns total files, total size, deduplication savings, and file count by type.
    """
    try:
        from ....services.deduplication_service import deduplication_service
        from ....services.path_service import path_service

        # Get deduplication stats
        dedupe_stats = await deduplication_service.get_deduplication_stats(organization_id)

        # Calculate storage used by organization
        total_files = 0
        total_size = 0
        files_by_type = {"uploaded": 0, "processed": 0}

        if organization_id:
            org_paths = [path_service.resolve_organization_path(organization_id)]
        else:
            # All organizations
            base_path = settings.files_root_path
            org_base = base_path / "organizations"
            shared_base = base_path / "shared"

            org_paths = []
            if org_base.exists():
                org_paths.extend([p for p in org_base.iterdir() if p.is_dir()])
            if shared_base.exists():
                org_paths.append(shared_base)

        # Scan files
        for org_path in org_paths:
            if not org_path.exists():
                continue

            for file_type in ["uploaded", "processed"]:
                # Check batches
                batches_path = org_path / "batches"
                if batches_path.exists():
                    for batch_dir in batches_path.iterdir():
                        if not batch_dir.is_dir():
                            continue

                        type_dir = batch_dir / file_type
                        if type_dir.exists():
                            for file_path in type_dir.rglob("*"):
                                if file_path.is_file():
                                    total_files += 1
                                    files_by_type[file_type] += 1

                                    # Get actual file size (resolve symlinks)
                                    if file_path.is_symlink():
                                        resolved = file_path.resolve()
                                        if resolved.exists():
                                            total_size += resolved.stat().st_size
                                    else:
                                        total_size += file_path.stat().st_size

                # Check adhoc
                adhoc_dir = org_path / "adhoc" / file_type
                if adhoc_dir.exists():
                    for file_path in adhoc_dir.rglob("*"):
                        if file_path.is_file():
                            total_files += 1
                            files_by_type[file_type] += 1

                            if file_path.is_symlink():
                                resolved = file_path.resolve()
                                if resolved.exists():
                                    total_size += resolved.stat().st_size
                            else:
                                total_size += file_path.stat().st_size

        return {
            "organization_id": organization_id,
            "total_files": total_files,
            "total_size_bytes": total_size,
            "files_by_type": files_by_type,
            "deduplication": dedupe_stats,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get storage stats: {str(e)}")


@router.post("/storage/cleanup", tags=["System", "Storage"])
async def trigger_manual_cleanup(dry_run: bool = Query(default=True, description="Dry run mode")):
    """
    Manually trigger cleanup of expired files.

    By default runs in dry_run mode to preview what would be deleted.
    Set dry_run=false to actually delete files.
    """
    try:
        from ....services.retention_service import retention_service

        result = await retention_service.cleanup_expired_files(dry_run=dry_run)
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")


@router.get("/storage/retention", tags=["System", "Storage"])
async def get_retention_policy():
    """Get current retention policy settings."""
    return {
        "enabled": settings.file_cleanup_enabled,
        "retention_periods": {
            "uploaded_days": settings.file_retention_uploaded_days,
            "processed_days": settings.file_retention_processed_days,
            "batch_days": settings.file_retention_batch_days,
            "temp_hours": settings.file_retention_temp_hours,
        },
        "cleanup_schedule": settings.file_cleanup_schedule_cron,
        "batch_size": settings.file_cleanup_batch_size,
        "dry_run": settings.file_cleanup_dry_run,
    }


@router.get("/storage/deduplication", tags=["System", "Storage"])
async def get_deduplication_stats(organization_id: Optional[str] = None):
    """
    Get deduplication statistics and storage savings.

    Returns unique files, duplicate references, storage saved, and savings percentage.
    """
    try:
        from ....services.deduplication_service import deduplication_service

        stats = await deduplication_service.get_deduplication_stats(organization_id)
        return {
            "organization_id": organization_id,
            "enabled": settings.file_deduplication_enabled,
            "strategy": settings.file_deduplication_strategy,
            "min_file_size": settings.dedupe_min_file_size,
            **stats,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get deduplication stats: {str(e)}")


@router.get("/storage/duplicates", tags=["System", "Storage"])
async def list_duplicate_files(organization_id: Optional[str] = None):
    """
    List all files with duplicates.

    Returns hash, file count, document IDs, and storage saved per file.
    """
    try:
        from ....services.document_service import document_service

        duplicates = await document_service.find_duplicates(organization_id)

        return {
            "organization_id": organization_id,
            "duplicate_groups": len(duplicates),
            "total_storage_saved": sum(d.get("storage_saved", 0) for d in duplicates),
            "duplicates": duplicates,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list duplicates: {str(e)}")


@router.get("/storage/duplicates/{hash}", tags=["System", "Storage"])
async def get_duplicate_details(hash: str):
    """
    Get detailed info about a specific duplicate file group.

    Returns full reference list, file size, original name, and created dates.
    """
    try:
        from ....services.deduplication_service import deduplication_service

        refs = await deduplication_service.get_file_references(hash)

        if not refs:
            raise HTTPException(status_code=404, detail=f"Duplicate group not found: {hash}")

        return refs

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get duplicate details: {str(e)}")
