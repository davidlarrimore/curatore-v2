# backend/app/api/v1/routers/system.py
import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import redis
from fastapi import APIRouter, Depends, HTTPException, Query

from app.celery_app import app as celery_app
from app.config import settings
from app.connectors.adapters.document_service_adapter import document_service_adapter
from app.core.llm.llm_service import llm_service
from app.core.shared.config_loader import config_loader
from app.core.shared.database_service import database_service
from app.core.shared.document_service import document_service
from app.core.storage.storage_service import storage_service
from app.core.storage.zip_service import zip_service
from uuid import UUID

from app.dependencies import get_current_user, get_effective_org_id


def get_redis_client():
    """Get a Redis client for queue health checks."""
    broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    return redis.Redis.from_url(broker_url)

router = APIRouter(dependencies=[Depends(get_current_user)])


# ============================================================================
# HEALTH CHECK HELPERS (shared by individual and comprehensive endpoints)
# ============================================================================

async def _check_backend() -> Dict[str, Any]:
    """Check backend API health."""
    return {
        "status": "healthy",
        "message": "API is responding",
        "version": settings.api_version,
    }


async def _check_database() -> Dict[str, Any]:
    """Check database health."""
    try:
        db_health = await database_service.health_check()

        if db_health["status"] == "healthy":
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

            if "database_size_mb" in db_health:
                response["database_size_mb"] = db_health["database_size_mb"]

            return response
        else:
            return {
                "status": "unhealthy",
                "message": f"Database connection error: {db_health.get('error', 'unknown')}",
                "connected": False,
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Database health check failed: {str(e)}",
            "connected": False,
        }


async def _check_redis() -> Dict[str, Any]:
    """Check Redis health."""
    try:
        r = get_redis_client()
        ping_result = r.ping()
        return {
            "status": "healthy" if ping_result else "unhealthy",
            "message": "Redis connection successful" if ping_result else "Redis ping failed",
            "broker_url": os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
            "result_backend": os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1"),
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Redis connection error: {str(e)}",
        }


async def _check_celery() -> Dict[str, Any]:
    """Check Celery worker health."""
    try:
        insp = celery_app.control.inspect(timeout=5.0)
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
            "queue": os.getenv("CELERY_DEFAULT_QUEUE", "extraction"),
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Worker check error: {str(e)}",
            "worker_count": 0,
        }


async def _check_extraction() -> Dict[str, Any]:
    """Check document service health."""
    try:
        health_data = await document_service_adapter.health()
        is_healthy = health_data.get("status") == "ok"

        circuit = document_service_adapter.get_circuit_status()

        if is_healthy:
            result = {
                "status": "healthy",
                "message": "Document service is responding",
                "url": document_service_adapter.base_url,
                "engine": "document-service",
                "response": health_data,
            }
        elif not document_service_adapter.is_available:
            result = {
                "status": "not_configured",
                "message": "Document service not configured",
                "engine": "document-service",
            }
        else:
            error_msg = health_data.get("error", "Service check failed")
            result = {
                "status": "unhealthy",
                "message": f"Document service unreachable: {error_msg}",
                "url": document_service_adapter.base_url,
                "engine": "document-service",
            }

        result["circuit_breaker"] = circuit
        return result
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Document service error: {str(e)}",
        }


async def _check_storage() -> Dict[str, Any]:
    """Check object storage (S3/MinIO) health."""
    if not settings.use_object_storage:
        return {
            "status": "not_enabled",
            "message": "Object storage not enabled (USE_OBJECT_STORAGE=false)",
            "use_object_storage": False,
        }

    try:
        from app.core.storage.minio_service import get_minio_service

        minio = get_minio_service()
        if not minio:
            return {
                "status": "not_configured",
                "message": "MinIO service not initialized",
                "use_object_storage": True,
            }

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


async def _check_llm() -> Dict[str, Any]:
    """Check LLM connection health."""
    try:
        llm_status = await llm_service.test_connection()
        if llm_status.connected:
            return {
                "status": "healthy",
                "message": f"Connected to {llm_status.model}",
                "model": llm_status.model,
                "endpoint": llm_status.endpoint,
            }
        else:
            error_msg = llm_status.error or "Connection failed"
            return {
                "status": "unhealthy",
                "message": error_msg,
                "model": llm_status.model,
                "endpoint": llm_status.endpoint,
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"LLM check error: {str(e)}",
        }


async def _check_playwright() -> Dict[str, Any]:
    """Check Playwright rendering service health."""
    playwright_url = (getattr(settings, "playwright_service_url", None) or "").rstrip("/")
    if not playwright_url:
        return {
            "status": "not_configured",
            "message": "Playwright service not configured (missing PLAYWRIGHT_SERVICE_URL)",
            "configured": False,
        }

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
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
                        "configured": True,
                    }
            except httpx.HTTPStatusError:
                return {
                    "status": "unknown",
                    "message": "Playwright service configured but health endpoint not available",
                    "url": playwright_url,
                    "configured": True,
                }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Playwright service error: {str(e)}",
            "url": playwright_url,
            "configured": True,
        }


async def _check_sharepoint() -> Dict[str, Any]:
    """Check SharePoint / Microsoft Graph API connectivity."""
    import httpx

    tenant_id = os.getenv("MS_TENANT_ID", "").strip()
    client_id = os.getenv("MS_CLIENT_ID", "").strip()
    client_secret = os.getenv("MS_CLIENT_SECRET", "").strip()

    if not tenant_id or not client_id or not client_secret:
        return {
            "status": "not_configured",
            "message": "SharePoint integration not configured (missing MS_TENANT_ID, MS_CLIENT_ID, or MS_CLIENT_SECRET)",
            "configured": False,
        }

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
            token_resp = await client.post(token_url, data=token_payload)
            token_resp.raise_for_status()
            token_data = token_resp.json()
            access_token = token_data.get("access_token")

            if not access_token:
                return {
                    "status": "unhealthy",
                    "message": "Failed to obtain access token from Microsoft identity platform",
                    "configured": True,
                    "authenticated": False,
                }

            headers = {"Authorization": f"Bearer {access_token}"}
            try:
                graph_resp = await client.get(f"{graph_base}/sites/root", headers=headers, timeout=5.0)
                graph_resp.raise_for_status()

                return {
                    "status": "healthy",
                    "message": "Successfully authenticated with Microsoft Graph API",
                    "configured": True,
                    "authenticated": True,
                    "tenant_id": tenant_id,
                    "graph_endpoint": graph_base,
                }
            except httpx.HTTPStatusError as graph_error:
                if graph_error.response.status_code == 403:
                    return {
                        "status": "degraded",
                        "message": "Authenticated but missing required permissions (Sites.Read.All or Files.Read.All)",
                        "configured": True,
                        "authenticated": True,
                        "tenant_id": tenant_id,
                        "graph_endpoint": graph_base,
                        "error": "Permission denied",
                    }
                else:
                    return {
                        "status": "unhealthy",
                        "message": f"Graph API request failed: {graph_error.response.status_code}",
                        "configured": True,
                        "authenticated": True,
                        "tenant_id": tenant_id,
                        "graph_endpoint": graph_base,
                    }

    except httpx.HTTPStatusError as e:
        return {
            "status": "unhealthy",
            "message": f"Authentication failed: {e.response.status_code} - Check client credentials",
            "configured": True,
            "authenticated": False,
            "error": str(e),
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"SharePoint health check error: {str(e)}",
            "configured": True,
            "authenticated": False,
            "error": str(e),
        }


# ============================================================================
# INDIVIDUAL HEALTH ENDPOINTS (backward compatibility)
# ============================================================================

@router.get("/system/health/backend", tags=["System"])
async def health_check_backend() -> Dict[str, Any]:
    """Health check for backend API component."""
    return await _check_backend()


@router.get("/system/health/database", tags=["System"])
async def health_check_database() -> Dict[str, Any]:
    """Health check for database component."""
    return await _check_database()


@router.get("/system/health/redis", tags=["System"])
async def health_check_redis() -> Dict[str, Any]:
    """Health check for Redis component."""
    return await _check_redis()


@router.get("/system/health/celery", tags=["System"])
async def health_check_celery() -> Dict[str, Any]:
    """Health check for Celery worker component."""
    return await _check_celery()


@router.get("/system/health/extraction", tags=["System"])
async def health_check_extraction() -> Dict[str, Any]:
    """Health check for document service component."""
    return await _check_extraction()


@router.get("/system/health/storage", tags=["System"])
async def health_check_storage() -> Dict[str, Any]:
    """Health check for object storage (S3/MinIO)."""
    return await _check_storage()


@router.get("/system/health/llm", tags=["System"])
async def health_check_llm() -> Dict[str, Any]:
    """Health check for LLM connection component."""
    return await _check_llm()


@router.get("/system/health/playwright", tags=["System"])
async def health_check_playwright() -> Dict[str, Any]:
    """Health check for Playwright rendering service component."""
    return await _check_playwright()


@router.get("/system/health/sharepoint", tags=["System"])
async def health_check_sharepoint() -> Dict[str, Any]:
    """Health check for SharePoint / Microsoft Graph API connectivity."""
    return await _check_sharepoint()


@router.get("/system/health/comprehensive", tags=["System"])
async def comprehensive_health() -> Dict[str, Any]:
    """Comprehensive health check for all system components.

    Runs all component health checks in parallel and returns a unified report.
    This is the recommended single endpoint for monitoring system health.
    """
    # Run all health checks in parallel
    results = await asyncio.gather(
        _check_backend(),
        _check_database(),
        _check_redis(),
        _check_celery(),
        _check_extraction(),
        _check_storage(),
        _check_llm(),
        _check_playwright(),
        _check_sharepoint(),
        return_exceptions=True,
    )

    component_keys = [
        "backend", "database", "redis", "celery_worker",
        "document_service", "object_storage",
        "llm", "playwright", "sharepoint",
    ]

    health_report: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "overall_status": "healthy",
        "components": {},
    }

    issues = []

    for key, result in zip(component_keys, results):
        if isinstance(result, Exception):
            health_report["components"][key] = {
                "status": "unhealthy",
                "message": f"Health check failed: {str(result)}",
            }
            issues.append(f"{key}: {str(result)}")
        else:
            health_report["components"][key] = result
            status = result.get("status")
            if status == "unhealthy":
                issues.append(f"{key}: {result.get('message')}")
            elif status in ("degraded", "unknown"):
                issues.append(f"{key}: {result.get('message')}")

    # Determine overall status
    component_statuses = [c.get("status") for c in health_report["components"].values()]

    if any(s == "unhealthy" for s in component_statuses):
        health_report["overall_status"] = "unhealthy"
    elif any(s in ("degraded", "unknown") for s in component_statuses):
        health_report["overall_status"] = "degraded"
    else:
        health_report["overall_status"] = "healthy"

    if issues:
        health_report["issues"] = issues

    return health_report


# ============================================================================
# SYSTEM MANAGEMENT ENDPOINTS
# ============================================================================

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
            from app.core.storage.minio_service import get_minio_service
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


# ============================================================================
# CONFIGURATION ENDPOINTS
# ============================================================================

@router.get("/config/supported-formats", tags=["Configuration"])
async def get_supported_formats():
    """Get list of supported file formats."""
    formats_data = await document_service_adapter.supported_formats()

    return {
        "supported_extensions": formats_data.get("extensions", document_service.get_supported_extensions()),
        "max_file_size": settings.max_file_size,
    }


@router.get("/config/defaults", tags=["Configuration"])
async def get_default_config():
    """Get default configuration values."""
    return {
        "ocr_settings": {
            "language": settings.ocr_lang,
            "psm": settings.ocr_psm
        },
    }

@router.get("/config/extraction-services", tags=["Configuration"])
async def get_extraction_services() -> Dict[str, Any]:
    """List available document extraction services and which one is active."""
    try:
        return await document_service.available_extraction_services()
    except Exception as e:
        return {"active": None, "services": [], "error": str(e)}

@router.get("/config/extraction-engines", tags=["Configuration"])
async def get_extraction_engines() -> Dict[str, Any]:
    """List extraction engines available via the document service."""
    try:
        caps = await document_service_adapter.capabilities()
        engines_list = [
            {
                "id": "document-service",
                "name": "document-service",
                "display_name": "Document Service",
                "description": "Curatore Document Service with automatic triage",
                "engine_type": "document-service",
                "service_url": document_service_adapter.base_url,
                "timeout": document_service_adapter.timeout,
                "is_default": True,
                "is_system": True,
            }
        ]

        if caps.get("docling_available"):
            engines_list.append({
                "id": "docling",
                "name": "docling",
                "display_name": "Docling (via Document Service)",
                "description": "IBM Docling for complex PDFs and OCR, proxied through document service",
                "engine_type": "docling",
                "service_url": document_service_adapter.base_url,
                "timeout": document_service_adapter.timeout,
                "is_default": False,
                "is_system": True,
            })

        return {
            "engines": engines_list,
            "default_engine": "document-service",
            "default_engine_source": "document-service",
        }
    except Exception as e:
        return {
            "engines": [],
            "default_engine": None,
            "default_engine_source": None,
            "error": str(e)
        }


@router.get("/config/system-settings", tags=["Configuration"])
async def get_system_settings(
    current_user=Depends(get_current_user),
    org_id: Optional[UUID] = Depends(get_effective_org_id),
) -> Dict[str, Any]:
    """Read-only view of system configuration from config.yml.

    Aggregates configuration into grouped sections for display in the
    admin UI.  Secrets (API keys, passwords, tokens) are explicitly excluded.
    """
    from sqlalchemy import select

    from app.core.database.models import Organization

    sections: Dict[str, Any] = {}

    # ── Embedding & Indexing ───────────────────────────────────────────
    embedding_state = config_loader.get_embedding_config_state()
    embedding_section: Dict[str, Any] = {
        "model": embedding_state.get("model"),
        "dimensions": embedding_state.get("dimensions"),
    }

    # Per-org stored config comparison (skip if no org context)
    try:
        if org_id is not None:
            async with database_service.get_session() as session:
                result = await session.execute(
                    select(Organization).where(
                        Organization.id == org_id
                    )
                )
                org = result.scalar_one_or_none()
        else:
            org = None

        if org:
            org_settings = org.settings or {}
            stored = org_settings.get("embedding_config")
            embedding_section["stored_config"] = stored
            if stored:
                embedding_section["config_matches_stored"] = (
                    stored.get("model") == embedding_state.get("model")
                    and stored.get("dimensions") == embedding_state.get("dimensions")
                )
            else:
                embedding_section["config_matches_stored"] = None
    except Exception:
        embedding_section["stored_config"] = None
        embedding_section["config_matches_stored"] = None

    sections["embedding"] = embedding_section

    # ── Search Configuration ───────────────────────────────────────────
    search_cfg = config_loader.get_search_config()
    if search_cfg:
        sections["search"] = {
            "enabled": search_cfg.enabled,
            "default_mode": search_cfg.default_mode,
            "semantic_weight": search_cfg.semantic_weight,
            "chunk_size": search_cfg.chunk_size,
            "chunk_overlap": search_cfg.chunk_overlap,
            "batch_size": search_cfg.batch_size,
            "max_content_length": search_cfg.max_content_length,
        }

    # ── LLM Task Routing ──────────────────────────────────────────────
    llm_cfg = config_loader.get_llm_config()
    if llm_cfg:
        llm_section: Dict[str, Any] = {
            "provider": llm_cfg.provider,
            "default_model": llm_cfg.default_model,
            "base_url": llm_cfg.base_url,
            "timeout": llm_cfg.timeout,
            "max_retries": llm_cfg.max_retries,
            "verify_ssl": llm_cfg.verify_ssl,
        }
        if llm_cfg.task_types:
            task_table = []
            for task_name, task_cfg in llm_cfg.task_types.items():
                entry: Dict[str, Any] = {
                    "task_type": task_name,
                    "model": task_cfg.model,
                }
                if task_cfg.temperature is not None:
                    entry["temperature"] = task_cfg.temperature
                if task_cfg.dimensions is not None:
                    entry["dimensions"] = task_cfg.dimensions
                if task_cfg.max_tokens is not None:
                    entry["max_tokens"] = task_cfg.max_tokens
                task_table.append(entry)
            llm_section["task_types"] = task_table
        sections["llm_routing"] = llm_section

    # ── Queue ─────────────────────────────────────────────────────────
    queue_cfg = config_loader.get_queue_config()
    if queue_cfg:
        sections["queue"] = {
            "broker_url": queue_cfg.broker_url,
            "result_backend": queue_cfg.result_backend,
            "default_queue": queue_cfg.default_queue,
            "worker_concurrency": queue_cfg.worker_concurrency,
            "task_timeout": queue_cfg.task_timeout,
        }

    # ── Object Storage ────────────────────────────────────────────────
    minio_cfg = config_loader.get_minio_config()
    if minio_cfg:
        sections["storage"] = {
            "enabled": minio_cfg.enabled,
            "endpoint": minio_cfg.endpoint,
            "secure": minio_cfg.secure,
            "bucket_uploads": minio_cfg.bucket_uploads,
            "bucket_processed": minio_cfg.bucket_processed,
            "bucket_temp": minio_cfg.bucket_temp,
        }

    # ── Playwright ────────────────────────────────────────────────────
    pw_cfg = config_loader.get_playwright_config()
    if pw_cfg:
        sections["playwright"] = {
            "enabled": pw_cfg.enabled,
            "service_url": pw_cfg.service_url,
            "browser_pool_size": pw_cfg.browser_pool_size,
            "default_viewport": f"{pw_cfg.default_viewport_width}x{pw_cfg.default_viewport_height}",
            "default_timeout_ms": pw_cfg.default_timeout_ms,
            "default_wait_timeout_ms": pw_cfg.default_wait_timeout_ms,
        }

    # ── SAM.gov ───────────────────────────────────────────────────────
    sam_cfg = config_loader.get_sam_config()
    if sam_cfg:
        sections["sam"] = {
            "enabled": sam_cfg.enabled,
            "rate_limit_delay": sam_cfg.rate_limit_delay,
            "max_pages_per_pull": sam_cfg.max_pages_per_pull,
            "page_size": sam_cfg.page_size,
            "timeout": sam_cfg.timeout,
            "max_retries": sam_cfg.max_retries,
        }

    # ── Email ─────────────────────────────────────────────────────────
    email_cfg = config_loader.get_email_config()
    if email_cfg:
        sections["email"] = {
            "backend": email_cfg.backend,
            "from_address": email_cfg.from_address,
            "from_name": email_cfg.from_name,
        }

    return sections


# ============================================================================
# QUEUE ENDPOINTS
# ============================================================================

@router.get("/system/queues", tags=["System"])
async def queue_health() -> Dict[str, Any]:
    """Minimal Celery/Redis queue health endpoint."""
    enabled = os.getenv("USE_CELERY", "true").lower() in {"1", "true", "yes"}
    broker = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
    queue = os.getenv("CELERY_DEFAULT_QUEUE", "extraction")

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
        keys = [queue, "celery"] if queue != "celery" else ["celery"]
        total = 0
        for k in keys:
            try:
                total += int(r.llen(k))
            except Exception:
                continue
        info["pending"] = total
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
    job_ids: Optional[str] = Query(None, description="Comma-separated job IDs"),
) -> Dict[str, Any]:
    """Summarize status for a requested set of jobs."""
    if not batch_id and not job_ids:
        raise HTTPException(status_code=400, detail="batch_id or job_ids required")

    r = get_redis_client()
    target_job_ids: List[str] = []

    if job_ids:
        target_job_ids = [j.strip() for j in job_ids.split(",") if j.strip()]
    else:
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

    for jid in target_job_ids:
        try:
            raw = r.get(f"job:{jid}")
            if not raw:
                continue
            data = json.loads(raw)
            status = str(data.get("status", "")).upper()
            if status == "STARTED":
                running += 1
            elif status in ("SUCCESS", "FAILURE"):
                done += 1
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
