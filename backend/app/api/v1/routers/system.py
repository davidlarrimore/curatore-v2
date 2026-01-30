# backend/app/api/v1/routers/system.py
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends
import os
from typing import Dict, Any, Optional, List
import json
import redis

from ....config import settings
from ..models import HealthStatus, LLMConnectionStatus
from ....services.llm_service import llm_service
from ....services.document_service import document_service
from ....services.storage_service import storage_service
from ....services.zip_service import zip_service
from ....services.database_service import database_service
from ....services.config_loader import config_loader
from ....celery_app import app as celery_app
from ....dependencies import get_current_user


def get_redis_client():
    """Get a Redis client for queue health checks."""
    broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    return redis.Redis.from_url(broker_url)

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

        # Clear temp ZIPs and object storage
        try:
            zip_deleted = zip_service.cleanup_all_temp_archives()
        except Exception:
            zip_deleted = 0

        # Clear object storage buckets
        minio_deleted = {"uploads": 0, "processed": 0, "temp": 0}
        try:
            from ....services.minio_service import get_minio_service
            minio = get_minio_service()
            if minio and minio.enabled:
                try:
                    minio_deleted["uploads"] = minio.delete_all_objects_in_bucket(minio.bucket_uploads)
                except Exception:
                    pass
                try:
                    minio_deleted["processed"] = minio.delete_all_objects_in_bucket(minio.bucket_processed)
                except Exception:
                    pass
                try:
                    minio_deleted["temp"] = minio.delete_all_objects_in_bucket(minio.bucket_temp)
                except Exception:
                    pass
        except Exception:
            pass

        # Clear in-memory storage cache
        storage_service.clear_all()

        return {
            "success": True,
            "message": "System reset successfully",
            "timestamp": datetime.now(),
            "queue": {"revoked": revoked, "purged": purged},
            "temp_zips_deleted": zip_deleted,
            "minio_objects_deleted": minio_deleted,
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

    docling_url = (getattr(settings, "docling_service_url", None) or "").rstrip("/")
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


@router.get("/system/health/storage", tags=["System"])
async def health_check_storage() -> Dict[str, Any]:
    """Health check for object storage (S3/MinIO).

    Returns:
        Dict with status, message, and provider info when enabled.
        Returns not_enabled status when USE_OBJECT_STORAGE=false.
    """
    if not settings.use_object_storage:
        return {
            "status": "not_enabled",
            "message": "Object storage not enabled (USE_OBJECT_STORAGE=false)",
            "use_object_storage": False,
        }

    try:
        from ....services.minio_service import get_minio_service

        minio = get_minio_service()
        if not minio:
            return {
                "status": "not_configured",
                "message": "MinIO service not initialized",
                "use_object_storage": True,
            }

        # Check MinIO connection health
        connected, buckets, error = minio.check_health()

        if connected:
            return {
                "status": "healthy",
                "message": "Object storage is responding",
                "use_object_storage": True,
                "endpoint": minio.endpoint,
                "provider_connected": True,
                "buckets": buckets or [],
            }
        else:
            return {
                "status": "unhealthy",
                "message": f"MinIO connection failed: {error}",
                "use_object_storage": True,
                "endpoint": minio.endpoint,
                "error": error,
            }

    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Storage service error: {str(e)}",
            "use_object_storage": True,
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


@router.get("/system/health/playwright", tags=["System"])
async def health_check_playwright() -> Dict[str, Any]:
    """Health check for Playwright rendering service component.

    Verifies:
    - Playwright service URL is configured
    - Service is reachable and responding
    """
    playwright_url = (getattr(settings, "playwright_service_url", None) or "").rstrip("/")
    if not playwright_url:
        return {
            "status": "not_configured",
            "message": "Playwright service not configured (missing PLAYWRIGHT_SERVICE_URL)",
            "configured": False
        }

    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            health_url = f"{playwright_url}/health"
            try:
                resp = await client.get(health_url)
                if resp.status_code == 200:
                    health_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    return {
                        "status": "healthy",
                        "message": "Playwright service is responding",
                        "url": playwright_url,
                        "configured": True,
                        "browser_pool_size": health_data.get("browser_pool_size"),
                        "active_contexts": health_data.get("active_contexts"),
                    }
                else:
                    return {
                        "status": "degraded",
                        "message": f"Playwright returned status {resp.status_code}",
                        "url": playwright_url,
                        "configured": True
                    }
            except httpx.HTTPStatusError:
                return {
                    "status": "unknown",
                    "message": "Playwright service configured but health endpoint not available",
                    "url": playwright_url,
                    "configured": True
                }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Playwright service error: {str(e)}",
            "url": playwright_url,
            "configured": True
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
    - Playwright Rendering Service (if configured)
    - Object Storage (S3/MinIO) (if enabled)

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
    docling_url = (getattr(settings, "docling_service_url", None) or "").rstrip("/")
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

    # 8. Playwright Rendering Service
    playwright_status = await health_check_playwright()
    health_report["components"]["playwright"] = playwright_status
    if playwright_status.get("status") == "unhealthy":
        issues.append(f"Playwright: {playwright_status.get('message')}")

    # 9. Object Storage (S3/MinIO)
    storage_status = await health_check_storage()
    health_report["components"]["object_storage"] = storage_status
    if storage_status.get("status") == "unhealthy":
        issues.append(f"Object Storage: {storage_status.get('message')}")

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
# STORAGE MANAGEMENT & RETENTION ENDPOINTS
# ============================================================================

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
